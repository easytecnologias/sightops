# camsnapshot/uploader_imgbb.py
from __future__ import annotations
import os, base64, json
from pathlib import Path
from typing import Iterable, List, Union

# Opcional: carregar .env se existir
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

import requests  # requer 'requests' no requirements.txt

IMGBB_ENDPOINT = "https://api.imgbb.com/1/upload"

def _get_api_key() -> str:
    api = os.getenv("IMGBB_API_KEY", "").strip()
    if not api:
        raise RuntimeError("IMGBB_API_KEY não definido. Informe no .env ou variável de ambiente.")
    return api

def _to_file_list(target: Union[str, Path, Iterable[Union[str, Path]]]) -> List[Path]:
    """Aceita pasta, arquivo ou lista e retorna apenas .jpg existentes."""
    paths: List[Path] = []
    if isinstance(target, (str, Path)):
        p = Path(target)
        if p.is_dir():
            paths = sorted([x for x in p.glob("*.jpg") if x.is_file()])
        elif p.is_file():
            paths = [p]
        else:
            raise FileNotFoundError(f"Alvo não encontrado: {p}")
    else:
        for item in target:
            q = Path(item)
            if q.is_file() and q.suffix.lower() == ".jpg":
                paths.append(q)
    if not paths:
        raise FileNotFoundError("Nenhum arquivo .jpg encontrado no alvo informado.")
    return paths

def _upload_one(api_key: str, jpg_path: Path) -> str:
    """Faz upload de um JPG ao ImgBB e retorna a display_url."""
    with jpg_path.open("rb") as f:
        img_b64 = base64.b64encode(f.read())
    data = {"key": api_key, "image": img_b64}
    resp = requests.post(IMGBB_ENDPOINT, data=data, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"Falha ImgBB em {jpg_path.name}: {json.dumps(payload)[:200]}")
    return payload["data"]["display_url"]

def upload_folder(target: Union[str, Path, Iterable[Union[str, Path]]]) -> list:
    """
    Envia JPGs para ImgBB.
    target: pasta com .jpg, um arquivo .jpg, ou lista de caminhos.
    Retorna lista de URLs.
    """
    api_key = _get_api_key()
    files = _to_file_list(target)
    urls: List[str] = []
    print(f"[ImgBB] Enviando {len(files)} arquivo(s)...")

    for i, jpg in enumerate(files, 1):
        try:
            url = _upload_one(api_key, jpg)
            print(f"[ImgBB] {i}/{len(files)} OK: {jpg.name} -> {url}")
            urls.append(url)
        except Exception as e:
            print(f"[ImgBB] ERRO em {jpg.name}: {e}")

        # salvar links e atualizar CSV de inventário, se existir
    try:
        out_dir = Path(".\\saida")  # força a pasta de inventário
        links_path = out_dir / "links_imgbb.txt"
        links_path.write_text("\n".join(urls), encoding="utf-8")
        print(f"[ImgBB] Links salvos em: {links_path} ({len(urls)} link(s))")

        # Atualizar CSV (adicionar coluna 'snapshot_url')
        csv_path = out_dir / "cam-inventory.csv"
        if csv_path.exists():
            import pandas as pd
            df = pd.read_csv(csv_path, encoding="utf-8")
            jpgs = sorted([p for p in Path("output/snapshot").glob("*.jpg")])
            # associar IP a link
            mapping = {}
            for link, img in zip(urls, jpgs):
                ip = img.stem.replace("_", ".")
                mapping[ip] = link
            if "snapshot_url" not in df.columns:
                df["snapshot_url"] = ""
            for i, row in df.iterrows():
                ip = str(row["ip"]).strip()
                if ip in mapping:
                    df.at[i, "snapshot_url"] = mapping[ip]
            df.to_csv(csv_path, index=False, encoding="utf-8")
            print(f"[ImgBB] CSV atualizado com links: {csv_path}")
    except Exception as e:
        print(f"[ImgBB] Aviso: não foi possível salvar/atualizar CSV: {e}")

