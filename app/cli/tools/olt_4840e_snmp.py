"""Telemetria da OLT Intelbras 4840E (EPON) por SNMP.

Por que existe: a telemetria por CLI (`collect_onu_telemetry_4840e`) nunca traz
sinal optico -- `show onu-status` da estado e distancia, e os campos `rx_olt` /
`rx_onu` saiam SEMPRE vazios. Potencia so existia sob demanda, uma ONU por vez,
abrindo uma sessao SSH inteira. Aqui um walk traz as 84 ONUs de uma vez, tipado,
sem sessao e sem parse de texto (que ja descartou ONU em silencio antes).

OIDs confirmados na propria OLT com `show snmp mib` (nao no template Zabbix de
2021, que so conhecia temperatura e RX). Enterprise 13464 = Fiberhome; a 4840E
da Intelbras e OEM. Indice das tabelas: `<card>.<pon>.<onu>`, com card = 0.

RITMO IMPORTA: sao ~100 ONUs x varias colunas. Pedindo tudo em rajada a OLT para
de responder no meio do walk (medido na Barra em 2026-09-26). Por isso cada
pergunta tem pausa e o walk retoma de onde parou em vez de perder a tabela.

Pre-requisitos na OLT, que NAO sao codigo (ver docs/HANDOFF_AGENTES.md):
  1. `snmp-server enable` -- a config guarda `snmp-server disable`, e o servico
     NAO sobe sozinho no boot; precisa do comando explicito.
  2. rota de volta ate o servidor. A OLT so tem default pela VLAN de gerencia;
     ICMP e SSH respondem pela interface de entrada, mas o agente SNMP responde
     por socket e consulta a tabela de rotas -- sem rota, o pedido chega e a
     resposta sai pelo lado errado.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from app.services import connector_routing_vnat as _vnat
from app.services.snmp_client import Snmp

_BASE_OPM = "1.3.6.1.4.1.13464.1.13.3.3.1"   # eponOnuOpm  -- diagnostico optico
_BASE_INFO = "1.3.6.1.4.1.13464.1.13.3.1.1"  # eponOnuInfo -- identidade/estado

# Colunas que valem a pena. Deixadas de fora de proposito:
#   eponPonOpmRxPower -- existe so por PORTA PON (agregado), nao por ONU, entao
#     nao serve como "potencia que a OLT recebe DESTA ONU";
#   OMCI -- e conceito GPON. Esta OLT e EPON e nao tem. O campo saia sempre
#     vazio na telemetria por CLI, fingindo um dado que nunca existiu.
_COLUNAS_OPM = {
    "temperatura": "4",
    "vcc": "5",
    "bias": "6",
    "onu_tx": "7",
    "onu_rx": "8",
}
_COLUNAS_INFO = {
    "oper_status_raw": "4",
    "onu_name": "5",
    "llid": "6",
    "distance_m": "18",
    "registered_at": "19",
    "offline_reason_raw": "23",
}

# eponOnuOperationStatus. Conferido ONU a ONU contra o `State` do
# `show onu-status` na Barra (2026-09-26): o CLI disse 84 Up / 13 Down e o SNMP
# devolveu exatamente 84 valores 1 e 13 valores 0, nas mesmas posicoes.
_OPER_STATUS = {0: "down", 1: "up"}

# eponOnuOfflineReason. So dois valores foram observados ao vivo, e em
# correlacao perfeita com o status: 0 nas 84 no ar, 1 nas 13 fora. Os demais
# codigos desta coluna nao foram vistos, entao nao invento rotulo para eles --
# aparecem como "codigo N" ate alguem observar o caso real.
_OFFLINE_REASON = {0: "", 1: "fora do ar"}


def _indice(oid: str, base: str, coluna: str) -> Tuple[int, int] | None:
    """Extrai (pon, onu) do sufixo `<card>.<pon>.<onu>` do OID."""
    prefixo = f"{base}.{coluna}."
    if not oid.startswith(prefixo):
        return None
    partes = oid[len(prefixo):].split(".")
    if len(partes) < 3:
        return None
    try:
        return int(partes[1]), int(partes[2])
    except ValueError:
        return None


def _walk_coluna(
    snmp: Snmp, base: str, coluna: str, pausa: float, tentativas: int, limite: int = 600,
) -> Dict[Tuple[int, int], Any]:
    """Caminha uma coluna inteira, retomando quando a OLT engasga.

    A OLT deixa de responder sob rajada. Um timeout no meio nao pode custar a
    tabela toda: espera um pouco e continua a partir do ultimo OID que veio.
    """
    raiz = f"{base}.{coluna}"
    valores: Dict[Tuple[int, int], Any] = {}
    atual = raiz
    falhas = 0
    for _ in range(limite):
        try:
            erro, oid, valor = snmp._ask(atual, 0xA1)  # GETNEXT
        except Exception:
            falhas += 1
            if falhas > tentativas:
                break
            time.sleep(pausa * 10)
            continue
        falhas = 0
        if erro or not oid.startswith(raiz + ".") or valor == "<endOfMibView>":
            break
        chave = _indice(oid, base, coluna)
        if chave:
            valores[chave] = valor
        atual = oid
        time.sleep(pausa)
    return valores


def _texto(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _para_km(valor: Any) -> str:
    """A OLT devolve distancia em metros; o inventario guarda em km."""
    try:
        metros = float(_texto(valor))
    except (TypeError, ValueError):
        return ""
    return str(round(metros / 1000.0, 3)) if metros else ""


def collect_onu_telemetry_4840e_snmp(
    olt_ip: str,
    community: str = "public",
    timeout: float = 5.0,
    pausa: float = 0.03,
    tentativas: int = 3,
) -> List[Dict[str, Any]]:
    """Telemetria de todas as ONUs da OLT. Mesmo formato da versao por CLI.

    Levanta excecao se a OLT nao responder nada -- quem chama cai para o CLI.
    """
    # Conector isolado: quem resolve o IP de alcance e o DRIVER, como nos outros
    # (olt_4840e_collect_macs, olt_8820i_*, olt_vsol_epon). `req.olt_ip` fica
    # REAL de proposito para nao vazar o IP virtual para dentro do inventario --
    # sem esta linha o SNMP tenta o IP real, que nao existe na rota daqui, e
    # cai sempre para o CLI com "timed out".
    host = _vnat.reach_olt_ip(olt_ip) or olt_ip
    snmp = Snmp(host, community, timeout=timeout)
    # Primeiro contato: se nem o sysDescr vem, nao adianta tentar as tabelas.
    snmp.get("1.3.6.1.2.1.1.1.0")

    colunas: Dict[str, Dict[Tuple[int, int], Any]] = {}
    for nome, coluna in _COLUNAS_INFO.items():
        colunas[nome] = _walk_coluna(snmp, _BASE_INFO, coluna, pausa, tentativas)
    for nome, coluna in _COLUNAS_OPM.items():
        colunas[nome] = _walk_coluna(snmp, _BASE_OPM, coluna, pausa, tentativas)

    posicoes = sorted({chave for valores in colunas.values() for chave in valores})
    if not posicoes:
        raise RuntimeError("SNMP respondeu, mas nenhuma tabela de ONU veio")

    saida: List[Dict[str, Any]] = []
    for pon, onu in posicoes:
        bruto = colunas["oper_status_raw"].get((pon, onu))
        try:
            oper = _OPER_STATUS.get(int(bruto), "")
        except (TypeError, ValueError):
            oper = ""
        motivo_bruto = colunas["offline_reason_raw"].get((pon, onu))
        try:
            motivo = _OFFLINE_REASON.get(int(motivo_bruto), f"codigo {motivo_bruto}")
        except (TypeError, ValueError):
            motivo = ""

        saida.append({
            "pon": pon,
            "onu_id": onu,
            "serial": "",           # o MAC vem da coleta de MACs, nao daqui
            "oper_status": oper,
            # EPON nao tem OMCI (e GPON). Fica vazio de proposito.
            "omci_status": "",
            # Nao existe RX por ONU medido na OLT nesta MIB -- so por porta PON.
            # Preencher com o TX da ONU seria inventar dado.
            "rx_olt": "",
            "rx_onu": _texto(colunas["onu_rx"].get((pon, onu))),
            "distance_km": _para_km(colunas["distance_m"].get((pon, onu))),
            # Extras que a CLI nunca deu:
            "onu_tx": _texto(colunas["onu_tx"].get((pon, onu))),
            "temperatura": _texto(colunas["temperatura"].get((pon, onu))),
            "vcc": _texto(colunas["vcc"].get((pon, onu))),
            "bias": _texto(colunas["bias"].get((pon, onu))),
            "onu_name": _texto(colunas["onu_name"].get((pon, onu))),
            "llid": _texto(colunas["llid"].get((pon, onu))),
            "registered_at": _texto(colunas["registered_at"].get((pon, onu))),
            "offline_reason": motivo,
            "source": "snmp",
        })
    return saida
