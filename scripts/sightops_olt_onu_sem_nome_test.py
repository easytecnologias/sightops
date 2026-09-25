"""ONU sem descricao nao pode sumir da coleta da OLT 4840E.

Caso real (2026-09-24, Barra de Sao Miguel): a OLT reiniciou, as ONUs
re-registraram com autenticacao desligada e algumas perderam a descricao. A
regex do `show pon` exigia descricao (`.+`), entao a linha inteira nao casava e
a ONU era descartada em silencio -- a 0/1/32 levou junto os 21 CPEs da Escola
Medea, e nenhuma sincronizacao trazia aquelas cameras de volta.

Roda: python scripts/sightops_olt_onu_sem_nome_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli.tools.olt_4840e_collect_macs import _parse_show_pon

# saida literal da OLT da Barra (show pon), com e sem descricao
SAIDA = """ ONU    Mac Address       LLID ONU-TYPE Config Description
 0/1/30 54:6c:ac:39:bf:7f 0017 other    enable Ginasio_1
 0/1/32 98:e5:5b:12:ee:4c 0002 other    enable 
 0/4/6  98:2a:0a:9b:b0:12 000b other    enable 
 0/4/7  80:85:44:c8:75:a1 0001 other    enable
 0/4/8  98:2a:0a:82:ce:2d 000e other    enable ONU-16-17
 0/2/18 98:e5:5b:12:ee:0b 000d other    enable Ginasio_AltoBarra
Total onu entries: 6 .
"""


def main() -> None:
    achados = _parse_show_pon(SAIDA)
    por_onu = {a["onu"]: a for a in achados}

    esperadas = {"0/1/30", "0/1/32", "0/4/6", "0/4/7", "0/4/8", "0/2/18"}
    assert set(por_onu) == esperadas, f"faltou: {sorted(esperadas - set(por_onu))}"

    # sem nome entra com descricao vazia -- nunca some
    assert por_onu["0/1/32"]["description"] == "", por_onu["0/1/32"]
    assert por_onu["0/4/7"]["description"] == "", por_onu["0/4/7"]  # sem espaco no fim

    # com nome continua igual, e o resto da linha nao pode ser contaminado
    assert por_onu["0/1/30"]["description"] == "Ginasio_1", por_onu["0/1/30"]
    assert por_onu["0/1/30"]["onu_mac"] == "54:6c:ac:39:bf:7f", por_onu["0/1/30"]
    assert por_onu["0/1/30"]["llid"] == "0017", por_onu["0/1/30"]
    assert por_onu["0/2/18"]["pon"] == "0/2", por_onu["0/2/18"]
    assert por_onu["0/2/18"]["onu_id"] == "18", por_onu["0/2/18"]

    # cabecalho e rodape continuam ignorados
    assert "ONU" not in por_onu and "Total" not in por_onu

    print("OK coleta da OLT: ONU sem nome entra na lista; ONU com nome nao muda")


if __name__ == "__main__":
    main()
