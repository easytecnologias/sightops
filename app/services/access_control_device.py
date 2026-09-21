from __future__ import annotations

import json
import base64
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.parse import urlencode

import requests
from fastapi import HTTPException
from requests.auth import HTTPDigestAuth

_TIMEOUT = 10.0
_ACCESS_REC_LIMIT = 1024
_ACCESS_REC_LOOKBACK_DAYS = 90
_CONNECTOR_JOB_TIMEOUT = 75.0
_ACCESS_REC_CURSOR_OVERLAP_SECONDS = 600


class _AccessRemoteResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


def _base_url(device: Dict[str, Any]) -> str:
    host = str(device.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Dispositivo sem host configurado.")
    return f"http://{host}"


def _has_vnat_mapping(device: Dict[str, Any]) -> bool:
    """O conector deste dispositivo tem faixa virtual (vnat/isolado)?"""
    cid = _connector_id(device)
    host = str(device.get("host") or "").strip()
    if not cid or not host:
        return False
    try:
        from app.services import connector_routing_vnat as _vnat
        v = _vnat.virtual_ip_for(cid, host)
        return bool(v and v != host)
    except Exception:
        return False


def _base_url_direct(device: Dict[str, Any]) -> str:
    """Base URL do acesso DIRETO (do container, pelo wgc): usa o IP VIRTUAL
    (vnat) do conector isolado, igual cameras/nvr/dvr. Sem mapeamento vnat,
    virtual_ip_for devolve o proprio IP -- entao e seguro pra conector nao
    isolado. NAO usar no caminho via-agente (o agente esta na LAN, ve o IP
    real)."""
    host = str(device.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Dispositivo sem host configurado.")
    cid = _connector_id(device)
    if cid:
        try:
            from app.services import connector_routing_vnat as _vnat
            v = _vnat.virtual_ip_for(cid, host)
            if v:
                host = v
        except Exception:
            pass
    return f"http://{host}"


def _connector_id(device: Dict[str, Any]) -> str:
    return str(device.get("connector_id") or device.get("remote_connector_id") or "").strip()


def _auth(device: Dict[str, Any]) -> HTTPDigestAuth:
    return HTTPDigestAuth(str(device.get("username") or "admin"), str(device.get("password") or ""))


def _raise_device_auth_error() -> None:
    raise HTTPException(status_code=502, detail="Usuario ou senha invalidos no dispositivo.")


def _looks_like_auth_error(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "authentication failed",
            "auth failed",
            "unauthorized",
            "invalid user",
            "invalid password",
            "usuario",
            "senha",
            "login error",
        )
    )


def _parse_routeros_access_http_result(text: str) -> str:
    raw = str(text or "").strip()
    if raw.lower().startswith("fetch_error"):
        if _looks_like_auth_error(raw):
            _raise_device_auth_error()
        raise HTTPException(status_code=502, detail="Conector nao conseguiu acessar o dispositivo.")
    if raw.startswith("status="):
        _, _, rest = raw.partition(";data=")
        return rest if rest or ";data=" in raw else raw
    return raw


def _get_via_connector(device: Dict[str, Any], path: str, params: Dict[str, Any] | None = None) -> _AccessRemoteResponse:
    connector_id = _connector_id(device)
    if not connector_id:
        raise HTTPException(status_code=400, detail="Dispositivo sem conector configurado.")
    url = f"{_base_url(device)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    try:
        from app.services.connector_service import create_job, list_jobs

        job = create_job(
            {
                "connector_id": connector_id,
                "type": "access_http_get",
                "payload": {
                    "url": url,
                    "username": str(device.get("username") or "admin"),
                    "password": str(device.get("password") or ""),
                },
            }
        ).get("job") or {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = str(job.get("id") or "")
    if not job_id:
        raise HTTPException(status_code=502, detail="Nao foi possivel criar job no conector.")

    deadline = time.monotonic() + _CONNECTOR_JOB_TIMEOUT
    final_job: Dict[str, Any] | None = None
    while time.monotonic() < deadline:
        jobs = list_jobs(connector_id, limit=100).get("jobs") or []
        final_job = next((item for item in jobs if str(item.get("id") or "") == job_id), None)
        if final_job and final_job.get("status") in {"done", "failed"}:
            break
        time.sleep(2.0)
    if not final_job or final_job.get("status") not in {"done", "failed"}:
        raise HTTPException(status_code=504, detail="Tempo esgotado aguardando o conector executar o teste.")
    result = final_job.get("result") if isinstance(final_job.get("result"), dict) else {}
    text = _parse_routeros_access_http_result(str(result.get("access_http") or final_job.get("error") or ""))
    if final_job.get("status") == "failed":
        if _looks_like_auth_error(text):
            _raise_device_auth_error()
        raise HTTPException(status_code=502, detail=text or "Conector nao conseguiu acessar o dispositivo.")
    return _AccessRemoteResponse(text=text, status_code=200)


def _post_json_via_connector(
    device: Dict[str, Any], path_with_query: str, payload: Dict[str, Any], action_label: str
) -> _AccessRemoteResponse:
    connector_id = _connector_id(device)
    if not connector_id:
        raise HTTPException(status_code=400, detail="Dispositivo sem conector configurado.")
    try:
        from app.services.connector_service import create_job, list_jobs

        job = create_job(
            {
                "connector_id": connector_id,
                "type": "access_http_post",
                "payload": {
                    "url": f"{_base_url(device)}{path_with_query}",
                    "username": str(device.get("username") or "admin"),
                    "password": str(device.get("password") or ""),
                    "content_type": "application/json",
                    "body": json.dumps(payload, ensure_ascii=False),
                },
            }
        ).get("job") or {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = str(job.get("id") or "")
    if not job_id:
        raise HTTPException(status_code=502, detail="Nao foi possivel criar job no conector.")

    deadline = time.monotonic() + _CONNECTOR_JOB_TIMEOUT
    final_job: Dict[str, Any] | None = None
    while time.monotonic() < deadline:
        jobs = list_jobs(connector_id, limit=100).get("jobs") or []
        final_job = next((item for item in jobs if str(item.get("id") or "") == job_id), None)
        if final_job and final_job.get("status") in {"done", "failed"}:
            break
        time.sleep(2.0)
    if not final_job or final_job.get("status") not in {"done", "failed"}:
        raise HTTPException(status_code=504, detail=f"Tempo esgotado aguardando o conector executar {action_label}.")
    result = final_job.get("result") if isinstance(final_job.get("result"), dict) else {}
    text = _parse_routeros_access_http_result(str(result.get("access_http") or final_job.get("error") or ""))
    if final_job.get("status") == "failed":
        if _looks_like_auth_error(text):
            _raise_device_auth_error()
        raise HTTPException(status_code=502, detail=text or f"Conector nao conseguiu executar {action_label}.")
    return _AccessRemoteResponse(text=text, status_code=200)


class _TunelIndisponivel(Exception):
    """A requisicao nao chegou ao dispositivo (rede/tunel).

    Diferente de o dispositivo ter respondido recusando: so este caso justifica
    tentar de novo pelo agente do conector.
    """


def _host_no_inventario_do_conector(device: Dict[str, Any]) -> bool:
    """O IP deste dispositivo aparece na rede DESTE conector?

    E o que autoriza falar pelo tunel: o agente do site reporta ARP/DHCP, entao
    se o IP esta la, ele e daquele site. Sem essa confirmacao o acesso direto
    fica proibido -- IP privado repetido entre clientes e normal, e falar com a
    controladora do cliente errado seria muito pior do que falhar.
    """
    connector_id = _connector_id(device)
    host = str(device.get("host") or "").strip()
    if not connector_id or not host:
        return False
    try:
        from app.services.connector_service import get_connector

        conector = get_connector(connector_id, include_token=False, enforce_tenant=True) or {}
    except Exception:
        return False
    inventario = conector.get("inventory") if isinstance(conector.get("inventory"), dict) else {}
    for chave in ("arp_sample", "dhcp_sample", "neighbor_sample", "known_targets"):
        bruto = inventario.get(chave) or conector.get(chave)
        if not bruto:
            continue
        if host in str(bruto):
            return True
    return False


def _get_direto(device: Dict[str, Any], path: str, params: Dict[str, Any] | None = None) -> requests.Response:
    """Fala com o dispositivo pelo tunel, com Digest (o que o RouterOS nao faz)."""
    url = f"{_base_url_direct(device)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    try:
        resp = requests.get(url, auth=_auth(device), timeout=_TIMEOUT)
    except requests.ConnectTimeout as exc:
        raise _TunelIndisponivel("tempo esgotado ao conectar") from exc
    except requests.ConnectionError as exc:
        raise _TunelIndisponivel("nao foi possivel conectar") from exc
    except requests.RequestException as exc:
        raise _TunelIndisponivel(str(exc)) from exc
    if resp.status_code in {401, 403}:
        _raise_device_auth_error()
    if _looks_like_auth_error(resp.text or ""):
        _raise_device_auth_error()
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Dispositivo respondeu com erro (HTTP {resp.status_code}): {(resp.text or '').strip()}",
        )
    return resp


def _get(device: Dict[str, Any], path: str, params: Dict[str, Any] | None = None) -> requests.Response:
    if _connector_id(device):
        # Tunel primeiro -- so quando o IP e comprovadamente daquele conector.
        # Erro de credencial NAO cai para o agente: a senha estaria errada nos
        # dois caminhos, e mascarar isso viraria "tempo esgotado" sem explicacao.
        if _host_no_inventario_do_conector(device) or _has_vnat_mapping(device):
            try:
                return _get_direto(device, path, params)
            except _TunelIndisponivel:
                pass  # tunel fora do ar: vale tentar pelo agente
        return _get_via_connector(device, path, params)  # type: ignore[return-value]
    url = f"{_base_url(device)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    try:
        resp = requests.get(url, auth=_auth(device), timeout=_TIMEOUT)
    except requests.ConnectTimeout as exc:
        raise HTTPException(status_code=502, detail="Tempo esgotado ao conectar no IP do dispositivo.") from exc
    except requests.ConnectionError as exc:
        raise HTTPException(status_code=502, detail="Nao foi possivel conectar no IP do dispositivo.") from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Nao foi possivel falar com o dispositivo: {exc}") from exc
    if resp.status_code in {401, 403}:
        _raise_device_auth_error()
    if _looks_like_auth_error(resp.text or ""):
        _raise_device_auth_error()
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Dispositivo respondeu com erro (HTTP {resp.status_code}): {(resp.text or '').strip()}",
        )
    return resp


def _is_intelbras_device(device: Dict[str, Any]) -> bool:
    vendor = str(device.get("vendor") or "").strip().lower()
    model = str(device.get("model") or "").strip().lower()
    return vendor == "intelbras" or model.startswith("asi") or "intelbras" in model


def _check_device_response(resp: requests.Response, action: str) -> str:
    if resp.status_code in {401, 403}:
        _raise_device_auth_error()
    text = (resp.text or "").strip()
    if _looks_like_auth_error(text):
        _raise_device_auth_error()
    if resp.status_code >= 400 or "Error" in text or "error" in text:
        raise HTTPException(status_code=502, detail=f"Dispositivo recusou {action}: {text}")
    return text


def _post_direto(device: Dict[str, Any], path_with_query: str, payload: Dict[str, Any], action_label: str):
    """Escreve no dispositivo pelo tunel, com Digest."""
    url = f"{_base_url_direct(device)}{path_with_query}"
    try:
        # Escrita precisa de mais folego que leitura: enviar foto facial faz a
        # controladora processar biometria, e passa MUITO dos 10s de _TIMEOUT.
        # Sem isso o POST estoura, cai no agente e falha por Digest -- era o que
        # deixava o sync das pessoas em "falhou".
        return requests.post(url, auth=_auth(device), json=payload, timeout=_CONNECTOR_JOB_TIMEOUT)
    except requests.ConnectTimeout as exc:
        raise _TunelIndisponivel("tempo esgotado ao conectar") from exc
    except requests.ConnectionError as exc:
        raise _TunelIndisponivel("nao foi possivel conectar") from exc
    except requests.RequestException as exc:
        raise _TunelIndisponivel(str(exc)) from exc


def _post_json(device: Dict[str, Any], path_with_query: str, payload: Dict[str, Any], action_label: str) -> str:
    if _connector_id(device):
        # Tunel primeiro, pela mesma regra da leitura: so quando o IP e
        # comprovadamente daquele conector. O agente RouterOS nao fala Digest,
        # entao por ele a escrita nunca completa.
        if _host_no_inventario_do_conector(device) or _has_vnat_mapping(device):
            try:
                return _check_device_response(
                    _post_direto(device, path_with_query, payload, action_label), action_label
                )
            except _TunelIndisponivel:
                pass  # tunel fora do ar: vale tentar pelo agente
        return _check_device_response(_post_json_via_connector(device, path_with_query, payload, action_label), action_label)
    url = f"{_base_url(device)}{path_with_query}"
    try:
        resp = requests.post(url, auth=_auth(device), json=payload, timeout=_TIMEOUT)
    except requests.ConnectTimeout as exc:
        raise HTTPException(status_code=502, detail="Tempo esgotado ao conectar no IP do dispositivo.") from exc
    except requests.ConnectionError as exc:
        raise HTTPException(status_code=502, detail="Nao foi possivel conectar no IP do dispositivo.") from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Nao foi possivel {action_label} no dispositivo: {exc}") from exc
    return _check_device_response(resp, action_label)


def _parse_kv_text(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _parse_record_table(text: str) -> List[Dict[str, str]]:
    records: Dict[int, Dict[str, str]] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        match = re.match(r"^records\[(\d+)\]\.(.+)$", key.strip())
        if not match:
            continue
        index = int(match.group(1))
        field = match.group(2).strip()
        records.setdefault(index, {})[field] = value.strip()
    return [records[index] for index in sorted(records)]


def _timestamp_to_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text)).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return text
    return text


def _timestamp_number(value: Any) -> int:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else 0


def _event_start_timestamp(device: Dict[str, Any], since_number: int) -> int:
    latest = str(device.get("last_event_start_time") or "").strip()
    if since_number and latest:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(latest[:19], fmt)
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                if dt.date() < today_start.date():
                    return max(0, int(today_start.timestamp()) - _ACCESS_REC_CURSOR_OVERLAP_SECONDS)
                return max(0, int(dt.timestamp()) - _ACCESS_REC_CURSOR_OVERLAP_SECONDS)
            except ValueError:
                continue
    return int((datetime.now() - timedelta(days=_ACCESS_REC_LOOKBACK_DAYS)).timestamp())


def _record_finder_found_count(text: str) -> int:
    match = re.search(r"(?:^|\n)found=(\d+)", text or "")
    return int(match.group(1)) if match else 0


def _fetch_access_event_rows(device: Dict[str, Any], since_id: str = "") -> List[Dict[str, str]]:
    """Le historico Intelbras sem ficar preso no primeiro bloco de 1024 eventos.

    Algumas controladoras ASI retornam sempre os primeiros registros quando a
    consulta nao informa StartTime, mesmo com `count` maior que 1024. Por isso,
    quando fazemos polling incremental, buscamos tambem uma janela recente por
    timestamp e filtramos por RecNo depois.
    """
    queries: List[Dict[str, Any]] = [
        {"action": "find", "name": "AccessControlCardRec"},
    ]
    since_number = int(since_id) if str(since_id or "").isdigit() else 0
    start_time = _event_start_timestamp(device, since_number)
    page_limit = 50 if _connector_id(device) else _ACCESS_REC_LIMIT
    recent_query = {
        "action": "find",
        "name": "AccessControlCardRec",
        "StartTime": str(start_time),
        "count": str(page_limit),
    }
    # Com cursor salvo, a janela recente e a parte que interessa. Sem cursor,
    # mantemos tambem a leitura antiga para preservar importacao inicial.
    if since_number:
        queries = [recent_query]
    else:
        queries.append(recent_query)

    rows_by_id: Dict[str, Dict[str, str]] = {}
    for params in queries:
        guard = 0
        current_params = dict(params)
        while guard < 8:
            guard += 1
            resp = _get(device, "/cgi-bin/recordFinder.cgi", current_params)
            text = (resp.text or "").strip()
            if not text:
                break
            if text.startswith("Error"):
                raise HTTPException(status_code=502, detail=f"Dispositivo respondeu com erro ao listar eventos: {text}")
            found_count = _record_finder_found_count(text)
            rows = _parse_record_table(text)
            if not rows:
                break
            for row in rows:
                raw_id = _first_text(row, "RecNo", "RecordNo", "ID")
                if raw_id:
                    rows_by_id[raw_id] = row
            if (found_count < page_limit and len(rows) < page_limit) or "StartTime" not in current_params:
                break
            max_ts = max(_timestamp_number(_first_text(row, "CreateTime", "Time", "UTC")) for row in rows)
            if max_ts <= int(current_params.get("StartTime") or 0):
                break
            current_params["StartTime"] = str(max_ts + 1)
    return sorted(rows_by_id.values(), key=lambda row: int(_first_text(row, "RecNo", "RecordNo", "ID") or "0"))


def _photo_data_from_access_face_text(text: str) -> bytes | None:
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if not key.strip().lower().endswith(".photodata[0]"):
            continue
        encoded = value.strip()
        if not encoded:
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
        except Exception:
            continue
        if data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG") or data.startswith(b"RIFF"):
            return data
    return None


def _first_text(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def list_controller_people(device: Dict[str, Any]) -> List[Dict[str, str]]:
    if not _is_intelbras_device(device):
        raise HTTPException(status_code=400, detail="Importacao de pessoas homologada apenas para Intelbras.")
    resp = _get(device, "/cgi-bin/recordFinder.cgi", {"action": "find", "name": "AccessControlCard"})
    people: List[Dict[str, str]] = []
    for row in _parse_record_table(resp.text):
        user_id = _first_text(row, "UserID", "RecNo")
        name = _first_text(row, "CardName", "UserName", "Name")
        if not user_id or not name:
            continue
        people.append(
            {
                "controller_user_id": "".join(ch for ch in user_id if ch.isdigit()),
                "full_name": name,
                "document_id": _first_text(row, "CitizenIDNo"),
                "card_no": _first_text(row, "CardNo"),
                "rec_no": _first_text(row, "RecNo"),
                "valid_from": _first_text(row, "ValidDateStart"),
                "valid_to": _first_text(row, "ValidDateEnd"),
                "raw_active": _first_text(row, "CardStatus", "UserStatus"),
            }
        )
    return people


def get_controller_person_photo(device: Dict[str, Any], controller_user_id: str) -> bytes | None:
    if not _is_intelbras_device(device):
        raise HTTPException(status_code=400, detail="Importacao de fotos homologada apenas para Intelbras.")
    user_id = "".join(ch for ch in str(controller_user_id or "") if ch.isdigit())
    if not user_id:
        return None
    try:
        resp = _get(device, "/cgi-bin/AccessFace.cgi", {"action": "list", "UserIDList[0]": user_id})
    except HTTPException as exc:
        if exc.status_code in {400, 404, 502}:
            return None
        raise
    return _photo_data_from_access_face_text(resp.text)


def get_system_info(device: Dict[str, Any]) -> Dict[str, str]:
    resp = _get(device, "/cgi-bin/magicBox.cgi", {"action": "getSystemInfo"})
    return _parse_kv_text(resp.text)


def open_door(device: Dict[str, Any], channel: int = 1) -> Dict[str, Any]:
    resp = _get(
        device,
        "/cgi-bin/accessControl.cgi",
        {"action": "openDoor", "channel": int(channel or 1), "UserID": "SightOps", "Type": "Remote"},
    )
    text = (resp.text or "").strip()
    if text.upper().startswith("ERROR") or "Error" in text:
        raise HTTPException(status_code=502, detail=f"Dispositivo recusou abrir a porta: {text}")
    return {"ok": True, "raw": text}


def _provision_intelbras_person(
    device: Dict[str, Any], person: Dict[str, Any], photo_bytes: bytes | None = None
) -> Dict[str, Any]:
    full_name = str(person.get("full_name") or "").strip()
    controller_user_id = "".join(ch for ch in str(person.get("controller_user_id") or "") if ch.isdigit())
    if not full_name:
        raise HTTPException(status_code=400, detail="Pessoa sem nome para provisionar.")
    if not controller_user_id:
        raise HTTPException(status_code=400, detail="Informe o ID na controladora para provisionar na Intelbras.")

    user_payload = {
        "UserList": [
            {
                "UserID": controller_user_id,
                "UserName": full_name,
                "UserType": 0,
                "UseTime": 200,
                "IsFirstEnter": False,
                "UserStatus": 1 if person.get("active") is False else 0,
                "Authority": 2,
                "CitizenIDNo": "",
                "Password": "123456",
                "Doors": [0],
                "TimeSections": [0],
                "ValidFrom": "2024-08-01 00:00:00",
                "ValidTo": "2034-08-01 23:59:59",
            }
        ]
    }
    card_text = _post_json(
        device,
        "/cgi-bin/AccessUser.cgi?action=insertMulti",
        user_payload,
        "o cadastro do usuario",
    )

    face_text = ""
    if photo_bytes:
        payload = {
            "FaceList": [
                {
                    "UserID": controller_user_id,
                    "PhotoData": [base64.b64encode(photo_bytes).decode("ascii")],
                }
            ]
        }
        try:
            face_text = _post_json(device, "/cgi-bin/AccessFace.cgi?action=insertMulti", payload, "a face")
        except HTTPException as exc:
            if "Batch Process Error" not in str(exc.detail):
                raise
            face_text = _post_json(device, "/cgi-bin/AccessFace.cgi?action=updateMulti", payload, "a face")

    return {"ok": True, "raw": card_text, "face_raw": face_text, "controller_user_id": controller_user_id}


def provision_person(device: Dict[str, Any], person: Dict[str, Any], photo_bytes: bytes | None = None) -> Dict[str, Any]:
    full_name = str(person.get("full_name") or "").strip()
    person_id = str(person.get("id") or "").strip()
    if not full_name or not person_id:
        raise HTTPException(status_code=400, detail="Pessoa sem nome/id para provisionar.")
    if _is_intelbras_device(device):
        return _provision_intelbras_person(device, person, photo_bytes)
    info = {
        "UserID": person_id,
        "UserName": full_name,
        "UserType": 0,
        "Doors": [0],
        "ValidFrom": "2020-01-01 00:00:00",
        "ValidTo": "2037-12-31 23:59:59",
    }
    files = {"json": (None, json.dumps({"action": "insertMulti", "Info": [info]}))}
    if photo_bytes:
        files["Photo"] = ("face.jpg", photo_bytes, "image/jpeg")
    url = f"{_base_url(device)}/cgi-bin/AccessUser.cgi"
    try:
        resp = requests.post(url, auth=_auth(device), files=files, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Nao foi possivel provisionar no dispositivo: {exc}") from exc
    if resp.status_code == 401:
        _raise_device_auth_error()
    text = (resp.text or "").strip()
    if resp.status_code >= 400 or "Error" in text or "error" in text:
        raise HTTPException(status_code=502, detail=f"Dispositivo recusou o cadastro: {text}")
    return {"ok": True, "raw": text}


def remove_person(device: Dict[str, Any], person_id: str) -> Dict[str, Any]:
    if _is_intelbras_device(device):
        resp = _get(
            device,
            "/cgi-bin/AccessUser.cgi",
            {"action": "removeMulti", "UserIDList[0]": str(person_id)},
        )
        text = _check_device_response(resp, "a remocao")
        return {"ok": True, "raw": text}
    if _connector_id(device):
        text = _post_json(
            device,
            "/cgi-bin/AccessUser.cgi?action=removeMulti",
            {"UserIDList": [str(person_id)]},
            "a remocao",
        )
        return {"ok": True, "raw": text}
    url = f"{_base_url(device)}/cgi-bin/AccessUser.cgi"
    files = {"json": (None, json.dumps({"action": "removeMulti", "UserIDList": [str(person_id)]}))}
    try:
        resp = requests.post(url, auth=_auth(device), files=files, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Nao foi possivel remover no dispositivo: {exc}") from exc
    text = (resp.text or "").strip()
    if resp.status_code == 401:
        _raise_device_auth_error()
    if resp.status_code >= 400 or "Error" in text or "error" in text:
        raise HTTPException(status_code=502, detail=f"Dispositivo recusou a remocao: {text}")
    return {"ok": True, "raw": text}


def poll_events(device: Dict[str, Any], since_id: str = "") -> List[Dict[str, Any]]:
    """Busca historico de acesso em controladoras Intelbras.

    Em controladoras ASI/Intelbras primeiro, `eventManager.cgi` pode responder
    "No Events" mesmo com historico gravado. O historico real confirmado ao vivo
    fica em `recordFinder.cgi?action=find&name=AccessControlCardRec`.
    """
    if not _is_intelbras_device(device):
        raise HTTPException(status_code=400, detail="Coleta de eventos homologada apenas para Intelbras.")
    events: List[Dict[str, Any]] = []
    since_number = int(since_id) if str(since_id or "").isdigit() else 0
    for row in _fetch_access_event_rows(device, since_id=since_id):
        raw_id = _first_text(row, "RecNo", "RecordNo", "ID")
        if not raw_id:
            continue
        if since_number and raw_id.isdigit() and int(raw_id) <= since_number:
            continue
        status = _first_text(row, "Status")
        if status and status not in {"1", "true", "True", "OK", "ok"}:
            continue
        raw_type = _first_text(row, "Type").lower()
        event_type = "saida" if raw_type in {"exit", "out", "leave", "saida"} else "entrada"
        events.append(
            {
                "raw_id": raw_id,
                "occurred_at": _timestamp_to_text(_first_text(row, "CreateTime", "Time", "UTC")),
                "person_name_raw": _first_text(row, "CardName", "UserName", "Name"),
                "user_id": _first_text(row, "UserID"),
                "card_no": _first_text(row, "CardNo"),
                "event_type": event_type,
                "status": status,
                "method": _first_text(row, "Method"),
                "door": _first_text(row, "Door"),
                "reader_id": _first_text(row, "ReaderID"),
            }
        )
    return events
