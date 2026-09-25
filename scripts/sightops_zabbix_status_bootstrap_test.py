"""Cliente com inventario e ZERO host no Zabbix nao pode passar em silencio.

Caso real (2026-09-25, Easy Tecnologias / tenant `default`): o loop de fundo
chama o status-sync com ensure_hosts=False -- ele LE o Zabbix, nao cria host.
Como esse cliente nao tinha NENHUM host la, a leitura devolvia ok=True com
total=387 e matched=0: sucesso aparente, zero erro no log, e o status das 387
cameras congelado em 17/09 por 8 dias. Camera no ar aparecia offline e camera
morta aparecia online, porque a tela repetia o retrato antigo.

Roda: python scripts/sightops_zabbix_status_bootstrap_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.main as main


class _SyncFalso:
    """Finge o status-sync: sem host no Zabbix ate alguem pedir para criar."""

    def __init__(self, total: int, hosts_existem: bool):
        self.total = total
        self.hosts_existem = hosts_existem
        self.chamadas: list[bool] = []

    def __call__(self, payload):
        ensure = payload.get("ensure_hosts", True)
        self.chamadas.append(bool(ensure))
        if ensure:
            self.hosts_existem = True          # criar hosts resolve
        casados = self.total if self.hosts_existem else 0
        return {
            "ok": True,
            "total": self.total,
            "matched": casados,
            "updated": casados,
            "online": casados,
        }


def _roda(total, hosts_existem):
    falso = _SyncFalso(total, hosts_existem)
    original = main.scripts_zabbix_status_sync
    main.scripts_zabbix_status_sync = falso
    try:
        return falso, main._run_zabbix_status_sync_for_mode("olt", "default")
    finally:
        main.scripts_zabbix_status_sync = original


def main_() -> None:
    # 1) o caso que quebrou: tem inventario, nao tem host
    falso, r = _roda(total=387, hosts_existem=False)
    assert falso.chamadas == [False, True], falso.chamadas   # tentou ler, depois criou
    assert r.get("host_bootstrap_forcado") is True, r
    assert r["matched"] == 387, r                            # e passou a enxergar
    assert r["updated"] == 387, r

    # 2) o dia a dia: hosts ja existem -> NAO cria de novo (barato)
    falso, r = _roda(total=387, hosts_existem=True)
    assert falso.chamadas == [False], falso.chamadas
    assert "host_bootstrap_forcado" not in r, r

    # 3) cliente sem inventario nenhum: nada a fazer, nao inventa host
    falso, r = _roda(total=0, hosts_existem=False)
    assert falso.chamadas == [False], falso.chamadas
    assert "host_bootstrap_forcado" not in r, r

    print("OK zabbix status: inventario com 0 host no Zabbix agora cria e avisa,")
    print("   em vez de devolver sucesso mudo e congelar o status")


if __name__ == "__main__":
    main_()
