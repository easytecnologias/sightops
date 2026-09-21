#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
from pathlib import Path
from urllib.parse import unquote
import base64
import io
import os

import pandas as pd
import requests
from PIL import Image
import xlsxwriter
from dotenv import load_dotenv


COL_ORDER = [
    "ip",
    "mac",
    "fabricante",
    "modelo",
    "titulo",
    "status",

    # CAMPOS GPON / OLT (ANTES DE snapshot_url e thumb_url)
    "pon",
    "onu_id",
    "onu_name",
    "onu_serial",
    "onu_model",
    "olt_ip",
    "olt_name",
    "vlan",

    # CAMPOS DE IMAGEM
    "snapshot_url",
    "thumb_url",
]

# ---------------- Leitura dos links ----------------
def load_links(path: Path) -> pd.DataFrame:
    """Lê arquivo de links (2 colunas: ip,url  |  3 colunas: ip,snapshot_url,thumb_url). Decodifica URLs com unquote()."""
    if not path or not path.exists():
        return pd.DataFrame(columns=["ip", "snapshot_url", "thumb_url"])
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return pd.DataFrame(columns=["ip", "snapshot_url", "thumb_url"])
    for sep in [",", ";", "\t", "|"]:
        try:
            df = pd.read_csv(path, sep=sep, header=None, dtype=str, engine="python")
            if df.shape[1] == 2:
                df.columns = ["ip", "snapshot_url"]
                df["thumb_url"] = ""
            elif df.shape[1] >= 3:
                df = df.iloc[:, :3]
                df.columns = ["ip", "snapshot_url", "thumb_url"]
            else:
                continue
            df = df.fillna("").astype(str)
            df = df.apply(lambda col: col.str.strip())
            for col in ["snapshot_url", "thumb_url"]:
                df[col] = df[col].apply(lambda s: unquote(s) if "%" in s else s)
            df = df.drop_duplicates(subset=["ip"], keep="last")
            return df[["ip", "snapshot_url", "thumb_url"]]
        except Exception:
            continue
    return pd.DataFrame(columns=["ip", "snapshot_url", "thumb_url"])


# ---------------- Organização das colunas ----------------
def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for c in df.columns:
        lc = c.lower().strip().lstrip("_")
        if lc in COL_ORDER:
            rename_map[c] = lc
    if rename_map:
        df = df.rename(columns=rename_map)
    for c in COL_ORDER:
        if c not in df.columns:
            df[c] = ""
    return df[COL_ORDER]


# ---------------- Geração do Excel ----------------
def write_excel(df: pd.DataFrame, xlsx_path: Path):
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
        sheet_name = "inventario"
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        wb = writer.book
        ws = writer.sheets[sheet_name]

        ws.freeze_panes(1, 0)  # congela cabeçalho

        # larguras
        widths = {
            "ip": 13, "mac": 18, "modelo": 16, "titulo": 28,
            "snapshot_path": 36, "status": 10, "snapshot_url": 46, "thumb_url": 46
        }
        for idx, col in enumerate(df.columns):
            ws.set_column(idx, idx, widths.get(col, 18))

        # cria tabela com estilo
        last_row = len(df) + 1
        last_col = len(df.columns)
        last_col_letter = xlsxwriter.utility.xl_col_to_name(last_col - 1)
        table_range = f"A1:{last_col_letter}{last_row}"
        ws.add_table(table_range, {
            "style": "Table Style Medium 9",
            "columns": [{"header": col} for col in df.columns]
        })

        # cores de status
        fmt_green = wb.add_format({"font_color": "#008000"})
        fmt_red = wb.add_format({"font_color": "#C00000"})
        status_col = df.columns.get_loc("status")
        ws.conditional_format(1, status_col, len(df), status_col,
                              {"type": "text", "criteria": "containing", "value": "online", "format": fmt_green})
        ws.conditional_format(1, status_col, len(df), status_col,
                              {"type": "text", "criteria": "containing", "value": "offline", "format": fmt_red})

        # links clicáveis
        for url_col in ["snapshot_url", "thumb_url"]:
            cidx = df.columns.get_loc(url_col)
            for r in range(len(df)):
                url = str(df.iloc[r, cidx]).strip()
                if url and (url.startswith("http://") or url.startswith("https://")):
                    ws.write_url(r + 1, cidx, url, string=url)


# ---------------- Ordenação por IP ----------------
def ip_sort(df: pd.DataFrame) -> pd.DataFrame:
    import ipaddress
    df = df.assign(_ipnum=df["ip"].apply(lambda x: int(ipaddress.ip_address(x.strip())) if str(x).strip() else 0))
    df = df.sort_values(by="_ipnum", ascending=True, ignore_index=True).drop(columns="_ipnum")
    return df


# ---------------- Funções auxiliares de imagem ----------------
def _pil_thumbnail_bytes(src_path: Path, width: int = 360) -> bytes:
    im = Image.open(src_path).convert("RGB")
    w, h = im.size
    if w > width:
        new_h = int(h * (width / float(w)))
        im = im.resize((width, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _imgbb_upload(image_bytes: bytes, api_key: str, name_hint: str = "") -> str:
    """Envia bytes ao ImgBB e retorna o 'display_url'."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": api_key, "image": b64, "name": name_hint[:100]}
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return data.get("display_url") or data.get("url") or ""


# ---------------- Geração de thumbs ----------------
def fill_thumbs_with_imgbb(df: pd.DataFrame, width: int = 360) -> pd.DataFrame:
    """
    Procura automaticamente as imagens em output/snapshot/
    usando o IP como nome do arquivo. Se encontrar, gera e
    envia a miniatura real para o ImgBB.
    """
    load_dotenv()
    api_key = os.getenv("IMGBB_API_KEY", "").strip()
    if not api_key:
        print("[WARN] IMGBB_API_KEY não encontrado no .env — pulando geração de thumbs.")
        return df

    base_dir = Path.cwd() / "saida" / "snapshot"


    exts = [".jpg", ".jpeg", ".png"]
    filled, missing = 0, []

    for idx, row in df.iterrows():
        ip = str(row.get("ip", "")).strip()
        if not ip:
            continue
        if str(row.get("thumb_url", "")).strip():
            continue  # já tem thumb

        # procura automaticamente o arquivo por IP
        found = None
        for ext in exts:
            candidate = base_dir / f"{ip}{ext}"
            if candidate.exists():
                found = candidate
                break

        if not found:
            missing.append(ip)
            continue

        try:
            img_bytes = _pil_thumbnail_bytes(found, width=width)
            hint = ip.replace(".", "-")
            thumb_link = _imgbb_upload(img_bytes, api_key, name_hint=hint)
            if thumb_link:
                df.at[idx, "thumb_url"] = thumb_link
                filled += 1
        except Exception as e:
            print(f"[WARN] Falhou thumb {ip}: {e}")

    print(f"[INFO] thumbs geradas/enviadas: {filled}")
    if missing:
        preview = ", ".join(missing)
        print(f"[WARN] snapshot não encontrados ({len(missing)}): {preview}")
    return df


# ---------------- Main ----------------
def main():
    ap = argparse.ArgumentParser(description="Atualiza CSV (URLs) e gera XLSX formatado. Opcional: cria thumbs reais via ImgBB.")
    ap.add_argument("--csv", required=True, help="Caminho do CSV de inventário (atualizado in-place).")
    ap.add_argument("--xlsx", default=None, help="Caminho do XLSX de saída (default: cam-inventory.xlsx ao lado do CSV).")
    ap.add_argument("--links", default=None, help="Arquivo com IP e URL (2 ou 3 colunas). URLs podem estar percent-encodadas.")
    ap.add_argument("--make-thumbs", action="store_true", help="Gera miniaturas reais (upload no ImgBB) usando IMGBB_API_KEY.")
    ap.add_argument("--thumb-width", type=int, default=360, help="Largura da miniatura (padrão: 360).")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV não encontrado: {csv_path}")

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df = ensure_columns(df)

    # aplica links
    if args.links:
        links_df = load_links(Path(args.links))
        if not links_df.empty:
            df = df.merge(links_df, on="ip", how="left", suffixes=("", "__lnk"))
            for col in ["snapshot_url", "thumb_url"]:
                link_col = f"{col}__lnk"
                if link_col in df.columns:
                    df[col] = df[col].where(df[col].astype(str).str.len() > 0, df[link_col].fillna(""))
                    df = df.drop(columns=[link_col])

    # gera thumbs se solicitado
    if args.make_thumbs:
        df = fill_thumbs_with_imgbb(df, width=args.thumb_width)

    # fallback: thumb = snapshot se ainda vazia
    df["thumb_url"] = df["thumb_url"].where(
        df["thumb_url"].astype(str).str.len() > 0,
        df["snapshot_url"]
    )

    # ordena e salva
    df = ip_sort(df)
    df.to_csv(csv_path, index=False)

    # gera XLSX
    xlsx_path = Path(args.xlsx) if args.xlsx else csv_path.with_name("cam-inventory.xlsx")
    write_excel(df, xlsx_path)

    print(f"[OK] CSV atualizado: {csv_path}")
    print(f"[OK] XLSX gerado:   {xlsx_path}")


if __name__ == "__main__":
    main()
