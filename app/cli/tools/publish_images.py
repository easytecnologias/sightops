#!/usr/bin/env python3
"""Publica snapshot no ImgBB e atualiza o CSV + links_imgbb.txt.

Fluxo:
  1. Lê IMGBB_API_KEY do .env
  2. Varre o diretório de snapshot (por default: output/snapshot)
  3. Para cada arquivo X.jpg/.jpeg/.png:
       - envia ao ImgBB
       - associa o IP = nome do arquivo sem extensão
  4. Atualiza o CSV (cam-inventory.csv) com colunas:
       - snapshot_url
       - thumb_url
  5. Gera links_imgbb.txt no mesmo diretório do CSV:
       ip,url
"""
from __future__ import annotations
import argparse, os, sys, csv, base64, json
from pathlib import Path
from typing import Dict, Any

import requests
from dotenv import load_dotenv

def load_api_key() -> str:
    load_dotenv()
    key = os.getenv("IMGBB_API_KEY", "").strip().strip('"')
    if not key:
        print("[ImgBB] IMGBB_API_KEY não encontrado (.env ou ambiente).", flush=True)
    return key

def list_snapshot(dir_path: str) -> list[Path]:
    p = Path(dir_path)
    if not p.exists():
        print(f"[Publish] Diretório de snapshot não encontrado: {p}", flush=True)
        return []
    files: list[Path] = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        files.extend(p.glob(ext))
    files = sorted([f for f in files if f.is_file()])
    print(f"[Publish] Encontrados {len(files)} arquivo(s) em '{p}'.", flush=True)
    return files

def upload_one(path: Path, api_key: str, timeout: int = 60) -> Dict[str, Any]:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    data = {
        "key": api_key,
        "image": b64,
        "name": path.stem[:100],
    }
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data=data,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json() or {}
    data = payload.get("data") or {}
    url = data.get("display_url") or data.get("url")
    thumb = None
    thumb_data = data.get("thumb") or data.get("medium")
    if isinstance(thumb_data, dict):
        thumb = thumb_data.get("url")
    if not thumb:
        thumb = url
    if not url:
        raise RuntimeError(f"Resposta inesperada do ImgBB para {path}: {payload!r}")
    return {
        "file": str(path),
        "url": url,
        "thumbnail_url": thumb or url,
    }

def update_inventory(inv_path: Path, ip_to_info: Dict[str, Dict[str, Any]]) -> None:
    """Atualiza inventário (JSON ou CSV) com snapshot_url e thumb_url."""
    if not inv_path.exists():
        print(f"[Publish] Inventário não encontrado para atualização: {inv_path}", flush=True)
        return

    if inv_path.suffix.lower() == ".json":
        print(f"[Publish] Atualizando JSON: {inv_path}", flush=True)
        try:
            data = json.loads(inv_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[Publish][ERRO] Falha ao ler JSON: {e}", flush=True)
            return
        if not isinstance(data, list):
            print("[Publish][ERRO] JSON inválido (esperado lista).", flush=True)
            return

        changed = 0
        for row in data:
            if not isinstance(row, dict):
                continue
            ip = str(row.get("ip") or row.get("IP") or "").strip()
            if not ip:
                continue
            info = ip_to_info.get(ip)
            if not info:
                continue
            row["snapshot_url"] = info.get("url") or row.get("snapshot_url", "")
            row["thumb_url"] = info.get("thumbnail_url") or row.get("thumb_url", "")
            changed += 1

        tmp = inv_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(inv_path)
        print(f"[Publish] OK: {changed} linha(s) atualizadas no JSON.", flush=True)
        return

    # fallback CSV (legado)
    print(f"[Publish] Atualizando CSV: {inv_path}", flush=True)
    with inv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("[Publish] CSV vazio, nada a atualizar.", flush=True)
        return

    # garante colunas
    fieldnames = list(rows[0].keys())
    for col in ["snapshot_url", "thumb_url"]:
        if col not in fieldnames:
            fieldnames.append(col)

    changed = 0
    for r in rows:
        ip = (r.get("ip") or r.get("IP") or "").strip()
        if not ip:
            continue
        info = ip_to_info.get(ip)
        if not info:
            continue
        r["snapshot_url"] = info.get("url") or r.get("snapshot_url", "")
        r["thumb_url"] = info.get("thumbnail_url") or r.get("thumb_url", "")
        changed += 1

    tmp_csv = inv_path.with_suffix(".tmp.csv")
    with tmp_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    tmp_csv.replace(inv_path)
    print(f"[Publish] OK: {changed} linha(s) atualizadas no CSV.", flush=True)

def write_links(csv_dir: Path, ip_to_info: Dict[str, Dict[str, Any]]) -> None:
    if not ip_to_info:
        print("[Publish] Nenhum upload para gerar links_imgbb.json.", flush=True)
        return

    out_json = csv_dir / "links_imgbb.json"

    try:
        payload: Dict[str, Dict[str, Any]] = {}
        for ip, info in sorted(ip_to_info.items()):
            url = (info.get("url") or "").strip()
            if not url:
                continue

            payload[ip] = {
                "url": url,
                "thumb": (info.get("thumb") or info.get("thumb_url") or "").strip(),
                "delete_url": (info.get("delete_url") or info.get("delete") or "").strip(),
            }

        if not payload:
            print("[Publish] Nenhum URL válido para escrever em links_imgbb.json.", flush=True)
            return

        with out_json.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"[Publish] links_imgbb.json gerado com {len(payload)} item(ns) em {out_json}", flush=True)

    except Exception as e:
        print(f"[Publish] WARN: falha ao escrever links_imgbb.json: {e}", flush=True)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publica snapshot no ImgBB e atualiza inventário (JSON/CSV) + links_imgbb.txt."
    )
    parser.add_argument("--snapshot-dir", default="output/snapshot")
    parser.add_argument("--json", default="saida/cam-inventory.json")
    parser.add_argument("--csv", default="saida/cam-inventory.csv")  # legado (fallback)
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key:
        sys.exit(1)

    snaps = list_snapshot(args.snapshot_dir)
    if not snaps:
        print("[Publish] Nada para enviar. Verifique o diretório e extensões.", flush=True)
        sys.exit(2)

    ip_to_info: Dict[str, Dict[str, Any]] = {}
    total = len(snaps)
    for idx, img in enumerate(snaps, 1):
        ip = img.stem.strip()
        try:
            info = upload_one(img, api_key=api_key)
            ip_to_info[ip] = info
            print(f"[ImgBB] {idx}/{total} OK: {img.name}", flush=True)
        except Exception as e:
            print(f"[ImgBB] ERRO em {img}: {e}", flush=True)

    if not ip_to_info:
        print("[Publish] Nenhum upload concluído com sucesso.", flush=True)
        sys.exit(3)

    # prioridade: JSON (porque teu projeto agora é JSON)
    inv_path = Path(args.json) if args.json else Path(args.csv)
    update_inventory(inv_path, ip_to_info)

    out_dir = inv_path.parent if inv_path.parent.as_posix() != "" else Path(".")
    write_links(out_dir, ip_to_info)

    print("[Publish] Finalizado com sucesso.", flush=True)
    sys.exit(0)

if __name__ == "__main__":
    main()
