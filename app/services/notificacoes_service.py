"""Notificacoes por site (Configuracoes > Notificacoes).

Cada cliente tem GRUPOS do Telegram (destinos) e cada grupo diz quais SITES,
quais EVENTOS e quais TIPOS de equipamento recebe. Site sem grupo proprio vai
para o(s) grupo(s) PADRAO -- nenhum aviso se perde. Os tres emissores
(monitoramento, alerta de panico e controle de acesso) passam por aqui.

Robo: o da Easy (um so para todos os clientes, configurado no Painel do Dono;
o cliente vincula o grupo mandando "/vincular CODIGO" la dentro) ou o robo
proprio do cliente (token dele, como era antes).

Guardado em app_settings["notificacoes"] do cliente (tenant). O robo da Easy
fica em json_state do tenant "_platform". Tokens nunca saem nas respostas.
"""
from __future__ import annotations

import html
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import requests

from app.core.tenant_context import get_current_tenant_slug, reset_current_tenant_slug, set_current_tenant_slug
from app.services.db_store import get_json_state, load_app_settings, save_app_settings, set_json_state

logger = logging.getLogger("cam-snapshot")

try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem base de fusos: Brasilia e UTC-3 o ano todo desde 2019
    FUSO = timezone(timedelta(hours=-3))

EVENTOS = {
    "queda": "Equipamento caiu",
    "volta": "Equipamento voltou",
    "sem_imagem": "Gravador sem imagem",
    "sinal_onu": "Sinal da ONU baixo",
    "alarme": "Alarme do gateway / AP",
    "panico": "Alerta de pânico",
    "acesso": "Passagens no controle de acesso",
}
EVENTOS_PADRAO = ["queda", "volta", "sem_imagem", "alarme", "panico"]
TIPOS = {
    "camera": "Câmeras", "nvr": "NVR", "dvr": "DVR", "onu": "ONU", "olt": "OLT", "switch": "Switch",
    "access_point": "Access point", "access_device": "Controladoras", "connector": "Conector",
    "windows": "Computadores", "whatsapp": "WhatsApp",
}
_CHAVE_BOT = "telegram_bot__tenant___platform"
_CHAVE_ENVIOS = "notificacoes_envios"
_CHAVE_CURSOR = "telegram_bot_cursor__tenant___platform"
_MAX_GRUPOS = 200
_MAX_ENVIOS = 1000


def _t(v: Any, limite: int = 200) -> str:
    return str(v or "").strip()[:limite]


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _agora()).isoformat(timespec="seconds")


def _site_chave(site: Any) -> str:
    return _t(site, 160).upper()


# --------------------------------------------------------------------------- robo da Easy (plataforma)

def bot_easy() -> Dict[str, Any]:
    cfg = get_json_state(_CHAVE_BOT, {}) or {}
    return cfg if isinstance(cfg, dict) else {}


def bot_easy_publico() -> Dict[str, Any]:
    cfg = bot_easy()
    return {"configurado": bool(cfg.get("token")), "username": _t(cfg.get("username")),
            "url_publica": _t(cfg.get("url_publica"), 300)}


def salvar_bot_easy(token: str, url_publica: str = "") -> Dict[str, Any]:
    """So admin da plataforma (a rota confere). Token vazio mantem o atual."""
    atual = bot_easy()
    token = _t(token, 200) or _t(atual.get("token"), 200)
    url = _t(url_publica, 300) or _t(atual.get("url_publica"), 300)
    if url and not re.match(r"^https://[^\s]+$", url):
        raise ValueError("o endereco publico precisa comecar com https://")
    username = _t(atual.get("username"))
    if token and token != atual.get("token"):
        r = _telegram(token, "getMe", {})
        if not r.get("ok"):
            raise ValueError(f"o Telegram recusou o token: {r.get('description') or 'token invalido'}")
        username = _t((r.get("result") or {}).get("username"))
    set_json_state(_CHAVE_BOT, {"token": token, "username": username, "url_publica": url, "atualizado_em": _iso()})
    return bot_easy_publico()


# --------------------------------------------------------------------------- config do cliente

def _grupo_limpo(g: Dict[str, Any], antigo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    antigo = antigo or {}
    eventos = [e for e in (g.get("eventos") if g.get("eventos") is not None else antigo.get("eventos") or EVENTOS_PADRAO) if e in EVENTOS]
    tipos = [x for x in (g.get("tipos") if g.get("tipos") is not None else antigo.get("tipos") or list(TIPOS)) if x in TIPOS]
    sites = sorted({_site_chave(s) for s in (g.get("sites") if g.get("sites") is not None else antigo.get("sites") or []) if _site_chave(s)})
    sil = g.get("silencio") if isinstance(g.get("silencio"), dict) else (antigo.get("silencio") or {})
    de, ate = _t(sil.get("de") or "22:00", 5), _t(sil.get("ate") or "06:00", 5)
    for h in (de, ate):
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", h):
            raise ValueError("horario do silencio invalido (use HH:MM)")
    bot = _t(g.get("bot") or antigo.get("bot") or "easy", 10)
    if bot not in ("easy", "proprio"):
        raise ValueError("robo invalido")
    chat = _t(g.get("chat_id") if g.get("chat_id") is not None else antigo.get("chat_id"), 40)
    if not re.match(r"^-?\d{3,20}$|^@[A-Za-z0-9_]{4,40}$", chat):
        raise ValueError("chat do Telegram invalido")
    return {
        "id": _t(antigo.get("id") or g.get("id"), 24) or secrets.token_hex(6),
        "nome": _t(g.get("nome") if g.get("nome") is not None else antigo.get("nome"), 80) or "Grupo do Telegram",
        "chat_id": chat,
        "chat_titulo": _t(g.get("chat_titulo") or antigo.get("chat_titulo"), 120),
        "bot": bot,
        "padrao": bool(g.get("padrao") if g.get("padrao") is not None else antigo.get("padrao")),
        "ativo": bool(g.get("ativo") if g.get("ativo") is not None else antigo.get("ativo", True)),
        "sites": sites,
        "eventos": eventos,
        "tipos": tipos,
        "juntar": bool(g.get("juntar") if g.get("juntar") is not None else antigo.get("juntar", True)),
        "silencio": {"ativo": bool(sil.get("ativo")), "de": de, "ate": ate},
        "criado_em": antigo.get("criado_em") or _iso(),
        "ultimo_envio": antigo.get("ultimo_envio") or "",
        "ultimo_erro": antigo.get("ultimo_erro") or "",
    }


def _migrar_antigo(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Config antiga (um bot + um chat do cliente) vira o grupo padrao, com o
    robo proprio. Sem config antiga, comeca vazio."""
    velho = settings.get("telegram_notifications") or {}
    cfg: Dict[str, Any] = {"grupos": [], "bot_proprio_token": "",
                           "sinal": {"warn_rx": float(velho.get("warn_rx", -27)), "critical_rx": float(velho.get("critical_rx", -29))}}
    if velho.get("bot_token") and velho.get("chat_id"):
        eventos = ["queda", "sem_imagem", "sinal_onu", "alarme", "panico"]
        if velho.get("notify_recovery", True):
            eventos.append("volta")
        if velho.get("enabled"):
            eventos.append("acesso")
        try:
            cfg["grupos"].append(_grupo_limpo({
                "nome": "Grupo do cliente", "chat_id": velho.get("chat_id"), "bot": "proprio", "padrao": True,
                "ativo": bool(velho.get("enabled")), "eventos": eventos,
                "tipos": [x for x in (velho.get("types") or list(TIPOS)) if x in TIPOS],
            }))
            cfg["bot_proprio_token"] = _t(velho.get("bot_token"), 200)
        except ValueError:
            pass
    return cfg


def config() -> Dict[str, Any]:
    """Config COMPLETA do cliente atual (com token proprio). So uso interno."""
    settings = load_app_settings()
    cfg = settings.get("notificacoes")
    if not isinstance(cfg, dict):
        cfg = _migrar_antigo(settings)
    cfg.setdefault("grupos", [])
    cfg.setdefault("bot_proprio_token", "")
    cfg.setdefault("sinal", {"warn_rx": -27.0, "critical_rx": -29.0})
    return cfg


def _salvar(cfg: Dict[str, Any]) -> None:
    settings = load_app_settings()
    settings["notificacoes"] = cfg
    save_app_settings(settings)


def config_publica() -> Dict[str, Any]:
    cfg = config()
    return {
        "grupos": cfg["grupos"], "sinal": cfg["sinal"],
        "bot_proprio": bool(cfg.get("bot_proprio_token")),
        "bot_easy": bot_easy_publico(),
        "eventos": EVENTOS, "tipos": TIPOS,
    }


def salvar_grupo(dados: Dict[str, Any]) -> Dict[str, Any]:
    cfg = config()
    gid = _t(dados.get("id"), 24)
    atual = next((g for g in cfg["grupos"] if g["id"] == gid), None) if gid else None
    if gid and not atual:
        raise ValueError("grupo nao encontrado")
    if not atual and len(cfg["grupos"]) >= _MAX_GRUPOS:
        raise ValueError("limite de grupos atingido")
    novo = _grupo_limpo(dados, atual)
    if novo["bot"] == "proprio" and not cfg.get("bot_proprio_token") and not _t(dados.get("bot_proprio_token")):
        raise ValueError("informe o token do robo proprio")
    if _t(dados.get("bot_proprio_token")):
        cfg["bot_proprio_token"] = _t(dados.get("bot_proprio_token"), 200)
    cfg["grupos"] = [novo if g["id"] == novo["id"] else g for g in cfg["grupos"]] if atual else cfg["grupos"] + [novo]
    _salvar(cfg)
    return novo


def excluir_grupo(gid: str) -> bool:
    cfg = config()
    antes = len(cfg["grupos"])
    cfg["grupos"] = [g for g in cfg["grupos"] if g["id"] != _t(gid, 24)]
    if len(cfg["grupos"]) == antes:
        return False
    _salvar(cfg)
    return True


def definir_sites(gid: str, sites: List[str], modo: str = "adicionar") -> Dict[str, Any]:
    """Mudanca em lote da tela: adicionar/tirar sites de um grupo."""
    cfg = config()
    g = next((x for x in cfg["grupos"] if x["id"] == _t(gid, 24)), None)
    if not g:
        raise ValueError("grupo nao encontrado")
    alvo = {_site_chave(s) for s in sites or [] if _site_chave(s)}
    atuais = set(g.get("sites") or [])
    g["sites"] = sorted(atuais | alvo if modo == "adicionar" else atuais - alvo)
    _salvar(cfg)
    return g


def salvar_sinal(warn_rx: float, critical_rx: float) -> Dict[str, Any]:
    warn, crit = float(warn_rx), float(critical_rx)
    if not (-40 <= crit < warn <= -10):
        raise ValueError("limites invalidos: o critico precisa ser menor que o alerta (entre -40 e -10 dBm)")
    cfg = config()
    cfg["sinal"] = {"warn_rx": warn, "critical_rx": crit}
    _salvar(cfg)
    return cfg["sinal"]


# --------------------------------------------------------------------------- quem recebe

def _no_silencio(g: Dict[str, Any], quando: Optional[datetime] = None) -> bool:
    sil = g.get("silencio") or {}
    if not sil.get("ativo"):
        return False
    local = (quando or _agora()).astimezone(FUSO).strftime("%H:%M")
    de, ate = sil.get("de") or "22:00", sil.get("ate") or "06:00"
    return (de <= local < ate) if de < ate else (local >= de or local < ate)


def destinos(cfg: Dict[str, Any], site: Any, evento: str, tipo: str = "", urgente: bool = False,
             quando: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Grupos que recebem este aviso. Site com grupo proprio (algum grupo
    ativo o lista) vai para esses; senao para os grupos padrao."""
    chave = _site_chave(site)
    ativos = [g for g in cfg.get("grupos") or [] if g.get("ativo")]
    do_site = [g for g in ativos if chave and chave in (g.get("sites") or [])]
    candidatos = do_site or [g for g in ativos if g.get("padrao")]
    out = []
    for g in candidatos:
        if evento not in (g.get("eventos") or []):
            continue
        if tipo and tipo not in (g.get("tipos") or []):
            continue
        if _no_silencio(g, quando) and not urgente:
            continue
        out.append(g)
    return out


# --------------------------------------------------------------------------- envio

def _telegram(token: str, metodo: str, dados: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{metodo}", json=dados, timeout=timeout)
        return r.json() if r.content else {"ok": False, "description": f"HTTP {r.status_code}"}
    except Exception as exc:
        return {"ok": False, "description": str(exc)[:200]}


def _token_do_grupo(cfg: Dict[str, Any], g: Dict[str, Any]) -> str:
    return _t(cfg.get("bot_proprio_token"), 200) if g.get("bot") == "proprio" else _t(bot_easy().get("token"), 200)


def _link_sightops(tela: str = "monitoring") -> str:
    base = _t(bot_easy().get("url_publica"), 300).rstrip("/")
    return f"{base}/?tela={tela}" if base else ""


def _registrar_envio(gid: str, ok: bool, erro: str = "", agrupados: int = 1) -> None:
    from app.core.tenant_context import tenant_scoped_key

    try:
        lista = get_json_state(tenant_scoped_key(_CHAVE_ENVIOS), []) or []
        lista = [x for x in lista if isinstance(x, dict)][-(_MAX_ENVIOS - 1):]
        lista.append({"em": _iso(), "grupo": gid, "ok": bool(ok), "erro": erro[:160], "n": int(agrupados)})
        set_json_state(tenant_scoped_key(_CHAVE_ENVIOS), lista)
    except Exception:
        logger.exception("notificacoes: falha ao registrar envio")


def enviar_para_grupo(cfg: Dict[str, Any], g: Dict[str, Any], texto: str, tela: str = "monitoring",
                      agrupados: int = 1) -> Dict[str, Any]:
    token = _token_do_grupo(cfg, g)
    if not token:
        res = {"ok": False, "description": "robo do Telegram nao configurado"}
    else:
        corpo: Dict[str, Any] = {"chat_id": g["chat_id"], "text": texto[:4000], "parse_mode": "HTML",
                                 "disable_web_page_preview": True}
        link = _link_sightops(tela)
        if link:
            corpo["reply_markup"] = {"inline_keyboard": [[{"text": "Abrir no SightOps", "url": link}]]}
        res = _telegram(token, "sendMessage", corpo)
        novo_chat = _t(((res.get("parameters") or {}).get("migrate_to_chat_id")), 40)
        if not res.get("ok") and novo_chat:
            # O grupo virou "supergrupo" no Telegram e trocou de numero.
            g["chat_id"] = novo_chat
            corpo["chat_id"] = novo_chat
            res = _telegram(token, "sendMessage", corpo)
    ok = bool(res.get("ok"))
    erro = "" if ok else _t(res.get("description"), 160) or "falha no envio"
    try:
        atual = config()
        for x in atual["grupos"]:
            if x["id"] == g["id"]:
                x["chat_id"] = g["chat_id"]
                if ok:
                    x["ultimo_envio"], x["ultimo_erro"] = _iso(), ""
                else:
                    x["ultimo_erro"] = f"{_iso()} {erro}"
        _salvar(atual)
    except Exception:
        logger.exception("notificacoes: falha ao atualizar o grupo %s", g.get("id"))
    _registrar_envio(g["id"], ok, erro, agrupados)
    return {"ok": ok, "erro": erro}


def enviar_evento(evento: str, site: Any, texto: str, tipo: str = "", urgente: bool = False,
                  tela: str = "monitoring") -> Dict[str, Any]:
    """Um aviso avulso (panico, controle de acesso) para os grupos do site."""
    cfg = config()
    alvos = destinos(cfg, site, evento, tipo, urgente=urgente)
    resultados = [enviar_para_grupo(cfg, g, texto, tela) for g in alvos]
    return {"ok": any(r["ok"] for r in resultados) if resultados else True,
            "enviados": sum(1 for r in resultados if r["ok"]), "destinos": len(alvos),
            "erros": [r["erro"] for r in resultados if not r["ok"]][:5]}


def testar_grupo(gid: str) -> Dict[str, Any]:
    cfg = config()
    g = next((x for x in cfg["grupos"] if x["id"] == _t(gid, 24)), None)
    if not g:
        raise ValueError("grupo nao encontrado")
    tenant = _t(get_current_tenant_slug() or "default")
    sites = ", ".join(g.get("sites") or []) or ("os sites sem grupo próprio" if g.get("padrao") else "nenhum site ainda")
    texto = (f"<b>SightOps conectado</b>\n\nCliente: {html.escape(tenant)}\nGrupo: {html.escape(g['nome'])}\n"
             f"Recebe avisos de: {html.escape(sites)}")
    return enviar_para_grupo(cfg, g, texto)


def resumo_envios() -> Dict[str, Any]:
    from app.core.tenant_context import tenant_scoped_key

    lista = get_json_state(tenant_scoped_key(_CHAVE_ENVIOS), []) or []
    corte = (_agora() - timedelta(hours=24)).isoformat(timespec="seconds")
    dia = [x for x in lista if isinstance(x, dict) and str(x.get("em") or "") >= corte]
    return {"avisos_24h": sum(1 for x in dia if x.get("ok")), "falhas_24h": sum(1 for x in dia if not x.get("ok")),
            "agrupados_24h": sum(int(x.get("n") or 1) for x in dia if x.get("ok") and int(x.get("n") or 1) > 1)}


# --------------------------------------------------------------------------- vincular grupo pelo robo da Easy

_codigos: Dict[str, Dict[str, Any]] = {}
_codigos_lock = threading.Lock()
_CODIGO_TTL = 600
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def novo_codigo(tenant: str, usuario: str = "") -> Dict[str, Any]:
    if not bot_easy().get("token"):
        raise ValueError("o robo do SightOps ainda nao foi configurado pela Easy")
    with _codigos_lock:
        agora = time.monotonic()
        for k in [k for k, v in _codigos.items() if v["expira"] < agora - 3600]:
            _codigos.pop(k, None)
        bruto = "".join(secrets.choice(_ALFABETO) for _ in range(6))
        codigo = f"{bruto[:4]}-{bruto[4:]}"
        _codigos[codigo] = {"tenant": _t(tenant, 80).lower(), "expira": agora + _CODIGO_TTL, "grupo": None,
                            "usuario": usuario}
    return {"codigo": codigo, "bot_username": bot_easy_publico()["username"], "validade_s": _CODIGO_TTL}


def situacao_codigo(tenant: str, codigo: str) -> Dict[str, Any]:
    with _codigos_lock:
        item = _codigos.get(_t(codigo, 12).upper())
    if not item or item["tenant"] != _t(tenant, 80).lower():
        return {"status": "invalido"}
    if item["grupo"]:
        return {"status": "vinculado", "grupo": item["grupo"]}
    if item["expira"] < time.monotonic():
        return {"status": "expirado"}
    return {"status": "aguardando"}


_RE_VINCULAR = re.compile(r"^/vincular(?:@\w+)?\s+([A-Za-z0-9]{4})-?([A-Za-z0-9]{2})\b", re.I)


def tratar_update(update: Dict[str, Any], responder: Optional[Callable[[str, str], None]] = None) -> Optional[Dict[str, Any]]:
    """Uma mensagem recebida pelo robo da Easy. "/vincular CODIGO" num grupo
    cria o grupo no cliente dono do codigo (e so nele)."""
    msg = update.get("message") or update.get("channel_post") or {}
    texto = _t(msg.get("text"), 200)
    m = _RE_VINCULAR.match(texto)
    if not m:
        return None
    codigo = f"{m.group(1).upper()}-{m.group(2).upper()}"
    chat = msg.get("chat") or {}
    chat_id = _t(chat.get("id"), 40)
    titulo = _t(chat.get("title") or chat.get("username") or chat.get("first_name"), 120) or "Grupo do Telegram"
    with _codigos_lock:
        item = _codigos.get(codigo)
        valido = bool(item and not item["grupo"] and item["expira"] >= time.monotonic())
        if valido:
            item["grupo"] = {"pendente": True}  # reserva: um codigo vincula um grupo so
    if not valido:
        if responder and chat_id:
            responder(chat_id, "Código inválido ou vencido. Gere outro no SightOps (Configurações > Notificações).")
        return None
    tok = set_current_tenant_slug(item["tenant"])
    try:
        cfg = config()
        existente = next((g for g in cfg["grupos"] if g["chat_id"] == chat_id), None)
        if existente:
            grupo = existente
        else:
            grupo = _grupo_limpo({"nome": titulo, "chat_titulo": titulo, "chat_id": chat_id, "bot": "easy",
                                  "padrao": not cfg["grupos"], "ativo": True})
            cfg["grupos"].append(grupo)
            _salvar(cfg)
    except Exception:
        with _codigos_lock:
            item["grupo"] = None
        logger.exception("notificacoes: falha ao vincular grupo")
        return None
    finally:
        reset_current_tenant_slug(tok)
    with _codigos_lock:
        item["grupo"] = {"id": grupo["id"], "nome": grupo["nome"]}
    if responder:
        responder(chat_id, "Grupo vinculado ao SightOps. Escolha na tela quais sites e avisos ele recebe.")
    return grupo


def ler_atualizacoes_uma_vez(timeout: int = 25) -> int:
    """Uma rodada de getUpdates do robo da Easy (laco de fundo em main.py)."""
    token = _t(bot_easy().get("token"), 200)
    if not token:
        return 0
    cursor = get_json_state(_CHAVE_CURSOR, {}) or {}
    offset = int(cursor.get("offset") or 0)
    r = _telegram(token, "getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "channel_post"]},
                  timeout=timeout + 10)
    if not r.get("ok"):
        raise RuntimeError(_t(r.get("description")) or "getUpdates falhou")
    updates = r.get("result") or []

    def responder(chat_id: str, texto: str) -> None:
        _telegram(token, "sendMessage", {"chat_id": chat_id, "text": texto})

    for u in updates:
        try:
            tratar_update(u, responder)
        except Exception:
            logger.exception("notificacoes: falha ao tratar mensagem do Telegram")
        offset = max(offset, int(u.get("update_id") or 0) + 1)
    if updates:
        set_json_state(_CHAVE_CURSOR, {"offset": offset})
    return len(updates)


# --------------------------------------------------------------------------- compatibilidade

def compat_telegram() -> Dict[str, Any]:
    """Formato antigo (GET /api/monitoring/telegram): cartoes da visao geral."""
    cfg = config()
    ativos = [g for g in cfg["grupos"] if g.get("ativo")]
    return {
        "enabled": bool(ativos), "configured": bool(cfg["grupos"]), "chat_id": "",
        "grupos": len(cfg["grupos"]), "grupos_ativos": len(ativos),
        "warn_rx": float(cfg["sinal"].get("warn_rx", -27)), "critical_rx": float(cfg["sinal"].get("critical_rx", -29)),
        "notify_recovery": any("volta" in (g.get("eventos") or []) for g in ativos),
        "types": list(TIPOS),
    }
