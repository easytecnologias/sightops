from __future__ import annotations

import base64
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.tenant_context import tenant_scoped_key
from app.services import db_store
from app.services.access_control_photos import save_person_face_photo
from app.services.access_control_store import (
    list_devices,
    list_group_members,
    list_groups,
    list_people,
    list_people_sites,
    save_person,
    set_group_members,
)
from app.services.access_control_sync import enqueue_person_provisioning

DRAFTS_KEY = "access_control_whatsapp_registration_drafts"
TRIAGE_KEY = "access_control_whatsapp_triage_items"
INBOUND_TOKEN_KEY = "access_control_whatsapp_inbound_token"
TRIAGE_GROUPS_KEY = "access_control_whatsapp_triage_groups"

FIELD_ALIASES = {
    "nome": "full_name",
    "name": "full_name",
    "pessoa": "full_name",
    "matricula": "enrollment_code",
    "mat": "enrollment_code",
    "codigo": "enrollment_code",
    "id": "controller_user_id",
    "usuario": "controller_user_id",
    "controladora": "controller_user_id",
    "site": "site",
    "escola": "site",
    "unidade": "site",
    "tipo": "person_type",
    "documento": "document_id",
    "doc": "document_id",
    "turma": "class_name",
    "responsavel": "guardian_name",
    "telefone": "guardian_phone",
    "whatsapp": "guardian_phone",
    "grupo": "group_name",
}

PERSON_TYPES = {
    "aluno": "student",
    "student": "student",
    "funcionario": "employee",
    "colaborador": "employee",
    "employee": "employee",
    "visitante": "visitor",
    "visitor": "visitor",
}


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _norm(value: Any) -> str:
    clean = re.sub(r"\s+", " ", _text(value, 200)).casefold()
    return "".join(ch for ch in unicodedata.normalize("NFKD", clean) if not unicodedata.combining(ch))


def _sender_key(number: Any) -> str:
    digits = _digits(number)
    return digits[-14:] if digits else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: Any) -> datetime | None:
    raw = _text(value, 80)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _draft_defaults(from_number: str, site: str = "") -> Dict[str, Any]:
    return {
        "from_number": _text(from_number, 40),
        "full_name": "",
        "person_type": "student",
        "document_id": "",
        "enrollment_code": "",
        "class_name": "",
        "site": _text(site, 120),
        "controller_user_id": "",
        "guardian_name": "",
        "guardian_phone": "",
        "whatsapp_enabled": True,
        "group_name": "",
        "photo_base64": "",
        "updated_at": _now(),
    }


def _load_drafts() -> Dict[str, Any]:
    raw = db_store.get_json_state(tenant_scoped_key(DRAFTS_KEY), {})
    return raw if isinstance(raw, dict) else {}


def _save_drafts(drafts: Dict[str, Any]) -> None:
    db_store.set_json_state(tenant_scoped_key(DRAFTS_KEY), drafts)


def _load_triage_items() -> List[Dict[str, Any]]:
    raw = db_store.get_json_state(tenant_scoped_key(TRIAGE_KEY), [])
    return raw if isinstance(raw, list) else []


def _save_triage_items(items: List[Dict[str, Any]]) -> None:
    db_store.set_json_state(tenant_scoped_key(TRIAGE_KEY), items)


def ensure_access_whatsapp_inbound_token() -> str:
    settings = db_store.load_app_settings()
    token = _text(settings.get(INBOUND_TOKEN_KEY), 120)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    settings[INBOUND_TOKEN_KEY] = token
    db_store.save_app_settings(settings)
    return token


def verify_access_whatsapp_inbound_token(token: Any) -> bool:
    expected = ensure_access_whatsapp_inbound_token()
    given = _text(token, 200)
    return bool(given and secrets.compare_digest(given, expected))


def _load_triage_group_rules() -> List[Dict[str, Any]]:
    settings = db_store.load_app_settings()
    raw = settings.get(TRIAGE_GROUPS_KEY)
    return raw if isinstance(raw, list) else []


def _triage_group_rule(jid: Any) -> Dict[str, Any]:
    target = _text(jid, 160)
    if not target:
        return {}
    for item in _load_triage_group_rules():
        if not isinstance(item, dict):
            continue
        if _text(item.get("jid"), 160) == target and item.get("enabled", True) is not False:
            return item
    return {}


def _default_site() -> str:
    sites = [site for site in list_people_sites() if _text(site, 120)]
    if len(sites) == 1:
        return sites[0]
    device_sites = sorted({_text(device.get("site"), 120) for device in list_devices() if _text(device.get("site"), 120)})
    return device_sites[0] if len(device_sites) == 1 else ""


def _parse_key_values(text: str) -> Dict[str, str]:
    clean = _text(text, 2000)
    pairs: Dict[str, str] = {}
    key_pattern = "|".join(sorted(map(re.escape, FIELD_ALIASES.keys()), key=len, reverse=True))
    regex = re.compile(
        rf"(?P<key>\b(?:{key_pattern})\b)\s*[:=]\s*(?P<value>.*?)(?=\s+\b(?:{key_pattern})\b\s*[:=]|$)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in regex.finditer(clean):
        key = FIELD_ALIASES.get(_norm(match.group("key")))
        value = re.sub(r"\s+", " ", match.group("value")).strip(" ;,")
        if key and value:
            pairs[key] = value[:200]
    return pairs


def _apply_line_command(draft: Dict[str, Any], text: str) -> bool:
    clean = _text(text, 1000)
    first, _, rest = clean.partition(" ")
    field = FIELD_ALIASES.get(_norm(first))
    if not field or not rest.strip():
        return False
    value = rest.strip()
    if field == "person_type":
        value = PERSON_TYPES.get(_norm(value), _norm(value))
    draft[field] = value[:200]
    return True


def _apply_fields(draft: Dict[str, Any], fields: Dict[str, str]) -> None:
    for key, value in fields.items():
        if key == "person_type":
            draft[key] = PERSON_TYPES.get(_norm(value), _norm(value))
        else:
            draft[key] = value
    if not _text(draft.get("controller_user_id")) and _digits(draft.get("enrollment_code")):
        draft["controller_user_id"] = _digits(draft.get("enrollment_code"))
    if not _text(draft.get("enrollment_code")) and _digits(draft.get("controller_user_id")):
        draft["enrollment_code"] = _digits(draft.get("controller_user_id"))
    if not _text(draft.get("site")):
        draft["site"] = _default_site()
    if _text(draft.get("guardian_phone")):
        raw_phone = _text(draft.get("guardian_phone"), 40)
        digits = _digits(raw_phone)
        draft["guardian_phone"] = f"+{digits}" if raw_phone.startswith("+") else digits
    draft["updated_at"] = _now()


def _missing_fields(draft: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if not _text(draft.get("full_name")):
        missing.append("nome")
    if not _text(draft.get("enrollment_code")) and not _text(draft.get("controller_user_id")):
        missing.append("matricula ou id")
    if not _text(draft.get("site")):
        missing.append("site")
    if _text(draft.get("person_type")) not in {"student", "employee", "visitor"}:
        missing.append("tipo")
    return missing


def _find_group(group_name: str, site: str) -> Dict[str, Any] | None:
    clean = _norm(group_name)
    if not clean:
        return None
    groups = [
        group
        for group in list_groups()
        if group.get("active") and (not site or not _text(group.get("site")) or _text(group.get("site")) == site)
    ]
    exact = [group for group in groups if _norm(group.get("name")) == clean]
    if len(exact) == 1:
        return exact[0]
    contains = [group for group in groups if clean in _norm(group.get("name"))]
    return contains[0] if len(contains) == 1 else None


def _next_controller_user_id() -> str:
    max_id = 0
    for person in list_people():
        for key in ("controller_user_id", "enrollment_code"):
            raw = _digits(person.get(key))
            if raw:
                max_id = max(max_id, int(raw))
    return str(max(max_id + 1, 1000))


def _looks_like_name(line: str) -> bool:
    clean = _text(line, 160)
    if not clean or len(clean) < 4:
        return False
    if re.search(r"\d", clean):
        return False
    if _norm(clean) in {"cadastro", "cadastrar", "foto"}:
        return False
    if re.search(r"\b(quadra|lote|apto|apartamento|bloco|casa|unidade|portaria)\b", _norm(clean)):
        return False
    return len(clean.split()) >= 2


def infer_triage_fields(raw_text: Any, *, site: Any = "", source_group: Any = "") -> Dict[str, Any]:
    text = _text(raw_text, 3000)
    lines = [re.sub(r"\s+", " ", line).strip(" -:;") for line in text.splitlines() if line.strip()]
    fields = _parse_key_values(text)
    suggested: Dict[str, Any] = {
        "full_name": fields.get("full_name", ""),
        "person_type": PERSON_TYPES.get(_norm(fields.get("person_type")), fields.get("person_type", "student") or "student"),
        "document_id": fields.get("document_id", ""),
        "enrollment_code": fields.get("enrollment_code", ""),
        "class_name": fields.get("class_name", ""),
        "site": fields.get("site") or _text(site, 120) or _default_site(),
        "controller_user_id": fields.get("controller_user_id", ""),
        "guardian_name": fields.get("guardian_name", ""),
        "guardian_phone": fields.get("guardian_phone", ""),
        "group_name": fields.get("group_name", ""),
        "unit_label": "",
    }
    if not suggested["full_name"]:
        name_line = next((line for line in lines if _looks_like_name(line)), "")
        suggested["full_name"] = name_line
    unit_match = re.search(
        r"\b((?:quadra|lote|quadra/lote|apto|apartamento|bloco|casa)\s*[/\-]?\s*[A-Za-z0-9 ._-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if unit_match:
        suggested["unit_label"] = re.sub(r"\s+", " ", unit_match.group(1)).strip(" .;-")
    if not suggested["unit_label"]:
        short_unit = next((line for line in lines if re.fullmatch(r"[A-Za-z]{1,3}\s*-\s*\d{1,4}", line)), "")
        if short_unit:
            suggested["unit_label"] = re.sub(r"\s*-\s*", "-", short_unit.upper())
    if not suggested["enrollment_code"] and suggested["unit_label"]:
        suggested["enrollment_code"] = suggested["unit_label"][:64]
    if not suggested["controller_user_id"]:
        suggested["controller_user_id"] = _next_controller_user_id()
    if not suggested["group_name"] and source_group:
        suggested["group_name"] = _text(source_group, 160)
    return suggested


def _triage_status_for(suggested: Dict[str, Any], *, has_photo: bool = False) -> tuple[str, List[str]]:
    reasons: List[str] = []
    name = _text(suggested.get("full_name"), 160)
    site = _text(suggested.get("site"), 120)
    if not name:
        reasons.append("nome nao identificado")
    if not site:
        reasons.append("site nao identificado")
    if not has_photo:
        reasons.append("sem foto")
    name_key = _norm(name)
    if name_key:
        matches = [p for p in list_people() if _norm(p.get("full_name")) == name_key]
        if matches:
            reasons.append("possivel duplicado")
    if "possivel duplicado" in reasons:
        return "duplicate", reasons
    if reasons:
        return "review", reasons
    return "ready", []


def _status_rank(status: Any) -> int:
    order = {"ready": 0, "review": 1, "duplicate": 2, "approved": 3, "rejected": 4}
    return order.get(str(status or ""), 9)


def list_access_whatsapp_triage(status: str = "") -> Dict[str, Any]:
    clean_status = _text(status, 40).lower()
    items = _load_triage_items()
    if clean_status:
        items = [item for item in items if _text(item.get("status"), 40).lower() == clean_status]
    items = sorted(items, key=lambda item: (_status_rank(item.get("status")), str(item.get("created_at") or "")), reverse=False)
    summary = {
        "total": len(items),
        "ready": sum(1 for item in items if item.get("status") == "ready"),
        "review": sum(1 for item in items if item.get("status") == "review"),
        "duplicate": sum(1 for item in items if item.get("status") == "duplicate"),
        "approved": sum(1 for item in items if item.get("status") == "approved"),
        "rejected": sum(1 for item in items if item.get("status") == "rejected"),
    }
    return {"items": items, "summary": summary}


def create_access_whatsapp_triage_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    raw_text = _text(payload.get("text") or payload.get("raw_text"), 3000)
    source_group = _text(payload.get("source_group") or payload.get("group") or "", 160)
    site = _text(payload.get("site"), 120)
    suggested = payload.get("suggested") if isinstance(payload.get("suggested"), dict) else None
    if suggested is None:
        suggested = infer_triage_fields(raw_text, site=site, source_group=source_group)
    photo_base64 = _text(payload.get("photo_base64"), 200000)
    status, reasons = _triage_status_for(suggested, has_photo=bool(photo_base64 or payload.get("photo_url")))
    item = {
        "id": uuid.uuid4().hex,
        "status": status,
        "reasons": reasons,
        "source": _text(payload.get("source") or "whatsapp", 40),
        "source_group": source_group,
        "source_group_jid": _text(payload.get("source_group_jid"), 160),
        "from_number": _text(payload.get("from_number"), 40),
        "from_name": _text(payload.get("from_name"), 160),
        "raw_text": raw_text,
        "photo_url": _text(payload.get("photo_url"), 500),
        "photo_base64": photo_base64,
        "suggested": suggested,
        "created_at": _now(),
        "updated_at": _now(),
        "approved_at": "",
        "person_id": "",
        "last_error": "",
    }
    items = _load_triage_items()
    items.insert(0, item)
    _save_triage_items(items[:500])
    return item


def _merge_recent_triage_item(payload: Dict[str, Any]) -> Dict[str, Any] | None:
    raw_text = _text(payload.get("text") or payload.get("raw_text"), 3000)
    photo_url = _text(payload.get("photo_url"), 500)
    photo_base64 = _text(payload.get("photo_base64"), 200000)
    if not raw_text and not photo_url and not photo_base64:
        return None
    source_group_jid = _text(payload.get("source_group_jid"), 160)
    from_number = _text(payload.get("from_number"), 40)
    now_dt = datetime.now(timezone.utc)
    items = _load_triage_items()
    for idx, item in enumerate(items):
        if item.get("status") not in {"ready", "review", "duplicate"}:
            continue
        if _text(item.get("source_group_jid"), 160) != source_group_jid:
            continue
        item_text = _text(item.get("raw_text"), 3000)
        item_photo = _text(item.get("photo_url"), 500) or _text(item.get("photo_base64"), 200000)
        if raw_text and item_text == raw_text:
            if photo_url and not _text(item.get("photo_url"), 500):
                item["photo_url"] = photo_url
            if photo_base64 and not _text(item.get("photo_base64"), 200000):
                item["photo_base64"] = photo_base64
            status, reasons = _triage_status_for(
                item.get("suggested") if isinstance(item.get("suggested"), dict) else {},
                has_photo=bool(item.get("photo_url") or item.get("photo_base64")),
            )
            item["status"] = status
            item["reasons"] = reasons
            item["updated_at"] = _now()
            items[idx] = item
            _save_triage_items(items)
            return item
        if (
            not raw_text
            and item_text
            and item_photo
            and _text(item.get("from_name"), 160) == _text(payload.get("from_name"), 160)
        ):
            return item
        if _text(item.get("from_number"), 40) != from_number:
            continue
        created_at = _parse_time(item.get("created_at"))
        if created_at and abs((now_dt - created_at).total_seconds()) > 120:
            continue
        if item_text and raw_text and item_text != raw_text:
            continue
        if item_photo and (photo_url or photo_base64):
            if not raw_text and item_text:
                return item
            continue
        if raw_text and not item_text:
            item["raw_text"] = raw_text
            item["suggested"] = infer_triage_fields(
                raw_text,
                site=payload.get("site") or (item.get("suggested") or {}).get("site") or "",
                source_group=payload.get("source_group") or item.get("source_group") or "",
            )
        if photo_url and not _text(item.get("photo_url"), 500):
            item["photo_url"] = photo_url
        if photo_base64 and not _text(item.get("photo_base64"), 200000):
            item["photo_base64"] = photo_base64
        status, reasons = _triage_status_for(
            item.get("suggested") if isinstance(item.get("suggested"), dict) else {},
            has_photo=bool(item.get("photo_url") or item.get("photo_base64")),
        )
        item["status"] = status
        item["reasons"] = reasons
        item["updated_at"] = _now()
        items[idx] = item
        _save_triage_items(items)
        return item
    return None


def update_access_whatsapp_triage_item(item_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    clean_id = _text(item_id, 80)
    items = _load_triage_items()
    for idx, item in enumerate(items):
        if item.get("id") != clean_id:
            continue
        suggested = dict(item.get("suggested") or {})
        incoming = payload.get("suggested") if isinstance(payload.get("suggested"), dict) else payload
        for key in (
            "full_name",
            "person_type",
            "document_id",
            "enrollment_code",
            "class_name",
            "site",
            "controller_user_id",
            "guardian_name",
            "guardian_phone",
            "group_name",
            "unit_label",
        ):
            if key in incoming:
                suggested[key] = _text(incoming.get(key), 200)
        item["suggested"] = suggested
        item["raw_text"] = _text(payload.get("raw_text"), 3000) if "raw_text" in payload else item.get("raw_text", "")
        item["photo_base64"] = _text(payload.get("photo_base64"), 200000) if "photo_base64" in payload else item.get("photo_base64", "")
        item["photo_url"] = _text(payload.get("photo_url"), 500) if "photo_url" in payload else item.get("photo_url", "")
        status, reasons = _triage_status_for(suggested, has_photo=bool(item.get("photo_base64") or item.get("photo_url")))
        item["status"] = _text(payload.get("status"), 40) if payload.get("status") in {"ready", "review", "duplicate"} else status
        item["reasons"] = reasons
        item["updated_at"] = _now()
        items[idx] = item
        _save_triage_items(items)
        return item
    raise ValueError("Item de triagem nao encontrado.")


def _person_payload_from_triage(item: Dict[str, Any]) -> Dict[str, Any]:
    suggested = item.get("suggested") if isinstance(item.get("suggested"), dict) else {}
    controller_user_id = _text(suggested.get("controller_user_id"), 32) or _next_controller_user_id()
    enrollment = _text(suggested.get("enrollment_code"), 64) or controller_user_id
    notes = "Criado pela Triagem WhatsApp."
    unit_label = _text(suggested.get("unit_label"), 120)
    if unit_label:
        notes += f" Identificacao: {unit_label}."
    raw_text = _text(item.get("raw_text"), 500)
    if raw_text:
        notes += f" Origem WhatsApp: {raw_text}"
    return {
        "full_name": _text(suggested.get("full_name"), 160).upper(),
        "person_type": PERSON_TYPES.get(_norm(suggested.get("person_type")), _text(suggested.get("person_type"), 32) or "student"),
        "document_id": _text(suggested.get("document_id"), 64),
        "enrollment_code": enrollment,
        "class_name": _text(suggested.get("class_name"), 80),
        "site": _text(suggested.get("site"), 120),
        "controller_user_id": controller_user_id,
        "guardian_name": _text(suggested.get("guardian_name"), 160),
        "guardian_phone": _text(suggested.get("guardian_phone"), 40),
        "whatsapp_enabled": True,
        "active": True,
        "notes": notes[:500],
    }


def approve_access_whatsapp_triage_item(item_id: str) -> Dict[str, Any]:
    clean_id = _text(item_id, 80)
    items = _load_triage_items()
    for idx, item in enumerate(items):
        if item.get("id") != clean_id:
            continue
        if item.get("status") not in {"ready", "review", "duplicate"}:
            raise ValueError("Este item nao esta pendente.")
        suggested = item.get("suggested") if isinstance(item.get("suggested"), dict) else {}
        status, reasons = _triage_status_for(suggested, has_photo=bool(item.get("photo_base64") or item.get("photo_url")))
        if status != "ready":
            raise ValueError("Revise este cadastro antes de aprovar: " + ", ".join(reasons))
        person = save_person(_person_payload_from_triage(item))
        photo_saved = False
        if _text(item.get("photo_base64"), 200000):
            try:
                raw = base64.b64decode(_text(item.get("photo_base64"), 200000), validate=True)
                person = save_person_face_photo(person["id"], raw)["person"]
                photo_saved = True
            except Exception:
                photo_saved = False
        group_name = _text(suggested.get("group_name"), 160)
        group = _find_group(group_name, _text(person.get("site"), 120)) if group_name else None
        if group:
            members = list_group_members(group["id"])
            if person["id"] not in members:
                set_group_members(group["id"], [*members, person["id"]])
        queued = enqueue_person_provisioning([person["id"]], force=True)
        item.update({
            "status": "approved",
            "approved_at": _now(),
            "updated_at": _now(),
            "person_id": person["id"],
            "last_error": "",
        })
        items[idx] = item
        _save_triage_items(items)
        return {"item": item, "person": person, "queued": queued, "photo_saved": photo_saved}
    raise ValueError("Item de triagem nao encontrado.")


def reject_access_whatsapp_triage_item(item_id: str, reason: Any = "") -> Dict[str, Any]:
    clean_id = _text(item_id, 80)
    items = _load_triage_items()
    for idx, item in enumerate(items):
        if item.get("id") != clean_id:
            continue
        item["status"] = "rejected"
        item["reasons"] = [_text(reason, 200) or "recusado manualmente"]
        item["updated_at"] = _now()
        items[idx] = item
        _save_triage_items(items)
        return item
    raise ValueError("Item de triagem nao encontrado.")


def approve_ready_access_whatsapp_triage_items() -> Dict[str, Any]:
    items = _load_triage_items()
    ready_ids = [item["id"] for item in items if item.get("status") == "ready"]
    approved: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for item_id in ready_ids:
        try:
            approved.append(approve_access_whatsapp_triage_item(item_id))
        except Exception as exc:
            failed.append({"id": item_id, "error": str(exc)})
    remaining = list_access_whatsapp_triage()["summary"]
    names = [entry["person"].get("full_name", "") for entry in approved]
    lines = ["TODOS OK", "", f"{len(approved)} cadastros aprovados e enviados para a fila da controladora."]
    if names:
        lines.append("")
        lines.extend(f"- {name}" for name in names[:20])
    review_left = remaining.get("review", 0) + remaining.get("duplicate", 0)
    if review_left:
        lines.extend(["", f"{review_left} precisa(m) revisar antes de aprovar."])
    if failed:
        lines.extend(["", f"{len(failed)} falhou/falharam na aprovacao."])
    return {"approved": approved, "failed": failed, "group_message": "\n".join(lines), "summary": remaining}


def _format_preview(draft: Dict[str, Any]) -> str:
    kind = {
        "student": "aluno",
        "employee": "funcionario",
        "visitor": "visitante",
    }.get(_text(draft.get("person_type")), _text(draft.get("person_type")) or "aluno")
    lines = [
        "Rascunho do cadastro:",
        f"Nome: {_text(draft.get('full_name')) or '-'}",
        f"Tipo: {kind}",
        f"Matricula: {_text(draft.get('enrollment_code')) or '-'}",
        f"ID controladora: {_text(draft.get('controller_user_id')) or '-'}",
        f"Site: {_text(draft.get('site')) or '-'}",
        f"Grupo: {_text(draft.get('group_name')) or '-'}",
    ]
    if _text(draft.get("guardian_name")):
        lines.append(f"Responsavel: {_text(draft.get('guardian_name'))}")
    if _text(draft.get("guardian_phone")):
        lines.append(f"WhatsApp: {_text(draft.get('guardian_phone'))}")
    if _text(draft.get("class_name")):
        lines.append(f"Turma: {_text(draft.get('class_name'))}")
    lines.extend(["", "Envie CONFIRMAR para criar ou CANCELAR para descartar."])
    missing = _missing_fields(draft)
    if missing:
        lines.append(f"Falta informar: {', '.join(missing)}.")
    return "\n".join(lines)


def _confirm_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    missing = _missing_fields(draft)
    if missing:
        return {"ok": False, "reply": "Ainda falta: " + ", ".join(missing) + ".\n\n" + _format_preview(draft)}
    group_name = _text(draft.get("group_name"), 160)
    group = _find_group(group_name, _text(draft.get("site"), 120)) if group_name else None
    if group_name and not group:
        return {"ok": False, "reply": f"Nao encontrei um grupo unico chamado '{group_name}'. Corrija com: grupo NOME_DO_GRUPO"}
    payload = {
        "full_name": _text(draft.get("full_name"), 160).upper(),
        "person_type": _text(draft.get("person_type"), 32) or "student",
        "document_id": _text(draft.get("document_id"), 64),
        "enrollment_code": _text(draft.get("enrollment_code"), 64),
        "class_name": _text(draft.get("class_name"), 80),
        "site": _text(draft.get("site"), 120),
        "controller_user_id": _text(draft.get("controller_user_id"), 32),
        "guardian_name": _text(draft.get("guardian_name"), 160),
        "guardian_phone": _text(draft.get("guardian_phone"), 40),
        "whatsapp_enabled": True,
        "active": True,
        "notes": "Criado por fluxo WhatsApp.",
    }
    person = save_person(payload)
    photo_saved = False
    if _text(draft.get("photo_base64"), 200000):
        try:
            raw = base64.b64decode(_text(draft.get("photo_base64"), 200000), validate=True)
            person = save_person_face_photo(person["id"], raw)["person"]
            photo_saved = True
        except Exception:
            photo_saved = False
    if group:
        members = list_group_members(group["id"])
        if person["id"] not in members:
            set_group_members(group["id"], [*members, person["id"]])
    queued = enqueue_person_provisioning([person["id"]], force=True)
    details = [
        f"Cadastro criado: {person['full_name']}",
        f"Matricula: {person.get('enrollment_code') or '-'}",
        f"Site: {person.get('site') or '-'}",
        f"Provisionamento enfileirado: {queued} dispositivo(s).",
    ]
    if group:
        details.append(f"Grupo vinculado: {group.get('name')}.")
    if photo_saved:
        details.append("Foto recebida e salva.")
    elif _text(draft.get("photo_base64")):
        details.append("A foto nao foi salva. Envie uma imagem valida pela tela por enquanto.")
    return {"ok": True, "person": person, "queued": queued, "reply": "\n".join(details)}


def process_access_whatsapp_text(from_number: Any, text: Any, *, site: Any = "", photo_base64: Any = "") -> Dict[str, Any]:
    number = _text(from_number, 40)
    key = _sender_key(number)
    if not key:
        return {"ok": False, "reply": "Nao consegui identificar o numero que enviou a mensagem."}
    message = _text(text, 2000)
    command = _norm(message)
    drafts = _load_drafts()
    draft = drafts.get(key) if isinstance(drafts.get(key), dict) else _draft_defaults(number, _text(site, 120))

    if command in {"cancelar", "cancela", "cancel"}:
        drafts.pop(key, None)
        _save_drafts(drafts)
        return {"ok": True, "reply": "Cadastro cancelado. Nenhum dado foi criado.", "draft": None}

    if command in {"ajuda", "help", "inicio", "comecar", "começar", "cadastro", "cadastrar"}:
        drafts[key] = draft
        _save_drafts(drafts)
        return {
            "ok": True,
            "reply": (
                "Vamos cadastrar uma pessoa.\n"
                "Envie assim:\n"
                "nome: Maria Silva matricula: 1234 site: RESERVA grupo: GERAL\n\n"
                "Depois envie RESUMO para revisar e CONFIRMAR para criar."
            ),
            "draft": draft,
        }

    if command in {"resumo", "revisar", "preview"}:
        drafts[key] = draft
        _save_drafts(drafts)
        return {"ok": True, "reply": _format_preview(draft), "draft": draft}

    if command in {"confirmar", "confirma", "ok"}:
        result = _confirm_draft(draft)
        if result.get("ok"):
            drafts.pop(key, None)
        else:
            drafts[key] = draft
        _save_drafts(drafts)
        return {**result, "draft": None if result.get("ok") else draft}

    fields = _parse_key_values(message)
    changed_by_line = False
    if not fields:
        changed_by_line = _apply_line_command(draft, message)
    if not fields and not changed_by_line:
        return {
            "ok": False,
            "reply": "Nao entendi. Envie AJUDA para ver o formato ou RESUMO para revisar o cadastro em aberto.",
            "draft": draft,
        }
    _apply_fields(draft, fields)
    if _text(site, 120) and not _text(draft.get("site")):
        draft["site"] = _text(site, 120)
    if _text(photo_base64, 200000):
        draft["photo_base64"] = _text(photo_base64, 200000)
    drafts[key] = draft
    _save_drafts(drafts)
    return {"ok": True, "reply": _format_preview(draft), "draft": draft}


def extract_evolution_inbound(payload: Dict[str, Any]) -> Dict[str, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data and (isinstance(payload.get("key"), dict) or isinstance(payload.get("message"), dict)):
        data = payload
    message_obj = data.get("message") if isinstance(data.get("message"), dict) else {}
    image_obj = message_obj.get("imageMessage") if isinstance(message_obj.get("imageMessage"), dict) else {}
    key_obj = data.get("key") if isinstance(data.get("key"), dict) else {}
    remote = (
        payload.get("from")
        or payload.get("sender")
        or payload.get("number")
        or data.get("sender")
        or key_obj.get("remoteJid")
        or ""
    )
    remote_text = _text(remote, 120)
    is_group = remote_text.endswith("@g.us")
    sender_jid = _text(key_obj.get("participant") or data.get("participant") or remote_text, 120)
    text = (
        payload.get("text")
        or (payload.get("message") if isinstance(payload.get("message"), str) else "")
        or data.get("text")
        or message_obj.get("conversation")
        or (message_obj.get("extendedTextMessage") or {}).get("text")
        or image_obj.get("caption")
        or ""
    )
    site = payload.get("site") or data.get("site") or ""
    photo_url = (
        payload.get("photo_url")
        or payload.get("mediaUrl")
        or data.get("mediaUrl")
        or data.get("media")
        or image_obj.get("url")
        or ""
    )
    photo_base64 = payload.get("photo_base64") or data.get("base64") or image_obj.get("base64") or image_obj.get("jpegThumbnail") or ""
    return {
        "from_number": _digits(sender_jid if is_group else remote_text),
        "text": _text(text, 2000),
        "site": _text(site, 120),
        "is_group": is_group,
        "source_group_jid": remote_text if is_group else "",
        "source_group": _text(payload.get("groupName") or data.get("groupName") or data.get("pushName") or "", 160),
        "from_name": _text(payload.get("pushName") or data.get("pushName") or "", 160),
        "photo_url": _text(photo_url, 2000),
        "photo_base64": _text(photo_base64, 200000),
    }


def extract_meta_inbound(payload: Dict[str, Any]) -> Dict[str, str]:
    """Le o formato de webhook da Cloud API oficial.

    A Meta entrega tudo aninhado em entry[].changes[].value, e separa mensagens
    recebidas (`messages`) de confirmacoes de entrega (`statuses`). Aqui so as
    mensagens interessam -- os status sao tratados no endpoint.

    Grupo nao existe neste canal: a Cloud API atende apenas conversa individual.
    """
    vazio = {
        "from_number": "", "text": "", "site": "", "is_group": False,
        "source_group_jid": "", "source_group": "", "from_name": "",
        "photo_url": "", "photo_base64": "",
    }
    entradas = payload.get("entry") if isinstance(payload.get("entry"), list) else []
    for entrada in entradas:
        mudancas = (entrada or {}).get("changes") if isinstance(entrada, dict) else []
        for mudanca in mudancas if isinstance(mudancas, list) else []:
            valor = (mudanca or {}).get("value") if isinstance(mudanca, dict) else {}
            if not isinstance(valor, dict):
                continue
            mensagens = valor.get("messages") if isinstance(valor.get("messages"), list) else []
            if not mensagens:
                continue
            msg = mensagens[0] if isinstance(mensagens[0], dict) else {}
            tipo = _text(msg.get("type"), 32)
            texto = ""
            if tipo == "text":
                texto = (msg.get("text") or {}).get("body") or ""
            elif tipo in {"image", "document", "video"}:
                texto = (msg.get(tipo) or {}).get("caption") or ""
            elif tipo == "button":
                texto = (msg.get("button") or {}).get("text") or ""
            elif tipo == "interactive":
                interativo = msg.get("interactive") or {}
                texto = ((interativo.get("button_reply") or {}).get("title")
                         or (interativo.get("list_reply") or {}).get("title") or "")

            contatos = valor.get("contacts") if isinstance(valor.get("contacts"), list) else []
            nome = ""
            if contatos and isinstance(contatos[0], dict):
                nome = ((contatos[0].get("profile") or {}).get("name")) or ""

            return {
                **vazio,
                "from_number": _digits(msg.get("from")),
                "text": _text(texto, 2000),
                "from_name": _text(nome, 160),
            }
    return vazio


def extract_meta_statuses(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """Confirmacoes de entrega que a Meta manda pelo mesmo webhook.

    E o que faltava nos provedores nao oficiais: aqui a plataforma avisa quando
    a mensagem foi entregue, lida ou falhou -- e por que falhou.
    """
    saida: List[Dict[str, str]] = []
    for entrada in payload.get("entry") if isinstance(payload.get("entry"), list) else []:
        for mudanca in (entrada or {}).get("changes") or [] if isinstance(entrada, dict) else []:
            valor = (mudanca or {}).get("value") if isinstance(mudanca, dict) else {}
            for st in (valor.get("statuses") or []) if isinstance(valor, dict) else []:
                if not isinstance(st, dict):
                    continue
                erros = st.get("errors") if isinstance(st.get("errors"), list) else []
                motivo = ""
                if erros and isinstance(erros[0], dict):
                    motivo = _text(erros[0].get("title") or erros[0].get("message"), 200)
                saida.append({
                    "message_id": _text(st.get("id"), 120),
                    "status": _text(st.get("status"), 40),
                    "recipient": _digits(st.get("recipient_id")),
                    "error": motivo,
                })
    return saida


def process_access_whatsapp_inbound(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("object") == "whatsapp_business_account" or isinstance(payload.get("entry"), list):
        extracted = extract_meta_inbound(payload)
    else:
        extracted = extract_evolution_inbound(payload)
    if extracted["is_group"]:
        group_rule = _triage_group_rule(extracted.get("source_group_jid"))
        if not group_rule:
            return {
                "ok": True,
                "triage": False,
                "ignored": True,
                "reason": "Grupo nao liberado para Triagem WhatsApp.",
                "source_group_jid": extracted.get("source_group_jid"),
            }
        item_payload = {
            "text": extracted.get("text"),
            "site": extracted.get("site") or group_rule.get("site") or "",
            "source_group": group_rule.get("name") or extracted.get("source_group"),
            "source_group_jid": extracted.get("source_group_jid"),
            "from_name": extracted.get("from_name"),
            "from_number": extracted.get("from_number"),
            "photo_url": extracted.get("photo_url"),
            "photo_base64": extracted.get("photo_base64"),
        }
        item = _merge_recent_triage_item(item_payload) or create_access_whatsapp_triage_item(item_payload)
        return {
            "ok": True,
            "triage": True,
            "item": item,
            "reply": "Recebi e deixei na Triagem WhatsApp para conferencia.",
        }
    return process_access_whatsapp_text(
        extracted.get("from_number"),
        extracted.get("text"),
        site=extracted.get("site"),
    )
