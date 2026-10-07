"""Acesso web da ONU (ACL Intelbras), automatico e por cliente.

Em 07/10/2026 uma regra GLOBAL do GenieACS ("acl-intelbras", feita para a SIERRA)
gravou a faixa de gerencia da SIERRA na ONU 3/17 da Easy. Regra de ONU nunca
mais e global: o SightOps calcula a faixa A PARTIR DE CADA ONU e so mexe em ONU
do cliente da sessao.

Usa as duas regras de WAN que a ONU ja tem (regra nova nasce como LAN e nao
serve), a regra de LAN nao e tocada:

- a 1a regra de WAN recebe a rede de gerencia da propria ONU (IP + mascara da
  WAN de gerencia). Uma faixa so: a 140PoE nao liga web pela WAN na 2a regra.
- o SightOps chega na ONU SEMPRE de dentro dessa rede: o conector com tunel ja
  faz NAT; rede roteada direto (VLAN 7 da Easy) precisa de um masquerade no
  roteador (src SightOps -> rede de gerencia).
"""
from __future__ import annotations

import ipaddress
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cam-snapshot")

RAIZ = "InternetGatewayDevice.X_ITBS_Acl.AclServices"
NOME_GERENCIA = "SightOps-gerencia"
NOME_SERVIDOR = "SightOps-servidor"
ESTADO_KEY = "tr069_acl"
MAX_POR_CICLO = 5


def _v(no: Any, chave: str) -> Any:
    cur = no
    for parte in chave.split("."):
        if not isinstance(cur, dict) or parte not in cur:
            return None
        cur = cur[parte]
    return cur.get("_value") if isinstance(cur, dict) else None


def _regras(doc: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
    cur: Any = doc
    for parte in RAIZ.split("."):
        cur = cur.get(parte) if isinstance(cur, dict) else None
    if not isinstance(cur, dict):
        return []
    return sorted((int(k), v) for k, v in cur.items() if k.isdigit() and isinstance(v, dict))


def suporta(doc: Dict[str, Any]) -> bool:
    return bool(_regras(doc))


def faixas_desejadas(doc: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """{nome da regra: (ip inicial, ip final)} calculado da propria ONU."""
    from app.services import tr069_wan

    out: Dict[str, Tuple[str, str]] = {}
    gerencia = next((s for s in tr069_wan.servicos(doc) if s["gerencia"]), None)
    if gerencia and gerencia.get("ip"):
        mascara = _v(doc, gerencia["id"] + ".SubnetMask") or "255.255.255.0"
        try:
            rede = ipaddress.ip_network(f"{gerencia['ip']}/{mascara}", strict=False)
            if rede.prefixlen <= 30:
                hosts = list(rede.hosts()) if rede.num_addresses <= 1024 else None
                ini = hosts[0] if hosts else rede.network_address + 1
                fim = hosts[-1] if hosts else rede.broadcast_address - 1
                out[NOME_GERENCIA] = (str(ini), str(fim))
        except ValueError:
            pass
    return out


def regras_wan(doc: Dict[str, Any]) -> List[Tuple[int, Dict[str, Any]]]:
    """As regras de WAN que ja existem na ONU (na 140PoE: 2 e 3).

    Regra nova NAO serve: na Intelbras ela nasce como regra de LAN, sem os
    campos de WAN ("Invalid parameter name", 07/10/2026). Entao o SightOps usa
    as de WAN que vieram de fabrica: a 1a para a rede de gerencia, a 2a para o
    servidor.
    """
    return [(n, r) for n, r in _regras(doc)
            if str(_v(r, "INCName") or "").upper() != "LAN" and isinstance(r.get("HTTPWanEnable"), dict)]


def _valores_regra(base: str, regra: Dict[str, Any], ini: str, fim: str) -> List[list]:
    # So faixa, web (HTTP) e ping pela WAN. A 140PoE recusa mexer em HTTPS e
    # TELNET pela WAN nessas regras (cwmp 9003, 07/10/2026): eles ficam como a
    # ONU tem -- de fabrica, fechados.
    alvo = [("MinSrcIp", ini, "xsd:string"), ("MaxSrcIp", fim, "xsd:string"),
            ("HTTPWanEnable", True, "xsd:boolean"), ("PINGWanEnable", True, "xsd:boolean")]
    # so manda o que a regra tem e o que esta diferente
    return [[f"{base}.{k}", v, t] for k, v, t in alvo if isinstance(regra.get(k), dict) and _v(regra, k) != v]


def plano(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Passos para as regras de WAN ficarem com as faixas do SightOps (vazio = ja esta)."""
    wan = regras_wan(doc)
    if not wan:
        return []
    faixas = faixas_desejadas(doc)
    passos = []
    # So a 1a regra de WAN: na 140PoE a 3 tem os campos mas recusa ligar HTTP
    # pela WAN (cwmp 9003, 07/10/2026) -- na pratica existe uma faixa so.
    for (n, regra), nome in zip(wan[:1], [NOME_GERENCIA]):
        if nome not in faixas:
            continue
        ini, fim = faixas[nome]
        valores = _valores_regra(f"{RAIZ}.{n}", regra, ini, fim)
        if valores:
            passos.append({"op": "editar", "regra": n, "nome": nome, "valores": valores})
    return passos


def aplicar(tr, serial: str) -> Dict[str, Any]:
    """Executa o plano numa ONU do cliente da sessao, conferido."""
    doc, onu = tr._documento_do_cliente(serial)
    passos = plano(doc)
    if not passos:
        return {"ok": True, "mudou": False}
    conector = str(onu.get("connector_id") or onu.get("remote_connector_id") or "")

    def tarefa(t):
        d, _ = tr._documento_do_cliente(serial)
        criada = tr._nbi("POST", tr._device_path(d["_id"]) + "/tasks", body=t) or {}
        chamou, motivo = tr._chamar_onu(d, conector)
        if not chamou:
            raise tr.Tr069Error("ONU sem caminho para acao imediata: " + motivo)
        res = tr._esperar_tarefa(str(criada.get("_id") or ""), d["_id"], limite_s=40.0)
        if res != "aplicada":
            raise tr.Tr069Error(res)

    for p in passos:
        tarefa({"name": "setParameterValues", "parameterValues": p["valores"]})
    tarefa({"name": "refreshObject", "objectName": RAIZ})
    if plano(tr._documento_do_cliente(serial)[0]):
        raise tr.Tr069Error("a ONU aceitou, mas a ACL nao ficou com a faixa certa")
    return {"ok": True, "mudou": True, "regras": [f"{p['regra']}={p['nome']}" for p in passos]}


def manter_cliente(tr) -> Dict[str, Any]:
    """Laco de manutencao: confere as ONUs gerenciadas DO CLIENTE DA SESSAO."""
    from app.services.db_store import get_json_state, set_json_state

    feitos, erros = [], {}
    estado = dict(get_json_state(ESTADO_KEY, {}) or {})
    for linha in tr.listar().get("onus", []):
        if linha.get("estado") != "gerenciada" or len(feitos) + len(erros) >= MAX_POR_CICLO:
            continue
        try:
            doc, _ = tr._documento_do_cliente(linha["serial"])
            if not plano(doc):
                continue
            r = aplicar(tr, linha["serial"])
            if r.get("mudou"):
                feitos.append(linha["serial"])
                estado[linha["serial"]] = {"ok": True}
        except Exception as exc:  # uma ONU com problema nao para as outras
            erros[linha["serial"]] = str(exc)[:160]
            estado[linha["serial"]] = {"ok": False, "erro": str(exc)[:160]}
    if feitos or erros:
        set_json_state(ESTADO_KEY, estado)
    return {"ok": True, "aplicadas": feitos, "erros": erros}
