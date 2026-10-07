# -*- coding: utf-8 -*-
"""Senha padrao da interface web da ONU, por cliente, aplicada sozinha.

Em 07/10/2026 o operador percebeu que as ONUs que ele instala chegam com a
senha de fabrica e assim ficam: o SightOps nunca definiu nenhuma, e o TR-069
tambem nao conseguia dizer qual era. Equipamento novo entrando na planta com
credencial de catalogo e porta aberta na borda.

COMO SE SABE SE JA FOI APLICADA

`UserInterface.AdminPassword` e parametro de ESCRITA: a ONU sempre devolve
vazio, mesmo tendo senha. Entao nao da para comparar com o que esta no
equipamento -- diferente da ACL, que e legivel. Aqui se guarda a IMPRESSAO
(sha256 truncado) da senha que foi enviada a cada serial. Senha nova no
cliente muda a impressao e a frota inteira e reaplicada sozinha.

A senha em si nunca entra neste estado nem em log: fica cifrada na
configuracao do cliente, com a mesma chave das senhas de OLT.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger("cam-snapshot")

ESTADO_KEY = "tr069_senha_web"
CAMPO = "UserInterface.AdminPassword"
MAX_POR_CICLO = 5


def impressao(senha: str) -> str:
    """Identifica a senha sem guardar a senha."""
    return hashlib.sha256(str(senha or "").encode("utf-8")).hexdigest()[:16]


def senha_do_cliente(tr) -> str:
    """Senha padrao configurada para o cliente da sessao, ou vazio."""
    from app.core.crypto import decrypt
    from app.services.db_store import get_json_state

    cfg = get_json_state(tr.CONFIG_KEY, {}) or {}
    cifrada = cfg.get("senha_web_enc")
    if not cifrada:
        return ""
    try:
        return decrypt(cifrada) or ""
    except Exception:
        # chave trocada ou valor corrompido: melhor nao aplicar nada do que
        # gravar lixo como senha numa frota inteira.
        logger.warning("tr069: senha web do cliente nao pode ser decifrada")
        return ""


def definir_senha(tr, senha: str) -> Dict[str, Any]:
    """Guarda a senha padrao do cliente (cifrada) e marca a frota para reaplicar."""
    from app.core.crypto import encrypt
    from app.services.db_store import get_json_state, set_json_state

    senha = str(senha or "")
    if senha and len(senha) < 6:
        raise tr.Tr069Error("a senha da web precisa de pelo menos 6 caracteres")
    cfg = tr.garantir_credencial()
    if senha:
        cfg["senha_web_enc"] = encrypt(senha)
    else:
        cfg.pop("senha_web_enc", None)
    set_json_state(tr.CONFIG_KEY, cfg)
    return {"ok": True, "tem_senha_web": bool(senha)}


def aplicar(tr, serial: str, senha: str) -> Dict[str, Any]:
    """Grava a senha na ONU. Sem senha configurada, nao faz nada."""
    if not senha:
        return {"ok": False, "erro": "nenhuma senha padrao configurada neste cliente"}
    doc, onu = tr._documento_do_cliente(serial)
    raiz = "InternetGatewayDevice" if tr.padrao(doc) == "tr098" else "Device"
    tarefa = {"name": "setParameterValues",
              "parameterValues": [[f"{raiz}.{CAMPO}", senha, "xsd:string"]]}
    conector = str(onu.get("connector_id") or onu.get("remote_connector_id") or "")
    estado, detalhe = tr._tarefa_e_espera(doc, conector, tarefa)
    return {"ok": estado in ("concluido", "na_fila"), "estado": estado, "detalhe": detalhe}


def manter_cliente(tr) -> Dict[str, Any]:
    """Aplica a senha padrao nas ONUs do cliente que ainda nao a receberam."""
    from app.services.db_store import get_json_state, set_json_state

    senha = senha_do_cliente(tr)
    if not senha:
        return {"ok": True, "aplicadas": [], "erros": {}, "motivo": "sem senha padrao"}

    alvo = impressao(senha)
    estado = dict(get_json_state(ESTADO_KEY, {}) or {})
    feitos, erros = [], {}
    for linha in tr.listar().get("onus", []):
        if linha.get("estado") != "gerenciada":
            continue
        if len(feitos) + len(erros) >= MAX_POR_CICLO:
            break
        serial = linha["serial"]
        if (estado.get(serial) or {}).get("impressao") == alvo:
            continue  # ja recebeu ESTA senha
        try:
            r = aplicar(tr, serial, senha)
            if r.get("ok"):
                feitos.append(serial)
                estado[serial] = {"impressao": alvo, "ok": True,
                                  "em": datetime.now(timezone.utc).isoformat()}
            else:
                erros[serial] = str(r.get("detalhe") or r.get("erro") or "falhou")[:160]
                estado[serial] = {"ok": False, "erro": erros[serial]}
        except Exception as exc:  # uma ONU com problema nao para as outras
            erros[serial] = str(exc)[:160]
            estado[serial] = {"ok": False, "erro": erros[serial]}
    if feitos or erros:
        set_json_state(ESTADO_KEY, estado)
    return {"ok": True, "aplicadas": feitos, "erros": erros}
