"""Testa os helpers que resumem VLAN pro historico de acoes de ONU
(_vlan_summary_from_services, _vlan_summary_from_macs).

app.services.olt_service tem um import quebrado PRE-EXISTENTE e nao
relacionado (app.cli.tools.olt_4840e_collect_macs faltando funcoes -- ver
memoria de sessao "sightops-olt-service-import-quebrado"). Este teste
tapa esse buraco so pra conseguir importar o modulo e testar os helpers
puros -- nao mexe no arquivo quebrado.

Roda direto:  python scripts/sightops_onu_vlan_summary_test.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Tapa os buracos de import quebrado PRE-EXISTENTES (nao mexe nos arquivos
# reais) -- dois modulos distintos ficaram sem alguma funcao que
# app.services.olt_service importa, por trabalho paralelo do Codex.
import app.cli.tools.olt_4840e_collect_macs as _m4840e  # noqa: E402
for _name in ("collect_onu_telemetry_4840e", "delete_onu_4840e", "discover_onus_4840e", "find_onu_4840e", "onu_signal_4840e"):
    if not hasattr(_m4840e, _name):
        setattr(_m4840e, _name, lambda *a, **kw: None)

import app.services.connector_service as _connector_service  # noqa: E402
if not hasattr(_connector_service, "ensure_connector_targets_allowed"):
    _connector_service.ensure_connector_targets_allowed = lambda *a, **kw: None

import app.services.olt_service as olt_service  # noqa: E402

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


class _FakeService:
    def __init__(self, vlan):
        self.vlan = vlan


def main() -> None:
    check(
        olt_service._vlan_summary_from_services([_FakeService(3000)]) == "3000",
        "uma entrada, service com atributo .vlan",
    )
    check(
        olt_service._vlan_summary_from_services([{"vlan": 3000}, {"vlan": 300}]) == "3000,300",
        "duas entradas, dict com chave 'vlan', sem duplicar",
    )
    check(
        olt_service._vlan_summary_from_services([{"vlan": 3000}, {"vlan": 3000}]) == "3000",
        "vlan repetida nao deve duplicar no resumo",
    )
    check(
        olt_service._vlan_summary_from_services(None, fallback_vlan=3000) == "3000",
        "sem services, cai no fallback_vlan",
    )
    check(
        olt_service._vlan_summary_from_services(None, fallback_vlan=None) == "",
        "sem services e sem fallback, resumo vazio",
    )

    macs_ok = [
        {"mac": "18:0d:2c:c0:26:f0", "interface": "gpon 7 onu 1 gem 257 - vlan 3000"},
        {"mac": "80:8f:e8:f8:58:1e", "interface": "gpon 7 onu 2 gem 258 - vlan 3000"},
    ]
    check(
        olt_service._vlan_summary_from_macs(macs_ok) == "3000",
        f"MACs da mesma vlan devem resumir num valor so: {olt_service._vlan_summary_from_macs(macs_ok)}",
    )
    macs_mistas = [
        {"mac": "aa", "interface": "gpon 7 onu 1 gem 257 - vlan 3000"},
        {"mac": "bb", "interface": "gpon 7 onu 1 gem 258 - vlan 300"},
    ]
    check(
        olt_service._vlan_summary_from_macs(macs_mistas) == "3000,300",
        f"MACs de vlans diferentes devem listar as duas: {olt_service._vlan_summary_from_macs(macs_mistas)}",
    )
    check(olt_service._vlan_summary_from_macs([]) == "", "sem MACs, resumo vazio")
    check(olt_service._vlan_summary_from_macs(None) == "", "None no lugar da lista nao deve quebrar")

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print(" -", f)
        raise SystemExit(1)
    print("OK: sightops_onu_vlan_summary_test")


if __name__ == "__main__":
    main()
