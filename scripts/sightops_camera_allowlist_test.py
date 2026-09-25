"""Inventario declarativo: quem manda e a lista do usuario, nao a descoberta.

Roda direto:
    python scripts/sightops_camera_allowlist_test.py
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


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeProc:
    returncode = 0
    stdout = "ok"
    stderr = ""


def _fake_scan_returning(rows):
    def fake_run(cmd, cwd=None, capture_output=True, text=True, check=False):
        if "--out" not in cmd:
            return FakeProc()
        out_path = Path(cmd[cmd.index("--out") + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(rows), encoding="utf-8")
        return FakeProc()

    return fake_run


def caso_normaliza(camera_allowlist) -> None:
    check(camera_allowlist.normalize_entry(" 10.0.0.5 ") == "10.0.0.5", "IP simples")
    check(camera_allowlist.normalize_entry("10.0.0.0/24") == "10.0.0.0/24", "CIDR")
    check(camera_allowlist.normalize_entry("10.0.0.10-20") == "10.0.0.10-10.0.0.20", "faixa curta")
    check(camera_allowlist.normalize_entry("10.0.0.20-10.0.0.10") == "10.0.0.10-10.0.0.20", "faixa invertida")
    check(camera_allowlist.normalize_entry("nao-e-ip") == "", "lixo deve ser recusado")
    print("  ok: aceita IP, CIDR e faixa; recusa lixo")


def caso_site_sem_lista_nao_muda(camera_allowlist) -> None:
    check(camera_allowlist.is_allowed("SITE SEM LISTA", "1.2.3.4"), "site sem lista deve continuar liberado")
    check(not camera_allowlist.site_is_enforced("SITE SEM LISTA"), "site sem lista nao e estrito")
    print("  ok: site sem lista continua funcionando como antes")


def caso_estrito(camera_allowlist) -> None:
    camera_allowlist.set_site("ESCOLA MEDEA", ["100.65.10.57", "100.65.10.58", "100.65.8.0/24"])
    check(camera_allowlist.site_is_enforced("ESCOLA MEDEA"), "site com lista deve ficar estrito")
    check(camera_allowlist.is_allowed("ESCOLA MEDEA", "100.65.10.57"), "IP declarado deve passar")
    check(camera_allowlist.is_allowed("escola medea", "100.65.8.21"), "CIDR declarado deve passar (site case-insensitive)")
    check(not camera_allowlist.is_allowed("ESCOLA MEDEA", "100.65.10.99"), "IP nao declarado deve ser barrado")
    print("  ok: so passa o que foi declarado")


def caso_varredura_respeita(scan_service, ScanRequest, load_inventory_json) -> None:
    original = scan_service.subprocess.run
    scan_service.subprocess.run = _fake_scan_returning([
        {"ip": "100.65.10.57", "mac": "aa:aa:aa:aa:aa:01", "status": "online", "local": "ESCOLA MEDEA"},
        {"ip": "100.65.10.58", "mac": "aa:aa:aa:aa:aa:02", "status": "online", "local": "ESCOLA MEDEA"},
        {"ip": "100.65.10.99", "mac": "aa:aa:aa:aa:aa:03", "status": "online", "local": "ESCOLA MEDEA"},
        {"ip": "100.65.10.250", "mac": "aa:aa:aa:aa:aa:04", "status": "online", "local": "ESCOLA MEDEA"},
    ])
    try:
        result = scan_service.run_http_scan(
            ScanRequest(
                alvo="100.65.10.0/24",
                usuario="admin",
                senha="senha",
                local="ESCOLA MEDEA",
                inventory_mode="basic",
                capture_snapshot=False,
                excel=False,
            )
        )
    finally:
        scan_service.subprocess.run = original

    rows = load_inventory_json(mode="basic") or []
    ips = sorted(str(r.get("ip") or "") for r in rows)
    check(ips == ["100.65.10.57", "100.65.10.58"], f"so os autorizados deviam entrar, veio: {ips}")
    check(result.get("blocked_allowlist_count") == 2, f"deveria barrar 2: {result.get('blocked_allowlist_count')}")
    print("  ok: varredura de /24 achou 4, cadastrou so os 2 autorizados")


def caso_remover_da_lista(camera_allowlist) -> None:
    camera_allowlist.remove_entries("ESCOLA MEDEA", ["100.65.10.58"])
    check(not camera_allowlist.is_allowed("ESCOLA MEDEA", "100.65.10.58"), "IP removido nao pode mais passar")
    check(camera_allowlist.is_allowed("ESCOLA MEDEA", "100.65.10.57"), "os outros continuam valendo")
    camera_allowlist.set_enforced("ESCOLA MEDEA", False)
    check(camera_allowlist.is_allowed("ESCOLA MEDEA", "100.65.10.99"), "com estrito desligado, tudo passa de novo")
    camera_allowlist.set_enforced("ESCOLA MEDEA", True)
    print("  ok: remover IP e desligar/ligar o modo estrito funcionam")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-allowlist-"))
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.models.requests import ScanRequest
        from app.services.inventory_json import load_inventory_json
        from app.services import camera_allowlist, scan_service

        token = set_current_tenant_slug("rads")
        try:
            caso_normaliza(camera_allowlist)
            caso_site_sem_lista_nao_muda(camera_allowlist)
            caso_estrito(camera_allowlist)
            caso_varredura_respeita(scan_service, ScanRequest, load_inventory_json)
            caso_remover_da_lista(camera_allowlist)
        finally:
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK allowlist: o inventario obedece a lista do usuario")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
