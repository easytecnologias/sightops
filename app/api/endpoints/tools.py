from __future__ import annotations

import io
import json
import os
import socket
import shutil
import zipfile
import ipaddress
import asyncio
import re
import requests
import secrets
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import permissions
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.paths import (
    BASE_DIR,
    DATA_DIR,
    OUTPUT_DIR,
    SAIDA_DIR,
    INVENTORY_JSON_PATH,
    DVR_INVENTORY_JSON_PATH,
    NVR_INVENTORY_JSON_PATH,
    KMZ_INPUT_DIR,
    KMZ_IMPORTED_PATH,
    KMZ_IMPORTED_GEOJSON_PATH,
    KMZ_OUTPUT_DIR,
)
from app.services.kmz_ops import (
    apply_locations_to_inventory,
    generate_enriched_kmz,
    kmz_to_geojson,
    read_geojson_file,
)
from app.services.camsnapshot.device_info import probe_device
from app.services.db_store import (
    decorate_legacy_rows,
    legacy_rows_from_db,
    replace_ip_inventory_rows,
    replace_recorder_inventory_rows,
    clear_inventory_source,
    load_app_settings,
    save_app_settings,
)
from app.core.tenant_context import (
    get_current_tenant_slug,
    tenant_kmz_imported_geojson_path,
    tenant_kmz_imported_path,
    tenant_kmz_input_dir,
    tenant_kmz_output_dir,
    tenant_locations_apply_report_path,
    tenant_recorder_inventory_path,
    tenant_report_logo_path,
)
from app.services.scan_service import _upload_imgbb_for_inventory
from app.services.scan_service import _enrich_inventory_with_olt, _enrich_inventory_with_switch
from app.services.pdf_inventory_report import build_inventory_preview_image
# Gerador VETORIAL (ReportLab): PDF com texto selecionavel, em paisagem.
# O build_inventory_pdf_report de pdf_inventory_report.py desenha a pagina
# com PIL e salva JPEG -- era o relatorio 'em foto', sem fonte nenhuma.
from app.services.camera_pdf_report import build_inventory_pdf_report
from app.services.inventory_json import inventory_row_key, load_inventory_json, save_inventory_json

router = APIRouter(prefix="/api", tags=["tools"])


def _report_color(value: Any = "") -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw
    if re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        return "#" + raw
    return "#0b2242"

# -----------------
# small utilities
# -----------------

def _safe_rmtree(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    root = target_dir.resolve()
    for member in zf.infolist():
        name = str(member.filename or "").replace("\\", "/")
        if not name or name.startswith("/") or ".." in Path(name).parts:
            raise HTTPException(400, "Backup invalido: caminho inseguro dentro do ZIP.")
        dest = (target_dir / name).resolve()
        if root != dest and root not in dest.parents:
            raise HTTPException(400, "Backup invalido: caminho fora do diretorio temporario.")
    zf.extractall(target_dir)


def _safe_name(value: str, fallback: str = "mapa") -> str:
    stem = Path(str(value or fallback)).stem.strip() or fallback
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-")
    return stem[:80] or fallback


def _kmz_layers_dir() -> Path:
    base = tenant_kmz_input_dir().parent if get_current_tenant_slug() else KMZ_INPUT_DIR.parent
    p = base / "kmz_layers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _kmz_generated_layers_dir() -> Path:
    base = tenant_kmz_output_dir().parent if get_current_tenant_slug() else KMZ_OUTPUT_DIR.parent
    p = base / "kmz_generated_layers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _kmz_layer_paths(layer_id: str) -> tuple[Path, Path, Path]:
    safe_id = _safe_name(layer_id, "layer")
    base = _kmz_layers_dir()
    return base / f"{safe_id}.kmz", base / f"{safe_id}.geojson", base / f"{safe_id}.meta.json"


def _kmz_generated_layer_paths(layer_id: str) -> tuple[Path, Path, Path]:
    safe_id = _safe_name(layer_id, "layer")
    base = _kmz_generated_layers_dir()
    return base / f"{safe_id}.kmz", base / f"{safe_id}.geojson", base / f"{safe_id}.meta.json"


def _read_kmz_layer_meta(meta_path: Path) -> dict[str, Any]:
    try:
        if meta_path.exists():
            data = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _write_kmz_layer_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------ camada x site
# Camada KMZ nao tem site gravado: o site e o das cameras do inventario que
# casam com os pontos (nome = titulo, ou IP), o mais frequente -- a mesma conta
# do mapa (mapLayerSite), mas com o inventario COMPLETO do cliente; aqui valem
# TODOS os sites casados (camada mista so para quem acessa todos). Sem camera
# casada, pelo nome da camada. meta["sites"] (camada criada/importada por
# usuario restrito) vale sobre a conta. Quem tem restricao de site so ve a
# camada cujos sites sao todos dele; sem site descoberto, nao ve (na duvida,
# nao mostra -- mesma regra do filtrar_por_site).
_RE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _chave_site(valor: Any) -> str:
    import unicodedata

    s = unicodedata.normalize("NFD", str(valor or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().upper()


def _sites_liberados() -> Optional[set]:
    """Chaves dos sites da sessao; None = sem restricao."""
    sites = permissions.sites_da_sessao()
    return None if sites is None else {_chave_site(s) for s in sites if str(s or "").strip()}


def _indice_sites_inventario() -> Dict[str, Any]:
    nome: Dict[str, str] = {}
    ip: Dict[str, str] = {}
    for modo in ("basico", "switch", "olt"):
        try:
            linhas = load_inventory_json(mode=modo) or []
        except Exception:
            continue
        for r in linhas:
            if not isinstance(r, dict):
                continue
            site = _chave_site(permissions.site_da_linha(r))
            if not site:
                continue
            titulo = str(r.get("titulo") or "").strip().lower()
            if titulo:
                nome.setdefault(titulo, site)
            r_ip = str(r.get("ip") or r.get("IP") or "").strip()
            if r_ip:
                ip.setdefault(r_ip, site)
    return {"nome": nome, "ip": ip, "sites": set(nome.values()) | set(ip.values())}


def _sites_da_camada(meta: Dict[str, Any], features: list, indice: Dict[str, Any]) -> list[str]:
    explicitos = meta.get("sites")
    if isinstance(explicitos, list) and any(str(s or "").strip() for s in explicitos):
        return sorted({_chave_site(s) for s in explicitos if str(s or "").strip()})
    conta: Dict[str, int] = {}
    for f in features or []:
        props = (f or {}).get("properties") or {} if isinstance(f, dict) else {}
        nome = str(props.get("name") or "").strip()
        achado = _RE_IP.search(str(props.get("description") or "")) or _RE_IP.search(nome)
        site = indice["nome"].get(nome.lower()) or (indice["ip"].get(achado.group(0)) if achado else None)
        if site:
            conta[site] = conta.get(site, 0) + 1
    if conta:
        return sorted(conta)
    rotulo = f" {re.sub(r'[^A-Z0-9]+', ' ', _chave_site(meta.get('label') or meta.get('original_name')))} "
    pelo_nome = [s for s in indice["sites"]
                 if len(s) >= 4 and f" {re.sub(r'[^A-Z0-9]+', ' ', s).strip()} " in rotulo]
    return [max(pelo_nome, key=len)] if pelo_nome else []


def _camada_liberada(meta: Dict[str, Any], features: list, indice: Optional[Dict[str, Any]], liberados: set) -> bool:
    sites = _sites_da_camada(meta, features, indice or {"nome": {}, "ip": {}, "sites": set()})
    return bool(sites) and set(sites) <= liberados


def _exigir_camada_liberada(layer_id: str, generated: bool = False) -> None:
    """404 (e nao 403: nem diz que existe) para camada de site alheio."""
    if _sites_liberados() is None:
        return
    paths_fn = _kmz_generated_layer_paths if generated else _kmz_layer_paths
    lista = _list_kmz_generated_layers(include_features=False) if generated else _list_kmz_import_layers(include_features=False)
    arquivos = {paths_fn(str(l.get("id") or ""))[0].name for l in lista}
    if paths_fn(layer_id)[0].name not in arquivos:
        raise HTTPException(404, "Camada KMZ nao encontrada.")


def _exigir_sem_restricao_de_site() -> None:
    """Rotas antigas do "ultimo KMZ importado" nao sabem de que site e o
    arquivo: so para quem acessa todos os sites."""
    if _sites_liberados() is not None:
        raise HTTPException(403, "Disponivel so para quem acessa todos os sites. Escolha a camada no mapa.")


def _sites_para_meta_nova() -> Dict[str, Any]:
    """Camada criada/importada por usuario restrito nasce com os sites dele."""
    sites = permissions.sites_da_sessao()
    return {"sites": sorted({str(s).strip() for s in sites if str(s or "").strip()})} if sites is not None else {}


def _kmz_layer_download_name(label: str, fallback: str = "mapa.kmz") -> str:
    raw = str(label or "").strip() or fallback
    stem = Path(raw).stem or "mapa"
    return f"{_safe_name(stem, 'mapa')}.kmz"


def _list_kmz_import_layers(include_features: bool = True) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    liberados = _sites_liberados()
    indice = _indice_sites_inventario() if liberados is not None else None
    for meta_path in sorted(_kmz_layers_dir().glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = _read_kmz_layer_meta(meta_path)
        layer_id = str(meta.get("id") or meta_path.stem.replace(".meta", "")).strip()
        kmz_path, geojson_path, _ = _kmz_layer_paths(layer_id)
        if not kmz_path.exists() or not geojson_path.exists():
            continue
        geojson: dict[str, Any] = {}
        features: list[Any] = []
        if include_features:
            geojson = read_geojson_file(geojson_path)
            features = geojson.get("features") or []
        elif geojson_path.exists():
            try:
                features = json.loads(geojson_path.read_text(encoding="utf-8") or "{}").get("features") or []
            except Exception:
                features = []
        if liberados is not None and not _camada_liberada(meta, features, indice, liberados):
            continue  # camada de site que o usuario nao acessa
        layers.append({
            "id": layer_id,
            "label": str(meta.get("label") or meta.get("original_name") or kmz_path.name).replace(".kmz", "").replace(".kml", ""),
            "original_name": meta.get("original_name") or kmz_path.name,
            "filename": kmz_path.name,
            "features_count": len(features),
            "created_at": meta.get("created_at") or "",
            "download_url": f"/api/kmz/import/layers/{layer_id}/download-enriched",
            "raw_download_url": f"/api/kmz/import/layers/{layer_id}/download",
            "update_url": f"/api/kmz/import/layers/{layer_id}",
            # camada criada no mapa aparece mesmo vazia (as outras com 0
            # pontos seguem escondidas na tela)
            "origem": str(meta.get("origem") or ""),
            "cor_outros": str(meta.get("cor_outros") or ""),
            # modo do inventario em que a camada aparece ("" = automatico)
            "modo": str(meta.get("modo") or ""),
            # caixas de CFTV e cabos desenhados no mapa (meta da camada)
            "caixas": meta.get("caixas") if isinstance(meta.get("caixas"), dict) else {},
            "cabos": meta.get("cabos") if isinstance(meta.get("cabos"), dict) else {},
            "ctos": meta.get("ctos") if isinstance(meta.get("ctos"), dict) else {},
            "cdos": meta.get("cdos") if isinstance(meta.get("cdos"), dict) else {},
            "fibras": meta.get("fibras") if isinstance(meta.get("fibras"), dict) else {},
            "motivos": meta.get("motivos") if isinstance(meta.get("motivos"), dict) else {},
            **({"features": features, "type": geojson.get("type") or "FeatureCollection"} if include_features else {}),
        })
    return layers


def _list_kmz_generated_layers(include_features: bool = True) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    liberados = _sites_liberados()
    indice = _indice_sites_inventario() if liberados is not None else None
    for meta_path in sorted(_kmz_generated_layers_dir().glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = _read_kmz_layer_meta(meta_path)
        generated_from = str(meta.get("generated_from") or "").strip()
        if generated_from == "imported-layer-download":
            continue
        layer_id = str(meta.get("id") or meta_path.stem.replace(".meta", "")).strip()
        kmz_path, geojson_path, _ = _kmz_generated_layer_paths(layer_id)
        if not kmz_path.exists() or not geojson_path.exists():
            continue
        geojson: dict[str, Any] = {}
        features: list[Any] = []
        if include_features:
            geojson = read_geojson_file(geojson_path)
            features = geojson.get("features") or []
        elif geojson_path.exists():
            try:
                features = json.loads(geojson_path.read_text(encoding="utf-8") or "{}").get("features") or []
            except Exception:
                features = []
        if liberados is not None and not _camada_liberada(meta, features, indice, liberados):
            continue  # camada de site que o usuario nao acessa
        layers.append({
            "id": layer_id,
            "label": str(meta.get("label") or meta.get("original_name") or kmz_path.name).replace(".kmz", "").replace(".kml", ""),
            "original_name": meta.get("original_name") or kmz_path.name,
            "filename": kmz_path.name,
            "features_count": len(features),
            "created_at": meta.get("created_at") or "",
            "source_layer_id": meta.get("source_layer_id") or "",
            "source": meta.get("source") or "generated",
            "mode": meta.get("mode") or "",
            "generated_from": generated_from,
            "download_url": f"/api/kmz/generated/layers/{layer_id}/download",
            "update_url": f"/api/kmz/generated/layers/{layer_id}",
            **({"features": features, "type": geojson.get("type") or "FeatureCollection"} if include_features else {}),
        })
    return layers


def _rename_kmz_layer(layer_id: str, label: str, generated: bool = False) -> dict[str, Any]:
    clean_label = str(label or "").strip()
    if not clean_label:
        raise HTTPException(400, "Nome da camada obrigatorio.")
    paths_fn = _kmz_generated_layer_paths if generated else _kmz_layer_paths
    list_fn = _list_kmz_generated_layers if generated else _list_kmz_import_layers
    kmz_path, geojson_path, meta_path = paths_fn(layer_id)
    if not kmz_path.exists() or not geojson_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    meta["id"] = layer_id
    meta["label"] = clean_label
    meta["original_name"] = _kmz_layer_download_name(clean_label, str(meta.get("original_name") or kmz_path.name))
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    layer = next((item for item in list_fn(include_features=False) if item.get("id") == layer_id), None)
    return layer or {"id": layer_id, "label": clean_label, "original_name": meta["original_name"]}


def _ensure_imported_layer_enriched(layer_id: str, source: str, mode: str = "") -> tuple[Path, str]:
    src = str(source or "ip").strip().lower()
    normalized_mode = _normalize_inventory_mode(mode) if src == "ip" else ""
    import_kmz_path, _, import_meta_path = _kmz_layer_paths(layer_id)
    if not import_kmz_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")

    # restrito: so cameras dos sites dele no popup (um ponto com IP de outro
    # site nao traz os dados daquela camera)
    rows_raw = permissions.filtrar_por_site(_load_rows_by_source(src, mode=normalized_mode))
    rows = _kmz_rows_for_source(src, rows_raw)
    if not rows:
        raise HTTPException(400, "Inventario vazio.")

    meta = _read_kmz_layer_meta(import_meta_path)
    label = str(meta.get("label") or meta.get("original_name") or import_kmz_path.stem).replace(".kmz", "").replace(".kml", "")
    generated_id = f"enriched-{_safe_name(layer_id, 'layer')}-{_safe_name(src, 'ip')}-{_safe_name(normalized_mode or 'all', 'all')}"
    generated_kmz_path, generated_geojson_path, generated_meta_path = _kmz_generated_layer_paths(generated_id)
    kmz_output_dir = tenant_kmz_output_dir() if get_current_tenant_slug() else KMZ_OUTPUT_DIR

    try:
        out_kmz = generate_enriched_kmz(import_kmz_path, rows, kmz_output_dir)
        geojson = kmz_to_geojson(out_kmz)
        generated_kmz_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_kmz, generated_kmz_path)
        generated_geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
        generated_meta = {
            "id": generated_id,
            "label": label,
            "original_name": _kmz_layer_download_name(label),
            "created_at": str(meta.get("created_at") or datetime.now().isoformat(timespec="seconds")),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "features_count": len(geojson.get("features") or []),
            "source_layer_id": layer_id,
            "source": src,
            "mode": normalized_mode if src == "ip" else "",
            "generated_from": "imported-layer-download",
            "rows_used": len(rows),
        }
        _write_kmz_layer_meta(generated_meta_path, generated_meta)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Falha ao gerar KMZ enriquecido: {exc}")

    return generated_kmz_path, str(generated_meta.get("original_name") or generated_kmz_path.name)


def _cleanup_kmz_workspace(keep_imported: bool = False) -> None:
    kmz_input_dir = tenant_kmz_input_dir() if get_current_tenant_slug() else KMZ_INPUT_DIR
    kmz_output_dir = tenant_kmz_output_dir() if get_current_tenant_slug() else KMZ_OUTPUT_DIR
    kmz_imported_path = tenant_kmz_imported_path() if get_current_tenant_slug() else KMZ_IMPORTED_PATH
    kmz_geojson_path = tenant_kmz_imported_geojson_path() if get_current_tenant_slug() else KMZ_IMPORTED_GEOJSON_PATH

    # Mantem workspace de KMZ limpo para evitar "sujeira" de imports antigos.
    kmz_input_dir.mkdir(parents=True, exist_ok=True)
    kmz_output_dir.mkdir(parents=True, exist_ok=True)
    kmz_imported_path.parent.mkdir(parents=True, exist_ok=True)

    # Limpa arquivos de input antigos
    for p in kmz_input_dir.glob("*"):
        if p.is_file():
            _safe_unlink(p)

    # Limpa artefatos gerados (mantemos somente a ultima geracao por sessao)
    for p in kmz_output_dir.glob("*"):
        if p.is_file():
            _safe_unlink(p)

    # Limpa import atual/caches quando requisitado
    if not keep_imported:
        _safe_unlink(kmz_imported_path)
        _safe_unlink(kmz_geojson_path)
        _safe_unlink(kmz_imported_path.with_suffix(".meta.json"))


def _zip_add_tree(
    zf: zipfile.ZipFile,
    src_dir: Path,
    arc_prefix: str,
    exclude_prefixes: Optional[List[str]] = None,
) -> None:
    exclude_prefixes = exclude_prefixes or []
    if not src_dir.exists():
        return
    for root, dirs, files in os.walk(src_dir):
        root_p = Path(root)
        rel_root = root_p.relative_to(src_dir)
        dirs[:] = [d for d in dirs if not any(str((rel_root / d)).startswith(x) for x in exclude_prefixes)]
        for fn in files:
            rel = rel_root / fn
            if any(str(rel).startswith(x) for x in exclude_prefixes):
                continue
            full_path = root_p / fn
            arcname = str(Path(arc_prefix) / rel).replace("\\", "/")
            try:
                zf.write(full_path, arcname)
            except Exception:
                continue


def _load_inventory_rows(mode: str = "olt", site: str = "") -> list[dict[str, Any]]:
    return load_inventory_json(site=site, mode=mode) or []


def _save_inventory_rows(rows: list[dict[str, Any]], mode: str = "olt") -> None:
    save_inventory_json(rows, mode=mode)


def _load_dvr_rows() -> list[dict[str, Any]]:
    if get_current_tenant_slug():
        p = tenant_recorder_inventory_path("dvr")
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []
    db_rows = legacy_rows_from_db("dvr")
    if db_rows:
        return db_rows
    p = Path(DVR_INVENTORY_JSON_PATH)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_dvr_rows(rows: list[dict[str, Any]]) -> None:
    if get_current_tenant_slug():
        p = tenant_recorder_inventory_path("dvr")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    try:
        replace_recorder_inventory_rows("dvr", rows)
        return
    except Exception:
        pass
    p = Path(DVR_INVENTORY_JSON_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_nvr_rows() -> list[dict[str, Any]]:
    if get_current_tenant_slug():
        p = tenant_recorder_inventory_path("nvr")
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []
    db_rows = legacy_rows_from_db("nvr")
    if db_rows:
        return db_rows
    p = Path(NVR_INVENTORY_JSON_PATH)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_nvr_rows(rows: list[dict[str, Any]]) -> None:
    if get_current_tenant_slug():
        p = tenant_recorder_inventory_path("nvr")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    try:
        replace_recorder_inventory_rows("nvr", rows)
        return
    except Exception:
        pass
    p = Path(NVR_INVENTORY_JSON_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_inventory_mode(mode: str = "") -> str:
    raw = str(mode or "").strip().lower()
    if raw in ("basic", "basico", "básico"):
        return "basico"
    if raw == "switch":
        return "switch"
    return "olt"


def _load_rows_by_source(source: str, mode: str = "") -> list[dict[str, Any]]:
    src = str(source or "ip").strip().lower()
    if src == "dvr":
        return _load_dvr_rows()
    if src == "nvr":
        return _load_nvr_rows()
    return _load_inventory_rows(mode=_normalize_inventory_mode(mode))


def _save_rows_by_source(source: str, rows: list[dict[str, Any]], mode: str = "") -> None:
    src = str(source or "ip").strip().lower()
    if src == "dvr":
        _save_dvr_rows(rows)
        return
    if src == "nvr":
        _save_nvr_rows(rows)
        return
    _save_inventory_rows(rows, mode=_normalize_inventory_mode(mode))


def _kmz_rows_for_source(source: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    src = str(source or "ip").strip().lower()
    if src not in ("dvr", "nvr"):
        return rows
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        host = str(r.get("host") or "").strip()
        if not host:
            continue
        ch = int(r.get("channel") or 0)
        ch_txt = f"{ch:02d}" if ch > 0 else "00"
        title = str(r.get("title") or "").strip() or f"Canal {ch_txt}"
        out.append(
            {
                "ip": host,
                "titulo": title,
                "title": title,
                "local": str(r.get("local") or "").strip(),
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "snapshot_url": str(r.get("imgbb_url") or r.get("snapshot_url") or "").strip(),
                "imgbb_url": str(r.get("imgbb_url") or "").strip(),
            }
        )
    return out


def _guess_service(port: int) -> str:
    common: dict[int, str] = {
        21: "ftp",
        22: "ssh",
        23: "telnet",
        53: "dns",
        80: "http",
        81: "http-alt",
        88: "http-alt",
        443: "https",
        554: "rtsp",
        8000: "http-alt",
        8080: "http-proxy",
        8291: "mikrotik-winbox",
        8443: "https-alt",
        37777: "dahua",
    }
    return common.get(port, "")


def _parse_ports(raw: str) -> list[int]:
    if not raw:
        return [80, 443, 554, 8000, 37777, 8291, 22]
    out: list[int] = []
    seen: set[int] = set()
    for token in [x.strip() for x in str(raw).replace(";", ",").split(",") if x.strip()]:
        if "-" in token:
            try:
                a, b = token.split("-", 1)
                start = int(a.strip())
                end = int(b.strip())
                if end < start:
                    start, end = end, start
                for p in range(start, end + 1):
                    if 1 <= p <= 65535 and p not in seen:
                        out.append(p)
                        seen.add(p)
            except Exception:
                continue
        else:
            try:
                p = int(token)
            except Exception:
                continue
            if 1 <= p <= 65535 and p not in seen:
                out.append(p)
                seen.add(p)
    return out or [80, 443, 554, 8000, 37777, 8291, 22]


def _split_tokens(raw: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\s;]+", raw or "") if t.strip()]


def _expand_host_token(token: str) -> list[str]:
    token = (token or "").strip()
    if not token:
        return []

    if "/" in token:
        try:
            net = ipaddress.ip_network(token, strict=False)
            return [str(ip) for ip in net.hosts()]
        except Exception:
            return [token]

    if "-" in token:
        left, right = token.split("-", 1)
        left = left.strip()
        right = right.strip()
        try:
            ip_left = ipaddress.ip_address(left)
            if ip_left.version == 4:
                if re.fullmatch(r"\d{1,3}", right):
                    parts = left.split(".")
                    start = int(parts[-1])
                    end = int(right)
                    if 0 <= start <= 255 and 0 <= end <= 255:
                        if end < start:
                            start, end = end, start
                        base = ".".join(parts[:-1])
                        return [f"{base}.{i}" for i in range(start, end + 1)]
                ip_right = ipaddress.ip_address(right)
                if ip_right.version == 4:
                    start_i = int(ip_left)
                    end_i = int(ip_right)
                    if end_i < start_i:
                        start_i, end_i = end_i, start_i
                    return [str(ipaddress.ip_address(i)) for i in range(start_i, end_i + 1)]
        except Exception:
            pass

    return [token]


def _parse_targets(raw: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in _split_tokens(raw):
        for host in _expand_host_token(token):
            if host not in seen:
                seen.add(host)
                out.append(host)
    return out


def _quick_scan_open_ports(ip: str, ports: list[int], timeout_s: float) -> list[dict[str, Any]]:
    opened: list[dict[str, Any]] = []
    for port in ports:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_s)
            rc = sock.connect_ex((ip, int(port)))
            if rc == 0:
                opened.append({"port": int(port), "service": _guess_service(int(port))})
        except Exception:
            continue
        finally:
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
    return opened


@router.post("/tools/scan-ip")
async def api_tools_scan_ip(payload: Dict[str, Any]) -> Dict[str, Any]:
    ip = str(payload.get("ip") or "").strip()
    user = str(payload.get("usuario") or payload.get("user") or "").strip()
    password = str(payload.get("senha") or payload.get("password") or payload.get("pass") or "").strip()
    ports_raw = str(payload.get("ports") or "").strip()
    timeout_ms = int(payload.get("timeout_ms") or 900)
    timeout_s = max(0.08, min(timeout_ms / 1000.0, 8.0))

    if not ip:
        raise HTTPException(400, "IP nao informado.")
    try:
        parsed = ipaddress.ip_address(ip)
    except Exception:
        raise HTTPException(400, "IP invalido.")
    if parsed.version != 4:
        raise HTTPException(400, "A ferramenta atual aceita apenas IPv4.")

    ports = _parse_ports(ports_raw)
    open_ports = _quick_scan_open_ports(ip, ports, timeout_s)
    online = bool(open_ports)

    hostname = ""
    try:
        hostname = socket.gethostbyaddr(ip)[0] or ""
    except Exception:
        hostname = ""

    info: Dict[str, Any] = {"ip": ip}
    try:
        if user:
            info = probe_device(ip, user, password, timeout=(timeout_s, max(1.0, timeout_s * 2.2)), retries=0) or {"ip": ip}
    except Exception:
        info = {"ip": ip}

    fabricante = str(info.get("fabricante") or "").strip()
    modelo = str(info.get("modelo") or "").strip()
    titulo = str(info.get("titulo") or "").strip()
    mac = str(info.get("mac") or "").strip().lower()
    status = str(info.get("status") or ("online" if online else "offline")).strip().lower()

    return {
        "ok": True,
        "ip": ip,
        "online": online,
        "hostname": hostname,
        "status": status,
        "fabricante": fabricante,
        "modelo": modelo,
        "titulo": titulo,
        "mac": mac,
        "open_ports": open_ports,
        "ports_checked": ports,
        "auth_used": bool(user),
    }


@router.post("/discovery/run")
async def api_discovery_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    targets = _parse_targets(str(payload.get("targets") or "").strip())
    ports = _parse_ports(str(payload.get("ports") or "").strip())
    timeout_ms = int(payload.get("timeout_ms") or 650)
    timeout_s = max(0.08, min(timeout_ms / 1000.0, 8.0))
    concurrency = max(1, min(int(payload.get("concurrency") or 256), 1024))
    fast_mode = bool(payload.get("fast_mode", True))

    user = str(payload.get("usuario") or payload.get("user") or "").strip()
    password = str(payload.get("senha") or payload.get("password") or payload.get("pass") or "").strip()
    collect_info = bool(payload.get("collect_info", True))

    if not targets:
        raise HTTPException(400, "Informe ao menos um alvo (IP/range/CIDR).")
    if not ports:
        raise HTTPException(400, "Informe ao menos uma porta.")

    sem = asyncio.Semaphore(concurrency)
    rows: list[dict[str, Any]] = []
    checked = 0

    async def _scan_host(ip: str) -> None:
        nonlocal checked
        open_ports: list[int] = []
        async with sem:
            for p in ports:
                try:
                    conn = asyncio.open_connection(ip, int(p))
                    reader, writer = await asyncio.wait_for(conn, timeout=timeout_s)
                    open_ports.append(int(p))
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass
                    if fast_mode:
                        break
                except Exception:
                    continue
            checked += 1

            if not open_ports:
                return

            hostname = ""
            try:
                hostname = socket.gethostbyaddr(ip)[0] or ""
            except Exception:
                hostname = ""

            info: Dict[str, Any] = {"ip": ip}
            if collect_info and user:
                try:
                    info = await asyncio.to_thread(
                        probe_device,
                        ip,
                        user,
                        password,
                        (timeout_s, max(1.0, timeout_s * 2.0)),
                        0,
                    ) or {"ip": ip}
                except Exception:
                    info = {"ip": ip}

            rows.append(
                {
                    "ip": ip,
                    "hostname": hostname,
                    "open_ports": [{"port": int(pp), "service": _guess_service(int(pp))} for pp in open_ports],
                    "fabricante": str(info.get("fabricante") or "").strip(),
                    "modelo": str(info.get("modelo") or "").strip(),
                    "titulo": str(info.get("titulo") or "").strip(),
                    "mac": str(info.get("mac") or "").strip().lower(),
                    "status": str(info.get("status") or "online").strip().lower(),
                }
            )

    tasks = [asyncio.create_task(_scan_host(ip)) for ip in targets]
    await asyncio.gather(*tasks, return_exceptions=True)
    rows.sort(key=lambda r: r.get("ip") or "")

    return {
        "ok": True,
        "targets_total": len(targets),
        "targets_checked": checked,
        "found": len(rows),
        "results": rows,
    }


# -----------------
# Inventory clear/export/import
# -----------------

@router.post("/inventory/clear")
async def api_inventory_clear(payload: Dict[str, Any] | None = None) -> dict[str, Any]:
    removed: list[str] = []
    wiped: dict[str, int] = {}
    db_clear: dict[str, Any] = {}
    data = payload if isinstance(payload, dict) else {}
    site = str(data.get("site") or "").strip()
    mode = str(data.get("mode") or "olt").strip().lower()

    def _row_matches_site(row: Dict[str, Any], wanted_site: str) -> bool:
        ws = str(wanted_site or "").strip().lower()
        if not ws:
            return False
        vals = [
            str(row.get("site") or "").strip(),
            str(row.get("site_name") or "").strip(),
            str(row.get("local") or row.get("LOCAL") or "").strip(),
        ]
        return any(v.lower() == ws for v in vals if v)

    if site:
        rows = _load_inventory_rows(mode=mode)
        kept = [r for r in rows if not (isinstance(r, dict) and _row_matches_site(r, site))]
        removed_count = max(0, len(rows) - len(kept))
        _save_inventory_rows(kept, mode=mode)
        return {
            "ok": True,
            "mode": mode,
            "site": site,
            "scope": "site",
            "removed_rows": removed_count,
            "remaining": len(kept),
            "wiped": {},
            "removed": [],
        }

    try:
        _save_inventory_rows([], mode=mode)
        db_clear = {"ok": True, "mode": mode}
    except Exception:
        db_clear = {"ok": False, "mode": mode}

    if mode == "olt":
        for path in [
            INVENTORY_JSON_PATH,
            SAIDA_DIR / "cam-inventory.ai.csv",
            BASE_DIR / "cam-inventory.json",
        ]:
            try:
                if path.exists():
                    path.unlink()
                    removed.append(path.name)
            except Exception:
                pass

    def _wipe_tree(dir_path: Path) -> int:
        try:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                return 0
            try:
                count = sum(1 for p in dir_path.rglob("*") if p.is_file())
            except Exception:
                count = 0
            shutil.rmtree(dir_path, ignore_errors=True)
            dir_path.mkdir(parents=True, exist_ok=True)
            return count
        except Exception:
            return 0

    if mode == "olt":
        for d in [OUTPUT_DIR / "snapshot", OUTPUT_DIR / "thumbs", OUTPUT_DIR / "snapshot_manual"]:
            wiped[str(d)] = _wipe_tree(d)

    return {"ok": True, "mode": mode, "scope": "all", "removed": removed, "wiped": wiped, "db_clear": db_clear}


@router.get("/inventory/export")
async def api_inventory_export(mode: str = "olt") -> Response:
    rows = permissions.filtrar_por_site(_load_inventory_rows(mode=mode))
    if not rows:
        raise HTTPException(404, "Inventario nao encontrado.")
    export_mode = str(mode or "olt").strip().lower()
    # Devolve direto, sem gravar em disco. Antes gravava em saida/cam-inventory.json
    # (pasta comum a todos os clientes), que o /api/db/migrate de OUTRO cliente lia
    # e importava como se fosse dele -- e dois clientes exportando ao mesmo tempo
    # podiam baixar o arquivo um do outro.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"cam-inventory-{export_mode}-backup-{ts}.json"
    return Response(
        content=json.dumps(rows, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"', "Cache-Control": "no-store"},
    )


@router.post("/inventory/import")
async def api_inventory_import(file: UploadFile = File(...), mode: str = "olt") -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")

    data: Any = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            data = json.loads(raw.decode(enc))
            break
        except Exception:
            continue
    if data is None:
        raise HTTPException(400, "JSON invalido.")

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("inventory") or data.get("rows") or data.get("data")
    else:
        rows = None

    if not isinstance(rows, list):
        raise HTTPException(400, "Formato invalido: esperado uma lista de cameras.")

    rows = [r for r in rows if isinstance(r, dict)]
    if not permissions.pode_excluir():
        # A importacao SUBSTITUI o inventario: arquivo sem uma camera que
        # existe e exclusao (com lista vazia, e o mesmo que "limpar").
        novos = {str(r.get("ip") or "").strip() for r in rows}
        sumiriam = [str(r.get("ip") or "") for r in _load_inventory_rows(mode=mode)
                    if str(r.get("ip") or "").strip() not in novos]
        if sumiriam:
            raise HTTPException(403, f"{permissions.MSG_EXCLUIR} O arquivo deixaria de fora {len(sumiriam)} câmera(s) que já estão no inventário: peça a um administrador para importar.")
    _save_inventory_rows(rows, mode=mode)
    saved = _load_inventory_rows(mode=mode)
    return {"ok": True, "count": len(saved), "inventory": saved}


@router.get("/inventory-last")
async def api_inventory_last(site: str = "", enrich: str = "") -> Dict[str, Any]:
    mode = (enrich or "olt").strip().lower()
    # Filtro de site so nas rotas de LEITURA: _load_inventory_rows tambem serve a
    # importar/limpar/excluir, que regravariam o inventario sem os outros sites.
    rows = permissions.filtrar_por_site(_load_inventory_rows(mode=mode, site=site))
    if mode == "olt":
        rows, _ = _enrich_inventory_with_olt(list(rows), SAIDA_DIR / "olt-cpe-macs.json")
    elif mode == "switch":
        rows, _ = _enrich_inventory_with_switch(list(rows), DATA_DIR / "switch-mac-table.json")
    return {"ok": True, "count": len(rows), "inventory": rows}


def _load_report_rows_and_config(
    site: str, company_name: str, report_color: str, mode: str, ips: str
) -> tuple[list[dict[str, Any]], Dict[str, Any]]:
    report_mode = str(mode or "").strip().lower()
    rows = permissions.filtrar_por_site(_load_inventory_rows(mode=(report_mode or "olt"), site=site))
    if report_mode == "olt":
        rows, _ = _enrich_inventory_with_olt(list(rows), SAIDA_DIR / "olt-cpe-macs.json")
    elif report_mode == "switch":
        rows, _ = _enrich_inventory_with_switch(list(rows), DATA_DIR / "switch-mac-table.json")
    selected_ips = {str(part or "").strip() for part in str(ips or "").split(",")}
    selected_ips.discard("")
    if selected_ips:
        rows = [
            r for r in rows
            if isinstance(r, dict) and str(r.get("ip") or r.get("IP") or "").strip() in selected_ips
        ]
    settings = load_app_settings()
    if not isinstance(settings, dict):
        settings = {}
    rep_cfg = settings.get("inventory_pdf_report") if isinstance(settings, dict) else {}
    rep_cfg = rep_cfg if isinstance(rep_cfg, dict) else {}
    company = str(company_name or rep_cfg.get("company_name") or "").strip()
    color = _report_color(report_color or rep_cfg.get("report_color") or "")
    report_logo_path = tenant_report_logo_path("inventory") if get_current_tenant_slug() else (DATA_DIR / "input" / "inventory-report-logo.png")
    logo = report_logo_path if report_logo_path.exists() else None
    cfg = {
        "site": site,
        "company_name": company,
        "logo_path": logo,
        "include_olt": (report_mode == "olt"),
        "include_switch": (report_mode == "switch"),
        "module_label": {"olt": "Cameras IP OLT", "switch": "Cameras IP Switch"}.get(report_mode, "Cameras IP Basico"),
        "report_color": color,
    }
    return rows, cfg


@router.get("/inventory/report.pdf")
async def api_inventory_report_pdf(site: str = "", company_name: str = "", report_color: str = "", mode: str = "", ips: str = "") -> FileResponse:
    rows, cfg = _load_report_rows_and_config(site, company_name, report_color, mode, ips)
    pdf_path = await asyncio.to_thread(
        build_inventory_pdf_report,
        rows,
        include_photos=True,
        **cfg,
    )
    return FileResponse(path=pdf_path, media_type="application/pdf", filename=pdf_path.name)


# Job assincrono com progresso: gerar o PDF (principalmente a galeria de
# fotos, que le/decodifica/redimensiona uma imagem por camera) pode levar
# de alguns segundos a alguns minutos num inventario grande. Uma unica
# requisicao sincrona nesse caso deixa o navegador parado sem feedback --
# aqui o front dispara o job, recebe um job_id e fica consultando o status
# (done/total/etapa) pra mostrar progresso real, so baixando o arquivo no
# final. Mesmo padrao ja usado pelas auditorias offline de OLT.
_report_jobs: dict[str, dict[str, Any]] = {}
_report_tasks: set[asyncio.Task[Any]] = set()
_REPORT_JOB_TTL_SECONDS = 30 * 60


def _prune_report_jobs() -> None:
    now = datetime.now()
    stale = [
        jid for jid, job in _report_jobs.items()
        if job.get("status") in ("done", "error")
        and (now - job.get("_created", now)).total_seconds() > _REPORT_JOB_TTL_SECONDS
    ]
    for jid in stale:
        job = _report_jobs.pop(jid, None)
        path = job.get("path") if job else None
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


async def _run_inventory_report_job(job_id: str, rows: list[dict[str, Any]], cfg: Dict[str, Any]) -> None:
    job = _report_jobs[job_id]
    job["status"] = "running"

    def _cb(done: int, total: int, stage: str) -> None:
        job["done"] = int(done)
        job["total"] = int(total)
        job["stage"] = stage

    try:
        pdf_path = await asyncio.to_thread(
            build_inventory_pdf_report,
            rows,
            include_photos=True,
            progress_cb=_cb,
            **cfg,
        )
        job["status"] = "done"
        job["path"] = str(pdf_path)
        job["filename"] = pdf_path.name
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc) or repr(exc)


def _inventory_report_job_do_cliente(job_id: str) -> dict[str, Any]:
    """Job do relatorio de cameras, so para o cliente que pediu.

    Antes bastava o job_id: o mesmo dicionario guarda os jobs do relatorio do
    mapa, e por estas rotas dava para baixar o mapa de outro cliente sem a
    checagem que as rotas do mapa fazem.
    """
    job = _report_jobs.get(job_id)
    if not job or job.get("kind", "inventario") != "inventario"             or job.get("tenant", "") != (get_current_tenant_slug() or ""):
        raise HTTPException(status_code=404, detail="job nao encontrado ou expirado")
    return job


@router.post("/inventory/report/job")
async def api_inventory_report_job_start(site: str = "", company_name: str = "", report_color: str = "", mode: str = "", ips: str = "") -> Dict[str, Any]:
    _prune_report_jobs()
    rows, cfg = _load_report_rows_and_config(site, company_name, report_color, mode, ips)
    job_id = uuid.uuid4().hex
    _report_jobs[job_id] = {
        "status": "queued",
        "done": 0,
        "total": 0,
        "stage": "preparando",
        "total_rows": len(rows),
        "kind": "inventario",
        "tenant": get_current_tenant_slug() or "",
        "_created": datetime.now(),
    }
    task = asyncio.create_task(_run_inventory_report_job(job_id, rows, cfg), name=f"inv-report-{job_id[:8]}")
    _report_tasks.add(task)
    task.add_done_callback(_report_tasks.discard)
    return {"ok": True, "job_id": job_id, "total_rows": len(rows)}


@router.get("/inventory/report/job/{job_id}/status")
def api_inventory_report_job_status(job_id: str) -> Dict[str, Any]:
    job = _inventory_report_job_do_cliente(job_id)
    return {
        "ok": True,
        "status": job.get("status"),
        "done": job.get("done", 0),
        "total": job.get("total", 0),
        "stage": job.get("stage", ""),
        "total_rows": job.get("total_rows", 0),
        "error": job.get("error"),
        "ready": job.get("status") == "done",
    }


@router.get("/inventory/report/job/{job_id}/download")
def api_inventory_report_job_download(job_id: str) -> FileResponse:
    job = _inventory_report_job_do_cliente(job_id)
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail="relatorio ainda esta sendo gerado")
    path = Path(job.get("path") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="arquivo do relatorio nao encontrado")
    return FileResponse(path=path, media_type="application/pdf", filename=job.get("filename") or path.name)


# ---- Relatorio do Mapa -------------------------------------------------------
# Mesmo esquema de job do relatorio de cameras: baixar os tiles do mapa geral e
# de cada area pode passar dos 60 s do nginx. O job guarda o cliente que pediu:
# status e download so respondem para ele (o job_id sozinho nao basta).
async def _run_map_report_job(job_id: str, cfg: Dict[str, Any]) -> None:
    from app.services.map_pdf_report import build_map_pdf_report

    job = _report_jobs[job_id]
    job["status"] = "running"

    def _cb(done: int, total: int, stage: str) -> None:
        job["done"], job["total"], job["stage"] = int(done), int(total), stage

    try:
        pdf_path = await asyncio.to_thread(build_map_pdf_report, progress_cb=_cb, **cfg)
        job["status"], job["path"], job["filename"] = "done", str(pdf_path), pdf_path.name
    except Exception as exc:
        job["status"], job["error"] = "error", str(exc) or repr(exc)


def _id_do_usuario() -> str:
    from app.core.tenant_context import get_current_user

    u = get_current_user() or {}
    return str(u.get("id") or "") if isinstance(u, dict) else ""


def _map_report_job_do_cliente(job_id: str) -> dict[str, Any]:
    job = _report_jobs.get(job_id)
    if not job or job.get("kind") != "mapa" or job.get("tenant") != (get_current_tenant_slug() or ""):
        raise HTTPException(status_code=404, detail="job nao encontrado ou expirado")
    if job.get("user") and job.get("user") != _id_do_usuario():
        raise HTTPException(status_code=404, detail="job nao encontrado ou expirado")
    return job


@router.post("/kmz/report/job")
async def api_map_report_job_start(site: str = "", company_name: str = "", report_color: str = "") -> Dict[str, Any]:
    if not get_current_tenant_slug():
        raise HTTPException(status_code=400, detail="relatorio do mapa precisa de um cliente selecionado")
    # restrito: site vazio = os sites dele (o relatorio filtra cameras e
    # camadas pela sessao); site de outro, nao
    liberados = _sites_liberados()
    if liberados is not None and site.strip() and _chave_site(site) not in liberados:
        raise HTTPException(status_code=403, detail="Site fora do seu acesso.")
    _prune_report_jobs()
    job_id = uuid.uuid4().hex
    _report_jobs[job_id] = {"status": "queued", "done": 0, "total": 0, "stage": "preparando", "kind": "mapa",
                            "tenant": get_current_tenant_slug() or "", "user": _id_do_usuario(), "_created": datetime.now()}
    cfg = {"site": site, "company_name": company_name, "report_color": report_color}
    task = asyncio.create_task(_run_map_report_job(job_id, cfg), name=f"map-report-{job_id[:8]}")
    _report_tasks.add(task)
    task.add_done_callback(_report_tasks.discard)
    return {"ok": True, "job_id": job_id}


@router.get("/kmz/report/job/{job_id}/status")
def api_map_report_job_status(job_id: str) -> Dict[str, Any]:
    job = _map_report_job_do_cliente(job_id)
    return {"ok": True, "status": job.get("status"), "done": job.get("done", 0), "total": job.get("total", 0),
            "stage": job.get("stage", ""), "error": job.get("error"), "ready": job.get("status") == "done"}


@router.get("/kmz/report/job/{job_id}/download")
def api_map_report_job_download(job_id: str) -> FileResponse:
    job = _map_report_job_do_cliente(job_id)
    if job.get("status") != "done":
        raise HTTPException(status_code=409, detail="relatorio ainda esta sendo gerado")
    path = Path(job.get("path") or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="arquivo do relatorio nao encontrado")
    return FileResponse(path=path, media_type="application/pdf", filename=job.get("filename") or path.name)


@router.get("/inventory/report/preview")
async def api_inventory_report_preview(site: str = "", company_name: str = "", report_color: str = "", mode: str = "", ips: str = "") -> StreamingResponse:
    rows, cfg = _load_report_rows_and_config(site, company_name, report_color, mode, ips)
    pdf_path = build_inventory_pdf_report(rows, **cfg)
    data = pdf_path.read_bytes()
    headers = {"Content-Disposition": f'inline; filename="{pdf_path.name}"'}
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf", headers=headers)


@router.get("/inventory/report/preview.jpg")
async def api_inventory_report_preview_jpg(site: str = "", company_name: str = "", report_color: str = "", mode: str = "", ips: str = "") -> FileResponse:
    rows, cfg = _load_report_rows_and_config(site, company_name, report_color, mode, ips)
    img_path = build_inventory_preview_image(rows, **cfg)
    return FileResponse(path=img_path, media_type="image/jpeg", filename=img_path.name)


@router.get("/inventory/report/settings")
async def api_inventory_report_settings() -> Dict[str, Any]:
    obj = load_app_settings()
    if not isinstance(obj, dict):
        obj = {}
    rep = obj.get("inventory_pdf_report")
    rep = rep if isinstance(rep, dict) else {}
    return {
        "ok": True,
        "company_name": str(rep.get("company_name") or "").strip(),
        "report_color": _report_color(rep.get("report_color") or ""),
        "has_logo": bool((tenant_report_logo_path("inventory") if get_current_tenant_slug() else (DATA_DIR / "input" / "inventory-report-logo.png")).exists()),
    }


@router.post("/inventory/report/settings")
async def api_inventory_report_settings_save(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    company = str(data.get("company_name") or "").strip()
    color = _report_color(data.get("report_color") or "")
    obj = load_app_settings()
    if not isinstance(obj, dict):
        obj = {}
    rep = obj.get("inventory_pdf_report")
    rep = rep if isinstance(rep, dict) else {}
    rep["company_name"] = company
    rep["report_color"] = color
    obj["inventory_pdf_report"] = rep
    save_app_settings(obj)
    return {"ok": True, "company_name": company, "report_color": color}


@router.post("/inventory/report/logo")
async def api_inventory_report_logo(file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise HTTPException(400, "Formato invalido. Use PNG/JPG/WEBP/BMP.")
    report_logo_path = tenant_report_logo_path("inventory") if get_current_tenant_slug() else (DATA_DIR / "input" / "inventory-report-logo.png")
    report_logo_path.parent.mkdir(parents=True, exist_ok=True)
    report_logo_path.write_bytes(raw)
    return {"ok": True, "has_logo": True}


@router.post("/inventory/imgbb/upload")
async def api_inventory_imgbb_upload(payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    mode = str(data.get("mode") or "olt").strip().lower()
    rows = _load_inventory_rows(mode=mode)
    if not rows:
        return {"ok": True, "uploaded": 0, "processed": 0, "error": "Inventario vazio.", "inventory": []}

    ips_raw = data.get("ips")
    keys_raw = data.get("keys")
    selected_ips: list[str] = []
    selected_keys: list[str] = []
    if isinstance(keys_raw, list):
        seen_keys: set[str] = set()
        for it in keys_raw:
            key = str(it or "").strip()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            selected_keys.append(key)
    if isinstance(ips_raw, list):
        seen: set[str] = set()
        for it in ips_raw:
            ip = str(it or "").strip()
            if not ip or ip in seen:
                continue
            seen.add(ip)
            selected_ips.append(ip)

    target_rows: list[dict[str, Any]]
    if selected_keys:
        want_keys = set(selected_keys)
        target_rows = [r for r in rows if isinstance(r, dict) and inventory_row_key(r) in want_keys]
        if not target_rows:
            return {"ok": False, "uploaded": 0, "processed": 0, "error": "Nenhuma camera selecionada encontrada no inventario.", "inventory": rows}
    elif selected_ips:
        want = set(selected_ips)
        target_rows = [r for r in rows if isinstance(r, dict) and str(r.get("ip") or r.get("IP") or "").strip() in want]
        if not target_rows:
            return {"ok": False, "uploaded": 0, "processed": 0, "error": "Nenhuma camera selecionada encontrada no inventario.", "inventory": rows}
    else:
        target_rows = [r for r in rows if isinstance(r, dict)]

    max_batch = int(os.getenv("IMGBB_UPLOAD_MAX_BATCH", "6") or "6")
    if len(target_rows) > max_batch:
        return {
            "ok": False,
            "uploaded": 0,
            "processed": 0,
            "error": f"Selecione no maximo {max_batch} cameras por lote. A tela atual envia automaticamente em lotes.",
            "inventory": rows,
        }

    uploaded_rows, uploaded, err = _upload_imgbb_for_inventory(target_rows)
    uploaded_by_key: dict[str, dict[str, Any]] = {}
    for r in uploaded_rows or []:
        if not isinstance(r, dict):
            continue
        key = inventory_row_key(r)
        if key and (str(r.get("imgbb_url") or "").strip() or str(r.get("imgbb_thumb_url") or "").strip()):
            uploaded_by_key[key] = r

    if uploaded_by_key:
        # `rows` foi carregado no INICIO da requisicao, antes do upload real
        # pro ImgBB (rede, um round-trip por camera). O sync automatico de
        # status Zabbix roda a cada 60s e faz a mesma coisa -- carrega tudo,
        # demora com chamadas de rede, salva tudo -- e o "salva tudo" de um
        # por cima do outro apaga silenciosamente o que o outro acabou de
        # gravar (visto em producao: upload confirmava no log mas o
        # imgbb_url sumia minutos depois). Recarrega aqui, bem antes de
        # salvar, e aplica so os campos do upload por chave.
        fresh_rows = _load_inventory_rows(mode=mode)
        changed = False
        for r in fresh_rows:
            if not isinstance(r, dict):
                continue
            u = uploaded_by_key.get(inventory_row_key(r))
            if not u:
                continue
            imgbb_url = str(u.get("imgbb_url") or u.get("url") or u.get("display_url") or "").strip()
            thumb_url = str(u.get("imgbb_thumb_url") or u.get("thumbnail_url") or u.get("thumb_url") or imgbb_url).strip()
            if imgbb_url:
                r["imgbb_url"] = imgbb_url
            if thumb_url:
                r["imgbb_thumb_url"] = thumb_url
            r["imgbb_status"] = "up"
            r["imgbb_updated_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
        if changed:
            _save_inventory_rows(fresh_rows, mode=mode)
            rows = fresh_rows
    err_text = str(err or "").strip()
    skipped_no_snapshot = 0
    if int(uploaded or 0) == 0 and "nenhum snapshot local" in err_text.lower():
        skipped_no_snapshot = len(target_rows)
    ok = int(uploaded or 0) > 0 or skipped_no_snapshot > 0
    if len(target_rows) == 0:
        ok = True
    return {
        "ok": ok,
        "mode": mode,
        "uploaded": int(uploaded or 0),
        "processed": len(target_rows),
        "skipped_no_snapshot": skipped_no_snapshot,
        "error": err_text,
        "inventory": rows,
    }


# -----------------
# Full backup export/import
# -----------------

def _create_full_backup_zip_file() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    backups_dir = OUTPUT_DIR / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = backups_dir / f"cam-snapshot-backup-{ts}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "app": "SightOps Cam Snapshot",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format": "sightops-full-backup-v1",
            "contains": ["data"] + ([] if OUTPUT_DIR == DATA_DIR else ["output"]),
        }
        zf.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        _zip_add_tree(zf, DATA_DIR, "data")
        if OUTPUT_DIR != DATA_DIR:
            _zip_add_tree(zf, OUTPUT_DIR, "output", exclude_prefixes=["backups"])

    # keep only last 5
    try:
        zips = sorted(backups_dir.glob("cam-snapshot-backup-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in zips[5:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass

    return zip_path


@router.get("/backup/export")
async def api_full_backup_export() -> FileResponse:
    try:
        zip_path = _create_full_backup_zip_file()
        return FileResponse(path=zip_path, media_type="application/zip", filename=zip_path.name)
    except Exception as exc:
        raise HTTPException(500, f"Falha ao gerar backup ZIP: {exc}")


@router.post("/backup/import")
async def api_full_backup_import(file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")

    tmp_root = BASE_DIR / "_tmp_restore"
    _safe_rmtree(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        _safe_extract_zip(zf, tmp_root)

    src_data = tmp_root / "data"
    src_output = tmp_root / "output"
    if not src_data.exists() and not src_output.exists():
        _safe_rmtree(tmp_root)
        raise HTTPException(400, "Backup invalido: nao encontrei as pastas 'data/' ou 'output/' dentro do ZIP.")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    unified_store = OUTPUT_DIR == DATA_DIR

    if unified_store:
        merged = tmp_root / "_merged_data"
        merged.mkdir(parents=True, exist_ok=True)
        if src_data.exists():
            shutil.copytree(src_data, merged, dirs_exist_ok=True)
        if src_output.exists():
            shutil.copytree(src_output, merged, dirs_exist_ok=True)

        if DATA_DIR.exists():
            prev_data = DATA_DIR.parent / f"data_prev_{ts}"
            try:
                if prev_data.exists():
                    _safe_rmtree(prev_data)
                shutil.move(str(DATA_DIR), str(prev_data))
            except Exception:
                pass

        if merged.exists():
            shutil.move(str(merged), str(DATA_DIR))
        else:
            DATA_DIR.mkdir(parents=True, exist_ok=True)

        _safe_rmtree(tmp_root)
        return {
            "ok": True,
            "message": "Backup restaurado.",
            "restored": {"data": True, "output": False, "output_is_alias_of_data": True},
        }

    if DATA_DIR.exists():
        prev_data = DATA_DIR.parent / f"data_prev_{ts}"
        try:
            if prev_data.exists():
                _safe_rmtree(prev_data)
            shutil.move(str(DATA_DIR), str(prev_data))
        except Exception:
            pass

    if OUTPUT_DIR.exists():
        prev_out = OUTPUT_DIR.parent / f"output_prev_{ts}"
        try:
            if prev_out.exists():
                _safe_rmtree(prev_out)
            shutil.move(str(OUTPUT_DIR), str(prev_out))
        except Exception:
            pass

    if src_data.exists():
        shutil.move(str(src_data), str(DATA_DIR))
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    if src_output.exists():
        shutil.move(str(src_output), str(OUTPUT_DIR))
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _safe_rmtree(tmp_root)
    return {"ok": True, "message": "Backup restaurado.", "restored": {"data": True, "output": True}}


# -----------------
# KMZ endpoints (minimal / compat)
# -----------------

@router.post("/kmz/import")
async def api_kmz_import(file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio.")

    kmz_input_dir = tenant_kmz_input_dir() if get_current_tenant_slug() else KMZ_INPUT_DIR
    kmz_imported_path = tenant_kmz_imported_path() if get_current_tenant_slug() else KMZ_IMPORTED_PATH
    kmz_geojson_path = tenant_kmz_imported_geojson_path() if get_current_tenant_slug() else KMZ_IMPORTED_GEOJSON_PATH

    original_name = (file.filename or "import.kmz").strip() or "import.kmz"
    layer_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_name(original_name)}-{secrets.token_hex(3)}"
    layer_kmz_path, layer_geojson_path, layer_meta_path = _kmz_layer_paths(layer_id)
    tmp_import = layer_kmz_path.with_suffix(".tmp.kmz")
    _safe_unlink(tmp_import)
    layer_kmz_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_import.write_bytes(raw)

    try:
        geojson = kmz_to_geojson(tmp_import)
        layer_geojson_path.write_text(
            json.dumps(geojson, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        _safe_unlink(tmp_import)
        raise HTTPException(400, f"Falha ao processar KMZ: {exc}")

    # So persiste o import definitivo apos validar que o KMZ e processavel.
    (kmz_input_dir / f"{layer_id}-{_safe_name(original_name)}.kmz").write_bytes(raw)
    tmp_import.replace(layer_kmz_path)

    layer_meta = {
        "id": layer_id,
        "original_name": original_name,
        "label": Path(original_name).stem,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "features_count": len(geojson.get("features") or []),
        **_sites_para_meta_nova(),
    }
    layer_meta_path.write_text(json.dumps(layer_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Compatibilidade: endpoints antigos seguem apontando para o ultimo importado.
    kmz_imported_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(layer_kmz_path, kmz_imported_path)
    kmz_geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")

    meta_path = kmz_imported_path.with_suffix(".meta.json")
    meta_path.write_text(
        json.dumps({"original_name": original_name, "layer_id": layer_id}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "id": layer_id,
        "path": str(layer_kmz_path),
        "filename": original_name,
        "features_count": len(geojson.get("features") or []),
        "message": "KMZ importado.",
    }


@router.get("/mapa/resolver-link")
def api_mapa_resolver_link(url: str) -> Dict[str, Any]:
    """Link curto do Google Maps (o que chega pelo WhatsApp) -> coordenada.
    So segue enderecos do Google; ver app/services/mapa_link.py."""
    from app.services.mapa_link import resolver_link
    return resolver_link(url)


@router.get("/kmz/import/layers")
async def api_kmz_import_layers(include_features: bool = True) -> Dict[str, Any]:
    layers = _list_kmz_import_layers(include_features=include_features)
    return {"ok": True, "count": len(layers), "layers": layers}


@router.post("/kmz/import/layers")
async def api_kmz_import_layer_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Camada nova, sem arquivo: nasce vazia e os pontos sao marcados no mapa.

    Nao mexe no "ultimo importado" de compatibilidade (KMZ_IMPORTED_PATH):
    uma camada vazia nao deve substituir o mapa que os endpoints antigos leem.
    """
    from app.services.kmz_ops import criar_kmz_vazio

    label = str(payload.get("label") or "").strip()[:120]
    if not label:
        raise HTTPException(400, "Informe o nome da camada.")
    layer_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_name(label)}-{secrets.token_hex(3)}"
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    criar_kmz_vazio(kmz_path, label)
    geojson_path.write_text(json.dumps(kmz_to_geojson(kmz_path), ensure_ascii=False), encoding="utf-8")
    meta = {
        "id": layer_id,
        "original_name": f"{label}.kmz",
        "label": label,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "features_count": 0,
        "origem": "mapa",
        **_sites_para_meta_nova(),
    }
    _write_kmz_layer_meta(meta_path, meta)
    layer = next((l for l in _list_kmz_import_layers(include_features=False) if l["id"] == layer_id), None)
    return {"ok": True, "id": layer_id, "layer": layer}


@router.get("/kmz/import/layers/{layer_id}/download")
async def api_kmz_import_layer_download(layer_id: str) -> FileResponse:
    _exigir_camada_liberada(layer_id)
    kmz_path, _, meta_path = _kmz_layer_paths(layer_id)
    if not kmz_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    filename = str(meta.get("original_name") or kmz_path.name)
    return FileResponse(kmz_path, media_type="application/vnd.google-earth.kmz", filename=filename)


@router.get("/kmz/import/layers/{layer_id}/download-enriched")
async def api_kmz_import_layer_download_enriched(
    layer_id: str,
    source: str = "ip",
    mode: str = "",
) -> FileResponse:
    _exigir_camada_liberada(layer_id)
    kmz_path, filename = _ensure_imported_layer_enriched(layer_id, source=source, mode=mode)
    return FileResponse(kmz_path, media_type="application/vnd.google-earth.kmz", filename=filename)


def _editar_ponto_da_camada(layer_id: str, ponto: Dict[str, Any], generated: bool = False) -> Dict[str, Any]:
    """Grava um ponto no KMZ da camada e regenera o geojson que o mapa le.

    A fonte de verdade continua sendo o KMZ: regerar o geojson dele evita que o
    mapa mostre um ponto que o arquivo baixado nao tem.
    """
    from app.services.kmz_ops import editar_ponto_no_kmz, kmz_to_geojson

    paths_fn = _kmz_generated_layer_paths if generated else _kmz_layer_paths
    kmz_path, geojson_path, meta_path = paths_fn(layer_id)
    if not kmz_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")

    def _coord(chave: str) -> float | None:
        valor = ponto.get(chave)
        if valor in (None, ""):
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Valor invalido para {chave}.")

    if ponto.get("remover") and not permissions.pode_excluir():
        raise permissions.erro_exige_admin()
    try:
        resultado = editar_ponto_no_kmz(
            kmz_path,
            nome=str(ponto.get("nome") or ""),
            lat=_coord("lat"),
            lon=_coord("lon"),
            descricao=str(ponto.get("descricao") or ""),
            remover=bool(ponto.get("remover")),
            novo_nome=str(ponto.get("novo_nome") or ""),
            lat_atual=_coord("lat_atual"),
            lon_atual=_coord("lon_atual"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    geojson_path.write_text(
        json.dumps(kmz_to_geojson(kmz_path), ensure_ascii=False), encoding="utf-8"
    )

    meta = _read_kmz_layer_meta(meta_path)
    meta["id"] = layer_id
    novo_nome = str(ponto.get("novo_nome") or "").strip()
    if novo_nome and not generated and not ponto.get("remover"):
        # renomear o ponto de uma caixa/CTO pelo editor: o cadastro acompanha
        # (senao a caixa ficava presa ao nome antigo e sumia do mapa)
        la, lo = _coord("lat_atual"), _coord("lon_atual")
        try:
            restantes = [str((f.get("properties") or {}).get("name") or "").strip().lower()
                         for f in json.loads(geojson_path.read_text(encoding="utf-8")).get("features") or []]
        except (OSError, ValueError):
            restantes = []
        pos = (la, lo) if la is not None and lo is not None else None
        antigo = str(ponto.get("nome") or "")
        # sem posicao e com o nome antigo ainda no mapa (nome repetido): nao da
        # para saber de qual caixa era -- nao mexe no cadastro
        if pos is not None or antigo.strip().lower() not in restantes:
            _trocar_nome_do_ponto_no_meta(meta, antigo, novo_nome, pos,
                                          unico=restantes.count(novo_nome.lower()) == 1)
    if not generated and not ponto.get("remover"):
        de = (_coord("lat_atual"), _coord("lon_atual"))
        para = (_coord("lat"), _coord("lon"))
        if None not in de and None not in para and de != para:
            _arrastar_ponto_no_meta(meta, str(ponto.get("novo_nome") or ponto.get("nome") or ""), de, para)
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)

    # A copia enriquecida foi gerada do KMZ antigo e ficaria desatualizada.
    if not generated:
        _apagar_geradas_do_mapa(layer_id)

    return resultado


# Ate onde a ponta do cabo conta como "no ponto": o cabo nasce encaixado no
# ponto, mas o KMZ e o meta arredondam diferente.
_PONTA_TOL = 1e-4  # ~11 m
# Curva no meio do cabo: so a que esta EM CIMA do ponto (~1 m); uma curva de
# esquina a 5 m de uma camera nao e da camera.
_CURVA_TOL = 1e-5


def _arrastar_ponto_no_meta(meta: dict, nome: str, de: tuple, para: tuple) -> int:
    """Ponto arrastado no editor: a caixa/CTO dele e a ponta dos cabos ligados
    nele vao junto. Sem isso a caixa perdia o ponto (sumia da tela) e o cabo
    ficava apontando para onde o ponto estava.

    A ponta e escolhida pelo vinculo (cabo da caixa = inicio; cabo ate a CTO
    ou ate a camera = fim) e so anda se estava mesmo no lugar antigo -- uma
    camera a 3 m da caixa nao arrasta o cabo da caixa. Devolve quantos cabos mudaram."""
    alvo = nome.strip().lower()
    if not alvo:
        return 0
    perto = lambda pt, ref: pt is not None and abs(float(pt[0]) - ref[0]) < _PONTA_TOL and abs(float(pt[1]) - ref[1]) < _PONTA_TOL
    em_cima = lambda pt, ref: pt is not None and abs(float(pt[0]) - ref[0]) < _CURVA_TOL and abs(float(pt[1]) - ref[1]) < _CURVA_TOL
    novo = [round(para[0], 7), round(para[1], 7)]
    ids_caixa = set()
    movidos: Dict[str, set] = {"ctos": set(), "cdos": set()}
    for grupo in ("caixas", "ctos", "cdos"):
        for c in (meta.get(grupo) or {}).values():
            if (c.get("ponto") or "").strip().lower() == alvo and c.get("lat") is not None \
                    and perto((c["lat"], c["lng"]), de):
                c["lat"], c["lng"] = novo
                if grupo == "caixas":
                    ids_caixa.add(c.get("id"))
                else:
                    movidos[grupo].add(c.get("id"))
    mudou = 0
    for cb in (meta.get("cabos") or {}).values():
        cam = cb.get("caminho") if isinstance(cb, dict) else None
        if not cam or len(cam) < 2:
            continue
        trocou = False
        if cb.get("caixa") in ids_caixa and perto(cam[0], de):
            cam[0] = list(novo)
            trocou = True
        fim = (cb.get("cto") or {}).get("ponto") if isinstance(cb.get("cto"), dict) else (cb.get("camera") or {}).get("ponto")
        if (fim or "").strip().lower() == alvo and perto(cam[-1], de):
            cam[-1] = list(novo)
            trocou = True
        # Curva do cabo em cima do ponto: o cabo "passa por" camera/CTO/caixa
        # com um clique e o vertice e gravado exatamente na posicao do ponto.
        # Arrastar o ponto leva a curva junto (so as que estavam em cima dele).
        for i in range(1, len(cam) - 1):
            if em_cima(cam[i], de):
                cam[i] = list(novo)
                trocou = True
        if trocou:
            cb["metros"] = _metros_do_caminho(cam)
            cb["metros_com_folga"] = round(cb["metros"] * (1 + int(cb.get("folga_pct") or 0) / 100), 1)
            mudou += 1
    # fibras da rede (tronco OLT->CDO, distribuicao CDO->CTO): pontas pelo id
    # da CDO/CTO; qualquer vertice em cima do ponto tambem vai junto
    for fb in (meta.get("fibras") or {}).values():
        cam = fb.get("caminho") if isinstance(fb, dict) else None
        if not cam or len(cam) < 2:
            continue
        trocou = False
        ini = (fb.get("de") or {}).get("cdo")
        fim = (fb.get("para") or {}).get("cto") or (fb.get("para") or {}).get("cdo")
        if ini and ini in movidos["cdos"] and perto(cam[0], de):
            cam[0] = list(novo); trocou = True
        if fim and (fim in movidos["ctos"] or fim in movidos["cdos"]) and perto(cam[-1], de):
            cam[-1] = list(novo); trocou = True
        for i in range(len(cam)):
            if em_cima(cam[i], de):
                cam[i] = list(novo); trocou = True
        if trocou:
            fb["metros"] = _metros_do_caminho(cam)
            fb["metros_com_folga"] = round(fb["metros"] * (1 + int(fb.get("folga_pct") or 0) / 100), 1)
            mudou += 1
    return mudou


def _remover_linhas_da_camada(layer_id: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    """Exclui linhas (traçados) do KMZ da camada -- uma ou varias. Excluir e
    so administrador (o operador recebe o pedido de senha)."""
    from app.services.kmz_ops import kmz_to_geojson, remover_linhas_no_kmz

    alvos = dados.get("remover") if isinstance(dados.get("remover"), list) else []
    alvos = [a for a in alvos if isinstance(a, dict)]
    if not alvos:
        raise HTTPException(400, "Informe as linhas a excluir.")
    if len(alvos) > 5000:
        raise HTTPException(400, "Linhas demais num pedido.")
    if not permissions.pode_excluir():
        raise permissions.erro_exige_admin()
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    if not kmz_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    with _LOCK_CAIXAS:
        try:
            removidas = remover_linhas_no_kmz(kmz_path, alvos)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if removidas:
            geojson_path.write_text(json.dumps(kmz_to_geojson(kmz_path), ensure_ascii=False), encoding="utf-8")
            meta = _read_kmz_layer_meta(meta_path)
            meta["id"] = _safe_name(layer_id, "layer")
            meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _write_kmz_layer_meta(meta_path, meta)
    if removidas:
        _apagar_geradas_do_mapa(layer_id)
    return {"removidas": removidas}


@router.patch("/kmz/import/layers/{layer_id}")
async def api_kmz_import_layer_update(layer_id: str, payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    _exigir_camada_liberada(layer_id)
    if isinstance(payload.get("ponto"), dict):
        return {"ok": True, **_editar_ponto_da_camada(layer_id, payload["ponto"])}
    if isinstance(payload.get("linhas"), dict):
        return {"ok": True, **_remover_linhas_da_camada(layer_id, payload["linhas"])}
    if isinstance(payload.get("motivo_ponto"), dict):
        u = getattr(request.state, "current_user", None) or {}
        por = str(u.get("username") or "") if isinstance(u, dict) else ""
        return {"ok": True, "layer": _motivo_do_ponto(layer_id, payload["motivo_ponto"], por)}
    if "cor_outros" in payload:
        return {"ok": True, "layer": _cor_outros_da_camada(layer_id, payload.get("cor_outros"))}
    if "modo" in payload:
        return {"ok": True, "layer": _modo_da_camada(layer_id, payload.get("modo"))}
    if isinstance(payload.get("caixa"), dict):
        u = getattr(request.state, "current_user", None) or {}
        return {"ok": True, **_caixa_da_camada(layer_id, payload["caixa"], str(u.get("username") or "") if isinstance(u, dict) else "")}
    if isinstance(payload.get("cabo"), dict):
        u = getattr(request.state, "current_user", None) or {}
        return {"ok": True, **_cabo_da_camada(layer_id, payload["cabo"], str(u.get("username") or "") if isinstance(u, dict) else "")}
    if isinstance(payload.get("cto"), dict):
        u = getattr(request.state, "current_user", None) or {}
        return {"ok": True, **_cto_da_camada(layer_id, payload["cto"], str(u.get("username") or "") if isinstance(u, dict) else "")}
    if isinstance(payload.get("cdo"), dict):
        u = getattr(request.state, "current_user", None) or {}
        return {"ok": True, **_cdo_da_camada(layer_id, payload["cdo"], str(u.get("username") or "") if isinstance(u, dict) else "")}
    if isinstance(payload.get("fibra"), dict):
        u = getattr(request.state, "current_user", None) or {}
        return {"ok": True, **_fibra_da_camada(layer_id, payload["fibra"], str(u.get("username") or "") if isinstance(u, dict) else "")}
    layer = _rename_kmz_layer(layer_id, str(payload.get("label") or ""))
    return {"ok": True, "layer": layer}


def _motivo_do_ponto(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    """Motivo de um ponto do mapa nao ter camera ("camera retirada", "previsto").

    Guardado no meta da camada pelo NOME do ponto -- o mesmo jeito que o Mapa e
    o relatorio casam ponto e camera -- sem mexer no KMZ. Motivo vazio apaga.
    O relatorio do mapa mostra este texto em vez do generico.
    """
    nome = str(dados.get("nome") or "").strip()
    if not nome:
        raise HTTPException(400, "Informe o nome do ponto.")
    motivo = " ".join(str(dados.get("motivo") or "").split())[:300]
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    if not kmz_path.exists() or not geojson_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    motivos = meta.get("motivos") if isinstance(meta.get("motivos"), dict) else {}
    if motivo:
        motivos[nome.lower()] = {"nome": nome, "motivo": motivo, "por": por,
                                 "em": datetime.now().isoformat(timespec="seconds")}
    else:
        motivos.pop(nome.lower(), None)
    meta["id"] = layer_id
    meta["motivos"] = motivos
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    layer = next((item for item in _list_kmz_import_layers(include_features=False) if item.get("id") == layer_id), None)
    return layer or {"id": layer_id, "motivos": motivos}


def _cor_outros_da_camada(layer_id: str, cor: Any) -> dict[str, Any]:
    """Cor dos pontos da camada que nao casam com nenhuma camera.

    Antes eles saiam na cor da propria camada (verde quando quase tudo esta
    online), sem rotulo -- um "tracinho" que ninguem sabia o que era. Vazio
    volta ao laranja padrao, o mesmo da legenda "outros".
    """
    valor = str(cor or "").strip()
    if valor and not re.fullmatch(r"#[0-9a-fA-F]{6}", valor):
        raise HTTPException(400, "Cor invalida: use o formato #rrggbb.")
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    if not kmz_path.exists() or not geojson_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    meta["id"] = layer_id
    meta["cor_outros"] = valor.lower()
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    layer = next((item for item in _list_kmz_import_layers(include_features=False) if item.get("id") == layer_id), None)
    return layer or {"id": layer_id, "cor_outros": meta["cor_outros"]}


_MODOS_CAMADA = ("", "olt", "switch", "basico", "todos")

# --------------------------------------------------------------------------- caixas de CFTV e cabos
# Caixa = um ponto da camada (pelo NOME, como motivos e edicao de ponto) com o
# que tem dentro e as portas do switch. Cabo = caixa -> camera, com o caminho
# desenhado (curvas), tipo, porta e folga; a metragem e calculada aqui.
_TIPOS_ITEM_CAIXA = ("switch_poe", "switch", "onu", "fonte", "nobreak", "dio", "roteador", "injetor_poe", "outro")
_TIPOS_CABO = ("utp5e", "utp6", "drop", "coaxial", "outro")
_UPLINK_PARA = ("onu", "fibra", "radio", "switch", "outro")
# Tipo da caixa: com switch (portas PoE), direto na ONU (camera na porta LAN
# da ONU, com fonte ou injetor) ou so passagem/fonte (sem portas). Caixa
# antiga, sem tipo, e "switch".
_TIPOS_CAIXA = ("switch", "onu", "passagem")
_ALIMENTACAO = ("", "fonte12", "injetor_poe", "poe_switch", "outro")
_MAX_LAN_ONU = 8


def _tipo_da_caixa(caixa: Dict[str, Any]) -> str:
    tipo = str((caixa or {}).get("tipo") or "switch")
    return tipo if tipo in _TIPOS_CAIXA else "switch"


def _equipamento_da_caixa(caixa: Dict[str, Any]) -> str:
    """Nome que vai na coluna SWITCH do inventario: o do switch/ONU, senao o
    da caixa ("ONU <caixa>" quando a camera esta direto na ONU)."""
    nome = str(caixa.get("switch_nome") or "").strip()
    if nome:
        return nome
    base = str(caixa.get("nome") or "").strip()
    return f"ONU {base}".strip() if _tipo_da_caixa(caixa) == "onu" else base


def _vlan_valida(valor: Any) -> str:
    vlan = str(valor or "").strip()
    if vlan and (not vlan.isdigit() or not 1 <= int(vlan) <= 4094):
        raise HTTPException(400, "VLAN invalida (1 a 4094).")
    return str(int(vlan)) if vlan else ""


def _switch_no_inventario(cabos: list, caixa: Dict[str, Any], limpar: bool = False) -> int:
    """Leva para o inventario (colunas SWITCH e PORTA de Cameras IP) o que foi
    ligado no mapa: switch_name/switch_ip/switch_port de cada camera dos cabos.
    limpar=True tira -- so se ainda for deste switch (outra fonte, como a
    tabela MAC do switch gerenciavel, pode ter escrito depois). Todos os modos
    (basico/olt/switch): a camera pode estar em mais de um. VLAN: a da porta
    (cabo) vale sobre a da caixa. Caixa direto na ONU: SWITCH = a ONU e
    PORTA = "LAN N"; caixa de passagem nao tem porta e nao escreve nada."""
    nome = _equipamento_da_caixa(caixa)
    if not limpar and _tipo_da_caixa(caixa) == "passagem":
        return 0
    lan = _tipo_da_caixa(caixa) == "onu"
    sw_ip = str(caixa.get("switch_ip") or "").strip()
    vlan = str(caixa.get("switch_vlan") or "").strip()
    por_ip = {str((c.get("camera") or {}).get("ip") or "").strip(): c for c in cabos}
    por_ip.pop("", None)
    if not por_ip:
        return 0
    sites = permissions.sites_da_sessao()
    sites_ok = {str(x).strip().upper() for x in sites} if sites is not None else None
    mudou = 0
    for modo in ("switch", "olt", "basico"):
        try:
            linhas = load_inventory_json(mode=modo) or []
        except Exception:
            continue
        alterou = False
        for r in linhas:
            if not isinstance(r, dict):
                continue
            cabo = por_ip.get(str(r.get("ip") or r.get("IP") or "").strip())
            if not cabo:
                continue
            if sites_ok is not None and permissions.site_da_linha(r).upper() not in sites_ok:
                continue  # camera de site que o usuario nao acessa (o IP vem da tela)
            if limpar:
                if str(r.get("switch_name") or "") == nome:
                    for k in ("switch_name", "switch_ip", "switch_port", "switch_vlan"):
                        r.pop(k, None)
                    alterou = True
                continue
            r["switch_name"] = nome
            if sw_ip:
                r["switch_ip"] = sw_ip
            porta = str(cabo.get("porta") or "")
            r["switch_port"] = f"LAN{porta}" if lan and porta else porta
            vlan_porta = str(cabo.get("vlan") or "") or vlan
            if vlan_porta:
                r["switch_vlan"] = vlan_porta
            alterou = True
        if alterou:
            save_inventory_json(linhas, mode=modo)
            mudou += 1
    return mudou


def _texto_curto(v: Any, limite: int) -> str:
    return " ".join(str(v or "").split())[:limite]


def _metros_do_caminho(caminho: list) -> float:
    import math

    total = 0.0
    for (la1, lo1), (la2, lo2) in zip(caminho, caminho[1:]):
        p1, p2 = math.radians(la1), math.radians(la2)
        dp, dl = p2 - p1, math.radians(lo2 - lo1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        total += 2 * 6371000 * math.asin(min(1.0, math.sqrt(a)))
    return round(total, 1)


# Le-altera-grava do meta (caixas/cabos) sob um lock: dois operadores salvando
# ao mesmo tempo nao apagam o cabo um do outro (a API roda num processo so).
_LOCK_CAIXAS = threading.Lock()
_MAX_CABOS = 2000


def _meta_da_camada_ou_404(layer_id: str) -> tuple[dict[str, Any], Path]:
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    if not kmz_path.exists() or not geojson_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    # o id SANEADO (o da URL pode trazer lixo depois do ponto, que o
    # _safe_name corta mas iria cru para o meta e para a tela)
    meta["id"] = _safe_name(layer_id, "layer")
    return meta, meta_path


def _exige_admin_para_excluir() -> None:
    from app.core import permissions

    if not permissions.pode_excluir():
        raise permissions.erro_exige_admin()


def _trocar_nome_do_ponto_no_meta(meta: dict, antigo: str, novo: str, pos: Any, unico: bool) -> None:
    """O ponto mudou de nome no KMZ: caixa e CTO daquele lugar, cabos que
    terminam na CTO (guardam so o nome) e o motivo do ponto acompanham."""
    a = str(antigo or "").strip().lower()
    perto = lambda c: (pos is None or c.get("lat") is None
                       or (abs(float(c["lat"]) - pos[0]) < 3e-5 and abs(float(c["lng"]) - pos[1]) < 3e-5))
    for chave in ("caixas", "ctos", "cdos"):
        for c in (meta.get(chave) or {}).values():
            if isinstance(c, dict) and str(c.get("ponto") or "").strip().lower() == a and perto(c):
                c["ponto"] = novo
    if unico:  # cabo da CTO nao tem posicao: so com o nome unico na camada
        for cb in (meta.get("cabos") or {}).values():
            if isinstance(cb, dict) and isinstance(cb.get("cto"), dict) and str(cb["cto"].get("ponto") or "").strip().lower() == a:
                cb["cto"]["ponto"] = novo
        motivos = meta.get("motivos") if isinstance(meta.get("motivos"), dict) else {}
        if a in motivos:
            motivos[novo.lower()] = {**motivos.pop(a), "nome": novo}


def _pontos_da_camada(layer_id: str) -> Optional[list]:
    """[(nome em minusculas, lat, lng)] dos pontos da camada; None se o geojson
    nao der para ler (ai nao da para conferir e a conferencia e pulada)."""
    _kmz, geojson_path, _ = _kmz_layer_paths(layer_id)
    try:
        feats = json.loads(geojson_path.read_text(encoding="utf-8")).get("features") or []
    except (OSError, ValueError):
        return None
    out = []
    for f in feats:
        g = (f or {}).get("geometry") or {}
        if g.get("type") != "Point":
            continue
        try:
            lo, la = float(g["coordinates"][0]), float(g["coordinates"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        out.append((str(((f.get("properties") or {}).get("name")) or "").strip().lower(), la, lo))
    return out


def _seguir_nome_no_ponto(layer_id: str, meta: dict, antigo: str, novo: str, pos: Any) -> str:
    """Renomeia o ponto do KMZ para o nome da caixa/CTO. Devolve aviso (texto)
    quando nao deu: outro ponto ja tem esse nome, ou o nome repete sem posicao."""
    from app.services.kmz_ops import editar_ponto_no_kmz, kmz_to_geojson

    kmz_path, geojson_path, _ = _kmz_layer_paths(layer_id)
    try:
        feats = json.loads(geojson_path.read_text(encoding="utf-8")).get("features") or []
    except (OSError, ValueError):
        feats = []
    nomes = [str((f.get("properties") or {}).get("name") or "").strip().lower() for f in feats
             if (f.get("geometry") or {}).get("type") == "Point"]
    if antigo.strip().lower() not in nomes:
        return f'O ponto "{antigo}" nao foi achado no mapa para receber o nome novo.'
    if novo.strip().lower() in nomes:
        return f'O ponto no mapa continua "{antigo}": ja existe outro ponto "{novo}" nesta camada. Renomeie aquele antes.'
    repetido = nomes.count(antigo.strip().lower()) > 1
    if repetido and pos is None:
        return f'O ponto no mapa continua "{antigo}": esse nome se repete na camada.'
    try:
        editar_ponto_no_kmz(kmz_path, nome=antigo, novo_nome=novo,
                            lat_atual=pos[0] if pos else None, lon_atual=pos[1] if pos else None)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        return f'O ponto no mapa continua "{antigo}": {exc}'
    geojson_path.write_text(json.dumps(kmz_to_geojson(kmz_path), ensure_ascii=False), encoding="utf-8")
    _trocar_nome_do_ponto_no_meta(meta, antigo, novo, pos, unico=not repetido)
    return ""


def _caixa_da_camada(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    with _LOCK_CAIXAS:
        return _caixa_da_camada_sem_lock(layer_id, dados, por)


def _mover_caixa(layer_id: str, meta: dict, meta_path: Path, caixa: dict, dados: Dict[str, Any], cabos: dict) -> None:
    """Move a caixa: o ponto no KMZ (pelo nome + posicao antiga), a posicao
    gravada e a ponta dos cabos dela (metragem refeita)."""
    from app.services.kmz_ops import editar_ponto_no_kmz, kmz_to_geojson

    try:
        de = [float(dados["de"]["lat"]), float(dados["de"]["lng"])]
        para = [float(dados["mover"]["lat"]), float(dados["mover"]["lng"])]
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Informe a posicao antiga (de) e a nova (mover).")
    if not (-90 <= para[0] <= 90 and -180 <= para[1] <= 180):
        raise HTTPException(400, "Posicao fora do mapa.")
    kmz_path, geojson_path, _ = _kmz_layer_paths(layer_id)
    try:
        editar_ponto_no_kmz(kmz_path, nome=str(caixa.get("ponto") or ""), lat=para[0], lon=para[1],
                            lat_atual=de[0], lon_atual=de[1])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    geojson_path.write_text(json.dumps(kmz_to_geojson(kmz_path), ensure_ascii=False), encoding="utf-8")
    caixa["lat"], caixa["lng"] = round(para[0], 7), round(para[1], 7)
    for c in cabos.values():
        cam = c.get("caminho") if isinstance(c, dict) else None
        if not cam or c.get("caixa") != caixa.get("id"):
            continue
        c["caminho"] = [[round(para[0], 7), round(para[1], 7)]] + cam[1:]
        c["metros"] = _metros_do_caminho(c["caminho"])
        c["metros_com_folga"] = round(c["metros"] * (1 + int(c.get("folga_pct") or 0) / 100), 1)
    # cabos de OUTRAS caixas que passam por cima desta (curva no ponto)
    _arrastar_ponto_no_meta({"caixas": {}, "ctos": {}, "cabos": cabos}, str(caixa.get("ponto") or ""), tuple(de), tuple(para))


def _caixa_da_camada_sem_lock(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    meta, meta_path = _meta_da_camada_ou_404(layer_id)
    caixas = meta.get("caixas") if isinstance(meta.get("caixas"), dict) else {}
    cabos = meta.get("cabos") if isinstance(meta.get("cabos"), dict) else {}
    cid = _texto_curto(dados.get("id"), 24)
    aviso = ""
    inventario: Optional[tuple] = None  # (cabos, caixa, limpar) para depois de gravar o meta
    if isinstance(dados.get("mover"), dict):
        if cid not in caixas:
            raise HTTPException(404, "Caixa nao encontrada.")
        _mover_caixa(layer_id, meta, meta_path, caixas[cid], dados, cabos)
        meta["caixas"], meta["cabos"] = caixas, cabos
        meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
        _write_kmz_layer_meta(meta_path, meta)
        _apagar_geradas_do_mapa(layer_id)
        return {"caixas": caixas, "cabos": cabos}
    if dados.get("excluir"):
        if cid not in caixas:
            raise HTTPException(404, "Caixa nao encontrada.")
        _exige_admin_para_excluir()
        inventario = ([v for v in cabos.values() if (v or {}).get("caixa") == cid], caixas[cid], True)
        caixas.pop(cid, None)
        # os cabos dela saem junto (nao ficam "pendurados" no mapa)
        cabos = {k: v for k, v in cabos.items() if (v or {}).get("caixa") != cid}
    else:
        ponto = _texto_curto(dados.get("ponto"), 160)
        if not ponto:
            raise HTTPException(400, "Informe o ponto do mapa que e a caixa.")
        atual = caixas.get(cid) if cid else None
        # o KMZ repete nome de ponto ("Caixa - S 4P" em 14 lugares): a caixa e
        # o ponto pelo nome E pela posicao
        try:
            lat = float(dados["lat"]) if dados.get("lat") not in (None, "") else None
            lng = float(dados["lng"]) if dados.get("lng") not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(400, "Posicao da caixa invalida.")
        if lat is None or lng is None:
            lat, lng = (atual or {}).get("lat"), (atual or {}).get("lng")
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(400, "Posicao da caixa fora do mapa.")

        def _mesmo_lugar(c: dict) -> bool:
            if c.get("lat") is None or lat is None:
                return c.get("lat") is None and lat is None
            return abs(float(c["lat"]) - lat) < 3e-5 and abs(float(c["lng"]) - lng) < 3e-5

        outra = next((c for c in caixas.values() if c.get("ponto", "").lower() == ponto.lower()
                      and c.get("id") != cid and _mesmo_lugar(c)), None)
        if outra:
            raise HTTPException(400, "Este ponto ja e uma caixa.")
        if cid and not atual:
            raise HTTPException(404, "Caixa nao encontrada.")
        # Duas caixas no mesmo lugar: a de baixo some da tela e os cabos dela
        # ficam sem dono visivel (foi assim que a C.CFTV-15 "nova" escondeu a
        # caixa de verdade, com 4 cameras).
        em_cima = next((c for c in caixas.values() if c.get("id") != cid and lat is not None
                        and c.get("lat") is not None and _mesmo_lugar(c)), None)
        if em_cima:
            raise HTTPException(400, f'Ja existe a caixa "{em_cima.get("nome") or em_cima.get("ponto")}" neste lugar do mapa. Abra aquela em vez de criar outra.')
        # A caixa e o ponto do mapa pelo nome E pela posicao: um ponto com
        # esse nome que fica em outro lugar nao serve (a caixa sumia da tela).
        pontos = _pontos_da_camada(layer_id)
        if pontos and lat is not None and not any(
                n == ponto.strip().lower() and abs(pla - lat) < 1e-4 and abs(plo - lng) < 1e-4 for n, pla, plo in pontos):
            raise HTTPException(400, f'O ponto "{ponto}" nao esta neste lugar do mapa. Feche o painel e abra a caixa clicando no ponto dela.')
        # Renomear para o nome de outro ponto: recusa sem gravar nada. Gravar
        # "assim mesmo" deixava a caixa com um nome que o mapa nao tem aqui.
        nome_novo = _texto_curto(dados.get("nome"), 80) or ponto
        if pontos and nome_novo.strip().lower() != ponto.strip().lower() \
                and any(n == nome_novo.strip().lower() for n, _la, _lo in pontos):
            dono = next((c for c in caixas.values() if c.get("id") != cid
                         and (c.get("ponto") or "").strip().lower() == nome_novo.strip().lower()), None)
            de_quem = f' (a caixa {dono.get("nome") or dono.get("ponto")})' if dono else ''
            raise HTTPException(400, f'Ja existe outro ponto "{nome_novo}" nesta camada{de_quem}. Escolha outro nome ou renomeie aquele antes.')
        if not atual and len(caixas) >= 500:
            raise HTTPException(400, "Limite de caixas na camada.")
        itens = []
        for it in (dados.get("itens") if isinstance(dados.get("itens"), list) else [])[:30]:
            if not isinstance(it, dict):
                continue
            tipo = _texto_curto(it.get("tipo"), 20)
            if tipo not in _TIPOS_ITEM_CAIXA:
                raise HTTPException(400, f"Item invalido: {tipo}")
            try:
                qtd = max(1, min(int(it.get("qtd") or 1), 99))
            except (TypeError, ValueError):
                qtd = 1
            itens.append({"tipo": tipo, "modelo": _texto_curto(it.get("modelo"), 80), "qtd": qtd,
                          "obs": _texto_curto(it.get("obs"), 120)})
        tipo = _texto_curto(dados.get("tipo") or (atual or {}).get("tipo") or "switch", 10)
        if tipo not in _TIPOS_CAIXA:
            raise HTTPException(400, "Tipo de caixa invalido.")
        try:
            padrao = 4 if tipo == "onu" else 8
            portas = max(0, min(int(dados.get("portas") if dados.get("portas") is not None else padrao), 64))
        except (TypeError, ValueError):
            raise HTTPException(400, "Numero de portas invalido.")
        if tipo == "passagem":
            portas = 0
        elif tipo == "onu" and not 1 <= portas <= _MAX_LAN_ONU:
            raise HTTPException(400, f"A ONU tem de 1 a {_MAX_LAN_ONU} portas LAN.")
        em_uso = [int(v.get("porta")) for v in cabos.values() if (v or {}).get("caixa") == cid and v.get("porta")]
        if em_uso and max(em_uso) > portas:
            raise HTTPException(400, f"A porta {max(em_uso)} tem cabo ligado: a caixa nao pode ter menos portas. Tire o cabo da porta antes.")
        agora = datetime.now().isoformat(timespec="seconds")
        cid = cid or f"cx{uuid.uuid4().hex[:10]}"
        sw_ip = _texto_curto(dados.get("switch_ip"), 45)
        if sw_ip:
            try:
                ipaddress.ip_address(sw_ip)
            except ValueError:
                raise HTTPException(400, "IP do switch invalido.")
        try:
            uplinks = max(0, min(int(dados.get("uplinks") if dados.get("uplinks") is not None else 1), 8))
        except (TypeError, ValueError):
            raise HTTPException(400, "Numero de portas de uplink invalido.")
        vlan = _vlan_valida(dados.get("switch_vlan"))
        uplink_para = _texto_curto(dados.get("uplink_para") or "onu", 10)
        if uplink_para not in _UPLINK_PARA:
            raise HTTPException(400, "Destino do uplink invalido.")
        caixas[cid] = {
            "id": cid, "ponto": ponto, "nome": _texto_curto(dados.get("nome"), 80) or ponto, "tipo": tipo,
            "lat": round(lat, 7) if lat is not None else None, "lng": round(lng, 7) if lng is not None else None,
            "itens": itens, "portas": portas, "obs": _texto_curto(dados.get("obs"), 300),
            # o switch da caixa: nome e portas vao para o inventario das cameras
            "switch_nome": _texto_curto(dados.get("switch_nome"), 60),
            "switch_modelo": _texto_curto(dados.get("switch_modelo"), 80),
            "switch_ip": sw_ip, "switch_vlan": vlan,
            "uplinks": uplinks if tipo == "switch" else 0, "uplink_para": uplink_para,
            "uplink_obs": _texto_curto(dados.get("uplink_obs"), 80),
            "criado_em": (atual or {}).get("criado_em") or agora, "criado_por": (atual or {}).get("criado_por") or por,
            "atualizado_em": agora, "atualizado_por": por,
        }
        dela = [v for v in cabos.values() if (v or {}).get("caixa") == cid and not (v or {}).get("cto")]
        if atual and dela and any((c.get("camera") or {}).get("ip") for c in dela):
            # salvar a caixa sempre leva o switch/porta das cameras dela ao
            # inventario (cabos feitos antes de existir o switch tambem entram);
            # mudou o nome ou o tipo: tira o antigo antes
            if (_equipamento_da_caixa(atual), _tipo_da_caixa(atual)) != (_equipamento_da_caixa(caixas[cid]), tipo):
                _switch_no_inventario(dela, atual, limpar=True)
            inventario = (dela, caixas[cid], False)
        # o ponto do mapa leva o nome da caixa: senao o rotulo diz C.CFTV-02 e
        # o ponto continua C.CFTV-01 (e "ja existe um ponto C.CFTV-01")
        if caixas[cid]["nome"].lower() != ponto.lower():
            meta["caixas"], meta["cabos"] = caixas, cabos
            aviso = _seguir_nome_no_ponto(layer_id, meta, ponto, caixas[cid]["nome"],
                                          (lat, lng) if lat is not None else None)
    meta["caixas"], meta["cabos"] = caixas, cabos
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    if inventario:
        _switch_no_inventario(*inventario)
    if not aviso and not dados.get("excluir") and caixas.get(cid, {}).get("ponto") != ponto:
        _apagar_geradas_do_mapa(layer_id)
    return {"caixas": caixas, "cabos": cabos, "ctos": meta.get("ctos") or {}, "aviso": aviso}


# --------------------------------------------------------------------------- CTO
# A CTO e um ponto da camada (pelo nome E posicao, como a caixa) com splitter,
# origem (OLT/PON, de qual CDO/CTO vem) e as portas: em cada uma, a ONU que
# esta ligada (entity_key do monitoramento, para mostrar sinal e status). As
# caixas ligadas por cabo drop ({cto:{ponto,porta}}) ocupam a porta sozinhas.
# CTO e passiva: nao tem host no Zabbix; as ONUs das portas ja tem.

_SPLITTERS = ("", "1:2", "1:4", "1:8", "1:16", "1:32", "1:64")
_NIVEIS_CTO = ("", "primario", "secundario")


def _cto_da_camada(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    with _LOCK_CAIXAS:
        return _cto_da_camada_sem_lock(layer_id, dados, por)


def _cto_da_camada_sem_lock(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    meta, meta_path = _meta_da_camada_ou_404(layer_id)
    ctos = meta.get("ctos") if isinstance(meta.get("ctos"), dict) else {}
    cabos = meta.get("cabos") if isinstance(meta.get("cabos"), dict) else {}
    tid = _texto_curto(dados.get("id"), 24)
    aviso = ""
    if dados.get("excluir"):
        if tid not in ctos:
            raise HTTPException(404, "CTO nao encontrada.")
        _exige_admin_para_excluir()
        ctos.pop(tid, None)  # o ponto e os cabos das caixas continuam no mapa
        # a fibra de distribuicao ate ela sai junto (nao fica cabo sem destino)
        if isinstance(meta.get("fibras"), dict):
            meta["fibras"] = {k: v for k, v in meta["fibras"].items() if (v or {}).get("para", {}).get("cto") != tid}
    else:
        ponto = _texto_curto(dados.get("ponto"), 160)
        if not ponto:
            raise HTTPException(400, "Informe o ponto do mapa que e a CTO.")
        atual = ctos.get(tid) if tid else None
        if tid and not atual:
            raise HTTPException(404, "CTO nao encontrada.")
        try:
            lat = float(dados["lat"]) if dados.get("lat") not in (None, "") else None
            lng = float(dados["lng"]) if dados.get("lng") not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(400, "Posicao da CTO invalida.")
        if lat is None or lng is None:
            lat, lng = (atual or {}).get("lat"), (atual or {}).get("lng")
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(400, "Posicao da CTO fora do mapa.")

        def _mesmo_lugar(c: dict) -> bool:
            if c.get("lat") is None or lat is None:
                return c.get("lat") is None and lat is None
            return abs(float(c["lat"]) - lat) < 3e-5 and abs(float(c["lng"]) - lng) < 3e-5

        if any(c.get("ponto", "").lower() == ponto.lower() and c.get("id") != tid and _mesmo_lugar(c) for c in ctos.values()):
            raise HTTPException(400, "Este ponto ja e uma CTO.")
        if not atual and len(ctos) >= 1000:
            raise HTTPException(400, "Limite de CTOs na camada.")
        splitter = _texto_curto(dados.get("splitter"), 5)
        if splitter not in _SPLITTERS:
            raise HTTPException(400, "Splitter invalido.")
        nivel = _texto_curto(dados.get("nivel"), 12)
        if nivel not in _NIVEIS_CTO:
            raise HTTPException(400, "Nivel do splitter invalido.")
        try:
            padrao = int(splitter.split(":")[1]) if splitter else 8
            portas = int(dados.get("portas") if dados.get("portas") not in (None, "") else padrao)
        except (TypeError, ValueError):
            raise HTTPException(400, "Numero de portas invalido.")
        if not 1 <= portas <= 64:
            raise HTTPException(400, "A CTO tem de 1 a 64 portas.")
        # porta com caixa ligada nao some
        em_uso = [int((c.get("cto") or {}).get("porta") or 0) for c in cabos.values()
                  if isinstance(c, dict) and str((c.get("cto") or {}).get("ponto") or "").lower() == ponto.lower()]
        if em_uso and max(em_uso) > portas:
            raise HTTPException(400, f"A porta {max(em_uso)} tem caixa ligada: a CTO nao pode ter menos portas.")
        onus: Dict[str, Any] = {}
        vistos: set = set()
        bruto = dados.get("portas_info") if isinstance(dados.get("portas_info"), dict) else {}
        for chave, info in list(bruto.items())[:64]:
            try:
                n = int(chave)
            except (TypeError, ValueError):
                raise HTTPException(400, "Porta invalida.")
            if not 1 <= n <= portas or not isinstance(info, dict):
                raise HTTPException(400, f"Porta {chave} fora da CTO (1 a {portas}).")
            item = {"onu_key": _texto_curto(info.get("onu_key"), 200), "onu_nome": _texto_curto(info.get("onu_nome"), 80),
                    "obs": _texto_curto(info.get("obs"), 120)}
            if item["onu_key"]:
                if item["onu_key"] in vistos:
                    raise HTTPException(400, f"A ONU {item['onu_nome'] or item['onu_key']} esta em duas portas.")
                vistos.add(item["onu_key"])
            if item["onu_key"] or item["obs"]:
                onus[str(n)] = item
        agora = datetime.now().isoformat(timespec="seconds")
        tid = tid or f"ct{uuid.uuid4().hex[:10]}"
        ctos[tid] = {
            "id": tid, "ponto": ponto, "nome": _texto_curto(dados.get("nome"), 80) or ponto,
            "lat": round(lat, 7) if lat is not None else None, "lng": round(lng, 7) if lng is not None else None,
            "modelo": _texto_curto(dados.get("modelo"), 80), "splitter": splitter, "nivel": nivel, "portas": portas,
            "olt_key": _texto_curto(dados.get("olt_key"), 200), "olt_nome": _texto_curto(dados.get("olt_nome"), 80),
            "pon": _texto_curto(dados.get("pon"), 20), "vem_de": _texto_curto(dados.get("vem_de"), 160),
            "portas_info": onus, "obs": _texto_curto(dados.get("obs"), 300),
            "criado_em": (atual or {}).get("criado_em") or agora, "criado_por": (atual or {}).get("criado_por") or por,
            "atualizado_em": agora, "atualizado_por": por,
        }
        if ctos[tid]["nome"].lower() != ponto.lower():
            meta["ctos"], meta["cabos"] = ctos, cabos
            aviso = _seguir_nome_no_ponto(layer_id, meta, ponto, ctos[tid]["nome"],
                                          (lat, lng) if lat is not None else None)
            if not aviso:
                _apagar_geradas_do_mapa(layer_id)
    meta["ctos"] = ctos
    _herdar_da_cdo(meta)
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    return {**_rede_da_camada(meta), "aviso": aviso}


# --------------------------------------------------------------------------- CDO
# A CDO (caixa de emenda com o splitter PRIMARIO) e filha da OLT e mae das
# CTOs: OLT/PON -> cabo tronco -> CDO (splitter balanceado) -> cabo de
# distribuicao -> CTO (splitter secundario) -> caixa CFTV -> cameras.
# Ponto da camada (pelo nome E posicao, como CTO e caixa). Os cabos da rede
# optica ficam em meta["fibras"], separados dos cabos das caixas, e ligam pelo
# ID (renomear nao solta). Ligar a CTO numa CDO faz a CTO herdar OLT, PON e
# "vem de" -- CTO sem CDO continua como era (direto na OLT).

_SPLITTERS_CDO = ("", "1:2", "1:4", "1:8", "1:16", "1:32", "1:64")
# splitter: CDO de verdade (atende CTOs pelas portas). passagem: caixa de emenda
# (CEO) so de passagem/derivacao -- sem splitter, nao atende CTO por porta.
_TIPOS_CDO = ("splitter", "passagem")
_FIBRAS_POR_CABO = (1, 2, 4, 6, 12, 24, 36, 48, 72, 96, 144)
# Codigo de cores de fibra (ABNT NBR 14160 / EIA-598): a 13a fibra repete a
# cor no 2o tubo; o tubo tambem segue a sequencia.
_CORES_FIBRA = ("verde", "amarela", "branca", "azul", "vermelha", "violeta",
                "marrom", "rosa", "preta", "cinza", "laranja", "aqua")
_TIPOS_FIBRA = ("tronco", "distribuicao")


def cor_da_fibra(n: int) -> dict:
    n = max(1, int(n))
    tubo = (n - 1) // 12 + 1
    return {"fibra": n, "cor": _CORES_FIBRA[(n - 1) % 12], "tubo": tubo, "tubo_cor": _CORES_FIBRA[(tubo - 1) % 12]}


def _rede_da_camada(meta: dict) -> dict:
    return {k: (meta.get(k) if isinstance(meta.get(k), dict) else {})
            for k in ("caixas", "cabos", "ctos", "cdos", "fibras")}


def _herdar_da_cdo(meta: dict) -> None:
    """CTO ligada a uma CDO (fibra de distribuicao) herda OLT, PON e "vem de".
    CTO que perdeu a fibra fica com o ultimo valor e sem o vinculo."""
    ctos = meta.get("ctos") if isinstance(meta.get("ctos"), dict) else {}
    cdos = meta.get("cdos") if isinstance(meta.get("cdos"), dict) else {}
    ligadas = set()
    for fid, fb in (meta.get("fibras") or {}).items():
        if not isinstance(fb, dict) or fb.get("tipo") != "distribuicao":
            continue
        cto = ctos.get((fb.get("para") or {}).get("cto"))
        cdo = cdos.get((fb.get("de") or {}).get("cdo"))
        if not cto or not cdo:
            continue
        ligadas.add(cto["id"])
        cto["cdo"] = {"id": cdo["id"], "porta": (fb.get("de") or {}).get("porta"), "fibra_id": fid}
        cto["olt_key"], cto["olt_nome"], cto["pon"] = cdo.get("olt_key", ""), cdo.get("olt_nome", ""), cdo.get("pon", "")
        cto["vem_de"] = cdo.get("nome") or cdo.get("ponto") or ""
    for cto in ctos.values():
        if isinstance(cto, dict) and cto.get("cdo") and cto.get("id") not in ligadas:
            cto.pop("cdo", None)


def _cdo_da_camada(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    with _LOCK_CAIXAS:
        return _cdo_da_camada_sem_lock(layer_id, dados, por)


def _cdo_da_camada_sem_lock(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    meta, meta_path = _meta_da_camada_ou_404(layer_id)
    cdos = meta.get("cdos") if isinstance(meta.get("cdos"), dict) else {}
    fibras = meta.get("fibras") if isinstance(meta.get("fibras"), dict) else {}
    did = _texto_curto(dados.get("id"), 24)
    aviso = ""
    if dados.get("excluir"):
        if did not in cdos:
            raise HTTPException(404, "CDO nao encontrada.")
        _exige_admin_para_excluir()
        cdos.pop(did, None)
        # as fibras dela saem junto; as CTOs ficam com a ultima OLT/PON
        fibras = {k: v for k, v in fibras.items()
                  if (v or {}).get("de", {}).get("cdo") != did and (v or {}).get("para", {}).get("cdo") != did}
    else:
        ponto = _texto_curto(dados.get("ponto"), 160)
        if not ponto:
            raise HTTPException(400, "Informe o ponto do mapa que e a CDO.")
        atual = cdos.get(did) if did else None
        if did and not atual:
            raise HTTPException(404, "CDO nao encontrada.")
        try:
            lat = float(dados["lat"]) if dados.get("lat") not in (None, "") else None
            lng = float(dados["lng"]) if dados.get("lng") not in (None, "") else None
        except (TypeError, ValueError):
            raise HTTPException(400, "Posicao da CDO invalida.")
        if lat is None or lng is None:
            lat, lng = (atual or {}).get("lat"), (atual or {}).get("lng")
        elif not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(400, "Posicao da CDO fora do mapa.")
        if lat is not None and any(c.get("id") != did and c.get("lat") is not None
                                   and abs(float(c["lat"]) - lat) < 3e-5 and abs(float(c["lng"]) - lng) < 3e-5
                                   for c in cdos.values()):
            raise HTTPException(400, "Ja existe uma CDO neste lugar do mapa.")
        if not atual and len(cdos) >= 500:
            raise HTTPException(400, "Limite de CDOs na camada.")
        tipo_cdo = _texto_curto(dados.get("tipo") or (atual or {}).get("tipo") or "splitter", 10)
        if tipo_cdo not in _TIPOS_CDO:
            raise HTTPException(400, "Tipo de caixa invalido (splitter ou passagem).")
        splitter = "" if tipo_cdo == "passagem" else _texto_curto(dados.get("splitter"), 5)
        if splitter not in _SPLITTERS_CDO:
            raise HTTPException(400, "Splitter invalido (balanceado: 1:2 a 1:64).")
        try:
            padrao = int(splitter.split(":")[1]) if splitter else 8
            portas = 0 if tipo_cdo == "passagem" else int(dados.get("portas") if dados.get("portas") not in (None, "") else padrao)
            bandejas = int(dados.get("bandejas") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Numero de portas ou bandejas invalido.")
        if tipo_cdo == "splitter" and not 1 <= portas <= 64:
            raise HTTPException(400, "A CDO tem de 1 a 64 portas.")
        if not 0 <= bandejas <= 48:
            raise HTTPException(400, "Bandejas: de 0 a 48.")
        em_uso = [int((v.get("de") or {}).get("porta") or 0) for v in fibras.values()
                  if isinstance(v, dict) and (v.get("de") or {}).get("cdo") == did]
        if did and em_uso and max(em_uso) > portas:
            raise HTTPException(400, f"A porta {max(em_uso)} tem CTO ligada: tire os cabos de distribuicao antes"
                                     + (" de virar caixa de passagem." if tipo_cdo == "passagem" else " de diminuir as portas."))
        agora = datetime.now().isoformat(timespec="seconds")
        did = did or f"cd{uuid.uuid4().hex[:10]}"
        cdos[did] = {
            "id": did, "ponto": ponto, "nome": _texto_curto(dados.get("nome"), 80) or ponto,
            "lat": round(lat, 7) if lat is not None else None, "lng": round(lng, 7) if lng is not None else None,
            "modelo": _texto_curto(dados.get("modelo"), 80), "tipo": tipo_cdo, "splitter": splitter, "portas": portas,
            "bandejas": bandejas,
            "olt_key": _texto_curto(dados.get("olt_key"), 200), "olt_nome": _texto_curto(dados.get("olt_nome"), 80),
            "pon": _texto_curto(dados.get("pon"), 20), "obs": _texto_curto(dados.get("obs"), 300),
            "criado_em": (atual or {}).get("criado_em") or agora, "criado_por": (atual or {}).get("criado_por") or por,
            "atualizado_em": agora, "atualizado_por": por,
        }
        if cdos[did]["nome"].lower() != ponto.lower():
            meta["cdos"], meta["fibras"] = cdos, fibras
            aviso = _seguir_nome_no_ponto(layer_id, meta, ponto, cdos[did]["nome"],
                                          (lat, lng) if lat is not None else None)
            if not aviso:
                _apagar_geradas_do_mapa(layer_id)
    meta["cdos"], meta["fibras"] = cdos, fibras
    _herdar_da_cdo(meta)  # OLT/PON da CDO desce para as CTOs filhas
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    return {**_rede_da_camada(meta), "aviso": aviso}


def _fibra_da_camada(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    with _LOCK_CAIXAS:
        return _fibra_da_camada_sem_lock(layer_id, dados, por)


def _fibra_da_camada_sem_lock(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    """Cabo da rede optica. tronco: OLT/PON -> CDO. distribuicao: porta da CDO -> CTO."""
    meta, meta_path = _meta_da_camada_ou_404(layer_id)
    cdos = meta.get("cdos") if isinstance(meta.get("cdos"), dict) else {}
    ctos = meta.get("ctos") if isinstance(meta.get("ctos"), dict) else {}
    fibras = meta.get("fibras") if isinstance(meta.get("fibras"), dict) else {}
    fid = _texto_curto(dados.get("id"), 24)
    if dados.get("excluir"):
        if fid not in fibras:
            raise HTTPException(404, "Cabo nao encontrado.")
        _exige_admin_para_excluir()
        fibras.pop(fid, None)
    else:
        atual = fibras.get(fid) if fid else None
        if fid and not atual:
            raise HTTPException(404, "Cabo nao encontrado.")
        tipo = _texto_curto(dados.get("tipo"), 14)
        if tipo not in _TIPOS_FIBRA:
            raise HTTPException(400, "Tipo de cabo invalido (tronco ou distribuicao).")
        try:
            n_fibras = int(dados.get("fibras") or 12)
            fibra = int(dados.get("fibra") or 1)
            folga = max(0, min(int(dados.get("folga_pct") or 0), 100))
        except (TypeError, ValueError):
            raise HTTPException(400, "Fibras invalidas.")
        if n_fibras not in _FIBRAS_POR_CABO:
            raise HTTPException(400, "Numero de fibras do cabo invalido.")
        if not 1 <= fibra <= n_fibras:
            raise HTTPException(400, f"A fibra usada vai de 1 a {n_fibras}.")
        caminho = _caminho_do_cabo(dados)
        de_raw = dados.get("de") if isinstance(dados.get("de"), dict) else {}
        para_raw = dados.get("para") if isinstance(dados.get("para"), dict) else {}
        if tipo == "distribuicao":
            cdo = cdos.get(_texto_curto(de_raw.get("cdo"), 24))
            cto = ctos.get(_texto_curto(para_raw.get("cto"), 24))
            if not cdo:
                raise HTTPException(400, "CDO de origem nao encontrada (cadastre a CDO antes).")
            if cdo.get("tipo") == "passagem":
                raise HTTPException(400, "Caixa de passagem nao tem splitter: ligue a CTO na CDO com splitter (o cabo pode passar por esta caixa).")
            if not cto:
                raise HTTPException(400, "CTO de destino nao encontrada (cadastre a CTO antes).")
            try:
                porta = int(de_raw.get("porta") or 0)
            except (TypeError, ValueError):
                porta = 0
            if not 1 <= porta <= int(cdo.get("portas") or 0):
                raise HTTPException(400, f"Escolha a porta da CDO (1 a {cdo.get('portas')}).")
            for k, v in fibras.items():
                if k == fid or not isinstance(v, dict) or v.get("tipo") != "distribuicao":
                    continue
                if (v.get("de") or {}).get("cdo") == cdo["id"] and int((v.get("de") or {}).get("porta") or 0) == porta:
                    raise HTTPException(400, f"A porta {porta} da CDO ja atende outra CTO.")
                if (v.get("para") or {}).get("cto") == cto["id"]:
                    raise HTTPException(400, "Esta CTO ja esta ligada a uma CDO. Tire aquele cabo antes.")
            de, para = {"cdo": cdo["id"], "porta": porta}, {"cto": cto["id"]}
        else:
            cdo = cdos.get(_texto_curto(para_raw.get("cdo"), 24))
            if not cdo:
                raise HTTPException(400, "CDO de destino nao encontrada (cadastre a CDO antes).")
            for k, v in fibras.items():
                if k != fid and isinstance(v, dict) and v.get("tipo") == "tronco" and (v.get("para") or {}).get("cdo") == cdo["id"]:
                    raise HTTPException(400, "Esta CDO ja tem cabo tronco. Edite aquele.")
            de = {"olt_key": _texto_curto(de_raw.get("olt_key"), 200), "olt_nome": _texto_curto(de_raw.get("olt_nome"), 80),
                  "pon": _texto_curto(de_raw.get("pon"), 20)}
            para = {"cdo": cdo["id"]}
            # o tronco diz de qual OLT/PON vem a CDO (e dai as CTOs dela)
            if de["olt_key"] or de["pon"]:
                cdo["olt_key"], cdo["olt_nome"], cdo["pon"] = de["olt_key"], de["olt_nome"], de["pon"]
        if not atual and len(fibras) >= 2000:
            raise HTTPException(400, "Limite de cabos de fibra na camada.")
        # religar um cabo existente em outra CDO/CTO/porta = excluir + criar:
        # mesma regra do cabo de camera (so admin)
        if atual and (atual.get("tipo") != tipo or atual.get("de", {}).get("cdo") != de.get("cdo")
                      or atual.get("de", {}).get("porta") != de.get("porta") or atual.get("para") != para):
            _exige_admin_para_excluir()
        agora = datetime.now().isoformat(timespec="seconds")
        metros = _metros_do_caminho(caminho)
        fid = fid or f"fb{uuid.uuid4().hex[:10]}"
        fibras[fid] = {
            "id": fid, "tipo": tipo, "de": de, "para": para, "caminho": caminho,
            "fibras": n_fibras, "fibra": fibra, **{k: v for k, v in cor_da_fibra(fibra).items() if k != "fibra"},
            "metros": metros, "folga_pct": folga, "metros_com_folga": round(metros * (1 + folga / 100), 1),
            "obs": _texto_curto(dados.get("obs"), 200),
            "criado_em": (atual or {}).get("criado_em") or agora, "criado_por": (atual or {}).get("criado_por") or por,
            "atualizado_em": agora, "atualizado_por": por,
        }
    meta["cdos"], meta["fibras"] = cdos, fibras
    _herdar_da_cdo(meta)
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    return _rede_da_camada(meta)


def _caminho_do_cabo(dados: Dict[str, Any]) -> list:
    bruto = dados.get("caminho") if isinstance(dados.get("caminho"), list) else []
    caminho = []
    for p in bruto[:300]:
        try:
            lat, lng = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise HTTPException(400, "Caminho do cabo invalido.")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(400, "Coordenada fora do mapa.")
        caminho.append([round(lat, 7), round(lng, 7)])
    if len(caminho) < 2:
        raise HTTPException(400, "O cabo precisa de pelo menos dois pontos.")
    return caminho


def _gravar_cabo(meta: dict, meta_path: Path, caixas: dict, cabos: dict, kid: str, caixa: dict,
                 dados: Dict[str, Any], por: str, cto: dict) -> dict[str, Any]:
    """Cabo da ONU da caixa ate a CTO (fibra drop). Nao vai ao inventario de cameras."""
    tipo = _texto_curto(dados.get("tipo") or "drop", 10)
    if tipo not in _TIPOS_CABO:
        raise HTTPException(400, "Tipo de cabo invalido.")
    caminho = _caminho_do_cabo(dados)
    try:
        folga = max(0, min(int(dados.get("folga_pct") if dados.get("folga_pct") is not None else 10), 100))
    except (TypeError, ValueError):
        folga = 10
    metros = _metros_do_caminho(caminho)
    agora = datetime.now().isoformat(timespec="seconds")
    kid = kid or f"cb{uuid.uuid4().hex[:10]}"
    cabos[kid] = {
        "id": kid, "caixa": caixa["id"], "cto": cto, "camera": {}, "tipo": tipo, "porta": None, "folga_pct": folga,
        "caminho": caminho, "metros": metros, "metros_com_folga": round(metros * (1 + folga / 100), 1),
        "criado_em": (cabos.get(kid) or {}).get("criado_em") or agora, "criado_por": (cabos.get(kid) or {}).get("criado_por") or por,
        "atualizado_em": agora,
    }
    meta["cabos"] = cabos
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    return {"caixas": caixas, "cabos": cabos}


def _cabo_da_camada(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    with _LOCK_CAIXAS:
        return _cabo_da_camada_sem_lock(layer_id, dados, por)


def _cabo_da_camada_sem_lock(layer_id: str, dados: Dict[str, Any], por: str = "") -> dict[str, Any]:
    meta, meta_path = _meta_da_camada_ou_404(layer_id)
    caixas = meta.get("caixas") if isinstance(meta.get("caixas"), dict) else {}
    cabos = meta.get("cabos") if isinstance(meta.get("cabos"), dict) else {}
    kid = _texto_curto(dados.get("id"), 24)
    inventario: Optional[tuple] = None
    _limpar_depois: Optional[tuple] = None
    antigo_cabo = dict(cabos[kid]) if kid in cabos else None
    if dados.get("excluir"):
        if kid not in cabos:
            raise HTTPException(404, "Cabo nao encontrado.")
        _exige_admin_para_excluir()
        caixa_do_cabo = caixas.get(cabos[kid].get("caixa")) or {}
        inventario = ([cabos[kid]], caixa_do_cabo, True)
        cabos.pop(kid, None)
    else:
        caixa = caixas.get(_texto_curto(dados.get("caixa"), 24))
        if not caixa:
            raise HTTPException(400, "Caixa nao encontrada nesta camada.")
        if kid and kid not in cabos:
            raise HTTPException(404, "Cabo nao encontrado.")
        if not kid and len(cabos) >= _MAX_CABOS:
            raise HTTPException(400, "Limite de cabos na camada.")
        tipo = _texto_curto(dados.get("tipo") or "utp5e", 10)
        if tipo not in _TIPOS_CABO:
            raise HTTPException(400, "Tipo de cabo invalido.")
        bruto = dados.get("caminho") if isinstance(dados.get("caminho"), list) else []
        caminho = []
        for p in bruto[:300]:
            try:
                lat, lng = float(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                raise HTTPException(400, "Caminho do cabo invalido.")
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise HTTPException(400, "Coordenada fora do mapa.")
            caminho.append([round(lat, 7), round(lng, 7)])
        if len(caminho) < 2:
            raise HTTPException(400, "O cabo precisa de pelo menos dois pontos.")
        cto = dados.get("cto") if isinstance(dados.get("cto"), dict) else None
        camera = dados.get("camera") if isinstance(dados.get("camera"), dict) else {}
        destino = {"ponto": _texto_curto(camera.get("ponto"), 160), "ip": _texto_curto(camera.get("ip"), 45)}
        if cto is not None:
            # ONU da caixa ligada numa CTO: um por caixa, porta da CTO (nao do switch)
            ponto_cto = _texto_curto(cto.get("ponto"), 160)
            if not ponto_cto:
                raise HTTPException(400, "Informe a CTO.")
            try:
                porta_cto = int(cto.get("porta")) if cto.get("porta") not in (None, "") else None
            except (TypeError, ValueError):
                raise HTTPException(400, "Porta da CTO invalida.")
            if porta_cto is not None and not 1 <= porta_cto <= 64:
                raise HTTPException(400, "Porta da CTO invalida (1 a 64).")
            if kid:
                antigo = cabos[kid]
                if antigo.get("caixa") != caixa["id"] or (antigo.get("cto") or {}).get("ponto") != ponto_cto:
                    _exige_admin_para_excluir()  # trocar a CTO = excluir + criar
            na_porta = porta_cto and next((c for k, c in cabos.items() if k != kid and (c.get("cto") or {}).get("porta") == porta_cto
                                           and str((c.get("cto") or {}).get("ponto") or "").lower() == ponto_cto.lower()), None)
            if na_porta:
                outra_cx = (caixas.get(na_porta.get("caixa")) or {}).get("nome") or "outra caixa"
                raise HTTPException(400, f"A porta {porta_cto} da CTO {ponto_cto} ja tem a caixa {outra_cx}.")
            outro = next((c for k, c in cabos.items() if k != kid and c.get("caixa") == caixa["id"] and c.get("cto")), None)
            if outro:
                raise HTTPException(400, f"Esta caixa ja esta ligada na CTO {outro['cto'].get('ponto')}. Exclua o cabo antigo antes.")
            return _gravar_cabo(meta, meta_path, caixas, cabos, kid, caixa, dados, por, cto={"ponto": ponto_cto, "porta": porta_cto})
        if not destino["ponto"] and not destino["ip"]:
            raise HTTPException(400, "Informe a camera do cabo.")

        def _mesma_camera(c: dict) -> bool:
            if c.get("cto"):
                return False
            outra = c.get("camera") or {}
            if destino["ip"] and outra.get("ip"):
                return outra.get("ip") == destino["ip"]
            return bool(destino["ponto"]) and str(outra.get("ponto") or "").lower() == destino["ponto"].lower()

        if kid:
            antigo = cabos[kid]
            if antigo.get("caixa") != caixa["id"] or not _mesma_camera(antigo):
                # trocar a caixa ou a camera de um cabo e excluir um e criar
                # outro: so com a regra de exclusao (admin ou a senha dele)
                _exige_admin_para_excluir()
        repetido = next((c for k, c in cabos.items() if k != kid and _mesma_camera(c)), None)
        if repetido:
            cx_nome = (caixas.get(repetido.get("caixa")) or {}).get("nome") or "outra caixa"
            raise HTTPException(400, f"Esta camera ja tem cabo ({cx_nome}{', porta ' + str(repetido['porta']) if repetido.get('porta') else ''}). Exclua o antigo antes.")
        porta = dados.get("porta")
        if porta not in (None, "", 0):
            try:
                porta = int(porta)
            except (TypeError, ValueError):
                raise HTTPException(400, "Porta invalida.")
            if _tipo_da_caixa(caixa) == "passagem":
                raise HTTPException(400, "Caixa de passagem nao tem porta: ligue a camera sem porta.")
            if not 1 <= porta <= int(caixa.get("portas") or 0):
                raise HTTPException(400, f"A caixa tem {caixa.get('portas') or 0} portas.")
            ocupada = next((c for k, c in cabos.items() if k != kid and c.get("caixa") == caixa["id"] and c.get("porta") == porta), None)
            if ocupada:
                raise HTTPException(400, f"A porta {porta} ja tem cabo ({ocupada.get('camera', {}).get('ponto') or ocupada.get('camera', {}).get('ip')}).")
        else:
            porta = None
        try:
            folga = max(0, min(int(dados.get("folga_pct") if dados.get("folga_pct") is not None else 10), 100))
        except (TypeError, ValueError):
            folga = 10
        # alimentacao da camera (fonte 12V, injetor...): sem o campo, fica a gravada
        alimentacao = _texto_curto(dados["alimentacao"], 12) if "alimentacao" in dados else str((antigo_cabo or {}).get("alimentacao") or "")
        if alimentacao not in _ALIMENTACAO:
            raise HTTPException(400, "Alimentacao invalida.")
        metros = _metros_do_caminho(caminho)
        agora = datetime.now().isoformat(timespec="seconds")
        kid = kid or f"cb{uuid.uuid4().hex[:10]}"
        cabos[kid] = {
            "id": kid, "caixa": caixa["id"], "camera": destino, "tipo": tipo, "porta": porta, "folga_pct": folga,
            "alimentacao": alimentacao,
            "vlan": _vlan_valida(dados.get("vlan")),  # vazio = a VLAN da caixa
            "caminho": caminho, "metros": metros, "metros_com_folga": round(metros * (1 + folga / 100), 1),
            "criado_em": (cabos.get(kid) or {}).get("criado_em") or agora, "criado_por": (cabos.get(kid) or {}).get("criado_por") or por,
            "atualizado_em": agora,
        }
        inventario = ([cabos[kid]], caixa, False)
        if antigo_cabo and not _mesma_camera(antigo_cabo):
            _limpar_depois = ([antigo_cabo], caixas.get(antigo_cabo.get("caixa")) or caixa)
    meta["cabos"] = cabos
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    if _limpar_depois:
        _switch_no_inventario(*_limpar_depois, limpar=True)
    if inventario:
        _switch_no_inventario(*inventario)
    return {"caixas": caixas, "cabos": cabos}


def _modo_da_camada(layer_id: str, modo: Any) -> dict[str, Any]:
    """Em que modo do inventario (seletor OLT/Switch/Basico do Mapa) a camada
    aparece. Vazio = automatico (a tela conta em qual inventario estao as
    cameras dela); "todos" = em qualquer modo (fibra, postes...)."""
    valor = str(modo or "").strip().lower()
    if valor not in _MODOS_CAMADA:
        raise HTTPException(400, "Modo invalido: use olt, switch, basico, todos ou vazio (automatico).")
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    if not kmz_path.exists() or not geojson_path.exists():
        raise HTTPException(404, "Camada KMZ nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    meta["id"] = _safe_name(layer_id, "layer")
    meta["modo"] = valor
    meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _write_kmz_layer_meta(meta_path, meta)
    layer = next((item for item in _list_kmz_import_layers(include_features=False) if item.get("id") == layer_id), None)
    return layer or {"id": layer_id, "modo": valor}


def _apagar_geradas_do_mapa(layer_id: str) -> list[str]:
    """Remove as camadas geradas a partir do mapa importado `layer_id`.

    Sem isso a copia enriquecida fica orfa no disco e reaparece na tela assim
    que o importado que a escondia deixa de existir.
    """
    alvo = str(layer_id or "").strip()
    if not alvo:
        return []
    removidas: list[str] = []
    for meta_path in _kmz_generated_layers_dir().glob("*.meta.json"):
        try:
            meta = _read_kmz_layer_meta(meta_path)
        except Exception:
            continue
        if str(meta.get("source_layer_id") or "").strip() != alvo:
            continue
        gid = str(meta.get("id") or meta_path.stem.replace(".meta", "")).strip()
        k, g, m = _kmz_generated_layer_paths(gid)
        _safe_unlink(k)
        _safe_unlink(g)
        _safe_unlink(m)
        removidas.append(gid)
    return removidas


@router.delete("/kmz/import/layers/{layer_id}")
async def api_kmz_import_layer_delete(layer_id: str) -> Dict[str, Any]:
    _exigir_camada_liberada(layer_id)
    kmz_path, geojson_path, meta_path = _kmz_layer_paths(layer_id)
    existed = kmz_path.exists() or geojson_path.exists() or meta_path.exists()
    _safe_unlink(kmz_path)
    _safe_unlink(geojson_path)
    _safe_unlink(meta_path)
    # a copia enriquecida vai junto: se ficar, reaparece na tela sem a origem
    geradas = _apagar_geradas_do_mapa(layer_id)
    return {
        "ok": True,
        "removed": bool(existed),
        "id": layer_id,
        "generated_removed": len(geradas),
        "generated_ids": geradas,
    }


@router.get("/kmz/import/geojson")
async def api_kmz_import_geojson() -> Dict[str, Any]:
    _exigir_sem_restricao_de_site()
    kmz_geojson_path = tenant_kmz_imported_geojson_path() if get_current_tenant_slug() else KMZ_IMPORTED_GEOJSON_PATH
    return read_geojson_file(kmz_geojson_path)


@router.get("/kmz/import/download")
async def api_kmz_import_download() -> FileResponse:
    _exigir_sem_restricao_de_site()
    kmz_imported_path = tenant_kmz_imported_path() if get_current_tenant_slug() else KMZ_IMPORTED_PATH
    if not kmz_imported_path.exists():
        raise HTTPException(404, "Nenhum KMZ importado.")

    filename = kmz_imported_path.name
    meta_path = kmz_imported_path.with_suffix(".meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
            filename = str(meta.get("original_name") or filename)
        except Exception:
            pass
    return FileResponse(kmz_imported_path, media_type="application/vnd.google-earth.kmz", filename=filename)


@router.post("/kmz/import/locations/apply")
async def api_kmz_import_locations_apply(payload: Dict[str, Any]) -> Dict[str, Any]:
    dry_run = bool(payload.get("dry_run", False))
    overwrite = bool(payload.get("overwrite", False))
    source = str(payload.get("source") or "ip").strip().lower()
    mode = _normalize_inventory_mode(str(payload.get("mode") or ""))
    # Mapa escolhido na tela; sem escolha, o ultimo importado (comportamento
    # antigo). Herdar o ultimo import sem dizer nada foi o que deixou alguem
    # aplicar um mapa achando que era outro.
    layer_id = str(payload.get("layer_id") or "").strip()
    if layer_id:
        _exigir_camada_liberada(layer_id)
    else:
        _exigir_sem_restricao_de_site()
    if layer_id:
        _, layer_geojson_path, _ = _kmz_layer_paths(layer_id)
        geojson = read_geojson_file(layer_geojson_path)
        if not geojson:
            raise HTTPException(400, "Mapa nao encontrado. Recarregue a lista de mapas.")
    else:
        kmz_geojson_path = tenant_kmz_imported_geojson_path() if get_current_tenant_slug() else KMZ_IMPORTED_GEOJSON_PATH
        geojson = read_geojson_file(kmz_geojson_path)
    if not geojson:
        raise HTTPException(400, "Nenhum KMZ importado/convertido para aplicar.")

    rows = _load_rows_by_source(source, mode=mode)
    if not rows:
        raise HTTPException(400, "Inventario vazio.")
    # Restrito: so as linhas dos sites dele entram no Aplicar (previa e
    # gravacao); as outras voltam intactas ao salvar. Site pedido de outro: 403.
    liberados = _sites_liberados()
    if liberados is not None and str(payload.get("site") or "").strip() and _chave_site(payload.get("site")) not in liberados:
        raise HTTPException(403, "Site fora do seu acesso.")
    visiveis = [i for i, r in enumerate(rows) if isinstance(r, dict)
                and (liberados is None or _chave_site(permissions.site_da_linha(r)) in liberados)]

    rows_for_apply = [rows[i] for i in visiveis]
    dvr_idx_map: dict[int, int] = {}
    if source in ("dvr", "nvr"):
        mapped: list[dict[str, Any]] = []
        for i in visiveis:
            r = rows[i]
            host = str(r.get("host") or "").strip()
            ch = int(r.get("channel") or 0)
            ch_txt = f"{ch:02d}" if ch > 0 else "00"
            title = str(r.get("title") or "").strip() or f"Canal {ch_txt}"
            mapped.append(
                {
                    "__idx": i,
                    "ip": host,
                    "titulo": title,
                    "local": str(r.get("local") or "").strip(),
                    "lat": r.get("lat"),
                    "lon": r.get("lon"),
                }
            )
            dvr_idx_map[len(mapped) - 1] = i
        rows_for_apply = mapped

    try:
        new_rows, summary, no_match_rows = apply_locations_to_inventory(
            rows_for_apply,
            geojson,
            dry_run=dry_run,
            overwrite=overwrite,
            site=str(payload.get("site") or "").strip(),
        )
    except ValueError as exc:
        # Mapa de um site aplicado em outro: erro do usuario, com texto que
        # explica o que fazer -- nao 500.
        raise HTTPException(400, str(exc)) from exc
    if not dry_run:
        if source in ("dvr", "nvr"):
            rows_out = [dict(r) for r in rows]
            for mapped_idx, raw_idx in dvr_idx_map.items():
                if mapped_idx >= len(new_rows) or raw_idx >= len(rows_out):
                    continue
                m = new_rows[mapped_idx] if isinstance(new_rows[mapped_idx], dict) else {}
                if "lat" in m:
                    rows_out[raw_idx]["lat"] = m.get("lat")
                if "lon" in m:
                    rows_out[raw_idx]["lon"] = m.get("lon")
            _save_rows_by_source(source, rows_out)
        else:
            rows_out = list(rows)
            for j, i in enumerate(visiveis):
                if j < len(new_rows):
                    rows_out[i] = new_rows[j]
            _save_rows_by_source(source, rows_out, mode=mode)

    report_path = tenant_locations_apply_report_path() if get_current_tenant_slug() else (DATA_DIR / "input" / "locations_apply_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "summary": summary,
                "no_match_rows": no_match_rows,
                "ts": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # A tela precisa saber DE QUE MAPA e DE QUE SITE ela esta falando antes de
    # deixar alguem clicar em Aplicar -- foi a falta disso que deixou o KMZ de um
    # site carimbar cameras de outro sem ninguem perceber. Na previa vao junto os
    # nomes das cameras sem ponto no mapa: numero solto ("323 sem match") nao
    # ajuda ninguem a agir.
    resposta = {
        "ok": True,
        "source": source,
        "mode": mode if source == "ip" else "",
        "layer": _kmz_layer_ativa(layer_id),
        **summary,
    }
    if dry_run:
        resposta["no_match_rows"] = no_match_rows[:60]
    return resposta


def _kmz_layer_ativa(layer_id: str = "") -> Dict[str, Any]:
    """Nome do KMZ que o Aplicar vai usar: o escolhido, ou o ultimo importado."""
    if layer_id:
        _, _, meta_path = _kmz_layer_paths(layer_id)
    else:
        kmz_imported_path = tenant_kmz_imported_path() if get_current_tenant_slug() else KMZ_IMPORTED_PATH
        meta_path = kmz_imported_path.with_suffix(".meta.json")
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    nome = str(meta.get("original_name") or "").strip()
    return {
        "id": str(meta.get("layer_id") or ""),
        "nome": Path(nome).stem if nome else "",
        "arquivo": nome,
    }


@router.post("/kmz/generate")
async def api_kmz_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
    source = str(payload.get("source") or "ip").strip().lower()
    mode = _normalize_inventory_mode(str(payload.get("mode") or ""))
    label = str(payload.get("label") or payload.get("name") or "Cameras do Inventario").strip() or "Cameras do Inventario"
    source_layer_id = str(payload.get("layer_id") or payload.get("source_layer_id") or "").strip()
    kmz_imported_path = tenant_kmz_imported_path() if get_current_tenant_slug() else KMZ_IMPORTED_PATH
    kmz_output_dir = tenant_kmz_output_dir() if get_current_tenant_slug() else KMZ_OUTPUT_DIR
    source_kmz_path = kmz_imported_path
    if source_layer_id:
        _exigir_camada_liberada(source_layer_id)
    else:
        _exigir_sem_restricao_de_site()
    if source_layer_id:
        layer_kmz_path, _, _ = _kmz_layer_paths(source_layer_id)
        if layer_kmz_path.exists():
            source_kmz_path = layer_kmz_path
    if not source_kmz_path.exists():
        raise HTTPException(400, "Importe um KMZ antes de gerar.")
    rows_raw = permissions.filtrar_por_site(_load_rows_by_source(source, mode=mode))
    rows = _kmz_rows_for_source(source, rows_raw)
    if not rows:
        raise HTTPException(400, "Inventario vazio.")

    try:
        out_kmz = generate_enriched_kmz(source_kmz_path, rows, kmz_output_dir)
        geojson = kmz_to_geojson(out_kmz)
        (kmz_output_dir / "generated.geojson").write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")

        layer_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_safe_name(label)}-{secrets.token_hex(3)}"
        layer_kmz_path, layer_geojson_path, layer_meta_path = _kmz_generated_layer_paths(layer_id)
        layer_kmz_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_kmz, layer_kmz_path)
        layer_geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
        layer_meta = {
            "id": layer_id,
            "label": label,
            "original_name": f"{_safe_name(label)}.kmz",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "features_count": len(geojson.get("features") or []),
            "source_layer_id": source_layer_id,
            "source": source,
            "mode": mode if source == "ip" else "",
            **_sites_para_meta_nova(),
        }
        layer_meta_path.write_text(json.dumps(layer_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(500, f"Falha ao gerar KMZ: {exc}")

    return {
        "ok": True,
        "id": layer_id,
        "label": label,
        "source": source,
        "mode": mode if source == "ip" else "",
        "source_layer_id": source_layer_id,
        "features_count": len(geojson.get("features") or []),
        "rows_used": len(rows),
        "path": str(layer_kmz_path),
        "latest": layer_kmz_path.name,
        "latest_url": f"/api/kmz/generated/layers/{layer_id}/download",
    }


@router.get("/kmz/generated/layers")
async def api_kmz_generated_layers(include_features: bool = True) -> Dict[str, Any]:
    layers = _list_kmz_generated_layers(include_features=include_features)
    return {"ok": True, "count": len(layers), "layers": layers}


@router.get("/kmz/generated/layers/{layer_id}/download")
async def api_kmz_generated_layer_download(layer_id: str) -> FileResponse:
    _exigir_camada_liberada(layer_id, generated=True)
    kmz_path, _, meta_path = _kmz_generated_layer_paths(layer_id)
    if not kmz_path.exists():
        raise HTTPException(404, "Camada KMZ gerada nao encontrada.")
    meta = _read_kmz_layer_meta(meta_path)
    filename = str(meta.get("original_name") or kmz_path.name)
    return FileResponse(kmz_path, media_type="application/vnd.google-earth.kmz", filename=filename)


@router.patch("/kmz/generated/layers/{layer_id}")
async def api_kmz_generated_layer_update(layer_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _exigir_camada_liberada(layer_id, generated=True)
    if isinstance(payload.get("ponto"), dict):
        return {"ok": True, **_editar_ponto_da_camada(layer_id, payload["ponto"], generated=True)}
    layer = _rename_kmz_layer(layer_id, str(payload.get("label") or ""), generated=True)
    return {"ok": True, "layer": layer}


@router.delete("/kmz/generated/layers/{layer_id}")
async def api_kmz_generated_layer_delete(layer_id: str) -> Dict[str, Any]:
    _exigir_camada_liberada(layer_id, generated=True)
    kmz_path, geojson_path, meta_path = _kmz_generated_layer_paths(layer_id)
    existed = kmz_path.exists() or geojson_path.exists() or meta_path.exists()
    _safe_unlink(kmz_path)
    _safe_unlink(geojson_path)
    _safe_unlink(meta_path)
    return {"ok": True, "removed": bool(existed), "id": layer_id}


@router.get("/kmz/generated/geojson")
async def api_kmz_generated_geojson() -> Dict[str, Any]:
    _exigir_sem_restricao_de_site()
    kmz_output_dir = tenant_kmz_output_dir() if get_current_tenant_slug() else KMZ_OUTPUT_DIR
    return read_geojson_file(kmz_output_dir / "generated.geojson")


@router.get("/kmz/generated/download")
async def api_kmz_generated_download() -> FileResponse:
    _exigir_sem_restricao_de_site()
    kmz_output_dir = tenant_kmz_output_dir() if get_current_tenant_slug() else KMZ_OUTPUT_DIR
    if not kmz_output_dir.exists():
        raise HTTPException(404, "Nenhum KMZ gerado.")
    kmzs = sorted(kmz_output_dir.glob("*.kmz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not kmzs:
        raise HTTPException(404, "Nenhum KMZ gerado.")
    latest = kmzs[0]
    return FileResponse(latest, media_type="application/vnd.google-earth.kmz", filename=latest.name)

@router.get("/geo/camera.kml")
async def api_geo_camera_kml() -> FileResponse:
    _exigir_sem_restricao_de_site()
    kmz_output_dir = tenant_kmz_output_dir() if get_current_tenant_slug() else KMZ_OUTPUT_DIR
    kml = kmz_output_dir / "camera.kml"
    if not kml.exists():
        raise HTTPException(404, "KML nao encontrado.")
    return FileResponse(kml, media_type="application/vnd.google-earth.kml+xml", filename="camera.kml")


# -----------------
# Settings: ImgBB
# -----------------

def _load_app_settings() -> Dict[str, Any]:
    return load_app_settings()


def _save_app_settings(settings: Dict[str, Any]) -> None:
    save_app_settings(settings)


def _mask_key(key: str) -> str:
    k = (key or "").strip()
    if len(k) <= 4:
        return "****"
    return "****" + k[-4:]


def _settings_imgbb_key(settings: Dict[str, Any]) -> str:
    return str((settings or {}).get("imgbb_key") or (settings or {}).get("imgbb_api_key") or "").strip()


def _imgbb_validate_key(api_key: str) -> tuple[bool, str]:
    api_key = (api_key or "").strip().strip('"')
    if not api_key:
        return False, "API key vazia"
    try:
        import requests
        tiny_png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/6X7b9kAAAAASUVORK5CYII="
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": api_key, "image": tiny_png_b64, "name": "cam_snapshot_web_test"},
            timeout=15,
        )
        payload = {}
        try:
            payload = r.json()
        except Exception:
            payload = {}
        if r.status_code == 200 and payload.get("success") is True:
            return True, "OK"
        err = (
            payload.get("error", {}).get("message")
            or payload.get("error", {}).get("code")
            or payload.get("message")
            or f"HTTP {r.status_code}"
        )
        return False, str(err)
    except Exception as e:
        return False, str(e)


@router.get("/settings/imgbb")
async def api_imgbb_get_settings() -> Dict[str, Any]:
    s = _load_app_settings()
    key = _settings_imgbb_key(s)
    has_key = bool(key)
    return {
        "ok": True,
        "has_key": has_key,
        "configured": has_key,  # alias esperado pelo frontend atual
        "masked": _mask_key(key) if key else "",
    }


@router.post("/settings/imgbb/test")
async def api_imgbb_test(payload: Dict[str, Any]) -> Dict[str, Any]:
    key = (payload.get("key") or payload.get("api_key") or "").strip()
    ok, msg = _imgbb_validate_key(key)
    return {"ok": ok, "message": msg}


@router.post("/settings/imgbb")
async def api_imgbb_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    key = (payload.get("key") or payload.get("api_key") or "").strip()
    validate = bool(payload.get("validate", False))
    if validate:
        ok, msg = _imgbb_validate_key(key)
        if not ok:
            return {"ok": False, "message": msg, "has_key": False, "configured": False, "masked": ""}

    s = _load_app_settings()
    s["imgbb_key"] = key
    s.pop("imgbb_api_key", None)
    _save_app_settings(s)
    has_key = bool(key)
    return {
        "ok": True,
        "has_key": has_key,
        "configured": has_key,  # alias esperado pelo frontend atual
        "masked": _mask_key(key) if key else "",
    }


# -----------------
# Telegram relay (Zabbix -> backend -> Telegram sendPhoto multipart)
# -----------------
@router.post("/telegram/relay_send")
async def api_telegram_relay_send(payload: Dict[str, Any]) -> Dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    chat_id = str(payload.get("chat_id") or payload.get("chat") or "").strip()
    text = str(payload.get("text") or payload.get("message") or "").strip()
    snapshot_url = str(payload.get("snapshot_url") or "").strip()
    map_url = str(payload.get("map_url") or "").strip()
    parse_mode = str(payload.get("parse_mode") or "HTML").strip() or "HTML"
    relay_key = str(payload.get("relay_key") or "").strip()
    expected_key = str(os.getenv("TELEGRAM_RELAY_KEY") or "").strip()

    if expected_key and relay_key != expected_key:
        raise HTTPException(status_code=403, detail="relay_key invalida")
    if not token:
        raise HTTPException(status_code=400, detail="token obrigatorio")
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id obrigatorio")
    if not snapshot_url:
        raise HTTPException(status_code=400, detail="snapshot_url obrigatorio")

    tg_base = f"https://api.telegram.org/bot{token}"

    low = snapshot_url.lower()
    looks_http = low.startswith("http://") or low.startswith("https://")
    looks_img = bool(re.search(r"(\.jpg|\.jpeg|\.png|\.webp)(\?|$)", low)) or ("i.ibb.co/" in low)

    if not (looks_http and looks_img):
        raise HTTPException(status_code=400, detail="snapshot_url invalido para envio de foto")

    # Envia como multipart (binario) para garantir foto embutida e suportar caption.
    try:
        img = requests.get(
            snapshot_url,
            timeout=25,
            stream=True,
            allow_redirects=True,
            headers={"User-Agent": "cam-snapshot-relay/1.0"},
        )
        data = img.content if img.status_code == 200 else b""
        ctype = str(img.headers.get("Content-Type") or "").lower()
        if not data:
            raise HTTPException(status_code=502, detail=f"download status={img.status_code}")
        mime = ctype if ctype.startswith("image/") else "image/jpeg"
        files = {"photo": ("snapshot.jpg", data, mime)}
        form = {"chat_id": chat_id}
        if text:
            caption = text if len(text) <= 1024 else (text[:1000] + "...")
            form["caption"] = caption
            form["parse_mode"] = parse_mode
        if map_url.lower().startswith(("http://", "https://")):
            form["reply_markup"] = json.dumps(
                {"inline_keyboard": [[{"text": "Abrir no Google Maps", "url": map_url}]]},
                ensure_ascii=False,
            )
        s = requests.post(f"{tg_base}/sendPhoto", data=form, files=files, timeout=35)
        sobj = {}
        try:
            sobj = s.json()
        except Exception:
            sobj = {"ok": False, "description": s.text[:500]}
        if s.status_code == 200 and sobj.get("ok"):
            return {"ok": True, "method": "sendPhoto_multipart"}
        raise HTTPException(status_code=502, detail=f"sendPhoto falhou: {str(sobj)[:500]}")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="download/sendPhoto exception")
