from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, List

from fastapi import HTTPException

from app.core.paths import BASE_DIR, SAIDA_DIR, TOOLS_DIR, ensure_dirs
from app.models.requests import RescanSingleIPRequest
from app.services.inventory_json import load_inventory_json, save_inventory_json, normalize_row, dedup_cam_inventory
from app.services.camsnapshot.device_info import get_snapshot


def rescan_single_ip(req: RescanSingleIPRequest) -> Dict[str, Any]:
    ensure_dirs()
    ip = (req.ip or "").strip()
    inventory_mode = str(getattr(req, "inventory_mode", "olt") or "olt").strip().lower()
    if not ip:
        raise HTTPException(400, "IP é obrigatório.")

    SAIDA_DIR.mkdir(parents=True, exist_ok=True)

    # Tambem identifica a primeira camera de um inventario durante a
    # Implantacao. Lista vazia e valida; a camera consultada vira o primeiro
    # registro sem exigir uma varredura anterior.
    inventory = load_inventory_json(mode=inventory_mode) or []

    tmp_json = SAIDA_DIR / f"rescan_{ip.replace('.', '_')}.tmp.json"
    script = TOOLS_DIR / "inventory_dry.py"
    if not script.exists():
        raise HTTPException(500, "inventory_dry.py não encontrado em tools/")

    cmd = [
        sys.executable,
        str(script),
        "--alvo",
        ip,
        "--usuario",
        req.usuario or "admin",
        "--senha",
        req.senha or "admin",
        "--out",
        str(tmp_json),
    ]

    try:
        proc = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, check=False)
    except Exception as e:
        raise HTTPException(500, f"Erro ao chamar inventory_dry.py: {e}")

    if proc.returncode != 0:
        return {
            "ok": False,
            "success": False,
            "return_code": proc.returncode,
            "cmd": " ".join(cmd),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "inventory": inventory,
        }

    new_rows: List[Dict[str, Any]] = []
    try:
        if tmp_json.exists():
            with tmp_json.open("r", encoding="utf-8") as f:
                new_rows = json.load(f)
    except Exception:
        new_rows = []

    if not isinstance(new_rows, list) or not new_rows:
        return {
            "ok": False,
            "success": False,
            "message": "inventory_dry.py rodou, mas não retornou dados para este IP.",
            "cmd": " ".join(cmd),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "inventory": inventory,
        }

    new_cam = normalize_row(new_rows[0])
    new_ip = (new_cam.get("ip") or "").strip()
    if new_ip and new_ip != ip:
        ip = new_ip

    updated = False
    for row in inventory:
        rip = (row.get("ip") or "").strip()
        if rip == ip:
            for k, v in new_cam.items():
                if v is None:
                    continue
                if isinstance(v, str) and v.strip() == "":
                    continue
                row[k] = v
            updated = True
            break

    if not updated:
        inventory.append(new_cam)

    save_inventory_json(inventory, mode=inventory_mode)

    # dedup final
    try:
        dedup_cam_inventory(mode=inventory_mode)
    except Exception as e:
        print(f"[dedup][erro][rescan-single-ip] {e}", flush=True)

    inventory2 = load_inventory_json(mode=inventory_mode)

    snap_err: str | None = None
    if getattr(req, "capture_snapshot", True):
        try:
            snaps_dir = SAIDA_DIR / "snapshot"
            snaps_dir.mkdir(parents=True, exist_ok=True)

            out_path = get_snapshot(ip, req.usuario or "admin", req.senha or "admin", output_dir=str(snaps_dir))
            if out_path:
                for row in inventory2:
                    if (row.get("ip") or "").strip() == ip:
                        row["snapshot_path"] = str(out_path)
                        break
                save_inventory_json(inventory2, mode=inventory_mode)
                try:
                    dedup_cam_inventory(mode=inventory_mode)
                except Exception as e:
                    print(f"[dedup][erro][rescan-single-ip][snapshot] {e}", flush=True)
                inventory2 = load_inventory_json(mode=inventory_mode)
            else:
                snap_err = "snapshot não foi gerado (get_snapshot retornou vazio)"
        except Exception as e:
            snap_err = f"erro ao capturar snapshot: {e}"

    try:
        if tmp_json.exists():
            tmp_json.unlink()
    except Exception:
        pass

    return {
        "ok": True,
        "success": True,
        "return_code": 0,
        "cmd": " ".join(cmd),
        "stdout": proc.stdout,
        "stderr": (proc.stderr or "") + ("\n" + snap_err if snap_err else ""),
        "inventory": inventory2,
    }
