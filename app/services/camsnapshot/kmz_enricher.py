# camsnapshot.kmz_enricher
from __future__ import annotations

import os, zipfile, shutil, re
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Union

KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)
_AUTO_NS_URI = "http://www.w3.org/2005/Atom"


def _sanitize_kml_xml(data: bytes | str) -> bytes:
    text = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    used_prefixes = set(re.findall(r"</?(ns\d+):[A-Za-z_][\w.-]*", text))
    if not used_prefixes:
        return text.encode("utf-8")
    m = re.search(r"<kml\b([^>]*)>", text, flags=re.IGNORECASE)
    if not m:
        return text.encode("utf-8")
    attrs = m.group(1) or ""
    missing = [p for p in sorted(used_prefixes) if f"xmlns:{p}=" not in attrs]
    if not missing:
        return text.encode("utf-8")
    additions = "".join(f' xmlns:{p}="{_AUTO_NS_URI}"' for p in missing)
    start, end = m.span()
    return (text[:end - 1] + additions + text[end - 1:]).encode("utf-8")


def _load_kml_from_kmz(kmz_path: str) -> str:
    with zipfile.ZipFile(kmz_path, "r") as z:
        kml_name = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
        if not kml_name:
            raise RuntimeError(f"[KMZ] doc.kml no encontrado: {kmz_path}")
        return _sanitize_kml_xml(z.read(kml_name)).decode("utf-8", errors="ignore")


def _write_kmz(doc_kml_bytes: bytes, out_kmz: str, extra_files: list | None = None):
    tmp = "__tmp_kmz"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    kml_path = os.path.join(tmp, "doc.kml")
    with open(kml_path, "wb") as f:
        f.write(doc_kml_bytes)

    if extra_files:
        for src, arc in extra_files:
            dst = os.path.join(tmp, arc)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy(src, dst)

    os.makedirs(os.path.dirname(out_kmz), exist_ok=True)
    with zipfile.ZipFile(out_kmz, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(kml_path, arcname="doc.kml")
        if extra_files:
            for _src, arc in extra_files:
                z.write(os.path.join(tmp, arc), arcname=arc)

    shutil.rmtree(tmp, ignore_errors=True)


def _pm_name(pm: ET.Element) -> str:
    el = pm.find(f"{{{KML_NS}}}name")
    return (el.text or "").strip() if el is not None else ""


def _pm_coords(pm: ET.Element):
    el = pm.find(f".//{{{KML_NS}}}coordinates")
    if el is None or not el.text:
        return None, None
    parts = el.text.strip().split(",")
    if len(parts) < 2:
        return None, None
    lon, lat = parts[0], parts[1]
    return lat, lon


def _add_styles(root: ET.Element, href_online: str, href_offline: str):
    doc = root.find(f"{{{KML_NS}}}Document")
    if doc is None:
        doc = root

    for s in list(doc.findall(f"{{{KML_NS}}}Style")):
        if s.get("id") in ("cam-online", "cam-offline"):
            doc.remove(s)

    s_on = ET.SubElement(doc, f"{{{KML_NS}}}Style", {"id": "cam-online"})
    isty = ET.SubElement(s_on, f"{{{KML_NS}}}IconStyle")
    icon = ET.SubElement(isty, f"{{{KML_NS}}}Icon")
    href = ET.SubElement(icon, f"{{{KML_NS}}}href")
    href.text = href_online

    s_off = ET.SubElement(doc, f"{{{KML_NS}}}Style", {"id": "cam-offline"})
    isty2 = ET.SubElement(s_off, f"{{{KML_NS}}}IconStyle")
    icon2 = ET.SubElement(isty2, f"{{{KML_NS}}}Icon")
    href2 = ET.SubElement(icon2, f"{{{KML_NS}}}href")
    href2.text = href_offline


def _build_maps(
    inv: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Aceita inventrio como:
      - lista de dicts  (cam-inventory.json items)
      - dict name->dict (formato antigo)

    Retorna:
      - map_exato:   key = titulo.strip()
      - map_lower:   key = titulo.strip().lower()
    """
    map_exato: Dict[str, Dict[str, Any]] = {}
    map_lower: Dict[str, Dict[str, Any]] = {}

    if isinstance(inv, dict):
        # j veio como mapa
        for k, v in inv.items():
            if not isinstance(v, dict):
                continue
            key = str(k or "").strip()
            if not key:
                continue
            map_exato[key] = v
            map_lower[key.lower()] = v
        return map_exato, map_lower

    # veio lista
    if isinstance(inv, list):
        for r in inv:
            if not isinstance(r, dict):
                continue
            title = str(r.get("titulo") or r.get("local") or r.get("name") or "").strip()
            if not title:
                continue
            # se existir duplicado, mantm o primeiro (normal e previsvel)
            if title not in map_exato:
                map_exato[title] = r
            tl = title.lower()
            if tl not in map_lower:
                map_lower[tl] = r

    return map_exato, map_lower


def _match(name: str, inv: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Match NORMAL:
      1) exato (strip)
      2) case-insensitive
      3) se tiver IP no nome, procura por IP no inventrio
    """
    name = (name or "").strip()
    if not name:
        return {"titulo": "", "ip": "", "mac": "", "modelo": "", "status": ""}

    map_exato, map_lower = _build_maps(inv)

    # 1) exato
    if name in map_exato:
        return map_exato[name]

    # 2) case-insensitive
    nl = name.lower()
    if nl in map_lower:
        return map_lower[nl]

    # 3) tenta por IP presente no nome
    ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", name)
    if ips:
        # varre inventrio (tanto mapa quanto lista)
        if isinstance(inv, dict):
            rows = list(inv.values())
        else:
            rows = inv

        for ip in ips:
            for v in rows:
                if isinstance(v, dict) and str(v.get("ip") or "").strip() == ip:
                    return v

    return {"titulo": name, "ip": "", "mac": "", "modelo": "", "status": ""}


def _popup_html(reg: Dict[str, Any], lat: Optional[str], lon: Optional[str]) -> str:
    """Popup estilo Telegram, textos em PRETO e apenas STATUS colorido."""
    C_TEXT = "#111827"
    C_GREEN = "#16a34a"
    C_RED = "#dc2626"

    #  NORMAL: no forar upper no contedo (pra no quebrar visual/nome)
    nome = (reg.get("titulo") or reg.get("local") or reg.get("name") or "").strip()
    mac = (reg.get("mac") or "").strip()
    ip = (reg.get("ip") or "").strip()
    modelo = (reg.get("modelo") or reg.get("model") or "").strip()

    status_raw = (reg.get("status") or "Online").strip().lower()
    is_on = status_raw.startswith("on")
    dot = "🟢" if is_on else "🔴"
    status_txt = "ONLINE" if is_on else "OFFLINE"

    # Prioriza mídia remota (ImgBB) para abrir de qualquer lugar, depois local.
    snap = (
        reg.get("imgbb_url")
        or reg.get("imgbb_thumb_url")
        or reg.get("snapshot_url")
        or reg.get("thumb_url")
        or ""
    ).strip()
    fibra = (reg.get("fibra") or "").strip()
    onu = str(reg.get("onu_id") or "").strip()
    pon = str(reg.get("pon") or "").strip()
    onu_serial = str(reg.get("onu_serial") or "").strip()

    rota = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}" if lat and lon else ""
    gps = f"{lat},{lon}" if lat and lon else ""

    html: List[str] = []

    if snap:
        html.append(f'<img src="{snap}" style="max-width:320px;width:100%;height:auto;border-radius:10px;display:block;"/><br/>')

    if nome:
        html.append(
            f'<div style="font-weight:800;font-size:14px;margin:6px 0 6px 0;'
            f'color:{C_TEXT};letter-spacing:0.4px;">{nome}</div>'
        )

    linhas: List[str] = []

    def line(emoji: str, label: str, value: str):
        if not value:
            return
        linhas.append(
            f'{emoji} <span style="color:{C_TEXT};font-weight:700;">{label}:</span> '
            f'<span style="color:{C_TEXT};">{value}</span>'
        )

    line("📷", "CAMERA", modelo)
    if nome:
        if rota:
            linhas.append(
                f'📍 <span style="color:{C_TEXT};font-weight:700;">LOCAL:</span> '
                f'<a href="{rota}" target="_blank" rel="noopener noreferrer" '
                f'style="color:{C_TEXT};text-decoration:underline;">{nome}</a>'
            )
        else:
            line("📍", "LOCAL", nome)
    line("🧬", "MAC", mac)
    line("🌐", "IP", ip)

    cor_status = C_GREEN if is_on else C_RED
    linhas.append(
        f'{dot} <span style="color:{C_TEXT};font-weight:700;">STATUS:</span> '
        f'<span style="color:{cor_status};font-weight:800;">{status_txt}</span>'
    )

    line("🪢", "FIBRA", fibra)

    if onu_serial:
        linhas.append(
            f'🔑 <span style="color:{C_TEXT};font-weight:700;">ONU SERIAL:</span> '
            f'<span style="color:{C_TEXT};">{onu_serial}</span>'
        )

    if pon or onu:
        valor_pon_onu = f"PON {pon or '?'} / ONU {onu or '?'}"
        linhas.append(
            f'🛰️ <span style="color:{C_TEXT};font-weight:700;">PON/ONU:</span> '
            f'<span style="color:{C_TEXT};">{valor_pon_onu}</span>'
        )
    if gps:
        linhas.append(
            f'<span style="color:{C_TEXT};font-weight:700;">GPS:</span> '
            f'<span style="color:{C_TEXT};">{gps}</span>'
        )

    html.append("<br/>".join(linhas))

    return "\n".join(html)


def enrich_single_kmz(
    kmz_path: str,
    inventory: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]],
    out_dir: str
) -> str:
    kml_text = _load_kml_from_kmz(kmz_path)
    root = ET.fromstring(kml_text)

    icons_base = "files/icons"
    href_on = f"{icons_base}/cctv-green.png"
    href_off = f"{icons_base}/cctv-red.png"
    _add_styles(root, href_on, href_off)

    pms = root.findall(f".//{{{KML_NS}}}Placemark")
    for pm in pms:
        name = _pm_name(pm)
        lat, lon = _pm_coords(pm)
        reg = _match(name, inventory)

        html = _popup_html(reg, lat, lon)
        desc = pm.find(f"{{{KML_NS}}}description")
        if desc is None:
            desc = ET.SubElement(pm, f"{{{KML_NS}}}description")
        desc.text = html

        status = (reg.get("status") or "Online").strip().lower()
        style_url = "#cam-online" if status.startswith("on") else "#cam-offline"
        s = pm.find(f"{{{KML_NS}}}styleUrl")
        if s is None:
            s = ET.SubElement(pm, f"{{{KML_NS}}}styleUrl")
        s.text = style_url

    new_kml = ET.tostring(root, encoding="utf-8", method="xml")

    base = os.path.splitext(os.path.basename(kmz_path))[0]
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{base}-enriched.kmz")

    here = os.path.dirname(__file__)
    extra = [
        (os.path.join(here, "assets", "icons", "cctv-green.png"), "files/icons/cctv-green.png"),
        (os.path.join(here, "assets", "icons", "cctv-red.png"), "files/icons/cctv-red.png"),
    ]
    _write_kmz(new_kml, out_path, extra_files=extra)
    return out_path


def enrich_folder(
    kmz_in_dir: str,
    inventory: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]],
    out_dir: str
) -> List[str]:
    if not os.path.isdir(kmz_in_dir):
        return []

    outs: List[str] = []
    for f in os.listdir(kmz_in_dir):
        if f.lower().endswith(".kmz"):
            src = os.path.join(kmz_in_dir, f)
            try:
                outs.append(enrich_single_kmz(src, inventory, out_dir))
            except Exception as e:
                print(f"[KMZ] Falha {f}: {e}")
    return outs
