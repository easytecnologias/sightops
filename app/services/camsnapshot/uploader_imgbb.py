# Simple ImgBB uploader for cam-snapshot-web
# Re-implementado para compatibilizar com hooks.after_snapshot
# Assinatura esperada: upload_to_imgbb(images: List[str], api_key: str, name_prefix: str = "cam", report_path: str | None = None) -> List[Dict[str, Any]]

from __future__ import annotations
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import json
import re
import time

import requests

def _normalize_api_key(raw: str) -> str:
    key = (raw or "").strip().strip('"').strip()
    return key

def _extract_urls(payload: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    data = payload.get("data") or {}
    # display url
    url = data.get("display_url") or data.get("url")
    thumb_url = None
    thumb = data.get("thumb") or data.get("medium")
    if isinstance(thumb, dict):
        thumb_url = thumb.get("url")
    if not thumb_url:
        thumb_url = url
    return url, thumb_url

def _upload_single(image: Path, api_key: str, name: Optional[str] = None, timeout: int = 12) -> Dict[str, Any]:
    if not image.is_file():
        raise FileNotFoundError(image)
    with image.open("rb") as f:
        raw = f.read()
    payload = {"key": api_key}
    if name:
        payload["name"] = name
    files = {"image": raw}
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data=payload,
        files=files,
        timeout=timeout,
    )
    data: Dict[str, Any] = {}
    try:
        data = resp.json()
    except Exception:
        data = {}
    if resp.status_code >= 400:
        err_txt = ""
        if isinstance(data, dict):
            err_node = data.get("error") or {}
            if isinstance(err_node, dict):
                err_txt = str(err_node.get("message") or err_node.get("code") or "").strip()
            if not err_txt:
                err_txt = str(data.get("status") or "").strip()
        if not err_txt:
            err_txt = (resp.text or "").strip()[:220]
        raise RuntimeError(f"HTTP {resp.status_code} - {err_txt or 'erro no upload'}")
    url, thumb_url = _extract_urls(data)
    if not url:
        raise RuntimeError(f"Resposta inesperada do ImgBB para {image}: {data!r}")
    return {
        "file": str(image),
        "url": url,
        "thumbnail_url": thumb_url or url,
    }


def _sanitize_upload_name(raw: str) -> str:
    s = str(raw or "").strip()
    s = re.sub(r"[^0-9A-Za-z._-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-._")
    return s[:100]


def _name_from_image_path(image: Path, idx: int, name_prefix: str) -> str:
    stem = image.stem.strip()
    # Formato atual de snapshot por IP no projeto: 10_10_10_21.jpg
    if re.fullmatch(r"\d{1,3}(?:_\d{1,3}){3}", stem):
        return stem.replace("_", ".")
    # Já está em IP com pontos
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", stem):
        return stem
    safe = _sanitize_upload_name(stem)
    if safe:
        return safe
    return f"{name_prefix}-{idx:04d}"

def upload_to_imgbb(
    images: List[str],
    api_key: str,
    name_prefix: str = "cam",
    report_path: Optional[str] = None,
    name_map: Optional[Dict[str, str]] = None,
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """Envia uma lista de snapshot para o ImgBB.

    Retorna lista de dicts: {file, url, thumbnail_url}.
    Compatível com hooks.after_snapshot.
    """
    api_key = _normalize_api_key(api_key)
    if not api_key:
        raise RuntimeError("IMGBB_API_KEY vazio ao chamar upload_to_imgbb().")

    paths = [Path(p) for p in images]
    uploads: List[Dict[str, Any]] = []
    errors: List[str] = []
    total = len(paths)
    for idx, img in enumerate(paths, 1):
        custom_name = ""
        if isinstance(name_map, dict):
            custom_name = str(name_map.get(str(img), "") or "").strip()
        name = _sanitize_upload_name(custom_name) if custom_name else _name_from_image_path(img, idx, name_prefix)
        try:
            timeout = int(os.getenv("IMGBB_UPLOAD_TIMEOUT", "12") or "12")
            info = _upload_single(img, api_key=api_key, name=name, timeout=max(5, min(timeout, 30)))
            print(f"[ImgBB] {idx}/{total} OK: {img.name}")
            uploads.append(info)
            if callable(progress_cb):
                try:
                    progress_cb(
                        {
                            "idx": idx,
                            "total": total,
                            "file": str(img),
                            "ok": True,
                            "url": str(info.get("url") or ""),
                            "error": "",
                        }
                    )
                except Exception:
                    pass
            # Evita rajadas muito agressivas na API (reduz erros intermitentes).
            time.sleep(0.12)
        except Exception as e:
            msg = str(e)
            errors.append(f"{img.name}: {msg}")
            print(f"[ImgBB] ERRO em {img}: {msg}")
            if callable(progress_cb):
                try:
                    progress_cb(
                        {
                            "idx": idx,
                            "total": total,
                            "file": str(img),
                            "ok": False,
                            "url": "",
                            "error": msg,
                        }
                    )
                except Exception:
                    pass
            if "rate limit" in msg.lower():
                print("[ImgBB] Interrompido: limite de taxa da API atingido.")
                break

    if not uploads and errors:
        raise RuntimeError("; ".join(errors[:3]))

    # Relatório opcional em JSONL simples
    if report_path:
        try:
            rp = Path(report_path)
            rp.parent.mkdir(parents=True, exist_ok=True)
            with rp.open("w", encoding="utf-8") as f:
                for u in uploads:
                    f.write(json.dumps(u, ensure_ascii=False) + "\n")
            print(f"[ImgBB] Relatório salvo em {rp} ({len(uploads)} itens).")
        except Exception as e:
            print(f"[ImgBB] Aviso: falha ao gravar relatório {report_path}: {e}")

    return uploads
