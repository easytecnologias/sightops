"""Apagar camera e apagar: nao volta na varredura nem no sync da OLT.

Regressao do que o usuario mais reclamou. Nao usa lista de permitidos -- ela foi
removida de proposito: uma lista so, a de bloqueados.

Roda direto:
    python sightops_apagar_nao_volta_test.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SITE = "ESCOLA MEDEA"


def check(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise AssertionError(mensagem)


class FakeProc:
    returncode = 0
    stdout = "ok"
    stderr = ""


REDE = [
    {"ip": "100.65.8.21", "mac": "aa:aa:aa:aa:aa:01", "status": "online", "local": SITE,
     "site": SITE, "remote_connector_id": "conn-1"},
    {"ip": "100.65.8.22", "mac": "aa:aa:aa:aa:aa:02", "status": "online", "local": SITE,
     "site": SITE, "remote_connector_id": "conn-1"},
]


def _fake_scan(rows):
    def fake_run(cmd, cwd=None, capture_output=True, text=True, check=False):
        if "--out" not in cmd:
            return FakeProc()
        out = Path(cmd[cmd.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows), encoding="utf-8")
        return FakeProc()
    return fake_run


def varre(scan_service, ScanRequest, alvo="100.65.8.0/24"):
    original = scan_service.subprocess.run
    scan_service.subprocess.run = _fake_scan(REDE)
    try:
        return scan_service.run_http_scan(
            ScanRequest(alvo=alvo, usuario="admin", senha="x", local=SITE,
                        inventory_mode="basic", capture_snapshot=False, excel=False))
    finally:
        scan_service.subprocess.run = original


def ips(load_inventory_json):
    return sorted(str(r.get("ip") or "") for r in (load_inventory_json(mode="basic") or []))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-apagar-"))
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.models.requests import InventoryDeleteRequest, ScanRequest
        from app.services.inventory_delete_service import inventory_delete
        from app.services.inventory_json import load_inventory_json
        from app.services.olt_ignore_list import is_ignored_olt_row, list_ignored
        from app.services import scan_service

        token = set_current_tenant_slug("rads")
        try:
            varre(scan_service, ScanRequest)
            check(ips(load_inventory_json) == ["100.65.8.21", "100.65.8.22"], "as 2 deviam entrar")
            print("  ok: varredura cadastrou as 2 cameras")

            res = inventory_delete(InventoryDeleteRequest(
                ips=["100.65.8.22"], mode="basic", site=SITE, permanent=True))
            check(res.get("ok"), f"delete falhou: {res}")
            check(res.get("ignored_added") == 1, f"devia gravar 1 bloqueio: {res}")
            print("  ok: apagar gravou o bloqueio")

            varre(scan_service, ScanRequest)
            check(ips(load_inventory_json) == ["100.65.8.21"],
                  f"a apagada voltou: {ips(load_inventory_json)}")
            print("  ok: varredura seguinte NAO trouxe a camera de volta")

            # o bloqueio nao pode caducar quando o site e renomeado
            linha_renomeada = dict(REDE[1])
            linha_renomeada["site"] = "NOME NOVO DO SITE"
            linha_renomeada["local"] = "NOME NOVO DO SITE"
            check(is_ignored_olt_row(linha_renomeada),
                  "bloqueio deixou de valer so porque o site foi renomeado")
            print("  ok: bloqueio continua valendo apos renomear o site")

            # ... e nem quando a camera muda de ONU
            linha_remanejada = dict(REDE[1])
            linha_remanejada["onu_id"] = "99"
            linha_remanejada["pon"] = "0/9"
            check(is_ignored_olt_row(linha_remanejada),
                  "bloqueio deixou de valer so porque a camera mudou de ONU")
            print("  ok: bloqueio continua valendo apos remanejar de ONU")

            # mas nao pode bloquear o mesmo IP de OUTRO cliente
            outro = dict(REDE[1])
            outro["remote_connector_id"] = "conn-OUTRO-CLIENTE"
            check(not is_ignored_olt_row(outro),
                  "bloqueio vazou para outro conector/cliente")
            print("  ok: nao bloqueia o mesmo IP em outro cliente")

            # varrer o IP explicitamente e o jeito de trazer de volta
            varre(scan_service, ScanRequest, alvo="100.65.8.22")
            check("100.65.8.22" in ips(load_inventory_json),
                  "varrer o IP direto deveria reabilitar a camera")
            check(not any(x["ip"] == "100.65.8.22" for x in list_ignored()),
                  "o bloqueio deveria ter saido ao varrer o IP direto")
            print("  ok: varrer o IP explicitamente traz a camera de volta")
        finally:
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK apagar e apagar; so volta se voce pedir")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
