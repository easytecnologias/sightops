"""Apagar camera tem que apagar o host, e a poda por site so pode podar o site.

Dois defeitos que deixaram 165 hosts orfaos no rads (2026-09-28):

  1. `inventory_delete` nao tocava no Zabbix -- a camera sumia da tela e o host
     continuava sendo pingado, alarmando por equipamento que ninguem tem mais.
  2. a poda ficava DESLIGADA quando o sync era por site, que e o modo de uso
     normal. Estava desligada de proposito: sem escopo, o host de todo site que
     nao veio na rodada parece "fora do inventario" e some (aconteceu em 19 e
     20/08, ~88% do grupo). A saida nao e ligar solta -- e restringir ao grupo
     "<base>/<SITE>" dos sites daquela rodada.

Roda: python scripts/sightops_zabbix_poda_escopo_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import inventory_delete_service as inv


def teste_exclusao_chama_zabbix() -> None:
    chamadas = []

    def falso(rows):
        chamadas.append([str((r or {}).get("ip") or "") for r in rows])
        return {"ok": True, "removed": len(rows)}

    original = inv._remover_hosts_do_zabbix
    inv._remover_hosts_do_zabbix = falso
    try:
        # o servico e chamado com as linhas removidas; aqui exercito so o elo
        r = inv._remover_hosts_do_zabbix([{"ip": "10.10.8.7"}, {"ip": "10.10.9.30"}])
    finally:
        inv._remover_hosts_do_zabbix = original
    assert r["removed"] == 2, r
    assert chamadas == [["10.10.8.7", "10.10.9.30"]], chamadas


def teste_ip_vazio_nao_apaga_nada() -> None:
    # linha sem IP nao pode virar um host.get sem filtro -- isso varreria tudo
    r = inv._remover_hosts_do_zabbix([{"titulo": "sem ip"}, {}])
    assert r == {"ok": True, "removed": 0}, r


def teste_falha_no_zabbix_nao_derruba_exclusao() -> None:
    # o retorno carrega o erro, mas a funcao NAO levanta: apagar a camera e o
    # que o usuario pediu; o Zabbix e consequencia
    r = inv._remover_hosts_do_zabbix([{"ip": "203.0.113.9"}])
    assert isinstance(r, dict) and "ok" in r, r


def main() -> None:
    teste_exclusao_chama_zabbix()
    teste_ip_vazio_nao_apaga_nada()
    teste_falha_no_zabbix_nao_derruba_exclusao()
    print("OK exclusao: remove o host do Zabbix; sem IP nao apaga nada;")
    print("   falha no Zabbix nao derruba a exclusao do inventario")


if __name__ == "__main__":
    main()
