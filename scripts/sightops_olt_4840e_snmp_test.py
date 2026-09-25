"""Telemetria SNMP da 4840E: indice, status e conversoes, sem tocar na rede.

Os valores usados aqui sao os que a OLT da Barra devolveu de verdade em
2026-09-26 -- inclusive o mapeamento de status, que foi conferido ONU a ONU
contra o `show onu-status` (84 Up / 13 Down, nas mesmas posicoes).

Roda: python scripts/sightops_olt_4840e_snmp_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli.tools.olt_4840e_snmp import (
    _BASE_INFO,
    _BASE_OPM,
    _OFFLINE_REASON,
    _OPER_STATUS,
    _indice,
    _para_km,
    _texto,
)


def main() -> None:
    # Indice: o sufixo e <card>.<pon>.<onu> e card e sempre 0 nesta OLT.
    assert _indice(f"{_BASE_OPM}.8.0.1.5", _BASE_OPM, "8") == (1, 5)
    assert _indice(f"{_BASE_INFO}.4.0.4.19", _BASE_INFO, "4") == (4, 19)

    # Coluna vizinha nao pode ser confundida com a pedida: .4 nao casa com .18,
    # senao temperatura entraria no lugar de distancia.
    assert _indice(f"{_BASE_INFO}.18.0.1.1", _BASE_INFO, "4") is None
    assert _indice("1.3.6.1.2.1.1.1.0", _BASE_OPM, "8") is None

    # Status: 0 e DOWN. Inverter isso mostraria o parque inteiro no ar.
    assert _OPER_STATUS[0] == "down"
    assert _OPER_STATUS[1] == "up"
    assert _OFFLINE_REASON[0] == ""      # no ar nao tem motivo
    assert _OFFLINE_REASON[1] == "fora do ar"

    # Distancia: a OLT responde em METROS e o inventario guarda em km.
    assert _para_km("2510") == "2.51"
    assert _para_km(2091) == "2.091"
    assert _para_km("0") == ""           # sem medida nao vira "0.0"
    assert _para_km("") == ""
    assert _para_km(None) == ""
    assert _para_km("nao-numero") == ""

    # RX vem como string com sinal ("-30.0"). Tratar como numero e perder o
    # texto original; o importante e nao transformar em vazio.
    assert _texto("-30.0") == "-30.0"
    assert _texto(None) == ""
    assert _texto(0) == "0"

    print("OK telemetria SNMP 4840E: indice, status 0=down, metros->km")


if __name__ == "__main__":
    main()
