from __future__ import annotations

import json
import os
import re
import csv
import logging
from pathlib import Path
from typing import Any, Dict, List

from app.core.paths import INVENTORY_JSON_PATH, SAIDA_DIR, DATA_DIR
from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_key, tenant_scoped_path
from app.services.db_store import get_json_state, set_json_state, legacy_rows_from_db, replace_ip_inventory_rows


logger = logging.getLogger("cam_snapshot.inventory")


# ========================
# Helpers de inventário (JSON ONLY) — legado
# ========================


def _normalize_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
    return out


def _norm_mac(v: Any) -> str:
    s = (v or "").strip().lower()
    s = s.replace("-", ":").replace(".", ":")
    s = re.sub(r":+", ":", s)
    return s


def _norm_ip(v: Any) -> str:
    return (v or "").strip()


def _brand_from_model_hint(model: Any, current: Any = "") -> str:
    model_txt = str(model or "").strip()
    current_txt = str(current or "").strip()
    if not model_txt:
        return current_txt
    normalized = re.sub(r"[^A-Z0-9]+", "-", model_txt.upper()).strip("-")
    compact = re.sub(r"[^A-Z0-9]+", "", model_txt.upper())

    if "HILOOK" in normalized or "HI-LOOK" in normalized:
        return "HiLook"
    if normalized.startswith(("DS-", "HWI", "HWP", "HK")) or "HIKVISION" in normalized:
        return "Hikvision"
    if compact.startswith(("VIP", "MIB", "VHD", "MHD")):
        return "Intelbras"
    if normalized.startswith(("DHI-", "DH-", "HFW", "HDP")):
        return "Dahua"
    return current_txt


def inventory_row_key(row: dict[str, Any], fallback: str = "") -> str:
    """Chave logica do inventario.

    IP privado se repete entre clientes. Quando a linha vem de conector remoto,
    o connector_id passa a fazer parte da identidade.
    """
    r = row or {}
    ip = _norm_ip(r.get("ip") or r.get("IP") or r.get("host") or "")
    mac = _norm_mac(r.get("mac") or r.get("MAC") or r.get("mac_address") or "")
    connector_id = str(r.get("remote_connector_id") or r.get("connector_id") or "").strip()
    site = str(r.get("site") or r.get("site_name") or r.get("local") or "").strip().lower()
    if connector_id and ip:
        return f"REMOTE:{connector_id}:IP:{ip}"
    if connector_id and mac:
        return f"REMOTE:{connector_id}:MAC:{mac}"
    if site and ip and str(r.get("remote") or "").strip().lower() in {"1", "true", "yes", "sim"}:
        return f"REMOTE_SITE:{site}:IP:{ip}"
    if ip:
        return f"IP:{ip}"
    if mac:
        return f"MAC:{mac}"
    return fallback or f"ROW:{id(row)}"


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normaliza chaves do inventário para um padrão único.

    Padrão interno: ip, mac, fabricante, modelo, titulo (+ demais campos mantidos).
    """
    r = dict(row or {})
    ip = _norm_ip(r.get("ip") or r.get("IP") or "")
    mac = _norm_mac(r.get("mac") or r.get("MAC") or r.get("mac_address") or "")
    fabricante = (r.get("fabricante") or r.get("FABRICANTE") or r.get("manufacturer") or "").strip()
    modelo = (r.get("modelo") or r.get("MODELO") or r.get("model") or "").strip()
    titulo = (r.get("titulo") or r.get("TITULO") or r.get("nome") or r.get("title") or "").strip()

    if ip:
        r["ip"] = ip
    if mac:
        r["mac"] = mac
    if modelo:
        r["modelo"] = modelo
    fabricante = _brand_from_model_hint(modelo, fabricante)
    if fabricante:
        r["fabricante"] = fabricante
    if titulo:
        r["titulo"] = titulo

    # limpa aliases pra reduzir duplicação no JSON
    for k in (
        "IP",
        "MAC",
        "mac_address",
        "manufacturer",
        "model",
        "nome",
        "title",
        "FABRICANTE",
        "MODELO",
        "TITULO",
    ):
        if k in r:
            try:
                del r[k]
            except Exception:
                pass
    return r


def _dedup_key(row: dict[str, Any]) -> str:
    return inventory_row_key(row)


def _row_site(row: dict[str, Any]) -> str:
    return str(row.get("site") or row.get("site_name") or row.get("local") or "").strip().lower()


def _placeholder_title(row: dict[str, Any]) -> bool:
    title = str(row.get("titulo") or row.get("title") or "").strip()
    ip = _norm_ip(row.get("ip") or row.get("IP") or row.get("host") or "")
    return not title or bool(ip and title == ip)


def _row_quality(row: dict[str, Any]) -> int:
    score = 0
    for key in (
        "mac",
        "fabricante",
        "modelo",
        "pon",
        "onu_id",
        "onu_name",
        "onu_serial",
        "snapshot_url",
        "imgbb_url",
        "lat",
        "lon",
    ):
        if str(row.get(key) or "").strip():
            score += 1
    if not _placeholder_title(row):
        score += 3
    return score


def _merge_inventory_duplicate(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Une duplicatas do mesmo site+IP preservando a linha mais rica.

    O scan remoto pode trazer apenas IP/status/conector. Quando ja existe uma
    linha completa local, ela deve ser atualizada, nao duplicada nem empobrecida.
    """
    base, extra = (dict(a), dict(b)) if _row_quality(a) >= _row_quality(b) else (dict(b), dict(a))
    for key, value in extra.items():
        s = str(value or "").strip()
        if not s:
            continue
        if key in {"status", "health", "remote", "remote_connector_id", "remote_connector_name", "site", "site_name", "local"}:
            base[key] = value
            continue
        if key in {"titulo", "title"} and _placeholder_title({"titulo": value, "ip": base.get("ip")}):
            continue
        if not str(base.get(key) or "").strip():
            base[key] = value
    return base


def _normalize_inventory_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    by_site_ip: dict[str, int] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        nr = _normalize_row(r)
        ip = _norm_ip(nr.get("ip") or nr.get("IP") or nr.get("host") or "")
        site = _row_site(nr)
        site_ip_key = f"{site}|{ip}" if site and ip else ""
        if site_ip_key and site_ip_key in by_site_ip:
            idx = by_site_ip[site_ip_key]
            old_key = _dedup_key(out[idx])
            out[idx] = _merge_inventory_duplicate(out[idx], nr)
            seen.discard(old_key)
            seen.add(_dedup_key(out[idx]))
            continue
        k = _dedup_key(nr)
        if k in seen:
            continue
        seen.add(k)
        if site_ip_key:
            by_site_ip[site_ip_key] = len(out)
        out.append(nr)
    return out


def _normalize_inventory_mode(mode: str = "") -> str:
    raw = str(mode or "").strip().lower()
    if raw in {"switch", "sw", "via_switch", "via-switch"}:
        return "switch"
    if raw in {"basic", "basico", "básico", "base"}:
        return "basic"
    return "olt"


def _inventory_state_key(mode: str = "") -> str:
    return tenant_scoped_key(f"inventory_ip_{_normalize_inventory_mode(mode)}")


def _inventory_path(mode: str = "") -> Path:
    norm_mode = _normalize_inventory_mode(mode)
    tenant_slug = get_current_tenant_slug()
    if tenant_slug:
        filename = {
            "switch": "cam-inventory-switch.json",
            "basic": "cam-inventory-basic.json",
        }.get(norm_mode, "cam-inventory.json")
        return tenant_scoped_path(filename, tenant_slug)
    if norm_mode == "switch":
        return DATA_DIR / "cam-inventory-switch.json"
    if norm_mode == "basic":
        return DATA_DIR / "cam-inventory-basic.json"
    return INVENTORY_JSON_PATH


def _extract_rows_from_obj(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return _normalize_inventory_rows(_normalize_rows(obj))
    if isinstance(obj, dict):
        rows = obj.get("inventory") or obj.get("rows") or obj.get("data") or []
        return _normalize_inventory_rows(_normalize_rows(rows))
    return []


def _filter_rows_by_site(rows: list[dict[str, Any]], site: str = "") -> list[dict[str, Any]]:
    wanted = str(site or "").strip().lower()
    if not wanted:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        vals = [
            str(row.get("site") or "").strip(),
            str(row.get("site_name") or "").strip(),
            str(row.get("local") or row.get("LOCAL") or "").strip(),
        ]
        if any(v.lower() == wanted for v in vals if v):
            out.append(row)
    return out


def load_inventory_json(site: str = "", mode: str = "olt") -> list[dict[str, Any]]:
    norm_mode = _normalize_inventory_mode(mode)
    state_obj = get_json_state(_inventory_state_key(norm_mode), None)
    if state_obj is not None:
        # Chave ja existe no cache (mesmo que vazia): isso significa que este
        # modo ja foi salvo explicitamente antes (inclusive um "apagar tudo"),
        # entao e a fonte da verdade e NAO deve cair no fallback de
        # arquivo/OLT abaixo -- do contrario um inventario esvaziado de
        # proposito "ressuscita" a partir do modo OLT no proximo load.
        state_rows = _extract_rows_from_obj(state_obj)
        return _filter_rows_by_site(state_rows, site)

    if norm_mode == "olt":
        try:
            db_rows = legacy_rows_from_db("ip", site=str(site or "").strip())
            if db_rows:
                rows = _normalize_inventory_rows(_normalize_rows(db_rows))
                try:
                    save_inventory_json(rows, mode=norm_mode)
                except Exception:
                    pass
                return _filter_rows_by_site(rows, site)
        except Exception:
            pass
    """Carrega cam-inventory.json no formato legado, com normalização e dedup."""
    try:
        SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    inv_path = _inventory_path(norm_mode)
    if inv_path.exists():
        try:
            with inv_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            rows = _normalize_inventory_rows(_normalize_rows(data))
            try:
                set_json_state(_inventory_state_key(norm_mode), {"inventory": rows})
            except Exception:
                pass
            if rows:
                return _filter_rows_by_site(rows, site)
        except Exception as e:
            logger.error(f"[inventory] erro ao ler JSON: {e}")

    if norm_mode != "olt":
        # Sem edicao propria salva neste modo (switch/basico): usa o
        # inventario mestre (modo "olt", ligado ao DB) como base, em vez de
        # ficar vazio para sempre — mesma logica de recuperacao que o modo
        # "olt" ja tem contra o DB.
        return []

    return []


def save_inventory_json(rows: list[dict[str, Any]], mode: str = "olt") -> None:
    """Salva inventario IP separado por modo."""
    norm_mode = _normalize_inventory_mode(mode)
    rows = _normalize_inventory_rows(rows)
    try:
        set_json_state(_inventory_state_key(norm_mode), {"inventory": rows})
    except Exception:
        pass
    if norm_mode == "olt":
        try:
            replace_ip_inventory_rows(rows)
        except Exception:
            pass

    try:
        SAIDA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    inv_path = _inventory_path(norm_mode)
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    if get_current_tenant_slug():
        inv_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    tmp = inv_path.with_suffix(inv_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, inv_path)
    except Exception:
        try:
            inv_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            except Exception:
                pass
        except Exception:
            raise


def normalize_row(row: Any) -> Dict[str, Any]:
    """Normaliza 1 registro de inventário (compat legado)."""
    return _normalize_row(row)


def dedup_cam_inventory(mode: str = "olt") -> List[Dict[str, Any]]:
    """Dedup do cam-inventory.json (compat legado).
    Regrava o JSON já normalizado e sem duplicatas.
    """
    rows = load_inventory_json(mode=mode)
    rows2 = _normalize_inventory_rows(rows)
    save_inventory_json(rows2, mode=mode)
    return rows2
