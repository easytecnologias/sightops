#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""json_to_xlsx.py

Gera XLSX a partir do cam-inventory.json (fonte única).

Uso:
  python tools/json_to_xlsx.py --json saida/cam-inventory.json --xlsx saida/cam-inventory.xlsx
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd

COL_ORDER = [
    "ip","mac","fabricante","modelo","titulo","status","ping","pon","onu_id","onu_name","onu_serial",
    "snapshot_url","thumb_url"
]

def main() -> None:
    ap = argparse.ArgumentParser(description="Gera XLSX a partir do inventário JSON.")
    ap.add_argument("--json", required=True, help="Caminho do cam-inventory.json")
    ap.add_argument("--xlsx", required=True, help="Caminho do XLSX de saída")
    args = ap.parse_args()

    jpath = Path(args.json)
    xpath = Path(args.xlsx)

    data = json.loads(jpath.read_text(encoding="utf-8")) if jpath.exists() else []
    if not isinstance(data, list):
        data = []
    df = pd.DataFrame([r for r in data if isinstance(r, dict)])

    # normaliza nomes de colunas comuns
    rename = {}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc == "ip": rename[c] = "ip"
        if lc == "mac": rename[c] = "mac"
        if lc == "manufacturer": rename[c] = "fabricante"
        if lc == "model": rename[c] = "modelo"
        if lc == "title": rename[c] = "titulo"
    if rename:
        df = df.rename(columns=rename)

    # garante ordem + inclui extras no fim
    cols = []
    for c in COL_ORDER:
        if c in df.columns:
            cols.append(c)
    for c in df.columns:
        if c not in cols:
            cols.append(c)
    df = df[cols]

    xpath.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(xpath, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="inventory")
        ws = writer.sheets["inventory"]
        # tabela estilizada
        nrows, ncols = df.shape[0] + 1, df.shape[1]
        ws.add_table(0, 0, nrows-1, ncols-1, {
            "name": "cam_inventory",
            "style": "Table Style Medium 9",
            "columns": [{"header": h} for h in df.columns.tolist()],
        })
        ws.freeze_panes(1, 0)
    print(f"[OK] XLSX gerado: {xpath}")

if __name__ == "__main__":
    main()
