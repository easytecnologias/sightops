"""Sonda: o que a OLT 4840E entrega por SNMP, e o que ela NAO entrega.

So leitura (GET/GETNEXT) -- nao muda nada na OLT. Serve para separar, com
evidencia, o que da pra usar na telemetria do que e promessa do template
Zabbix que a OLT nao cumpre.

Contexto (2026-09-25): a telemetria da 4840E por CLI devolve `rx_olt` e
`rx_onu` SEMPRE vazios (collect_onu_telemetry_4840e) -- sinal optico so existe
sob demanda, uma ONU por vez, abrindo uma sessao SSH inteira. Os OIDs abaixo
vieram do template Zabbix "OLT 4840 E" do proprio usuario e resolveriam isso
com um walk. Falta a OLT responder: na Barra a config tem `snmp-server disable`
e na Santana nao ha community cadastrada.

Precisa rodar DE DENTRO do container da API -- o IP virtual do vnat nao existe
na tabela de rota do host:

    docker cp scripts/sightops_olt_4840e_snmp_probe.py sightops-v3-api:/tmp/p.py
    docker exec -e PYTHONPATH=/app sightops-v3-api python /tmp/p.py rads
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.snmp_client import Snmp

# Enterprise 13464 = Fiberhome (a 4840E da Intelbras e OEM Fiberhome).
#
# Os OIDs abaixo NAO vieram do template Zabbix de 2021: vieram do
# `show snmp mib` da propria OLT da Barra (2026-09-25), que lista a MIB que
# aquele firmware realmente expoe. O template so conhecia temperatura e RX --
# a OLT entrega bem mais, inclusive TX, tensao, corrente de bias e o MOTIVO de
# uma ONU estar offline.
SISTEMA = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "cpu_idle_%": "1.3.6.1.4.1.13464.1.2.1.1.2.11.0",
    "mem_total": "1.3.6.1.4.1.13464.1.2.1.1.2.12.0",
    "mem_avail": "1.3.6.1.4.1.13464.1.2.1.1.2.13.0",
}

# eponOnuOpm -- diagnostico optico, indexado por <card>.<PON>.<ONU> (card = 0).
# E isto que a telemetria por CLI nunca traz: hoje rx_olt e rx_onu saem vazios.
OPTICO = {
    "opm_pon_index": "1.3.6.1.4.1.13464.1.13.3.3.1.2",
    "opm_onu_index": "1.3.6.1.4.1.13464.1.13.3.3.1.3",
    "temperatura": "1.3.6.1.4.1.13464.1.13.3.3.1.4",
    "vcc": "1.3.6.1.4.1.13464.1.13.3.3.1.5",
    "bias": "1.3.6.1.4.1.13464.1.13.3.3.1.6",
    "tx_power": "1.3.6.1.4.1.13464.1.13.3.3.1.7",
    "rx_power": "1.3.6.1.4.1.13464.1.13.3.3.1.8",
}

# eponOnuInfo -- identidade e estado da ONU. Substituiria o parse de texto do
# 'show onu-status', que ja descartou ONU em silencio por causa da regex.
ONU_INFO = {
    "oper_status": "1.3.6.1.4.1.13464.1.13.3.1.1.4",
    "nome": "1.3.6.1.4.1.13464.1.13.3.1.1.5",
    "llid": "1.3.6.1.4.1.13464.1.13.3.1.1.6",
    "fabricante": "1.3.6.1.4.1.13464.1.13.3.1.1.7",
    "modelo": "1.3.6.1.4.1.13464.1.13.3.1.1.8",
    "distancia": "1.3.6.1.4.1.13464.1.13.3.1.1.18",
    "registrada_em": "1.3.6.1.4.1.13464.1.13.3.1.1.19",
    "motivo_offline": "1.3.6.1.4.1.13464.1.13.3.1.1.23",
}
TABELAS = {**OPTICO, **ONU_INFO}

COMUNIDADES = ("public", "private", "admin", "intelbras", "olt", "snmp")


def _descobre_comunidade(host: str) -> str | None:
    for com in COMUNIDADES:
        try:
            Snmp(host, com, timeout=2.5).get(SISTEMA["sysDescr"])
            return com
        except Exception:
            continue
    return None


def _alvos_do_registro(tenant: str) -> list[tuple[str, str]]:
    from app.core.tenant_context import set_current_tenant_slug
    from app.services import connector_routing_vnat as vnat
    from app.services.olt_registry import list_olts, resolve_credentials

    set_current_tenant_slug(tenant)
    saida: list[tuple[str, str]] = []
    for olt in list_olts(True):
        if "4840" not in str(olt.get("model") or ""):
            continue
        cred = resolve_credentials(int(olt["id"]))
        real = str(cred.get("host") or "")
        # Conector isolado: a OLT so responde pelo IP virtual (host NAT -> real).
        virtual = vnat.virtual_ip_for(str(cred.get("connector_id") or ""), real) or real
        saida.append((f"{olt.get('name')} ({real})", virtual))
    return saida


def sonda(nome: str, host: str) -> None:
    print(f"\n{'=' * 60}\n{nome}  ->  {host}\n{'=' * 60}")
    com = _descobre_comunidade(host)
    if not com:
        print(f"  SNMP NAO RESPONDE (testadas: {', '.join(COMUNIDADES)})")
        print("  Confira na OLT:  show running-config  ->  procure 'snmp-server'")
        print("  'snmp-server disable' explica silencio com a community certa.")
        return
    print(f"  community: {com!r}\n")
    s = Snmp(host, com, timeout=4.0)

    print("  -- escalares --")
    for rotulo, oid in SISTEMA.items():
        try:
            print(f"    {rotulo:12} = {s.get(oid)!r}")
        except Exception as exc:
            print(f"    {rotulo:12} FALHOU ({type(exc).__name__})")

    print("\n  -- tabelas de ONU --")
    for rotulo, raiz in TABELAS.items():
        try:
            linhas = list(s.walk(raiz, limite=400))
        except Exception as exc:
            print(f"    {rotulo:12} FALHOU ({type(exc).__name__})")
            continue
        if not linhas:
            print(f"    {rotulo:12} VAZIO (a OLT nao popula esta tabela)")
            continue
        print(f"    {rotulo:12} {len(linhas)} linhas. Amostra:")
        for oid, valor in linhas[:4]:
            print(f"        {oid} = {valor!r}")


def main() -> int:
    if len(sys.argv) == 3 and "." in sys.argv[2]:
        sonda(sys.argv[1], sys.argv[2])
        return 0
    tenant = sys.argv[1] if len(sys.argv) > 1 else "rads"
    alvos = _alvos_do_registro(tenant)
    if not alvos:
        print(f"nenhuma OLT 4840E cadastrada no tenant {tenant!r}")
        return 1
    for nome, host in alvos:
        sonda(nome, host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
