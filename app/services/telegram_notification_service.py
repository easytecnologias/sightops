from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from app.core.tenant_context import get_current_tenant_slug
from app.services.db_store import _conn, load_app_settings, save_app_settings
from app.services.monitoring_service import list_entities


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_telegram_config() -> Dict[str, Any]:
    cfg = load_app_settings().get("telegram_notifications") or {}
    return {
        "enabled": bool(cfg.get("enabled")), "configured": bool(cfg.get("bot_token") and cfg.get("chat_id")),
        "chat_id": _text(cfg.get("chat_id")), "warn_rx": float(cfg.get("warn_rx", -27)),
        "critical_rx": float(cfg.get("critical_rx", -29)), "notify_recovery": bool(cfg.get("notify_recovery", True)),
        "types": list(cfg.get("types") or ["connector", "olt", "onu", "camera", "nvr", "dvr", "windows", "whatsapp", "access_point"]),
    }


def save_telegram_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    settings = load_app_settings()
    old = settings.get("telegram_notifications") or {}
    token = _text(payload.get("bot_token")) or _text(old.get("bot_token"))
    settings["telegram_notifications"] = {
        "enabled": bool(payload.get("enabled")), "bot_token": token, "chat_id": _text(payload.get("chat_id")),
        "warn_rx": float(payload.get("warn_rx", -27)), "critical_rx": float(payload.get("critical_rx", -29)),
        "notify_recovery": bool(payload.get("notify_recovery", True)),
        # Sem "types" no payload, mantem a lista salva (antes voltava ao padrao sem avisar).
        "types": list(payload.get("types") or old.get("types") or ["connector", "olt", "onu", "camera", "nvr", "dvr", "windows", "whatsapp", "access_point"]),
    }
    save_app_settings(settings)
    return get_telegram_config()


def _send(cfg: Dict[str, Any], message: str) -> Dict[str, Any]:
    token, chat_id = _text(cfg.get("bot_token")), _text(cfg.get("chat_id"))
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram nao configurado."}
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20,
    )
    data = response.json() if response.content else {}
    if response.ok and data.get("ok"):
        return {"ok": True}
    return {"ok": False, "error": _text(data.get("description")) or f"HTTP {response.status_code}"}


def test_telegram() -> Dict[str, Any]:
    cfg = load_app_settings().get("telegram_notifications") or {}
    tenant = _text(get_current_tenant_slug() or "default")
    result = _send(cfg, f"✅ <b>SightOps conectado</b>\n\nCliente: {html.escape(tenant)}\nAs notificações de monitoramento estão prontas.")
    return {**result, "tenant": tenant}


def _state(entity_key: str, kind: str) -> Dict[str, Any]:
    tenant = _text(get_current_tenant_slug() or "default").lower()
    with _conn() as c:
        row = c.execute("SELECT * FROM notification_states WHERE tenant_slug=? AND entity_key=? AND alert_kind=?", (tenant, entity_key, kind)).fetchone()
    return dict(row or {})


def _set_state(entity_key: str, kind: str, active: bool, value: str) -> None:
    tenant, now = _text(get_current_tenant_slug() or "default").lower(), _now()
    current = _state(entity_key, kind)
    opened = current.get("opened_at") if current else None
    if active and not current.get("active"):
        opened = now
    closed = now if not active else None
    with _conn() as c:
        c.execute(
            "INSERT INTO notification_states(tenant_slug,entity_key,alert_kind,active,opened_at,closed_at,last_sent_at,last_value,updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(tenant_slug,entity_key,alert_kind) DO UPDATE SET active=excluded.active,opened_at=excluded.opened_at,closed_at=excluded.closed_at,last_sent_at=excluded.last_sent_at,last_value=excluded.last_value,updated_at=excluded.updated_at",
            (tenant, entity_key, kind, 1 if active else 0, opened, closed, now, value, now),
        )


def process_monitoring_notifications() -> Dict[str, Any]:
    raw_cfg = load_app_settings().get("telegram_notifications") or {}
    public = get_telegram_config()
    if not public["enabled"] or not public["configured"]:
        return {"ok": True, "skipped": True, "reason": "Telegram desativado ou nao configurado", "sent": 0}
    allowed = set(public["types"])
    sent, errors = 0, []
    for row in list_entities(limit=2000):
        entity_type, status = _text(row.get("entity_type")), _text(row.get("status"))
        if entity_type not in allowed:
            continue
        key, name, site = _text(row.get("entity_key")), _text(row.get("display_name")), _text(row.get("site")) or "--"
        down_state = _state(key, "offline")
        if status == "down" and not down_state.get("active"):
            msg = f"🔴 <b>EQUIPAMENTO OFFLINE</b>\n\nTipo: {html.escape(entity_type.upper())}\nEquipamento: {html.escape(name)}\nSite: {html.escape(site)}\nDetectado: {html.escape(_now())}"
            # Motivo vindo do monitoramento (ex.: WhatsApp "conectado" mas a
            # Meta recusando os avisos): sem ele o alerta so dizia "offline".
            try: motivo = _text(json.loads(_text(row.get("detail_json")) or "{}").get("motivo"))
            except Exception: motivo = ""
            if motivo:
                msg += f"\nMotivo: {html.escape(motivo)}"
            result = _send(raw_cfg, msg)
            if result.get("ok"): _set_state(key, "offline", True, status); sent += 1
            else: errors.append(result.get("error"))
        elif status == "up" and down_state.get("active") and public["notify_recovery"]:
            msg = f"🟢 <b>EQUIPAMENTO RECUPERADO</b>\n\nTipo: {html.escape(entity_type.upper())}\nEquipamento: {html.escape(name)}\nSite: {html.escape(site)}\nRecuperado: {html.escape(_now())}"
            result = _send(raw_cfg, msg)
            if result.get("ok"): _set_state(key, "offline", False, status); sent += 1
            else: errors.append(result.get("error"))
        if entity_type in ("nvr", "dvr"):
            # Gravador que responde mas nao recebe imagem de camera que esta no
            # ar: nunca fica "down", entao o aviso de offline nao cobre. Foi
            # assim que o NVR 01 da SIERRA perdeu 14 cameras sem ninguem saber.
            try: detail = json.loads(_text(row.get("detail_json")) or "{}")
            except Exception: detail = {}
            canais = [str(c) for c in (detail.get("canais_sem_imagem_lista") or [])]
            img_state = _state(key, "sem_imagem")
            atual = ",".join(canais)
            if canais and not (img_state.get("active") and atual == _text(img_state.get("last_value"))):
                msg = (f"🟠 <b>GRAVADOR SEM IMAGEM</b>\n\nGravador: {html.escape(name)}\nSite: {html.escape(site)}\n"
                       f"Cameras no ar sem imagem no gravador: <b>{len(canais)}</b>\nCanais: {html.escape(', '.join(canais))}\n"
                       f"Detectado: {html.escape(_now())}")
                result = _send(raw_cfg, msg)
                if result.get("ok"): _set_state(key, "sem_imagem", True, atual); sent += 1
                else: errors.append(result.get("error"))
            elif not canais and img_state.get("active"):
                if not public["notify_recovery"]:
                    _set_state(key, "sem_imagem", False, "")
                    continue
                msg = (f"🟢 <b>GRAVADOR COM IMAGEM DE NOVO</b>\n\nGravador: {html.escape(name)}\nSite: {html.escape(site)}\n"
                       f"Recuperado: {html.escape(_now())}")
                result = _send(raw_cfg, msg)
                if result.get("ok"): _set_state(key, "sem_imagem", False, ""); sent += 1
                else: errors.append(result.get("error"))
            continue
        if entity_type in ("connector", "access_point"):
            # Alarme do proprio equipamento (gateway/AP Ruijie: ex. "alimentacao
            # insuficiente"). O equipamento segue "up", entao o aviso de
            # offline nao cobre. So com a lista de alarmes lida (checado_em):
            # sem leitura, "nenhum alarme" seria chute.
            try: detail = json.loads(_text(row.get("detail_json")) or "{}")
            except Exception: detail = {}
            if not detail.get("checado_em"):
                continue
            alarmes = [str(a) for a in (detail.get("alarmes") or [])]
            if detail.get("conflito_ip"):
                alarmes.append("Conflito de IP na rede")
            al_state = _state(key, "alarme")
            atual = " | ".join(alarmes)
            if alarmes and not (al_state.get("active") and atual == _text(al_state.get("last_value"))):
                msg = (f"🟠 <b>ALARME NO EQUIPAMENTO</b>\n\nTipo: {html.escape(entity_type.upper())}\nEquipamento: {html.escape(name)}\n"
                       f"Site: {html.escape(site)}\nAlarmes: {html.escape(atual)}\nDetectado: {html.escape(_now())}")
                result = _send(raw_cfg, msg)
                if result.get("ok"): _set_state(key, "alarme", True, atual); sent += 1
                else: errors.append(result.get("error"))
            elif not alarmes and al_state.get("active"):
                if not public["notify_recovery"]:
                    _set_state(key, "alarme", False, "")
                    continue
                msg = (f"🟢 <b>ALARME RESOLVIDO</b>\n\nEquipamento: {html.escape(name)}\nSite: {html.escape(site)}\n"
                       f"Resolvido: {html.escape(_now())}")
                result = _send(raw_cfg, msg)
                if result.get("ok"): _set_state(key, "alarme", False, ""); sent += 1
                else: errors.append(result.get("error"))
            continue
        if entity_type != "onu":
            continue
        try: detail = json.loads(_text(row.get("detail_json")) or "{}")
        except Exception: detail = {}
        try: rx = float(_text(detail.get("onu_rx")).split()[0].replace(",", "."))
        except Exception: continue
        signal_state = _state(key, "signal")
        if rx <= public["warn_rx"] and not signal_state.get("active"):
            level = "CRÍTICO" if rx <= public["critical_rx"] else "DEGRADADO"
            msg = f"🟡 <b>SINAL ÓPTICO {level}</b>\n\nONU: {html.escape(name)}\nSite: {html.escape(site)}\nONU RX: <b>{rx:.2f} dBm</b>\nOLT RX: {html.escape(_text(detail.get('olt_rx')) or '--')}\nDistância: {html.escape(_text(detail.get('distance_km')) or '--')} km"
            result = _send(raw_cfg, msg)
            if result.get("ok"): _set_state(key, "signal", True, str(rx)); sent += 1
            else: errors.append(result.get("error"))
        elif rx > public["warn_rx"] + 1 and signal_state.get("active") and public["notify_recovery"]:
            result = _send(raw_cfg, f"🟢 <b>SINAL ÓPTICO NORMALIZADO</b>\n\nONU: {html.escape(name)}\nSite: {html.escape(site)}\nONU RX: <b>{rx:.2f} dBm</b>")
            if result.get("ok"): _set_state(key, "signal", False, str(rx)); sent += 1
            else: errors.append(result.get("error"))
    return {"ok": not errors, "sent": sent, "errors": errors[:5]}
