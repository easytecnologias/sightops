"""Notificacao do Alerta Termico no celular, pelo Firebase Cloud Messaging.

A chave da conta de servico fica fora de /app/data (essa pasta e servida pela
web): vem de FIREBASE_CREDENCIAL, montada somente leitura no container. Sem a
chave o envio so registra o motivo e o resto do alerta segue normal.

Quem recebe e decidido NA HORA DO ENVIO, pelo cadastro atual: usuario e cliente
ativos, modulo liberado, site permitido. Copiar isso no registro faria um
funcionario desligado continuar recebendo para sempre. Na duvida, nao manda.
A sessao nao entra na conta: ela vence em horas e o alerta tem de continuar
chegando. O token e unico: aparelho que trocou de dono muda de linha.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.tenant_context import get_current_tenant_slug
from app.services import db_store

logger = logging.getLogger(__name__)

CREDENCIAL_PADRAO = "/run/firebase/servico.json"
ESCOPO = "https://www.googleapis.com/auth/firebase.messaging"
CANAL = "alertas"
MODULO = "termico"
_trava = threading.Lock()
_cred: Any = None
_projeto = ""


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _txt(v: Any) -> str:
    return str(v or "").strip()


# ---------------------------------------------------------------- aparelhos

def registrar(token: str, usuario_id: int, usuario: str, plataforma: str = "android") -> Dict[str, Any]:
    tenant = get_current_tenant_slug()
    if not tenant:
        raise PermissionError("Cliente não identificado.")
    token = _txt(token)
    if not 20 <= len(token) <= 4096:
        raise ValueError("Token do aparelho inválido.")
    agora = _agora()
    with db_store._conn() as c:
        if c.execute("SELECT id FROM termico_aparelhos WHERE token=?", (token,)).fetchone():
            c.execute("UPDATE termico_aparelhos SET tenant_slug=?, usuario_id=?, usuario=?, plataforma=?, visto_at=? WHERE token=?",
                      (tenant, int(usuario_id), _txt(usuario)[:120], _txt(plataforma)[:20], agora, token))
        else:
            c.execute("INSERT INTO termico_aparelhos(id, tenant_slug, usuario_id, usuario, token, plataforma, criado_at, visto_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, tenant, int(usuario_id), _txt(usuario)[:120], token, _txt(plataforma)[:20], agora, agora))
    return {"ok": True}


def esquecer(token: str) -> Dict[str, Any]:
    """Saiu da conta: o celular para de receber. So apaga do proprio cliente."""
    tenant = get_current_tenant_slug()
    if not tenant:
        raise PermissionError("Cliente não identificado.")
    with db_store._conn() as c:
        c.execute("DELETE FROM termico_aparelhos WHERE tenant_slug=? AND token=?", (tenant, _txt(token)))
    return {"ok": True}


def esquecer_usuario(usuario_id: int) -> None:
    with db_store._conn() as c:
        c.execute("DELETE FROM termico_aparelhos WHERE usuario_id=?", (int(usuario_id),))


def pode_receber(usuario_id: int, tenant: str, site: str) -> bool:
    """Cadastro de agora. Admin que operava como outro cliente nao mora nele:
    fica de fora. Qualquer erro de leitura = nao manda."""
    from app.core import permissions as P
    from app.services.auth_store import usuario_para_aviso

    try:
        user = usuario_para_aviso(int(usuario_id))
        if not user or _txt(user.get("tenant_slug")).lower() != _txt(tenant).lower():
            return False
        if not P.modulo_no_plano(MODULO, user.get("effective_enabled_modules")) or not P.pode(user, MODULO, "ver"):
            return False
        # Direto no cadastro: sites_da_sessao depende do modo e de haver sessao.
        sites = P.sites_do_usuario(user)
        return not sites or _txt(site).upper() in {_txt(s).upper() for s in sites}
    except Exception:
        logger.exception("termico: nao conferiu o usuario %s", usuario_id)
        return False


def _destinos(tenant: str, site: str) -> List[str]:
    with db_store._conn() as c:
        linhas = [dict(r) for r in c.execute(
            "SELECT token, usuario_id FROM termico_aparelhos WHERE tenant_slug=?", (tenant,)).fetchall()]
    return [r["token"] for r in linhas if pode_receber(r.get("usuario_id") or 0, tenant, site)]


def _apagar_token(token: str) -> None:
    with db_store._conn() as c:
        c.execute("DELETE FROM termico_aparelhos WHERE token=?", (token,))


# -------------------------------------------------------------------- envio

def _bearer() -> Tuple[str, str]:
    """(token OAuth, id do projeto). Levanta erro claro sem a chave."""
    global _cred, _projeto
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    with _trava:
        if _cred is None:
            caminho = os.environ.get("FIREBASE_CREDENCIAL", CREDENCIAL_PADRAO)
            if not os.path.isfile(caminho):
                raise FileNotFoundError(f"chave do Firebase não encontrada em {caminho}")
            _cred = service_account.Credentials.from_service_account_file(caminho, scopes=[ESCOPO])
            _projeto = _cred.project_id
        if not _cred.valid:
            _cred.refresh(Request())
        return _cred.token, _projeto


def _mensagem(token: str, titulo: str, corpo: str, dados: Dict[str, str]) -> Dict[str, Any]:
    return {"message": {
        "token": token,
        "notification": {"title": titulo, "body": corpo},
        "data": dados,
        "android": {"priority": "HIGH", "ttl": "3600s",
                    "notification": {"channel_id": CANAL, "notification_priority": "PRIORITY_MAX", "default_sound": True}},
    }}


def enviar_aviso(tenant: str, site: str, titulo: str, corpo: str, dados: Dict[str, str]) -> Dict[str, int]:
    """Manda para os celulares do cliente que podem ver o site. Nunca levanta erro."""
    res = {"enviados": 0, "falhas": 0, "removidos": 0}
    tokens: List[str] = []
    try:
        tokens = _destinos(tenant, site)
        if not tokens:
            return res
        bearer, projeto = _bearer()
    except Exception as exc:
        logger.warning("termico: notificacao nao saiu (%s): %s", tenant, exc)
        # Chave do Firebase com problema: ninguem recebeu, e isso e falha.
        res["falhas"] = max(1, len(tokens))
        return res
    url = f"https://fcm.googleapis.com/v1/projects/{projeto}/messages:send"
    for token in tokens:
        try:
            r = requests.post(url, json=_mensagem(token, titulo, corpo, dados), timeout=10,
                              headers={"Authorization": f"Bearer {bearer}"})
            if r.status_code == 200:
                res["enviados"] += 1
            elif r.status_code == 404 or "UNREGISTERED" in r.text:
                _apagar_token(token)      # app desinstalado
                res["removidos"] += 1
            else:
                res["falhas"] += 1
                logger.warning("termico: FCM %s: %s", r.status_code, r.text[:200])
        except Exception as exc:
            res["falhas"] += 1
            logger.warning("termico: FCM sem resposta: %s", exc)
    return res


def avisar_pessoa(tenant: str, cam: Dict[str, Any], alerta: Dict[str, Any], mancha: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    temp = (mancha or {}).get("temp_media")
    extra = f" · {temp:.1f} °C".replace(".", ",") if isinstance(temp, (int, float)) else ""
    inicio = time.time()
    titulo = "TESTE: alarme de teste" if (mancha or {}).get("teste") else "Pessoa detectada pelo calor"
    res = enviar_aviso(tenant, cam.get("site") or "", titulo,
                       f"{cam.get('nome')} · {cam.get('site')}{extra}",
                       {"tipo": "termico", "alerta_id": str(alerta.get("id") or "")})
    logger.info("termico: notificacao %s (%s) em %.1fs: %s", alerta.get("id"), tenant, time.time() - inicio, res)
    if res["falhas"] and alerta.get("id"):
        _anotar_falha(tenant, cam, alerta["id"], res["falhas"])
    return res


def _anotar_falha(tenant: str, cam: Dict[str, Any], alerta_id: str, falhas: int) -> None:
    from app.services.termico_store import anotar_falha_aviso
    from app.services.zabbix_monitoring_service import enviar_termico_agora

    try:
        anotar_falha_aviso(tenant, alerta_id, falhas)
        enviar_termico_agora(tenant, cam.get("ip") or "", cam.get("connector_id") or "")
    except Exception as exc:
        logger.warning("termico: falha de aviso nao anotada (%s): %s", alerta_id, exc)
