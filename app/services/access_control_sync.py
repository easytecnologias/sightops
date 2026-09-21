from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import HTTPException

from app.services.access_control_device import poll_events, provision_person
from app.services.access_control_photos import load_person_face_photo
from app.services.access_control_store import (
    get_device_with_password,
    list_people,
    list_devices,
    list_door_group_members,
    list_group_members,
    list_groups,
    list_pending_provisions,
    list_rules,
    latest_device_event_occurred_at,
    normalize_access_direction,
    normalize_access_event_type,
    record_event,
    update_device_health,
    update_device_event_cursor,
    upsert_provision_status,
    list_provision_status_for_person,
)

logger = logging.getLogger("cam-snapshot")


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _event_ref_values(event: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in (
        "person_id",
        "controller_user_id",
        "user_id",
        "UserID",
        "userid",
        "card_no",
        "CardNo",
        "enrollment_code",
    ):
        value = _digits(event.get(key))
        if value:
            values.append(value)
    return values


def _resolve_event_person(event: Dict[str, Any], people: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    by_numeric_ref: Dict[str, Dict[str, Any]] = {}
    names: Dict[str, List[Dict[str, Any]]] = {}
    for person in people:
        for key in ("controller_user_id", "enrollment_code", "document_id"):
            value = _digits(person.get(key))
            if value and value not in by_numeric_ref:
                by_numeric_ref[value] = person
        name = _match_text(person.get("full_name"))
        if name:
            names.setdefault(name, []).append(person)

    for value in _event_ref_values(event):
        person = by_numeric_ref.get(value)
        if person:
            return person

    event_name = _match_text(
        event.get("person_name_raw")
        or event.get("person_name")
        or event.get("UserName")
        or event.get("name")
    )
    candidates = names.get(event_name, [])
    if len(candidates) == 1:
        return candidates[0]
    return None


def _resolve_event_type(event: Dict[str, Any], device_role: str) -> str:
    raw_value = str(event.get("event_type") or "").strip()
    if raw_value:
        parsed = normalize_access_event_type(raw_value)
        if parsed in {"saida", "saida_manual"}:
            return parsed
    if device_role in {"entrada", "saida"}:
        return device_role
    parsed = normalize_access_event_type(raw_value or "entrada")
    return "entrada" if parsed == "entrada_saida" else parsed


def _record_device_event(device: Dict[str, Any], event: Dict[str, Any], *, source: str = "device") -> str:
    device_id = str(device.get("id") or "").strip()
    device_role = normalize_access_direction(device.get("access_direction"))
    people = list_people(site=device.get("site", ""))
    event_type = _resolve_event_type(event, device_role)
    person = _resolve_event_person(event, people)
    person_name = (
        event.get("person_name_raw")
        or event.get("person_name")
        or event.get("UserName")
        or event.get("name")
        or (person or {}).get("full_name")
        or ""
    )
    event_id = record_event({
        "site": device.get("site", "") or (person or {}).get("site", ""),
        "device_id": device_id,
        "device_name": device.get("name", ""),
        "device_role": device_role,
        "person_id": (person or {}).get("id", ""),
        "person_name_raw": person_name,
        "event_type": event_type,
        "source": source,
        "raw_event_id": event.get("raw_event_id") or event.get("raw_id") or event.get("id") or "",
        "raw_payload": json.dumps(event, ensure_ascii=True, default=str)[:4000],
        "occurred_at": event.get("occurred_at", ""),
    })
    raw_id = str(event.get("raw_event_id") or event.get("raw_id") or event.get("id") or "").strip()
    if raw_id.isdigit():
        try:
            update_device_event_cursor(device_id, raw_id)
        except ValueError:
            logger.warning("Nao foi possivel atualizar cursor de eventos do dispositivo %s", device_id)
    return event_id


def record_device_event(device_id: str, event: Dict[str, Any], *, source: str = "connector_push") -> str:
    device = get_device_with_password(device_id)
    if not device:
        raise ValueError("Dispositivo nao encontrado neste cliente.")
    try:
        update_device_health(
            device_id,
            status="online",
            model=str(device.get("model") or ""),
            last_seen_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except ValueError:
        logger.warning("Nao foi possivel atualizar status do dispositivo %s", device_id)
    return _record_device_event(device, event, source=source)


def resolve_target_devices_for_person(person_id: str) -> List[Dict[str, Any]]:
    """Pessoa -> grupos que ela participa -> regras ativas -> grupos de porta -> dispositivos (unico por id)."""
    person_groups = {
        group["id"]
        for group in list_groups()
        if person_id in list_group_members(group["id"])
    }
    if not person_groups:
        return []
    door_group_ids = {
        rule["door_group_id"]
        for rule in list_rules()
        if rule.get("active") and rule.get("people_group_id") in person_groups
    }
    if not door_group_ids:
        return []
    device_ids: set[str] = set()
    for door_group_id in door_group_ids:
        device_ids.update(list_door_group_members(door_group_id))
    devices_by_id = {d["id"]: d for d in list_devices() if d.get("active")}
    return [devices_by_id[did] for did in device_ids if did in devices_by_id]


def enqueue_person_provisioning(person_ids: List[str], *, force: bool = False) -> int:
    """Marca provisionamento pendente sem chamar a controladora.

    Salvar uma pessoa ou confirmar cadastro pelo WhatsApp deve responder rapido.
    O envio real para cada controladora fica com retry_pending_provisions().
    """
    queued = 0
    seen: set[str] = set()
    for raw_id in person_ids:
        person_id = str(raw_id or "").strip()
        if not person_id or person_id in seen:
            continue
        seen.add(person_id)
        already_ok: set[str] = set()
        if not force:
            already_ok = {
                str(row.get("device_id") or "")
                for row in list_provision_status_for_person(person_id)
                if str(row.get("status") or "") == "ok"
            }
        for device in resolve_target_devices_for_person(person_id):
            if device["id"] in already_ok:
                continue
            upsert_provision_status(person_id, device["id"], "pending")
            queued += 1
    return queued


def provision_person_everywhere(person: Dict[str, Any]) -> Dict[str, Any]:
    """Provisiona a pessoa em todos os dispositivos-alvo resolvidos para ela.

    Uma falha em um dispositivo nunca impede tentar os demais nem propaga como
    excecao nao tratada -- e sempre capturada e registrada via
    upsert_provision_status, e refletida em results[i]["status"] == "failed".
    """
    targets = resolve_target_devices_for_person(person["id"])
    results: List[Dict[str, Any]] = []
    overall_ok = True
    for device in targets:
        upsert_provision_status(person["id"], device["id"], "pending")
        full_device = get_device_with_password(device["id"])
        if not full_device:
            overall_ok = False
            error_text = "Dispositivo nao encontrado neste cliente."
            upsert_provision_status(person["id"], device["id"], "failed", error_text)
            results.append({"device_id": device["id"], "status": "failed", "error": error_text})
            continue
        try:
            provision_person(full_device, person, load_person_face_photo(person))
            upsert_provision_status(person["id"], device["id"], "ok")
            results.append({"device_id": device["id"], "status": "ok", "error": ""})
        except HTTPException as exc:
            overall_ok = False
            error_text = str(exc.detail)
            upsert_provision_status(person["id"], device["id"], "failed", error_text)
            results.append({"device_id": device["id"], "status": "failed", "error": error_text})
            logger.warning(
                "Falha ao provisionar pessoa %s no dispositivo %s: %s", person["id"], device["id"], error_text
            )
        except Exception as exc:  # defesa extra: nunca deixar um dispositivo derrubar os demais
            overall_ok = False
            error_text = str(exc)
            upsert_provision_status(person["id"], device["id"], "failed", error_text)
            results.append({"device_id": device["id"], "status": "failed", "error": error_text})
            logger.exception(
                "Erro inesperado ao provisionar pessoa %s no dispositivo %s", person["id"], device["id"]
            )
    return {"ok": overall_ok, "results": results}


def retry_pending_provisions() -> Dict[str, Any]:
    """Reprocessa provisionamentos com status 'pending' ou 'failed' (chamado em loop pela Task 7).

    Sem backoff/retry-count aqui de proposito -- essa funcao so tenta uma vez
    por chamada; a politica de repeticao (intervalo, limite de tentativas)
    e responsabilidade de quem a chama em loop (Task 7), nao dela.

    Se a pessoa ou o dispositivo referenciados pela linha pendente nao
    existirem mais (removidos depois que o provisionamento foi enfileirado),
    a linha e marcada como "failed" com um erro explicito em vez de
    simplesmente pulada. Pular silenciosamente deixaria o status "pending"
    parado para sempre (list_pending_provisions() inclui pending e failed,
    entao de qualquer forma o item continuaria sendo revisitado a cada
    chamada) sem nenhum sinal visivel de que o item esta permanentemente
    quebrado -- quem olhar o status via list_provision_status_for_person()
    veria "pending" indefinidamente, como se so estivesse aguardando, quando
    na verdade nunca vai progredir sozinho. Marcar como "failed" com o motivo
    torna o problema visivel (ex.: na UI da Task 6) sem exigir nenhuma
    tentativa real no dispositivo.
    """
    pending, people_by_id = list_pending_provisions_for_retry()
    if not pending:
        return {"ok": True, "retried": 0}
    retried = sum(1 for item in pending if retry_one_pending_provision(item, people_by_id))
    return {"ok": True, "retried": retried}


def list_pending_provisions_for_retry() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Prepara os dados que o retry precisa (leitura, rapido) sem tentar
    nenhum dispositivo ainda -- separado de retry_one_pending_provision pra
    o loop assincrono (app/main.py) poder rodar as tentativas em paralelo em
    vez de uma atras da outra."""
    pending = list_pending_provisions()
    people_by_id = {p["id"]: p for p in list_people()} if pending else {}
    return pending, people_by_id


def retry_one_pending_provision(item: Dict[str, Any], people_by_id: Dict[str, Any]) -> bool:
    """Tenta reprocessar UM provisionamento pendente. Devolve True se contou
    como tentativa de verdade (pessoa e dispositivo existiam), False se foi
    descartado por referenciar algo que sumiu."""
    person = people_by_id.get(item["person_id"])
    device = get_device_with_password(item["device_id"])
    if not person or not device:
        error_text = "Pessoa nao encontrada." if not person else "Dispositivo nao encontrado."
        upsert_provision_status(item["person_id"], item["device_id"], "failed", error_text)
        logger.warning(
            "Provisionamento pendente descartado (pessoa %s, dispositivo %s): %s",
            item["person_id"], item["device_id"], error_text,
        )
        return False
    try:
        provision_person(device, person, load_person_face_photo(person))
        upsert_provision_status(item["person_id"], item["device_id"], "ok")
    except HTTPException as exc:
        upsert_provision_status(item["person_id"], item["device_id"], "failed", str(exc.detail))
        logger.warning(
            "Retry de provisionamento falhou para pessoa %s no dispositivo %s: %s",
            item["person_id"], item["device_id"], exc.detail,
        )
    except Exception as exc:
        upsert_provision_status(item["person_id"], item["device_id"], "failed", str(exc))
        logger.exception(
            "Erro inesperado no retry de provisionamento (pessoa %s, dispositivo %s)",
            item["person_id"], item["device_id"],
        )
    return True


def poll_device_events(device_id: str) -> int:
    """Busca eventos novos de um dispositivo e grava no historico.

    O cursor salvo em access_devices.last_event_id evita reler o historico
    inteiro da controladora a cada ciclo. record_event ainda deduplica por
    seguranca, caso algum firmware devolva uma janela sobreposta.
    """
    device = get_device_with_password(device_id)
    if not device:
        return 0
    device["last_event_start_time"] = latest_device_event_occurred_at(device_id)
    try:
        events = poll_events(device, since_id=device.get("last_event_id") or "")
    except HTTPException as exc:
        logger.warning("Falha ao consultar eventos do dispositivo %s: %s", device_id, exc.detail)
        try:
            update_device_health(device_id, status="offline", last_seen_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        except ValueError:
            logger.warning("Nao foi possivel marcar dispositivo %s como offline", device_id)
        return 0
    try:
        update_device_health(
            device_id,
            status="online",
            model=str(device.get("model") or ""),
            last_seen_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except ValueError:
        logger.warning("Nao foi possivel atualizar status do dispositivo %s", device_id)
    max_raw_event_id = 0
    for event in events:
        _record_device_event(device, event, source="device")
        raw_id = str(event.get("raw_event_id") or event.get("raw_id") or event.get("id") or "").strip()
        if raw_id.isdigit():
            max_raw_event_id = max(max_raw_event_id, int(raw_id))
    if max_raw_event_id:
        try:
            update_device_event_cursor(device_id, str(max_raw_event_id))
        except ValueError:
            logger.warning("Nao foi possivel atualizar cursor de eventos do dispositivo %s", device_id)
    return len(events)
