#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
import pandas as pd
from urllib.parse import unquote

def load_links(links_path: Path) -> dict:
    mapping = {}
    if not links_path.exists():
        print(f"[WARN] Arquivo de links não encontrado: {links_path}")
        return mapping
    with links_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "," not in line:
                continue
            ip, url_enc = line.split(",", 1)
            ip = ip.strip()
            url_enc = url_enc.strip()
            if not ip or not url_enc:
                continue
            # decodifica a URL (vem url-encoded no links_imgbb.txt)
            url = unquote(url_enc)
            mapping[ip] = url
    print(f"[INFO] Links carregados do ImgBB: {len(mapping)}")
    return mapping

def main() -> None:
    p = argparse.ArgumentParser(
        description="Anexa URLs do ImgBB ao inventário (snapshot_url e thumb_url)."
    )
    p.add_argument("--csv", required=True, help="Caminho do cam-inventory.csv")
    p.add_argument("--links", required=True, help="Caminho do links_imgbb.txt")
    p.add_argument("--out", required=True, help="CSV de saída (pode ser o mesmo do --csv)")
    args = p.parse_args()

    csv_path = Path(args.csv)
    links_path = Path(args.links)
    out_path = Path(args.out)

    if not csv_path.exists():
        print(f"[ERRO] CSV não encontrado: {csv_path}")
        return

    df = pd.read_csv(csv_path, encoding="utf-8")
    mapping = load_links(links_path)

    # garante colunas
    if "snapshot_url" not in df.columns:
        df["snapshot_url"] = ""
    if "thumb_url" not in df.columns:
        df["thumb_url"] = ""

    # aplica mapeamento por IP
    def apply_url(row):
        ip = str(row.get("ip", "")).strip()
        url = mapping.get(ip)
        if url:
            row["snapshot_url"] = url
            # por enquanto usamos a mesma URL como "thumb"
            row["thumb_url"] = url
        return row

    df = df.apply(apply_url, axis=1)

    df.to_csv(out_path, index=False, encoding="utf-8")
    print(f"[OK] CSV atualizado com URLs do ImgBB: {out_path}")

if __name__ == "__main__":
    main()
