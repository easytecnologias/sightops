"""Modulo Alerta: botao de panico/coacao do celular + atendimento da central.

Tres atores, tres portas de entrada:

  - o APP do servidor publico (professor/funcionario). Nao tem login do
    SightOps: ativa com um codigo de uso unico gerado pela central e recebe um
    token de aparelho. Toda chamada do app chega sem tenant no contexto -- o
    tenant sai da sessao do aparelho (`resolve_app_session`).
  - a CENTRAL (Guarda Municipal) no SightOps: usuario logado, tenant no
    contexto como em qualquer outra tela.
  - o LOOP de escalonamento: roda sem request, varre todos os tenants e so
    entra no contexto de cada um na hora de mandar o Telegram.

Coacao: a pessoa "cancela" o alerta digitando a senha de coacao em vez da
senha normal. O app mostra exatamente a mesma tela de "cancelado" nos dois
casos -- quem decide e o servidor, e a resposta pro app nao muda de formato.
Nunca retornar nada que um assaltante olhando a tela consiga distinguir.

Privacidade: posicao so e aceita para alerta ABERTO. Fora de alerta o app nao
manda e o servidor nao guarda localizacao nenhuma.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug, tenant_scoped_path
from app.services import db_store

logger = logging.getLogger("cam-snapshot")

OPEN_STATUSES = ("new", "acknowledged", "dispatched")
FINAL_STATUSES = ("closed", "cancelled")
ESCALATION_AFTER_S = 60
RECENT_FINAL_WINDOW_MIN = 30
ACTIVATION_TTL_DAYS = 7
# Alfabeto sem 0/O/1/I/L: codigo e ditado por telefone ou lido de papel.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8
_PIN_RE = re.compile(r"^\d{4,8}$")


# --------------------------------------------------------------------------
# utilitarios
# --------------------------------------------------------------------------

def _now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return _iso(_now_dt())


def _text(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def _cpf(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))[:11]


def _phone(value: Any) -> str:
    return re.sub(r"[^\d+]", "", str(value or ""))[:32]


def _float_or_none(value: Any) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        out = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _coord(value: Any, limit: float) -> Optional[float]:
    out = _float_or_none(value)
    if out is None or abs(out) > limit:
        return None
    return out


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_pin(pin: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"pbkdf2${salt}${digest}"


def _check_pin(pin: str, stored: str) -> bool:
    try:
        algo, salt, digest = str(stored or "").split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2":
        return False
    calc = hashlib.pbkdf2_hmac("sha256", str(pin or "").encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(calc, digest)


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _rows(c: Any, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def _row(c: Any, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    r = c.execute(sql, params).fetchone()
    return dict(r) if r else None


def _log(c: Any, tenant: str, incident_id: str, action: str, actor: str = "", note: str = "") -> None:
    c.execute(
        "INSERT INTO alert_incident_log(tenant_slug, incident_id, action, actor, note, created_at) VALUES(?,?,?,?,?,?)",
        (tenant, incident_id, action, _text(actor, 120), _text(note, 2000), _now()),
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# pessoas (cadastro feito pela central)
# --------------------------------------------------------------------------

_MEMBER_PUBLIC_COLS = (
    "id, tenant_slug, full_name, document_id, role_title, unit_name, unit_lat, unit_lon, unit_connector_id, "
    "phone, notes, active, camera_radius_m, pin_hash, activation_code_hash, activation_expires_at, created_at, updated_at"
)

# Raio das cameras por pessoa: 0 = padrao (NEARBY_RADIUS_M). Fora disso, de 5 a 500 m.
CAMERA_RADIUS_MIN_M = 5
CAMERA_RADIUS_MAX_M = 500


def _camera_radius(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        n = int(round(float(str(value).replace(",", "."))))
    except (TypeError, ValueError):
        raise ValueError("Raio das cameras: informe um numero de metros.")
    if n <= 0:
        return 0
    if n < CAMERA_RADIUS_MIN_M or n > CAMERA_RADIUS_MAX_M:
        raise ValueError(f"Raio das cameras: entre {CAMERA_RADIUS_MIN_M} e {CAMERA_RADIUS_MAX_M} m (ou vazio para o padrao).")
    return n


# --------------------------------------------------------------------------
# foto da pessoa (a central reconhece quem pediu ajuda nas cameras)
# --------------------------------------------------------------------------
# Arquivo JPEG reduzido na pasta do cliente (tenant_scoped_path). Sem coluna no
# banco: a versao da foto e o mtime do arquivo (cache-bust da tela).

FOTO_MAX_BYTES = 6 * 1024 * 1024   # o que chega do navegador (antes de reduzir)
FOTO_LADO_PX = 640


def _foto_path(member_id: str, tenant: str = "") -> "Path":
    limpo = re.sub(r"[^A-Za-z0-9_-]", "", str(member_id or ""))[:80]
    if not limpo:
        raise ValueError("Pessoa invalida.")
    return tenant_scoped_path(f"alert_fotos/{limpo}.jpg", tenant)


def _foto_versao(member_id: str, tenant: str = "") -> int:
    try:
        return int(_foto_path(member_id, tenant).stat().st_mtime)
    except (OSError, ValueError):
        return 0


def salvar_foto_membro(member_id: str, data_url: str) -> Dict[str, Any]:
    """Grava (ou remove, com `data_url` vazio) a foto da pessoa."""
    import base64
    import io

    from PIL import Image, ImageOps

    tenant = _tenant()
    with db_store._conn() as c:
        _exigir_membro_liberado(c, tenant, member_id)
    path = _foto_path(member_id, tenant)
    bruto = str(data_url or "").strip()
    if not bruto:
        path.unlink(missing_ok=True)
        return {"foto_v": 0}
    if bruto.startswith("data:"):
        bruto = bruto.split(",", 1)[-1]
    try:
        dados = base64.b64decode(bruto, validate=False)
    except ValueError:
        raise ValueError("Foto invalida.")
    if not dados or len(dados) > FOTO_MAX_BYTES:
        raise ValueError("Foto grande demais (maximo 6 MB).")
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()
    except Exception:
        raise ValueError("Arquivo nao e uma imagem (use JPG ou PNG).")
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((FOTO_LADO_PX, FOTO_LADO_PX))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    img.save(tmp, "JPEG", quality=85, optimize=True)
    tmp.replace(path)
    return {"foto_v": _foto_versao(member_id, tenant)}


def caminho_foto_membro(member_id: str) -> Optional["Path"]:
    """Arquivo da foto, so se a pessoa e do cliente e de um site do usuario."""
    tenant = _tenant()
    with db_store._conn() as c:
        _exigir_membro_liberado(c, tenant, member_id)
    path = _foto_path(member_id, tenant)
    return path if path.is_file() else None


def _member_public(row: Dict[str, Any], active_sessions: int = 0) -> Dict[str, Any]:
    pending_code = bool(row.get("activation_code_hash")) and str(row.get("activation_expires_at") or "") > _now()
    return {
        "foto_v": _foto_versao(row["id"], row.get("tenant_slug") or ""),
        "id": row["id"],
        "full_name": row.get("full_name") or "",
        "document_id": row.get("document_id") or "",
        "role_title": row.get("role_title") or "",
        "unit_name": row.get("unit_name") or "",
        "unit_lat": row.get("unit_lat"),
        "unit_lon": row.get("unit_lon"),
        "unit_connector_id": row.get("unit_connector_id") or "",
        "phone": row.get("phone") or "",
        "notes": row.get("notes") or "",
        "active": bool(int(row.get("active") or 0)),
        "camera_radius_m": int(row.get("camera_radius_m") or 0),
        "pins_configured": bool(row.get("pin_hash")),
        "activation_pending": pending_code,
        "activation_expires_at": row.get("activation_expires_at") if pending_code else "",
        "app_devices": int(active_sessions or 0),
        "site": site_do_membro(row),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


# --------------------------------------------------------------------------
# site da pessoa (restricao por site do usuario da central)
# --------------------------------------------------------------------------
# O site de uma pessoa e o do conector da lotacao dela (o "local monitorado");
# sem conector, o nome da lotacao -- mesma regra do Telegram (_site_do_alerta).
# O resumo roda a cada 1,5 s em todas as telas: o site do conector fica em
# cache curto, com o tenant na chave.

_SITE_CONECTOR_CACHE: Dict[Tuple[str, str], Tuple[float, str]] = {}
_SITE_CONECTOR_TTL_S = 30.0


def _site_do_conector(cid: str) -> str:
    cid = str(cid or "").strip()
    if not cid:
        return ""
    chave = (_tenant(), cid)
    agora = time.monotonic()
    hit = _SITE_CONECTOR_CACHE.get(chave)
    if hit and agora - hit[0] < _SITE_CONECTOR_TTL_S:
        return hit[1]
    try:
        from app.services.connector_service import get_connector

        site = str((get_connector(cid, include_token=False, enforce_tenant=True) or {}).get("site") or "").strip()
    except Exception:
        logger.warning("alerta: nao deu para ler o site do conector %s", cid, exc_info=True)
        return ""  # sem guardar: tenta de novo na proxima
    _SITE_CONECTOR_CACHE[chave] = (agora, site)
    return site


def site_do_membro(m: Optional[Dict[str, Any]]) -> str:
    """Com conector, vale SO o site do conector: cair no nome da lotacao (texto
    livre) quando a leitura falha poderia mostrar a pessoa ao site errado."""
    m = m or {}
    cid = str(m.get("unit_connector_id") or "").strip()
    if cid:
        return _site_do_conector(cid)
    return str(m.get("unit_name") or "").strip()


def _sites_liberados() -> Optional[set]:
    """None = ve todos (sem restricao, dono, app do celular, laco de fundo)."""
    from app.core import permissions

    sites = permissions.sites_da_sessao()
    if sites is None:
        return None
    return {str(s).strip().upper() for s in sites if str(s).strip()}


def _membro_liberado(m: Optional[Dict[str, Any]], liberados: Optional[set]) -> bool:
    """Com restricao, pessoa sem site definido fica de fora (na duvida, nao mostra)."""
    if liberados is None:
        return True
    site = site_do_membro(m).upper()
    return bool(site) and site in liberados


def _exigir_membro_liberado(c: Any, tenant: str, member_id: str) -> Dict[str, Any]:
    """Pessoa do cliente E de um site do usuario; senao 'nao encontrada' (nao
    conta que existe em outro site)."""
    row = _row(
        c,
        "SELECT id, active, unit_name, unit_connector_id FROM alert_members WHERE tenant_slug=? AND id=?",
        (tenant, member_id),
    )
    if not row or not _membro_liberado(row, _sites_liberados()):
        raise ValueError("Pessoa nao encontrada.")
    return row


def list_members(search: str = "") -> List[Dict[str, Any]]:
    tenant = _tenant()
    where, params = ["tenant_slug = ?"], [tenant]
    term = _text(search, 120).lower()
    if term:
        like = f"%{term}%"
        where.append("(lower(full_name) LIKE ? OR document_id LIKE ? OR lower(unit_name) LIKE ? OR lower(role_title) LIKE ?)")
        params += [like, like, like, like]
    with db_store._conn() as c:
        rows = _rows(c, f"SELECT {_MEMBER_PUBLIC_COLS} FROM alert_members WHERE {' AND '.join(where)} ORDER BY full_name", tuple(params))
        sessions = _rows(
            c,
            "SELECT member_id, platform, last_seen_at, gps_permission, battery, app_version, checkin_at "
            "FROM alert_app_sessions WHERE tenant_slug = ? AND revoked_at = ''",
            (tenant,),
        )
    # Por pessoa: quantos aparelhos e o que deu sinal por ultimo (e o que vale
    # para a prontidao -- um celular velho esquecido nao derruba quem usa o novo).
    by_member: Dict[str, Dict[str, Any]] = {}
    for s in sessions:
        atual = by_member.setdefault(s["member_id"], {"n": 0, "ultimo": None})
        atual["n"] += 1
        if atual["ultimo"] is None or str(s.get("last_seen_at") or "") > str(atual["ultimo"].get("last_seen_at") or ""):
            atual["ultimo"] = s
    liberados = _sites_liberados()
    out = []
    for r in rows:
        if not _membro_liberado(r, liberados):
            continue
        info = by_member.get(r["id"]) or {"n": 0, "ultimo": None}
        m = _member_public(r, info["n"])
        m["device"] = _device_public(info["ultimo"])
        m["prontidao"] = prontidao_do_membro(m)
        m["ponto"] = _ponto_do_membro(m)
        out.append(m)
    return out


# --------------------------------------------------------------------------
# mapa da central: onde fica cada lotacao e as cameras dos locais
# --------------------------------------------------------------------------
# Quase ninguem cadastra latitude/longitude da lotacao, mas as cameras do
# local monitorado quase sempre tem. Sem coordenada propria, a lotacao vai
# para o centro das cameras do conector. Ler os tres inventarios a cada
# consulta pesa: cache curto por tenant.

_CAMS_MAPA_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CAMS_MAPA_TTL_S = 60.0


def _cameras_com_coordenada() -> List[Dict[str, Any]]:
    tenant = _tenant()
    agora = time.monotonic()
    hit = _CAMS_MAPA_CACHE.get(tenant)
    if hit and agora - hit[0] < _CAMS_MAPA_TTL_S:
        return hit[1]
    lista: List[Dict[str, Any]] = []
    for _mode, r in _inventory_cameras():
        lat = _coord(r.get("lat") or r.get("latitude"), 90)
        lon = _coord(r.get("lon") or r.get("lng") or r.get("longitude"), 180)
        if lat is None or lon is None:
            continue
        lista.append({
            "lat": lat, "lon": lon,
            "titulo": _text(r.get("titulo") or r.get("nome"), 120) or "Camera",  # nunca o IP
            "connector": _text(r.get("remote_connector_id") or r.get("connector_id"), 80),
            "site": _text(r.get("site") or r.get("site_name") or r.get("local") or r.get("LOCAL"), 160),
            "status": _text(r.get("status"), 20),
        })
    _CAMS_MAPA_CACHE[tenant] = (agora, lista)
    return lista


def _centro_do_conector(cid: str) -> Optional[Tuple[float, float, int]]:
    pts = [(c["lat"], c["lon"]) for c in _cameras_com_coordenada() if c["connector"] == cid]
    if not pts:
        return None
    # Mediana, nao media: uma camera com coordenada errada (outra cidade) nao
    # arrasta o ponto para o meio do nada.
    lats = sorted(p[0] for p in pts)
    lons = sorted(p[1] for p in pts)
    meio = len(pts) // 2
    return lats[meio], lons[meio], len(pts)


def _ponto_do_membro(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if m.get("unit_lat") is not None and m.get("unit_lon") is not None:
        return {"lat": m["unit_lat"], "lon": m["unit_lon"], "origem": "lotacao"}
    cid = str(m.get("unit_connector_id") or "").strip()
    if not cid:
        return None
    c = _centro_do_conector(cid)
    if not c:
        return None
    return {"lat": c[0], "lon": c[1], "origem": "cameras", "cameras": c[2]}


def cameras_do_mapa(limite: int = 1500) -> List[Dict[str, Any]]:
    """Cameras com coordenada dos locais monitorados das pessoas que o usuario
    ve. So o necessario para desenhar um ponto (sem IP, sem credencial)."""
    from app.core import permissions

    cids = {str(m.get("unit_connector_id") or "") for m in list_members() if m.get("active")}
    cids.discard("")
    if not cids:
        return []
    cams = [c for c in _cameras_com_coordenada() if c["connector"] in cids]
    cams = permissions.filtrar_por_site(cams, ("site",))
    return [{k: c[k] for k in ("lat", "lon", "titulo", "site", "status")} for c in cams[: max(1, int(limite))]]


# Abaixo disso de dias sem abrir o app, a central desconfia do celular: app
# desinstalado, trocou de aparelho, sessao perdida. O app so da sinal quando abre.
SINAL_MAX_DIAS = 7


def _device_public(s: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    return {
        "platform": s.get("platform") or "",
        "last_seen_at": s.get("last_seen_at") or "",
        "gps_permission": s.get("gps_permission") or "",
        "battery": s.get("battery"),
        "app_version": s.get("app_version") or "",
        "checkin_at": s.get("checkin_at") or "",
    }


def prontidao_do_membro(m: Dict[str, Any], agora: Optional[datetime] = None) -> Dict[str, Any]:
    """A pessoa consegue pedir ajuda AGORA, e a central consegue ve-la?

    Cada pendencia tem um codigo (a tela decide icone/cor) e um texto curto.
    `bloqueia`: sem isso o botao nao funciona; o resto so piora o atendimento."""
    agora = agora or _now_dt()
    pend: List[Dict[str, Any]] = []

    def add(codigo: str, texto: str, bloqueia: bool = True) -> None:
        pend.append({"codigo": codigo, "texto": texto, "bloqueia": bloqueia})

    dev = m.get("device") or {}
    if not m.get("active"):
        add("inativo", "Cadastro inativo")
    elif not m.get("app_devices"):
        add("sem_app", "Codigo gerado, ainda nao ativou" if m.get("activation_pending") else "Nunca ativou o app")
    else:
        if not m.get("pins_configured"):
            add("sem_senha", "Ativou, mas nao criou as senhas")
        if dev.get("gps_permission") == "denied":
            add("gps_bloqueado", "Localizacao bloqueada no celular")
        visto = None
        try:
            visto = datetime.fromisoformat(str(dev.get("last_seen_at") or "").replace("Z", "+00:00"))
        except ValueError:
            pass
        if visto is None:
            add("sem_sinal", "App nunca deu sinal")
        else:
            dias = (agora - visto).total_seconds() / 86400
            if dias > SINAL_MAX_DIAS:
                add("sem_sinal", f"Nao abre o app ha {int(dias)} dias")
        bat = dev.get("battery")
        if isinstance(bat, (int, float)) and bat < 15:
            add("bateria", f"Bateria em {int(bat)}% no ultimo sinal", bloqueia=False)
    if m.get("active") and not m.get("unit_connector_id"):
        add("sem_cameras", "Sem cameras na lotacao", bloqueia=False)
    return {"pronta": not any(p["bloqueia"] for p in pend), "pendencias": pend}


def save_member(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    member_id = _text(payload.get("id"), 80)
    full_name = _text(payload.get("full_name"), 160)
    if not full_name:
        raise ValueError("Informe o nome da pessoa.")
    document_id = _cpf(payload.get("document_id"))
    if len(document_id) != 11:
        raise ValueError("Informe o CPF com 11 digitos.")
    unit_lat = _coord(payload.get("unit_lat"), 90)
    unit_lon = _coord(payload.get("unit_lon"), 180)
    if (unit_lat is None) != (unit_lon is None):
        raise ValueError("Informe latitude e longitude da lotacao juntas (ou deixe as duas vazias).")
    values = {
        "full_name": full_name,
        "document_id": document_id,
        "role_title": _text(payload.get("role_title"), 120),
        "unit_name": _text(payload.get("unit_name"), 160),
        "unit_lat": unit_lat,
        "unit_lon": unit_lon,
        "unit_connector_id": _text(payload.get("unit_connector_id"), 80),
        "phone": _phone(payload.get("phone")),
        "notes": _text(payload.get("notes"), 1000),
        "active": 0 if payload.get("active") is False else 1,
        "camera_radius_m": _camera_radius(payload.get("camera_radius_m")),
    }
    liberados = _sites_liberados()
    if liberados is not None and not _membro_liberado(values, liberados):
        # Quem so ve alguns sites so cadastra gente nesses sites -- senao a
        # pessoa some da lista dele na hora de salvar e ninguem entende.
        raise ValueError("Escolha o local monitorado: voce so cadastra pessoas dos seus sites.")
    now = _now()
    with db_store._conn() as c:
        dup = _row(
            c,
            "SELECT id, full_name FROM alert_members WHERE tenant_slug = ? AND document_id = ? AND id <> ?",
            (tenant, document_id, member_id),
        )
        if dup:
            if liberados is not None:
                dono = _row(c, "SELECT unit_name, unit_connector_id FROM alert_members WHERE tenant_slug=? AND id=?",
                            (tenant, dup["id"]))
                if not _membro_liberado(dono, liberados):
                    # Nao revela quem esta cadastrado em site que ele nao ve.
                    raise ValueError("CPF ja cadastrado em outro local. Fale com o administrador.")
            raise ValueError(f"CPF ja cadastrado para {dup['full_name']}.")
        if member_id:
            _exigir_membro_liberado(c, tenant, member_id)
            c.execute(
                "UPDATE alert_members SET full_name=?, document_id=?, role_title=?, unit_name=?, unit_lat=?, unit_lon=?, unit_connector_id=?, "
                "phone=?, notes=?, active=?, camera_radius_m=?, updated_at=? WHERE tenant_slug=? AND id=?",
                (*values.values(), now, tenant, member_id),
            )
            if not values["active"]:
                # Desativou a pessoa: o celular dela para de funcionar na hora.
                c.execute(
                    "UPDATE alert_app_sessions SET revoked_at=? WHERE tenant_slug=? AND member_id=? AND revoked_at=''",
                    (now, tenant, member_id),
                )
        else:
            member_id = uuid.uuid4().hex
            c.execute(
                "INSERT INTO alert_members(id, tenant_slug, full_name, document_id, role_title, unit_name, unit_lat, unit_lon, "
                "unit_connector_id, phone, notes, active, camera_radius_m, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (member_id, tenant, *values.values(), now, now),
            )
        row = _row(c, f"SELECT {_MEMBER_PUBLIC_COLS} FROM alert_members WHERE tenant_slug = ? AND id = ?", (tenant, member_id))
    return _member_public(row or {})


def delete_member(member_id: str) -> None:
    tenant = _tenant()
    with db_store._conn() as c:
        _exigir_membro_liberado(c, tenant, member_id)
        open_inc = _row(
            c,
            f"SELECT id FROM alert_incidents WHERE tenant_slug=? AND member_id=? AND status IN ({','.join('?' * len(OPEN_STATUSES))})",
            (tenant, member_id, *OPEN_STATUSES),
        )
        if open_inc:
            raise ValueError("Essa pessoa tem alerta em aberto. Encerre o alerta antes de excluir.")
        c.execute("UPDATE alert_app_sessions SET revoked_at=? WHERE tenant_slug=? AND member_id=? AND revoked_at=''", (_now(), tenant, member_id))
        c.execute("DELETE FROM alert_members WHERE tenant_slug=? AND id=?", (tenant, member_id))


def create_activation_code(member_id: str) -> Dict[str, Any]:
    """Gera o codigo que a pessoa digita no app. Uso unico, vale 7 dias.

    Gerar um codigo novo NAO derruba o celular ja ativado -- serve pra ativar
    um aparelho adicional ou trocar de celular. Pra bloquear, usar revoke.
    """
    tenant = _tenant()
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
    expires = _iso(_now_dt() + timedelta(days=ACTIVATION_TTL_DAYS))
    with db_store._conn() as c:
        row = _exigir_membro_liberado(c, tenant, member_id)
        if not int(row.get("active") or 0):
            raise ValueError("Pessoa inativa. Ative o cadastro antes de gerar o codigo.")
        c.execute(
            "UPDATE alert_members SET activation_code_hash=?, activation_expires_at=?, updated_at=? WHERE tenant_slug=? AND id=?",
            (_sha256(code), expires, _now(), tenant, member_id),
        )
    return {"code": code, "expires_at": expires}


def revoke_member_devices(member_id: str) -> int:
    tenant = _tenant()
    with db_store._conn() as c:
        _exigir_membro_liberado(c, tenant, member_id)
        n = _row(
            c,
            "SELECT COUNT(1) AS n FROM alert_app_sessions WHERE tenant_slug=? AND member_id=? AND revoked_at=''",
            (tenant, member_id),
        )
        c.execute("UPDATE alert_app_sessions SET revoked_at=? WHERE tenant_slug=? AND member_id=? AND revoked_at=''", (_now(), tenant, member_id))
    return int((n or {}).get("n") or 0)


# --------------------------------------------------------------------------
# app do celular
# --------------------------------------------------------------------------

class AppAuthError(Exception):
    pass


def _app_member_view(member: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "full_name": member.get("full_name") or "",
        "role_title": member.get("role_title") or "",
        "unit_name": member.get("unit_name") or "",
        "pins_configured": bool(member.get("pin_hash")),
    }


def activate_app(code: str, device_label: str = "", platform: str = "") -> Dict[str, Any]:
    clean = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
    if len(clean) != _CODE_LEN:
        raise AppAuthError("Codigo invalido.")
    now = _now()
    with db_store._conn() as c:
        member = _row(
            c,
            "SELECT * FROM alert_members WHERE activation_code_hash = ? AND activation_expires_at > ? AND active = 1",
            (_sha256(clean), now),
        )
        if not member:
            raise AppAuthError("Codigo invalido ou vencido. Peca um novo para a central.")
        token = secrets.token_urlsafe(32)
        c.execute(
            "INSERT INTO alert_app_sessions(id, tenant_slug, member_id, token_hash, device_label, platform, created_at, last_seen_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, member["tenant_slug"], member["id"], _sha256(token), _text(device_label, 120), _text(platform, 40), now, now),
        )
        c.execute(
            "UPDATE alert_members SET activation_code_hash='', activation_expires_at='', updated_at=? WHERE id=?",
            (now, member["id"]),
        )
    return {"token": token, "member": _app_member_view(member)}


def resolve_app_session(token: str) -> Dict[str, Any]:
    """Token do aparelho -> {tenant_slug, member}. Levanta AppAuthError."""
    raw = str(token or "").strip()
    if not raw:
        raise AppAuthError("Aparelho nao ativado.")
    with db_store._conn() as c:
        session = _row(c, "SELECT * FROM alert_app_sessions WHERE token_hash = ? AND revoked_at = ''", (_sha256(raw),))
        if not session:
            raise AppAuthError("Aparelho desativado. Peca um novo codigo para a central.")
        member = _row(
            c,
            "SELECT * FROM alert_members WHERE tenant_slug = ? AND id = ? AND active = 1",
            (session["tenant_slug"], session["member_id"]),
        )
        if not member:
            raise AppAuthError("Cadastro inativo. Procure a central.")
        c.execute("UPDATE alert_app_sessions SET last_seen_at=? WHERE id=?", (_now(), session["id"]))
    return {"tenant_slug": session["tenant_slug"], "member": member, "session_id": session["id"]}


def app_status(ctx: Dict[str, Any]) -> Dict[str, Any]:
    member = ctx["member"]
    with db_store._conn() as c:
        inc = _open_incident(c, ctx["tenant_slug"], member["id"])
    return {"member": _app_member_view(member), "incident": _app_incident_view(inc)}


_GPS_PERMISSOES = ("granted", "denied", "prompt")


def app_checkin(ctx: Dict[str, Any], gps_permission: str = "", battery: Any = None, app_version: str = "") -> None:
    """O app avisa, ao abrir, se a localizacao esta liberada e a bateria.

    Nao e posicao: nenhuma coordenada sai do celular fora de alerta."""
    gps = str(gps_permission or "").strip().lower()
    gps = gps if gps in _GPS_PERMISSOES else ""
    bat = _float_or_none(battery)
    bat_i = int(max(0, min(100, bat))) if bat is not None else None
    with db_store._conn() as c:
        c.execute(
            "UPDATE alert_app_sessions SET gps_permission=?, battery=?, app_version=?, checkin_at=?, last_seen_at=? "
            "WHERE id=? AND tenant_slug=? AND revoked_at=''",
            (gps, bat_i, _text(app_version, 40), _now(), _now(), ctx["session_id"], ctx["tenant_slug"]),
        )


def set_app_pins(ctx: Dict[str, Any], pin: str, duress_pin: str, current_pin: str = "") -> None:
    member = ctx["member"]
    pin, duress_pin = str(pin or "").strip(), str(duress_pin or "").strip()
    if not _PIN_RE.match(pin) or not _PIN_RE.match(duress_pin):
        raise ValueError("As senhas precisam ter de 4 a 8 numeros.")
    if pin == duress_pin:
        raise ValueError("A senha de coacao precisa ser diferente da senha normal.")
    if member.get("pin_hash") and not _check_pin(current_pin, member["pin_hash"]):
        raise ValueError("Senha atual incorreta.")
    with db_store._conn() as c:
        c.execute(
            "UPDATE alert_members SET pin_hash=?, duress_pin_hash=?, updated_at=? WHERE tenant_slug=? AND id=?",
            (_hash_pin(pin), _hash_pin(duress_pin), _now(), ctx["tenant_slug"], member["id"]),
        )


def _open_incident(c: Any, tenant: str, member_id: str) -> Optional[Dict[str, Any]]:
    return _row(
        c,
        f"SELECT * FROM alert_incidents WHERE tenant_slug=? AND member_id=? AND status IN ({','.join('?' * len(OPEN_STATUSES))}) "
        "ORDER BY opened_at DESC LIMIT 1",
        (tenant, member_id, *OPEN_STATUSES),
    )


def _app_incident_view(inc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # So o minimo. De proposito NAO inclui `kind`: em coacao o app nao pode
    # ter nenhum dado que revele que a central sabe.
    if not inc:
        return None
    return {"id": inc["id"], "opened_at": inc.get("opened_at") or "", "attended": inc.get("status") != "new"}


def _insert_position(c: Any, tenant: str, incident_id: str, pos: Dict[str, Any]) -> bool:
    lat, lon = _coord(pos.get("lat"), 90), _coord(pos.get("lon"), 180)
    if lat is None or lon is None:
        return False
    accuracy = _float_or_none(pos.get("accuracy"))
    battery = _float_or_none(pos.get("battery"))
    battery_i = int(max(0, min(100, battery))) if battery is not None else None
    now = _now()
    recorded = _text(pos.get("recorded_at"), 40) or now
    c.execute(
        "INSERT INTO alert_positions(tenant_slug, incident_id, lat, lon, accuracy, battery, recorded_at, received_at) VALUES(?,?,?,?,?,?,?,?)",
        (tenant, incident_id, lat, lon, accuracy, battery_i, recorded, now),
    )
    c.execute(
        "UPDATE alert_incidents SET last_lat=?, last_lon=?, last_accuracy=?, last_battery=COALESCE(?, last_battery), "
        "last_position_at=?, updated_at=? WHERE tenant_slug=? AND id=?",
        (lat, lon, accuracy, battery_i, recorded, now, tenant, incident_id),
    )
    return True


def trigger_incident(ctx: Dict[str, Any], position: Dict[str, Any], source: str = "app") -> Dict[str, Any]:
    """Botao de panico. Idempotente: se ja tem alerta aberto, reaproveita."""
    tenant, member = ctx["tenant_slug"], ctx["member"]
    now = _now()
    with db_store._conn() as c:
        inc = _open_incident(c, tenant, member["id"])
        created = False
        if not inc:
            incident_id = uuid.uuid4().hex
            c.execute(
                "INSERT INTO alert_incidents(id, tenant_slug, member_id, kind, status, source, opened_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (incident_id, tenant, member["id"], "panic", "new", _text(source, 20) or "app", now, now),
            )
            _log(c, tenant, incident_id, "opened", member.get("full_name") or "", "Botao de panico acionado")
            created = True
        else:
            incident_id = inc["id"]
            _log(c, tenant, incident_id, "retriggered", member.get("full_name") or "", "Botao acionado de novo")
        _insert_position(c, tenant, incident_id, position or {})
        inc = _row(c, "SELECT * FROM alert_incidents WHERE id=?", (incident_id,))
    return {"incident": _app_incident_view(inc), "created": created}


def record_positions(ctx: Dict[str, Any], incident_id: str, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    tenant, member = ctx["tenant_slug"], ctx["member"]
    with db_store._conn() as c:
        inc = _row(c, "SELECT * FROM alert_incidents WHERE tenant_slug=? AND id=? AND member_id=?", (tenant, incident_id, member["id"]))
        if not inc:
            raise ValueError("Alerta nao encontrado.")
        if inc["status"] not in OPEN_STATUSES:
            # Alerta encerrado: o app deve parar de mandar posicao.
            return {"tracking": False, "saved": 0}
        saved = sum(1 for p in (positions or [])[:50] if _insert_position(c, tenant, incident_id, p or {}))
    return {"tracking": True, "saved": saved}


def cancel_incident(ctx: Dict[str, Any], incident_id: str, pin: str) -> Dict[str, Any]:
    """Cancelamento pelo app. Senha normal cancela; senha de coacao NAO cancela
    (vira coacao e continua rastreando). A resposta tem o mesmo formato nos dois
    casos; `tracking` e o unico campo que muda e o app nao o mostra na tela."""
    tenant, member = ctx["tenant_slug"], ctx["member"]
    if not member.get("pin_hash"):
        raise ValueError("Senhas ainda nao configuradas neste aparelho.")
    is_normal = _check_pin(pin, member.get("pin_hash") or "")
    is_duress = (not is_normal) and _check_pin(pin, member.get("duress_pin_hash") or "")
    if not is_normal and not is_duress:
        raise ValueError("Senha incorreta.")
    now = _now()
    with db_store._conn() as c:
        inc = _row(c, "SELECT * FROM alert_incidents WHERE tenant_slug=? AND id=? AND member_id=?", (tenant, incident_id, member["id"]))
        if not inc or inc["status"] not in OPEN_STATUSES:
            return {"ok": True, "tracking": False}
        if is_normal:
            c.execute(
                "UPDATE alert_incidents SET status='cancelled', closed_at=?, closed_by=?, updated_at=? WHERE id=?",
                (now, "app", now, incident_id),
            )
            _log(c, tenant, incident_id, "cancelled_by_user", member.get("full_name") or "", "Cancelado no app com a senha normal")
            return {"ok": True, "tracking": False}
        c.execute(
            "UPDATE alert_incidents SET kind='duress', duress_at=?, updated_at=? WHERE id=?",
            (now, now, incident_id),
        )
        _log(c, tenant, incident_id, "duress", member.get("full_name") or "", "Senha de COACAO digitada no cancelamento")
    notify_async(tenant, incident_id, "duress")
    return {"ok": True, "tracking": True}


# --------------------------------------------------------------------------
# central (painel ao vivo)
# --------------------------------------------------------------------------

def _incident_view(inc: Dict[str, Any], member: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    m = member or {}
    return {
        "id": inc["id"],
        "kind": inc.get("kind") or "panic",
        "status": inc.get("status") or "new",
        "source": inc.get("source") or "app",
        "opened_at": inc.get("opened_at") or "",
        "acknowledged_at": inc.get("acknowledged_at") or "",
        "acknowledged_by": inc.get("acknowledged_by") or "",
        "dispatched_at": inc.get("dispatched_at") or "",
        "dispatched_by": inc.get("dispatched_by") or "",
        "arrived_at": inc.get("arrived_at") or "",
        "arrived_by": inc.get("arrived_by") or "",
        "closed_at": inc.get("closed_at") or "",
        "closed_by": inc.get("closed_by") or "",
        "close_note": inc.get("close_note") or "",
        "duress_at": inc.get("duress_at") or "",
        "escalated_at": inc.get("escalated_at") or "",
        "last_lat": inc.get("last_lat"),
        "last_lon": inc.get("last_lon"),
        "last_accuracy": inc.get("last_accuracy"),
        "last_battery": inc.get("last_battery"),
        "last_position_at": inc.get("last_position_at") or "",
        "site": site_do_membro(m),
        "member": {
            "id": m.get("id") or inc.get("member_id") or "",
            "full_name": m.get("full_name") or "(pessoa removida)",
            "document_id": m.get("document_id") or "",
            "role_title": m.get("role_title") or "",
            "unit_name": m.get("unit_name") or "",
            "unit_lat": m.get("unit_lat"),
            "unit_lon": m.get("unit_lon"),
            "unit_connector_id": m.get("unit_connector_id") or "",
            "phone": m.get("phone") or "",
            "notes": m.get("notes") or "",
            "camera_radius_m": int(m.get("camera_radius_m") or 0),
            "foto_v": _foto_versao(m["id"], inc.get("tenant_slug") or "") if m.get("id") else 0,
        },
    }


def _members_by_id(c: Any, tenant: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    rows = _rows(
        c,
        f"SELECT id, full_name, document_id, role_title, unit_name, unit_lat, unit_lon, unit_connector_id, phone, notes, camera_radius_m FROM alert_members "
        f"WHERE tenant_slug=? AND id IN ({','.join('?' * len(ids))})",
        (tenant, *ids),
    )
    return {r["id"]: r for r in rows}


def list_incidents(scope: str = "live", limit: int = 200) -> List[Dict[str, Any]]:
    """scope=live: abertos + encerrados nos ultimos 30 min. scope=history: tudo."""
    tenant = _tenant()
    limit = max(1, min(int(limit or 200), 1000))
    liberados = _sites_liberados()
    with db_store._conn() as c:
        if scope == "history":
            # Restrito: filtra por site primeiro e corta depois, senao o limite
            # gasta linhas de outros sites e o historico dele fica curto.
            lim_sql = limit if liberados is None else 20000
            rows = _rows(c, "SELECT * FROM alert_incidents WHERE tenant_slug=? ORDER BY opened_at DESC LIMIT ?", (tenant, lim_sql))
        else:
            since = _iso(_now_dt() - timedelta(minutes=RECENT_FINAL_WINDOW_MIN))
            rows = _rows(
                c,
                f"SELECT * FROM alert_incidents WHERE tenant_slug=? AND (status IN ({','.join('?' * len(OPEN_STATUSES))}) OR closed_at >= ?) "
                "ORDER BY opened_at DESC LIMIT ?",
                (tenant, *OPEN_STATUSES, since, limit),
            )
        members = _members_by_id(c, tenant, [r["member_id"] for r in rows])
    return [
        _incident_view(r, members.get(r["member_id"]))
        for r in rows
        if _membro_liberado(members.get(r["member_id"]), liberados)
    ][:limit]


def _exigir_incidente_liberado(c: Any, tenant: str, incident_id: str) -> Dict[str, Any]:
    """Alerta do cliente E de um site do usuario; senao 'nao encontrado'.

    Alerta de pessoa ja excluida nao tem site: so quem ve todos os sites abre."""
    inc = _row(c, "SELECT * FROM alert_incidents WHERE tenant_slug=? AND id=?", (tenant, incident_id))
    if not inc:
        raise LookupError("Alerta nao encontrado.")
    liberados = _sites_liberados()
    if liberados is not None:
        member = _members_by_id(c, tenant, [inc["member_id"]]).get(inc["member_id"])
        if not _membro_liberado(member, liberados):
            raise LookupError("Alerta nao encontrado.")
    return inc


def get_incident(incident_id: str) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        inc = _exigir_incidente_liberado(c, tenant, incident_id)
        members = _members_by_id(c, tenant, [inc["member_id"]])
        positions = _rows(
            c,
            "SELECT lat, lon, accuracy, battery, recorded_at FROM alert_positions WHERE tenant_slug=? AND incident_id=? "
            "ORDER BY recorded_at, id",
            (tenant, incident_id),
        )
        log = _rows(
            c,
            "SELECT action, actor, note, created_at FROM alert_incident_log WHERE tenant_slug=? AND incident_id=? ORDER BY id",
            (tenant, incident_id),
        )
    out = _incident_view(inc, members.get(inc["member_id"]))
    out["positions"] = positions
    out["log"] = log
    out["protocolo"] = _protocolo_do_incidente(out["site"], log)
    return out


_TRANSITIONS = {
    "acknowledge": ({"new"}, "acknowledged", "acknowledged_at", "acknowledged_by", "Alerta assumido"),
    "dispatch": ({"new", "acknowledged"}, "dispatched", "dispatched_at", "dispatched_by", "Equipe enviada ao local"),
    "close": (set(OPEN_STATUSES), "closed", "closed_at", "closed_by", "Alerta encerrado"),
}


def transition_incident(incident_id: str, action: str, operator: str, note: str = "") -> Dict[str, Any]:
    if action == "arrive":
        return _marcar_chegada(incident_id, operator, note)
    if action not in _TRANSITIONS:
        raise ValueError("Acao invalida.")
    allowed_from, new_status, at_col, by_col, default_note = _TRANSITIONS[action]
    note = _text(note, 2000)
    if action == "close" and len(note) < 3:
        raise ValueError("Descreva o que foi feito antes de encerrar.")
    tenant = _tenant()
    now = _now()
    with db_store._conn() as c:
        inc = _exigir_incidente_liberado(c, tenant, incident_id)
        if inc["status"] not in allowed_from:
            raise ValueError(f"Alerta ja esta como '{inc['status']}'.")
        extra = ", close_note=?" if action == "close" else ""
        params: list[Any] = [new_status, now, _text(operator, 120), now]
        if action == "close":
            params.append(note)
        c.execute(
            f"UPDATE alert_incidents SET status=?, {at_col}=?, {by_col}=?, updated_at=?{extra} WHERE tenant_slug=? AND id=?",
            (*params, tenant, incident_id),
        )
        # "Equipe enviada" direto de "novo" tambem conta como assumido.
        if action == "dispatch" and not inc.get("acknowledged_at"):
            c.execute(
                "UPDATE alert_incidents SET acknowledged_at=?, acknowledged_by=? WHERE tenant_slug=? AND id=?",
                (now, _text(operator, 120), tenant, incident_id),
            )
        _log(c, tenant, incident_id, action, operator, note or default_note)
    return get_incident(incident_id)


def _marcar_chegada(incident_id: str, operator: str, note: str = "") -> Dict[str, Any]:
    """Equipe chegou ao local. Nao muda o status (continua em atendimento):
    so marca a hora, para medir quanto a ajuda levou para chegar."""
    tenant = _tenant()
    now = _now()
    quem = _text(operator, 120)
    with db_store._conn() as c:
        inc = _exigir_incidente_liberado(c, tenant, incident_id)
        if inc["status"] not in ("acknowledged", "dispatched"):
            raise ValueError("Assuma o alerta antes de marcar a chegada." if inc["status"] == "new"
                             else f"Alerta ja esta como '{inc['status']}'.")
        if inc.get("arrived_at"):
            raise ValueError("A chegada ja foi marcada.")
        c.execute(
            "UPDATE alert_incidents SET arrived_at=?, arrived_by=?, updated_at=? WHERE tenant_slug=? AND id=?",
            (now, quem, now, tenant, incident_id),
        )
        # Chegou sem ter marcado "equipe enviada": a equipe foi, entao conta.
        if not inc.get("dispatched_at"):
            c.execute(
                "UPDATE alert_incidents SET status='dispatched', dispatched_at=?, dispatched_by=? WHERE tenant_slug=? AND id=?",
                (now, quem, tenant, incident_id),
            )
        _log(c, tenant, incident_id, "arrive", operator, _text(note, 2000) or "Equipe chegou ao local")
    return get_incident(incident_id)


# --------------------------------------------------------------------------
# passos do atendimento por site (o "protocolo")
# --------------------------------------------------------------------------
# Guardado na config do cliente: {"<SITE>": ["passo", ...], "*": [...]}.
# "*" vale para site sem lista propria. Cada passo marcado vira uma linha na
# linha do tempo do alerta (acao "step"/"step_undo"), entao o historico mostra
# quem fez o que e quando -- e nada fica num estado solto fora do log.

PROTOCOLO_PADRAO = "*"
_PROTOCOLO_MAX_PASSOS = 15
_PROTOCOLO_MAX_TEXTO = 140


def _chave_protocolos() -> str:
    return f"alert_protocolos__tenant__{_tenant()}"


def _ler_protocolos() -> Dict[str, List[str]]:
    dados = db_store.get_json_state(_chave_protocolos(), {}) or {}
    if not isinstance(dados, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for site, passos in dados.items():
        if isinstance(passos, list):
            out[str(site)] = [str(p) for p in passos if str(p or "").strip()]
    return out


def _passos_do_site(site: str, dados: Optional[Dict[str, List[str]]] = None) -> List[str]:
    dados = _ler_protocolos() if dados is None else dados
    alvo = str(site or "").strip().upper()
    for k, passos in dados.items():
        if k != PROTOCOLO_PADRAO and k.strip().upper() == alvo and alvo:
            return passos
    return dados.get(PROTOCOLO_PADRAO, [])


def listar_protocolos() -> Dict[str, Any]:
    """Para a tela de edicao: a lista de cada site que o usuario ve, mais o
    padrao. Restrito a sites nao ve (nem edita) o padrao nem site alheio."""
    from app.core import permissions

    dados = _ler_protocolos()
    liberados = _sites_liberados()
    sites = [s["name"] for s in permissions.sites_do_cliente(_tenant())]
    if liberados is not None:
        sites = [s for s in sites if s.strip().upper() in liberados]
    itens = [{"site": s, "passos": next((v for k, v in dados.items() if k != PROTOCOLO_PADRAO and k.strip().upper() == s.strip().upper()), [])}
             for s in sites]
    out: Dict[str, Any] = {"sites": itens, "pode_padrao": liberados is None}
    if liberados is None:
        out["padrao"] = dados.get(PROTOCOLO_PADRAO, [])
    return out


def salvar_protocolo(site: str, passos: Any) -> Dict[str, Any]:
    from app.core import permissions

    site = _text(site, 160)
    if not isinstance(passos, list):
        raise ValueError("passos deve ser uma lista")
    limpos: List[str] = []
    for p in passos:
        t = _text(p, _PROTOCOLO_MAX_TEXTO)
        if t and t not in limpos:
            limpos.append(t)
    if len(limpos) > _PROTOCOLO_MAX_PASSOS:
        raise ValueError(f"No maximo {_PROTOCOLO_MAX_PASSOS} passos por site.")
    liberados = _sites_liberados()
    if site == PROTOCOLO_PADRAO:
        if liberados is not None:
            raise ValueError("So quem ve todos os sites altera a lista padrao.")
        chave = PROTOCOLO_PADRAO
    else:
        validos = {s["name"].strip().upper(): s["name"] for s in permissions.sites_do_cliente(_tenant())}
        if site.strip().upper() not in validos:
            raise ValueError("Site desconhecido.")
        if liberados is not None and site.strip().upper() not in liberados:
            raise ValueError("Site desconhecido.")
        chave = validos[site.strip().upper()]
    dados = _ler_protocolos()
    for k in [k for k in dados if k != PROTOCOLO_PADRAO and k.strip().upper() == chave.strip().upper()]:
        dados.pop(k)
    if limpos:
        dados[chave] = limpos
    else:
        dados.pop(chave, None)
    res = db_store.set_json_state(_chave_protocolos(), dados)
    if not res.get("ok"):
        raise ValueError("Nao foi possivel salvar agora. Tente de novo.")
    return {"site": chave, "passos": limpos}


def _protocolo_do_incidente(site: str, log: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    estado: Dict[str, Dict[str, Any]] = {}
    for item in log:
        if item.get("action") in ("step", "step_undo"):
            estado[str(item.get("note") or "")] = item
    out = []
    for passo in _passos_do_site(site):
        ult = estado.get(passo)
        feito = bool(ult and ult.get("action") == "step")
        out.append({"texto": passo, "feito": feito,
                    "por": (ult or {}).get("actor", "") if feito else "",
                    "em": (ult or {}).get("created_at", "") if feito else ""})
    return out


def marcar_passo(incident_id: str, operator: str, passo: str, feito: bool = True) -> Dict[str, Any]:
    passo = _text(passo, _PROTOCOLO_MAX_TEXTO)
    tenant = _tenant()
    with db_store._conn() as c:
        inc = _exigir_incidente_liberado(c, tenant, incident_id)
        member = _members_by_id(c, tenant, [inc["member_id"]]).get(inc["member_id"])
        if passo not in _passos_do_site(site_do_membro(member)):
            raise ValueError("Esse passo nao esta na lista deste site.")
        _log(c, tenant, incident_id, "step" if feito else "step_undo", operator, passo)
    return get_incident(incident_id)


def add_incident_note(incident_id: str, operator: str, note: str) -> Dict[str, Any]:
    note = _text(note, 2000)
    if not note:
        raise ValueError("Escreva a observacao.")
    tenant = _tenant()
    with db_store._conn() as c:
        _exigir_incidente_liberado(c, tenant, incident_id)
        _log(c, tenant, incident_id, "note", operator, note)
    return get_incident(incident_id)


def live_summary() -> Dict[str, Any]:
    """Contagem leve pro badge do menu (poll de qualquer tela)."""
    # Sirene, voz e numero do menu saem daqui: quem so ve alguns sites nao
    # pode ouvir alerta de site alheio. Abertos sao poucos; filtra linha a linha.
    tenant = _tenant()
    with db_store._conn() as c:
        rows = _rows(
            c,
            f"SELECT id, member_id, status, kind, opened_at FROM alert_incidents WHERE tenant_slug=? "
            f"AND status IN ({','.join('?' * len(OPEN_STATUSES))}) ORDER BY opened_at DESC",
            (tenant, *OPEN_STATUSES),
        )
        liberados = _sites_liberados()
        if liberados is not None and rows:
            members = _members_by_id(c, tenant, [r["member_id"] for r in rows])
            rows = [r for r in rows if _membro_liberado(members.get(r["member_id"]), liberados)]
    novos = [r for r in rows if r["status"] == "new"]
    return {
        "open": len(rows),
        "new": len(novos),
        "duress": sum(1 for r in rows if r["kind"] == "duress"),
        "latest_new_id": novos[0]["id"] if novos else "",
    }


def _inventory_cameras():
    """Cameras IP do tenant nos tres inventarios (olt/switch/basic), sem
    misturar: o modo vai junto. Dedup por (modo, inventory_key/ip)."""
    from app.services.inventory_json import load_inventory_json

    seen: set = set()
    for mode in ("olt", "switch", "basic"):
        try:
            rows = load_inventory_json(mode=mode) or []
        except Exception:
            logger.exception("alerta: falha lendo inventario %s", mode)
            continue
        for r in rows:
            r = r or {}
            ip = _text(r.get("ip"), 64)
            if not ip:
                continue
            key = (mode, _text(r.get("inventory_key"), 200) or ip)
            if key in seen:
                continue
            seen.add(key)
            yield mode, r


def _camera_card(mode: str, r: Dict[str, Any], lat: Optional[float] = None, lon: Optional[float] = None) -> Dict[str, Any]:
    clat = _coord(r.get("lat") or r.get("latitude"), 90)
    clon = _coord(r.get("lon") or r.get("lng") or r.get("longitude"), 180)
    dist = haversine_m(lat, lon, clat, clon) if None not in (lat, lon, clat, clon) else None
    ip = _text(r.get("ip"), 64)
    snapshot = _text(r.get("imgbb_thumb_url") or r.get("imgbb_url") or r.get("snapshot_url"), 500)
    if not snapshot:
        # Mesmo criterio do inventario de cameras (/api/cameras): foto local.
        try:
            from app.services.photo_store import resolve_snapshot_file

            f = resolve_snapshot_file(path_hint=str(r.get("snapshot_path") or r.get("snapshot_file") or ""), ip=ip)
            if f is not None:
                snapshot = f"/data/snapshot/{f.name}"
        except Exception:
            pass
    return {
        "mode": mode,
        "ip": ip,
        "remote_connector_id": _text(r.get("remote_connector_id") or r.get("connector_id"), 80),
        "titulo": _text(r.get("titulo") or r.get("nome"), 160),
        "local": _text(r.get("local") or r.get("LOCAL"), 160),
        "site": _text(r.get("site") or r.get("site_name") or r.get("local") or r.get("LOCAL"), 160),
        "fabricante": _text(r.get("fabricante") or r.get("manufacturer"), 60),
        "modelo": _text(r.get("modelo") or r.get("model"), 80),
        "status": _text(r.get("status"), 20),
        "lat": clat,
        "lon": clon,
        "distance_m": round(dist) if dist is not None else None,
        "snapshot_url": snapshot,
    }


# Raio pra considerar que a camera esta NO LOCAL do alerta. Eram 3000 m, o que
# trazia camera de outro bairro como se fosse da cena. 20 m e a ordem de
# grandeza do proprio erro do GPS de celular -- por isso a central tambem
# recebe a distancia da mais proxima quando nada cai dentro do raio.
NEARBY_RADIUS_M = 20.0

# Teto pro ajuste por precisao: acima disso o GPS esta ruim demais pra dizer
# qualquer coisa (dentro de predio, por exemplo) -- ai vale a lista da lotacao,
# nao um raio de bairro fingindo precisao que nao existe.
MAX_ACCURACY_M = 150.0


def effective_radius_m(max_distance_m: float = NEARBY_RADIUS_M, accuracy_m: Optional[float] = None) -> float:
    """Raio de busca que nunca e menor que o erro do proprio GPS.

    Filtrar por 20 m quando o aparelho informou +-45 m e filtrar ruido: a
    camera certa pode cair fora por causa da impresicao, nao da distancia
    real. Entao o raio acompanha a precisao informada pelo aparelho."""
    base = float(max_distance_m or NEARBY_RADIUS_M)
    try:
        acc = float(accuracy_m) if accuracy_m is not None else 0.0
    except (TypeError, ValueError):
        acc = 0.0
    if acc <= 0 or acc > MAX_ACCURACY_M:
        return base
    return max(base, acc)


def nearby_cameras(
    lat: float,
    lon: float,
    limit: int = 6,
    max_distance_m: float = NEARBY_RADIUS_M,
    accuracy_m: Optional[float] = None,
    aceita: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> List[Dict[str, Any]]:
    """Cameras IP do tenant com coordenada, dentro do raio a partir do ponto.
    `aceita` (sites do usuario) filtra ANTES do corte: filtrar depois deixava
    lista vazia quando as mais perto eram de outro site."""
    raio = effective_radius_m(max_distance_m, accuracy_m)
    found = []
    for mode, r in _inventory_cameras():
        card = _camera_card(mode, r, lat, lon)
        if aceita is not None and not aceita(card):
            continue
        if card["distance_m"] is not None and card["distance_m"] <= raio:
            found.append(card)
    found.sort(key=lambda x: x["distance_m"])
    return found[: max(1, min(int(limit or 6), 20))]


def nearest_camera(lat: float, lon: float,
                   aceita: Optional[Callable[[Dict[str, Any]], bool]] = None) -> Optional[Dict[str, Any]]:
    """Camera com coordenada mais proxima do ponto, SEM limite de raio.

    Quando nada cai dentro do raio, "nao tem camera aqui" sozinho deixa a
    central no escuro: saber que a mais proxima esta a 180 m ou a 4 km muda a
    decisao de quem atende."""
    melhor = None
    for mode, r in _inventory_cameras():
        card = _camera_card(mode, r, lat, lon)
        if card["distance_m"] is None or (aceita is not None and not aceita(card)):
            continue
        if melhor is None or card["distance_m"] < melhor["distance_m"]:
            melhor = card
    return melhor


def connector_cameras(connector_id: str, lat: Optional[float] = None, lon: Optional[float] = None, limit: int = 64) -> List[Dict[str, Any]]:
    """Todas as cameras do conector da lotacao (escola/predio), com ou sem
    coordenada. Dentro de predio o GPS erra; a lotacao nao."""
    cid = _text(connector_id, 80)
    if not cid:
        return []
    found = [
        _camera_card(mode, r, lat, lon)
        for mode, r in _inventory_cameras()
        if _text(r.get("remote_connector_id") or r.get("connector_id"), 80) == cid
    ]
    found.sort(key=lambda x: (x["titulo"] or x["ip"]).lower())
    return found[: max(1, min(int(limit or 64), 200))]


# --------------------------------------------------------------------------
# notificacao (Telegram) e escalonamento
# --------------------------------------------------------------------------

def _format_message(inc: Dict[str, Any], reason: str) -> str:
    import html

    m = inc.get("member") or {}
    head = {
        "duress": "🆘 <b>COACAO</b> — senha de coacao digitada",
        "escalation": "🚨 <b>ALERTA SEM ATENDIMENTO</b> ha mais de 1 minuto",
    }.get(reason, "🚨 <b>ALERTA</b>")
    lines = [head, "", f"<b>{html.escape(m.get('full_name') or '')}</b>"]
    if m.get("role_title") or m.get("unit_name"):
        lines.append(html.escape(" · ".join(x for x in (m.get("role_title"), m.get("unit_name")) if x)))
    if m.get("phone"):
        lines.append(f"Tel: {html.escape(m['phone'])}")
    if inc.get("kind") == "duress" and reason != "duress":
        lines.append("⚠️ Marcado como COACAO")
    lat, lon = inc.get("last_lat"), inc.get("last_lon")
    if lat is not None and lon is not None:
        lines.append(f"Local: https://maps.google.com/?q={lat:.6f},{lon:.6f}")
    elif m.get("unit_lat") is not None:
        lines.append(f"Sem GPS. Lotacao: https://maps.google.com/?q={m['unit_lat']:.6f},{m['unit_lon']:.6f}")
    lines.append("")
    lines.append("Abra o SightOps > Alerta ao Vivo para atender.")
    return "\n".join(lines)


def _site_do_alerta(inc: Dict[str, Any]) -> str:
    """Site do alerta: o do conector da lotacao do membro, senao o nome da lotacao."""
    m = inc.get("member") or {}
    cid = str(m.get("unit_connector_id") or "").strip()
    if cid:
        try:
            from app.api.endpoints.maintenance import _site_do_conector

            site = str(_site_do_conector(cid) or "").strip()
            if site:
                return site
        except Exception:
            pass
    return str(m.get("unit_name") or "").strip()


def _send_telegram_for(tenant: str, incident_id: str, reason: str) -> Dict[str, Any]:
    """Pelos grupos do site (Configuracoes > Notificacoes). Panico e sempre
    urgente: passa por cima do silencio da noite."""
    from app.services import notificacoes_service as N

    ctx_token = set_current_tenant_slug(tenant)
    try:
        inc = get_incident(incident_id)
        res = N.enviar_evento("panico", _site_do_alerta(inc), _format_message(inc, reason), urgente=True, tela="alert-live")
        if not res["destinos"]:
            return {"ok": False, "error": "Nenhum grupo do Telegram recebe alerta de panico deste site."}
        return {"ok": res["ok"], "error": "; ".join(res["erros"])} if not res["ok"] else {"ok": True, "enviados": res["enviados"]}
    except Exception as exc:
        logger.exception("alerta: falha ao enviar Telegram (%s/%s)", tenant, incident_id)
        return {"ok": False, "error": str(exc)}
    finally:
        reset_current_tenant_slug(ctx_token)


def notify_async(tenant: str, incident_id: str, reason: str) -> None:
    """Dispara o Telegram fora da request: o app do celular nao pode esperar
    20s de timeout do Telegram pra receber 'cancelado'."""
    threading.Thread(
        target=_send_telegram_for, args=(tenant, incident_id, reason), name=f"alert-notify-{reason}", daemon=True
    ).start()


def escalate_unattended(after_s: int = ESCALATION_AFTER_S) -> List[Dict[str, Any]]:
    """Alertas 'new' sem ninguem assumir ha mais de `after_s`: avisa uma vez.

    Varre TODOS os tenants (roda no loop de fundo, sem request). Marca
    escalated_at antes de enviar -- se o Telegram falhar, nao fica reenviando
    a cada 15s; a tela ao vivo continua tocando a sirene de qualquer jeito.
    """
    cutoff = _iso(_now_dt() - timedelta(seconds=after_s))
    with db_store._conn() as c:
        rows = _rows(
            c,
            "SELECT id, tenant_slug FROM alert_incidents WHERE status='new' AND escalated_at='' AND opened_at <= ?",
            (cutoff,),
        )
        now = _now()
        for r in rows:
            c.execute("UPDATE alert_incidents SET escalated_at=? WHERE id=?", (now, r["id"]))
            _log(c, r["tenant_slug"], r["id"], "escalated", "sistema", f"Ninguem assumiu em {after_s}s: aviso enviado")
    results = []
    for r in rows:
        res = _send_telegram_for(r["tenant_slug"], r["id"], "escalation")
        results.append({"id": r["id"], "tenant": r["tenant_slug"], **res})
    return results
