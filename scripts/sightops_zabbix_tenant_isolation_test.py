"""Testa o isolamento por tenant dos hosts que tools/mk_zabbix_from_inventory.py
cria no Zabbix.

O bug real: o nome tecnico do host era so "CAM-{ip}" (ou "DVR-{ip}-CHx",
"WIN-{hostname}"), sem o cliente. Dois tenants com a mesma camera de IP
privado (achado real: 192.168.20.0/24 esta cadastrado em SIERRA e PERUCABA ao
mesmo tempo, ver scripts/sightops_wireguard_sync_test.py) colidiam no MESMO
host -- cada sincronismo sobrescrevia titulo/local/foto do cliente anterior.

Como os bancos ja sao isolados por tenant, o esperado e: sincronizar de novo
o MESMO cliente atualiza o host dele (upsert normal); sincronizar um cliente
DIFERENTE com o mesmo IP nunca toca no host do outro.

Roda direto:  python scripts/sightops_zabbix_tenant_isolation_test.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("mk_zabbix", ROOT / "tools" / "mk_zabbix_from_inventory.py")
mk_zabbix = importlib.util.module_from_spec(spec)
sys.modules["mk_zabbix"] = mk_zabbix
spec.loader.exec_module(mk_zabbix)

build_host_name = mk_zabbix.build_host_name

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


def main() -> None:
    camera_ip_repetido = {"ip": "192.168.20.5"}  # sem source -> camera generica

    # --- o bug real: mesmo IP, tenants diferentes ---
    host_sierra = build_host_name("sierra", camera_ip_repetido)
    host_perucaba = build_host_name("perucaba", camera_ip_repetido)
    check(host_sierra != host_perucaba, f"tenants diferentes colidiram no mesmo host: {host_sierra} == {host_perucaba}")
    check("SIERRA" in host_sierra, f"host da sierra deveria conter o tenant: {host_sierra}")
    check("PERUCABA" in host_perucaba, f"host da perucaba deveria conter o tenant: {host_perucaba}")
    check("192.168.20.5" in host_sierra and "192.168.20.5" in host_perucaba, "os dois deveriam manter o IP no nome")

    # --- o requisito do usuario: mesmo cliente, resincronizar = mesmo host (upsert) ---
    primeira_vez = build_host_name("sierra", camera_ip_repetido)
    segunda_vez = build_host_name("sierra", dict(camera_ip_repetido))  # nova instancia do dict, mesmo conteudo
    check(primeira_vez == segunda_vez, f"resincronizar o MESMO tenant deveria gerar o MESMO host: {primeira_vez} != {segunda_vez}")

    # --- as outras 3 formas de host (DVR por canal, Windows, host_key explicito) ---
    dvr_row = {"ip": "10.0.0.5", "source": "dvr", "channel": "3"}
    h1 = build_host_name("sierra", dvr_row)
    h2 = build_host_name("perucaba", dvr_row)
    check(h1 != h2, f"canal de DVR com mesmo IP+canal deveria isolar por tenant: {h1} vs {h2}")
    check("CH3" in h1, f"host de DVR deveria manter o canal: {h1}")

    win_row = {"ip": "10.0.0.9", "source": "windows", "hostname": "PC-RECEPCAO"}
    h1 = build_host_name("sierra", win_row)
    h2 = build_host_name("perucaba", win_row)
    check(h1 != h2, f"Windows com mesmo hostname deveria isolar por tenant: {h1} vs {h2}")
    check("PC-RECEPCAO" in h1, f"host de Windows deveria manter o hostname: {h1}")

    hk_row = {"ip": "10.0.0.1", "host_key": "onu-42-pon-3"}
    h1 = build_host_name("sierra", hk_row)
    h2 = build_host_name("perucaba", hk_row)
    check(h1 != h2, f"host_key explicito com mesmo valor deveria isolar por tenant: {h1} vs {h2}")

    # --- tenant vazio/None nao quebra, cai no default (nunca perde o prefixo) ---
    sem_tenant = build_host_name("", camera_ip_repetido)
    check(sem_tenant.startswith("DEFAULT-"), f"tenant vazio deveria cair em DEFAULT-, veio: {sem_tenant}")
    nulo = build_host_name(None, camera_ip_repetido)  # type: ignore[arg-type]
    check(nulo.startswith("DEFAULT-"), f"tenant None deveria cair em DEFAULT-, veio: {nulo}")

    # --- caracteres fora do padrao Zabbix (espaco, acento) sao sanitizados, nao quebram ---
    esquisito = build_host_name("Cliente Novo Ltda.", camera_ip_repetido)
    check(" " not in esquisito, f"nome de tenant com espaco deveria ser sanitizado: {esquisito}")

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print("  -", f)
        raise SystemExit(1)
    print("OK isolamento Zabbix por tenant: mesmo cliente reusa o host, clientes diferentes nunca colidem mesmo com IP identico")


if __name__ == "__main__":
    main()
