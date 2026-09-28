"""O host do Zabbix: NOME pelo IP real, INTERFACE pelo IP de alcance.

Caso real (2026-09-26, rads): 542 das 570 cameras tinham DOIS hosts -- um com o
IP real e outro com o IP virtual do vnat -- porque o nome do host carrega o IP e
o caminho mudou em algum momento. Resultado: dois alarmes para a mesma camera, e
o lado do IP real falhando 4x mais (119 sem resposta contra 31, mesmas cameras).

A regra: o nome sai do IP REAL (identidade estavel, casa com o inventario) e a
interface usa o IP de ALCANCE. Assim trocar o caminho nao cria host novo.

Roda: python scripts/sightops_zabbix_reach_ip_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.endpoints import maintenance as m


def main() -> None:
    reais = {"100.65.11.7": "10.209.3.7"}          # isolado: real -> virtual
    original = m._reach
    m._reach = lambda ip, cid="": reais.get(ip, ip)
    try:
        linhas = [
            {"ip": "100.65.11.7", "titulo": "CAM ISOLADA", "remote_connector_id": "abc"},
            {"ip": "192.168.0.50", "titulo": "CAM DIRETA"},   # sem conector
            {"titulo": "linha sem ip"},
        ]
        saida = m._build_zabbix_rows("ip", linhas)
    finally:
        m._reach = original

    por_ip = {r.get("ip"): r for r in saida if r.get("ip")}

    # isolada: identidade continua o IP real, mas o Zabbix pinga o virtual
    iso = por_ip["100.65.11.7"]
    assert iso["ip"] == "100.65.11.7", iso           # nome do host sai daqui
    assert iso["reach_ip"] == "10.209.3.7", iso      # interface usa isto

    # sem conector: os dois sao o mesmo, nada muda
    direta = por_ip["192.168.0.50"]
    assert direta["reach_ip"] == "192.168.0.50", direta

    # linha sem ip nao pode ser descartada nem ganhar reach_ip inventado
    assert len(saida) == 3, saida
    assert "reach_ip" not in saida[2], saida[2]

    # o titulo e o resto da linha seguem intactos
    assert iso["titulo"] == "CAM ISOLADA", iso

    print("OK zabbix: host identificado pelo IP real, medido pelo IP de alcance")


if __name__ == "__main__":
    main()
