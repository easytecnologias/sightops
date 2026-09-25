"""Regressao dos bugs reclamados em producao (inventario de cameras IP).

1. Camera apagada NAO pode voltar quando a varredura e de faixa/CIDR.
2. Varredura de um site novo NAO pode casar com a linha de outro site so
   porque o IP privado se repete (100.65.x existe em todo cliente).

Roda direto:
    python scripts/sightops_scan_respects_deleted_test.py
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


def caso_faixa_nao_ressuscita(scan_service, ScanRequest, load_inventory_json, add_ignored_rows, list_ignored) -> None:
    apagada = {
        "ip": "100.65.10.57",
        "mac": "c4:79:05:94:a1:b4",
        "local": "ESCOLA MEDEA",
        "site": "ESCOLA MEDEA",
        "olt_ip": "100.65.10.200",
        "pon": "0/1",
        "onu_id": "26",
    }
    add_ignored_rows([apagada], reason="apagado manualmente no inventario")

    original = scan_service.subprocess.run
    scan_service.subprocess.run = _fake_scan_returning([
        {
            "ip": "100.65.10.57",
            "mac": "c4:79:05:94:a1:b4",
            "status": "online",
            "titulo": "IPC2122LB-ASF28K-A",
            "local": "ESCOLA MEDEA",
        }
    ])
    try:
        result = scan_service.run_http_scan(
            ScanRequest(
                alvo="100.65.10.1-100.65.10.100",   # faixa, nao IP explicito
                usuario="admin",
                senha="senha",
                inventory_mode="basic",
                capture_snapshot=False,
                excel=False,
            )
        )
    finally:
        scan_service.subprocess.run = original

    rows = load_inventory_json(mode="basic") or []
    ips = [str(r.get("ip") or "") for r in rows]
    check("100.65.10.57" not in ips, f"camera apagada voltou no inventario: {ips}")
    check(result.get("blocked_ignored_count") == 1, f"deveria contar 1 bloqueada: {result.get('blocked_ignored_count')}")
    check(any(r["ip"] == "100.65.10.57" for r in list_ignored()), "IP deveria continuar na lista de ignorados")
    print("  ok: varredura de faixa nao ressuscita camera apagada")


def caso_site_novo_nao_rouba_ip(scan_service) -> None:
    antigo = [{
        "ip": "100.65.10.57",
        "mac": "c4:79:05:94:a1:b4",
        "titulo": "01 - ENTRADA ESC. MEDEA",
        "site": "ESCOLA MEDEA",
        "local": "ESCOLA MEDEA",
    }]
    novo = [{
        "ip": "100.65.10.57",
        "mac": "aa:bb:cc:dd:ee:ff",
        "titulo": "01 - PORTARIA",
        "site": "ESCOLA NOVA",
        "local": "ESCOLA NOVA",
    }]
    merged = scan_service._merge_inventory_rows(antigo, novo)
    check(len(merged) == 2, f"deveria virar 2 linhas (um site cada), veio {len(merged)}: {merged}")
    medea = [r for r in merged if str(r.get("site")) == "ESCOLA MEDEA"]
    check(len(medea) == 1, f"linha do site antigo sumiu: {merged}")
    check(medea[0].get("titulo") == "01 - ENTRADA ESC. MEDEA", f"titulo do site antigo foi sobrescrito: {medea[0]}")
    print("  ok: site novo nao rouba o IP nem o titulo do site antigo")


def caso_site_so_carimba_o_que_achou(scan_service) -> None:
    rows = [
        {"ip": "100.65.10.57", "local": ""},          # achada agora
        {"ip": "10.10.9.99", "local": ""},            # linha antiga de outro site
    ]
    out, changed = scan_service._apply_default_local(rows, "ESCOLA NOVA", only_ips={"100.65.10.57"})
    check(changed == 1, f"deveria carimbar so 1 linha, carimbou {changed}")
    check(out[0]["local"] == "ESCOLA NOVA", "linha achada deveria receber o site")
    check(out[1]["local"] == "", f"linha antiga nao podia receber o site novo: {out[1]}")
    print("  ok: site so e carimbado nas linhas desta varredura")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-scan-respects-"))
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.models.requests import ScanRequest
        from app.services.inventory_json import load_inventory_json
        from app.services.olt_ignore_list import add_ignored_rows, list_ignored
        from app.services import scan_service

        token = set_current_tenant_slug("rads")
        try:
            caso_faixa_nao_ressuscita(scan_service, ScanRequest, load_inventory_json, add_ignored_rows, list_ignored)
            caso_site_novo_nao_rouba_ip(scan_service)
            caso_site_so_carimba_o_que_achou(scan_service)
        finally:
            reset_current_tenant_slug(token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("OK scan respeita camera apagada e nao mistura sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
