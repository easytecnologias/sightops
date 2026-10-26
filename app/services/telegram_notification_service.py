"""Avisos do monitoramento no Telegram.

Cada ciclo do monitoramento junta o que MUDOU (caiu, voltou, gravador sem
imagem, alarme, sinal da ONU) e entrega pelas regras de Configuracoes >
Notificacoes (app/services/notificacoes_service.py): cada site vai para os
grupos dele, ou para o grupo padrao. Quedas do mesmo site no mesmo ciclo viram
UMA mensagem (grupo com "juntar"). O estado de cada aviso fica em
notification_states, como antes: so muda quando ao menos um envio deu certo
(senao tenta de novo no proximo ciclo).
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.tenant_context import get_current_tenant_slug
from app.services import notificacoes_service as N
from app.services.db_store import _conn
from app.services.monitoring_service import list_entities

ROTULO_TIPO = {"camera": "câmera", "nvr": "NVR", "dvr": "DVR", "onu": "ONU", "olt": "OLT", "switch": "switch",
               "access_point": "access point", "access_device": "controladora", "connector": "conector",
               "windows": "computador", "whatsapp": "WhatsApp"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- compatibilidade (rotas antigas)

def get_telegram_config() -> Dict[str, Any]:
    return N.compat_telegram()


def save_telegram_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Rota antiga: so os limites de sinal da ONU continuam valendo aqui."""
    if "warn_rx" in payload or "critical_rx" in payload:
        atual = N.config()["sinal"]
        N.salvar_sinal(payload.get("warn_rx", atual["warn_rx"]), payload.get("critical_rx", atual["critical_rx"]))
    return N.compat_telegram()


def test_telegram() -> Dict[str, Any]:
    cfg = N.config()
    res = [N.testar_grupo(g["id"]) for g in cfg["grupos"] if g.get("ativo")]
    if not res:
        return {"ok": False, "error": "Nenhum grupo do Telegram ligado."}
    return {"ok": all(r["ok"] for r in res), "enviados": sum(1 for r in res if r["ok"]),
            "erros": [r["erro"] for r in res if not r["ok"]][:5]}


def _send(cfg: Dict[str, Any], message: str) -> Dict[str, Any]:
    """Compatibilidade: envio direto com bot_token/chat_id (config antiga)."""
    token, chat_id = _text(cfg.get("bot_token")), _text(cfg.get("chat_id"))
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram nao configurado."}
    r = N._telegram(token, "sendMessage", {"chat_id": chat_id, "text": message, "parse_mode": "HTML",
                                           "disable_web_page_preview": True})
    return {"ok": True} if r.get("ok") else {"ok": False, "error": _text(r.get("description")) or "falha no envio"}


# --------------------------------------------------------------------------- estado por equipamento

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


def _detail(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        d = json.loads(_text(row.get("detail_json")) or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _duracao(desde: Any) -> str:
    try:
        ini = datetime.fromisoformat(_text(desde).replace("Z", "+00:00"))
        if ini.tzinfo is None:
            ini = ini.replace(tzinfo=timezone.utc)
        seg = max(0, int((datetime.now(timezone.utc) - ini).total_seconds()))
    except Exception:
        return ""
    if seg < 3600:
        return f"{max(1, seg // 60)} min"
    h, m = divmod(seg // 60, 60)
    return f"{h} h {m:02d} min" if m else f"{h} h"


def _hora_local() -> str:
    return datetime.now(timezone.utc).astimezone(N.FUSO).strftime("%H:%M")


# --------------------------------------------------------------------------- um ciclo

def _coletar(cfg: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, int]]]:
    """Eventos do ciclo: [{evento, tipo, site, chave, kind, ativo, valor, linha, extra}]."""
    eventos: List[Dict[str, Any]] = []
    por_site: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "down": 0})
    sinal = cfg.get("sinal") or {}
    warn, crit = float(sinal.get("warn_rx", -27)), float(sinal.get("critical_rx", -29))
    for row in list_entities(limit=2000):
        tipo, status = _text(row.get("entity_type")), _text(row.get("status"))
        key, nome, site = _text(row.get("entity_key")), _text(row.get("display_name")), _text(row.get("site"))
        sk = N._site_chave(site)
        por_site[sk]["total"] += 1
        if status == "down":
            por_site[sk]["down"] += 1
        detail = _detail(row)
        ip = _text(row.get("ip") or detail.get("ip") or row.get("host"))
        ident = f"{nome} · {ip}" if ip and ip not in nome else nome
        base = {"tipo": tipo, "site": site, "chave": key}

        st = _state(key, "offline")
        if status == "down" and not st.get("active"):
            motivo = _text(detail.get("motivo"))
            eventos.append({**base, "evento": "queda", "kind": "offline", "ativo": True, "valor": status,
                            "linha": ident + (f" — {motivo}" if motivo else "")})
        elif status == "up" and st.get("active"):
            dur = _duracao(st.get("opened_at"))
            eventos.append({**base, "evento": "volta", "kind": "offline", "ativo": False, "valor": status,
                            "linha": ident + (f" (fora {dur})" if dur else "")})

        if tipo in ("nvr", "dvr"):
            # So com o gravador CONFIRMADO "unstable" (histerese em
            # monitoring_service): a lista crua mudava a cada ping perdido de
            # camera e o aviso ia e voltava a cada 6 min.
            canais = [str(c) for c in (detail.get("canais_sem_imagem_lista") or [])] if status == "unstable" else []
            st = _state(key, "sem_imagem")
            atual = ",".join(canais)
            if canais and not (st.get("active") and atual == _text(st.get("last_value"))):
                eventos.append({**base, "evento": "sem_imagem", "kind": "sem_imagem", "ativo": True, "valor": atual,
                                "linha": f"{nome} · canais {', '.join(canais)} sem gravar, com a câmera no ar"})
            elif not canais and st.get("active"):
                eventos.append({**base, "evento": "volta", "kind": "sem_imagem", "ativo": False, "valor": "",
                                "linha": f"{nome} · imagem de volta em todos os canais"})

        if tipo in ("connector", "access_point") and detail.get("checado_em"):
            alarmes = [str(a) for a in (detail.get("alarmes") or [])]
            if detail.get("conflito_ip"):
                alarmes.append("Conflito de IP na rede")
            st = _state(key, "alarme")
            atual = " | ".join(alarmes)
            if alarmes and not (st.get("active") and atual == _text(st.get("last_value"))):
                eventos.append({**base, "evento": "alarme", "kind": "alarme", "ativo": True, "valor": atual,
                                "linha": f"{nome} · {atual}"})
            elif not alarmes and st.get("active"):
                eventos.append({**base, "evento": "volta", "kind": "alarme", "ativo": False, "valor": "",
                                "linha": f"{nome} · alarme resolvido"})

        if tipo == "onu":
            try:
                rx = float(_text(detail.get("onu_rx")).split()[0].replace(",", "."))
            except Exception:
                continue
            st = _state(key, "signal")
            if rx <= warn and not st.get("active"):
                nivel = "crítico" if rx <= crit else "baixo"
                eventos.append({**base, "evento": "sinal_onu", "kind": "signal", "ativo": True, "valor": str(rx),
                                "linha": f"{nome} · {rx:.2f} dBm ({nivel})"})
            elif rx > warn + 1 and st.get("active"):
                eventos.append({**base, "evento": "volta", "kind": "signal", "ativo": False, "valor": str(rx),
                                "linha": f"{nome} · sinal normal, {rx:.2f} dBm"})
    return eventos, por_site


_TITULO = {
    ("queda", 1): "{tipo} caiu", ("queda", 2): "{n} {tipos} caíram",
    ("volta", 1): "{tipo} voltou", ("volta", 2): "{n} {tipos} voltaram",
    ("sem_imagem", 1): "Gravador sem imagem", ("sem_imagem", 2): "{n} gravadores sem imagem",
    ("alarme", 1): "Alarme no equipamento", ("alarme", 2): "{n} equipamentos com alarme",
    ("sinal_onu", 1): "Sinal da ONU baixo", ("sinal_onu", 2): "{n} ONUs com sinal baixo",
}
_PLURAL = {"câmera": "câmeras", "controladora": "controladoras", "conector": "conectores", "computador": "computadores",
           "switch": "switches", "access point": "access points", "equipamento": "equipamentos"}
_ICONE = {"queda": "🔴", "volta": "🟢", "sem_imagem": "🟠", "alarme": "🟠", "sinal_onu": "🟡"}


def _mensagem(evento: str, site: str, itens: List[Dict[str, Any]], site_inteiro: bool = False) -> str:
    n = len(itens)
    tipos = {i["tipo"] for i in itens}
    tipo = ROTULO_TIPO.get(next(iter(tipos)), "equipamento") if len(tipos) == 1 else "equipamento"
    plural = _PLURAL.get(tipo, tipo + "s")
    titulo = _TITULO.get((evento, 1 if n == 1 else 2), "Aviso").format(n=n, tipo=tipo, tipos=plural)
    titulo = titulo[:1].upper() + titulo[1:]
    if site_inteiro:
        titulo = f"Site inteiro fora do ar · {n} equipamentos"
    linhas = [f"{_ICONE.get(evento, '')} <b>{html.escape(titulo)} · {html.escape(site or 'sem site')}</b>", ""]
    linhas += [html.escape(i["linha"]) for i in itens[:25]]
    if n > 25:
        linhas.append(f"… e mais {n - 25}")
    linhas += ["", f"<i>{_hora_local()}</i>"]
    return "\n".join(linhas)


def process_monitoring_notifications() -> Dict[str, Any]:
    cfg = N.config()
    if not any(g.get("ativo") for g in cfg.get("grupos") or []):
        return {"ok": True, "skipped": True, "reason": "nenhum grupo do Telegram ligado", "sent": 0}
    eventos, por_site = _coletar(cfg)
    if cfg.get("base_pendente"):
        # Primeiro grupo ligado agora: o que ja estava fora vira linha de base
        # (sem disparar tudo de uma vez); dai em diante so o que mudar.
        for ev in eventos:
            _set_state(ev["chave"], ev["kind"], ev["ativo"], ev["valor"])
        atual = N.config()
        atual.pop("base_pendente", None)
        N._salvar(atual)
        return {"ok": True, "sent": 0, "linha_de_base": len(eventos)}
    # (grupo, site, evento) -> itens; cada evento lembra os grupos que precisam recebe-lo
    caixas: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    grupos = {g["id"]: g for g in cfg["grupos"]}
    sem_destino: List[Dict[str, Any]] = []
    for ev in eventos:
        sk = N._site_chave(ev["site"])
        cont = por_site.get(sk) or {}
        ev["site_inteiro"] = ev["evento"] == "queda" and cont.get("total", 0) >= 2 and cont.get("down") == cont.get("total")
        alvos = N.destinos(cfg, ev["site"], ev["evento"], ev["tipo"], urgente=ev["site_inteiro"])
        # Sem o filtro do silencio: grupo existe, mas esta em silencio agora.
        ev["silenciado"] = not alvos and bool(N.destinos(cfg, ev["site"], ev["evento"], ev["tipo"], urgente=True))
        ev["pendentes"] = {g["id"] for g in alvos}
        ev["entregue"] = False
        if not alvos and not ev["silenciado"]:
            sem_destino.append(ev)
        for g in alvos:
            if g.get("juntar", True):
                caixas[(g["id"], sk, ev["evento"])].append(ev)
            else:
                caixas[(g["id"], sk, ev["evento"], ev["chave"], ev["kind"])].append(ev)
    sent, errors = 0, []
    for chave, itens in caixas.items():
        g = grupos[chave[0]]
        texto = _mensagem(chave[2], itens[0]["site"], itens, site_inteiro=any(i["site_inteiro"] for i in itens) and chave[2] == "queda")
        res = N.enviar_para_grupo(cfg, g, texto, agrupados=len(itens))
        if res["ok"]:
            sent += 1
            for i in itens:
                i["entregue"] = True
        else:
            errors.append(res["erro"])
    # Estado: muda quando ao menos um grupo recebeu, ou quando o aviso nao tem
    # destino (ninguem recebe esse site/evento: nao fica "pendente" para sempre
    # e nao dispara tudo de uma vez quando alguem criar um grupo depois).
    # Silenciado NAO muda: se ainda estiver assim quando o silencio acabar, o
    # aviso sai; se resolveu de madrugada, nenhum dos dois sai.
    for ev in eventos:
        if ev["entregue"] or (not ev["pendentes"] and not ev["silenciado"]):
            _set_state(ev["chave"], ev["kind"], ev["ativo"], ev["valor"])
    return {"ok": not errors, "sent": sent, "eventos": len(eventos), "sem_destino": len(sem_destino), "errors": errors[:5]}
