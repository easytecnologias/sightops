#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_with_gpon.py (JSON-only OLT)

Enriquece o cam-inventory.json com as informações vindas da OLT (arquivo olt-cpe-macs.json):
- pon
- onu_id
- onu_name
- onu_serial
- onu_model
- olt_ip
- olt_name
- vlan

Regras (MESMA LÓGICA DO ESTÁVEL):
- Não apaga campos existentes no JSON
- Preenche campos vazios
- Use --force para sobrescrever também campos já preenchidos

Compatibilidade:
- Inventário pode ser lista [] (legado) OU payload {meta, items}
- OLT pode ser JSON:
  - {meta, cpes}
  - {meta, items}
  - lista

Uso:
  python tools/enrich_with_gpon.py --inventory saida/cam-inventory.json --olt-macs saida/olt-cpe-macs.json
  python tools/enrich_with_gpon.py --inventory saida/cam-inventory.json --olt-macs saida/olt-cpe-macs.json --out saida/cam-inventory.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

GPON_COLS = [
    "pon",
    "onu_id",
    "onu_name",
    "onu_serial",
    "onu_model",
    "olt_ip",
    "olt_name",
    "vlan",
]


def _norm_mac(v: Any) -> str:
    s = str(v or "").strip().lower()
    s = s.replace("-", ":").replace(".", ":")
    while "::" in s:
        s = s.replace("::", ":")
    return s


def _unwrap_inventory(data: Any) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Retorna (kind, meta, rows)
      kind = "list" ou "payload"
    """
    if isinstance(data, list):
        return ("list", {}, [r for r in data if isinstance(r, dict)])

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        rows = [r for r in data.get("items") if isinstance(r, dict)]
        return ("payload", meta, rows)

    return ("list", {}, [])


def _wrap_inventory(kind: str, meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> Any:
    if kind == "payload":
        return {"meta": meta or {}, "items": rows or []}
    return rows or []


def load_inventory(path: Path) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    if not path.exists():
        return ("list", {}, [])
    data = json.loads(path.read_text(encoding="utf-8"))
    return _unwrap_inventory(data)


def save_inventory(path: Path, kind: str, meta: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = _wrap_inventory(kind, meta, rows)
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _extract_olt_rows(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        if isinstance(obj.get("cpes"), list):
            return [x for x in obj["cpes"] if isinstance(x, dict)]
        if isinstance(obj.get("items"), list):
            return [x for x in obj["items"] if isinstance(x, dict)]
    return []


def load_olt_map(path: Path) -> Dict[str, Dict[str, str]]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    rows = _extract_olt_rows(obj)

    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        mac = _norm_mac(row.get("cpe_mac") or row.get("mac") or row.get("MAC"))
        if not mac:
            continue
        out[mac] = {str(k): ("" if row.get(k) is None else str(row.get(k))) for k in row.keys()}
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Enriquece inventário JSON com dados GPON/OLT (OLT JSON).")
    p.add_argument("--inventory", required=True, help="cam-inventory.json")
    p.add_argument("--olt-macs", required=True, help="olt-cpe-macs.json")
    p.add_argument("--out", default="", help="JSON de saída (opcional). Se vazio, sobrescreve o --inventory")
    p.add_argument("--force", action="store_true", help="Sobrescreve campos existentes também")
    args = p.parse_args()

    inv_path = Path(args.inventory)
    olt_path = Path(args.olt_macs)
    out_path = Path(args.out) if str(args.out).strip() else inv_path

    if not inv_path.exists():
        print(f"[ERRO] Inventário não encontrado: {inv_path}")
        return
    if not olt_path.exists():
        print(f"[ERRO] Arquivo da OLT não encontrado: {olt_path}")
        return

    kind, meta, inv_rows = load_inventory(inv_path)
    olt_map = load_olt_map(olt_path)

    changed = 0

    for cam in inv_rows:
        mac = _norm_mac(cam.get("mac") or cam.get("MAC"))
        if not mac:
            continue
        g = olt_map.get(mac)
        if not g:
            continue

        def pick(*keys: str) -> str:
            for k in keys:
                v = (g.get(k) or "").strip()
                if v:
                    return v
            return ""

        updates = {
            "pon": pick("pon", "PON"),
            "onu_id": pick("onu_id", "onuId", "ONU_ID", "onu"),
            "onu_name": pick("onu_name", "onuName", "ONU_NAME"),
            "onu_serial": pick("onu_serial", "serial", "ONU_SERIAL"),
            "onu_model": pick("onu_model", "model", "ONU_MODEL"),
            "olt_ip": pick("olt_ip", "OLT_IP"),
            "olt_name": pick("olt_name", "OLT_NAME"),
            "vlan": pick("vlan", "VLAN"),
        }

        cam_changed = False
        for k, v in updates.items():
            if not v:
                continue
            if args.force or str(cam.get(k, "")).strip() == "":
                if cam.get(k) != v:
                    cam[k] = v
                    cam_changed = True

        if cam_changed:
            changed += 1

        for k in GPON_COLS:
            cam.setdefault(k, cam.get(k, ""))

    save_inventory(out_path, kind, meta, inv_rows)
    print(f"[OK] GPON/OLT aplicado em {changed} câmera(s). Saída: {out_path}")


if __name__ == "__main__":
    main()
