"""Importa uma rede FTTx desenhada no Google Earth (KMZ) para um projeto.

Le o jeito que a rede e desenhada hoje a mao:

- pastas por ramal de cor ("FIBRA VERDE / CTO VERDE / CDO VERDE / FIBRA");
- OLT, CDO (caixa de emenda com splitter 1x8/1x16 no nome), CTO com a cor
  da fibra que a alimenta na descricao ("FIBRA AZUL", "LUZ VERDE") e a
  potencia medida por porta ("1 19.14 2 19.46 ...");
- postes (PT-12), por onde passam as linhas do cabo;
- linhas de fibra com a ocupacao escrita ("FIBRA AZUL ATIVA CTO - 01 ...");
- cameras com IP, MAC, modelo, serial da ONU e PON/ONU na descricao.

Tudo vira equipamento planejado + rota (planning_routes) dentro de um
projeto novo, com um relatorio do que foi lido, ligado por aproximacao ou
ignorado. Nada aqui toca inventario real nem equipamento.
"""
from __future__ import annotations

import io
import ipaddress
import json
import math
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from app.services.db_store import _conn, _current_tenant_slug
from app.services import planning_service as ps

# Mesmas chaves de cor do formulario de CTO (PLANNING_FIBER_COLORS em minusculo).
FIBER_COLORS = ["verde", "amarelo", "branco", "azul", "vermelho", "lilas", "marrom", "rosa", "preto", "cinza", "laranja", "agua"]
_COLOR_ALIASES = {
    "verde": "verde", "amarela": "amarelo", "amarelo": "amarelo", "branca": "branco", "branco": "branco",
    "azul": "azul", "vermelha": "vermelho", "vermelho": "vermelho", "lilas": "lilas", "lilás": "lilas",
    "violeta": "lilas", "marrom": "marrom", "marron": "marrom", "rosa": "rosa", "preta": "preto", "preto": "preto",
    "cinza": "cinza", "laranja": "laranja", "aqua": "agua", "agua": "agua", "água": "agua",
}
_COLOR_RE = "|".join(sorted(_COLOR_ALIASES, key=len, reverse=True))
MAX_KMZ_BYTES = 30 * 1024 * 1024
POLE_SNAP_M = 4.0
EQUIPMENT_SNAP_M = 45.0


def _norm_color(word: str) -> Optional[str]:
    return _COLOR_ALIASES.get(str(word or "").strip().lower())


def _distance_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ps._distance_m(a[0], a[1], b[0], b[1])


def _strip_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", value or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Leitura do KML
# ---------------------------------------------------------------------------

def _read_kml(raw: bytes) -> ET.Element:
    if len(raw) > MAX_KMZ_BYTES:
        raise ValueError("Arquivo grande demais (limite de 30 MB)")
    data = raw
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as kmz:
                names = [n for n in kmz.namelist() if n.lower().endswith(".kml")]
                if not names:
                    raise ValueError("O KMZ nao tem nenhum .kml dentro")
                main = "doc.kml" if "doc.kml" in names else names[0]
                info = kmz.getinfo(main)
                if info.file_size > MAX_KMZ_BYTES * 4:
                    raise ValueError("KML grande demais")
                data = kmz.read(main)
        except zipfile.BadZipFile as exc:
            raise ValueError("Arquivo KMZ invalido") from exc
    if b"<!DOCTYPE" in data[:2000].upper() or b"<!ENTITY" in data.upper():
        raise ValueError("KML com DOCTYPE/ENTITY nao e aceito")
    # Google Earth escreve gx:/kml: sem declarar o namespace: troca por _.
    data = re.sub(rb"<(/?)(\w+):(\w)", rb"<\1\2_\3", data)
    data = re.sub(rb" (\w+):(\w+)=", rb" \1_\2=", data).replace(b"xmlns_", b"xmlnsx_")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"KML invalido: {exc}") from exc


def _tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _tag(child) == name:
            return (child.text or "").strip()
    return ""


def _placemarks(root: ET.Element) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def walk(node: ET.Element, path: List[str]) -> None:
        for child in node:
            kind = _tag(child)
            if kind in ("Document", "Folder"):
                walk(child, path + [_child_text(child, "name")])
            elif kind == "Placemark":
                coords: List[Tuple[float, float]] = []
                geometry = "point"
                for g in child.iter():
                    gtag = _tag(g)
                    if gtag in ("LineString", "Polygon"):
                        geometry = "line" if gtag == "LineString" else "polygon"
                    if gtag == "coordinates":
                        for token in (g.text or "").split():
                            parts = token.split(",")
                            try:
                                coords.append((float(parts[1]), float(parts[0])))
                            except (IndexError, ValueError):
                                continue
                if not coords:
                    continue
                out.append({
                    "path": [p for p in path if p],
                    "name": _child_text(child, "name"),
                    "description": _strip_html(_child_text(child, "description")),
                    "style": _child_text(child, "styleUrl").lstrip("#").lower(),
                    "geometry": geometry,
                    "coords": coords,
                })

    walk(root, [])
    return out


# ---------------------------------------------------------------------------
# Classificacao
# ---------------------------------------------------------------------------

def _folder_color(path: List[str]) -> Optional[str]:
    for folder in reversed(path):
        match = re.search(rf"\b(?:FIBRA|RAMAL)\s+({_COLOR_RE})\b", folder, flags=re.I)
        if match:
            return _norm_color(match.group(1))
    return None


def _splitter(text: str) -> Optional[int]:
    match = re.search(r"\b1\s*[xX]\s*(\d{1,2})\b", text or "")
    if match and int(match.group(1)) in (2, 4, 8, 16, 32):
        return int(match.group(1))
    return None


def _camera_fields(description: str) -> Dict[str, Any]:
    def grab(label: str) -> str:
        match = re.search(rf"{label}\s*:\s*([^|📍🧬🌐🟢🔴🔑🛰️📷]+)", description, flags=re.I)
        return match.group(1).strip() if match else ""

    fields: Dict[str, Any] = {}
    model = grab("CAMERA")
    if model:
        fields["model"] = model
    ip = grab("IP")
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip or ""):
        fields["ip"] = ip
    mac = grab("MAC")
    if re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", mac or ""):
        fields["mac"] = mac.lower()
    serial = grab("ONU SERIAL")
    if serial:
        fields["onu_serial"] = serial.upper()
    pon = re.search(r"PON\s*(\d+)\s*/\s*ONU\s*(\d+)", description, flags=re.I)
    if pon:
        fields["pon"], fields["onu_position"] = pon.group(1), pon.group(2)
    status = re.search(r"STATUS\s*:\s*(ONLINE|OFFLINE)", description, flags=re.I)
    if status:
        fields["status"] = status.group(1).lower()
    return fields


def _classify(pm: Dict[str, Any]) -> str:
    name = pm["name"].upper()
    path = " / ".join(pm["path"]).upper()
    desc = pm["description"].upper()
    style = pm["style"]
    if pm["geometry"] == "line":
        return "fiber" if ("FIBRA" in path or "FIBRA" in name or "RAMA" in path or "PRINCIPAL" in path or "LINHA" in name) else "line_other"
    if pm["geometry"] != "point":
        return "skip"
    if "CAMERA:" in desc or " IP:" in f" {desc}" or "MAC:" in desc or style.startswith("cam") or "CAMERA" in path:
        return "camera"
    if re.match(r"^OLT\b", name):
        return "olt"
    if "POSTE" in path or re.match(r"^PT\s*-?\s*\d", name):
        return "pole"
    if "CDO" in name or "EMENDA" in name or "cx emenda" in style or "cx_emenda" in style:
        return "cdo"
    if "CTO" in name or style.startswith("msn_cto") or style.startswith("cto"):
        return "cto"
    if "QUADRA" in name or "RUA" in path:
        return "label"
    return "other"


def _cto_feed_color(desc: str) -> Optional[str]:
    match = re.search(rf"\b(?:FIBRA|LUZ)\s+({_COLOR_RE})\b", desc or "", flags=re.I)
    return _norm_color(match.group(1)) if match else None


def _port_powers(desc: str) -> Dict[str, float]:
    """"FIBRA VERDE 1 19.14 2 19.46 ..." -> {"1": -19.14, "2": -19.46}."""
    powers: Dict[str, float] = {}
    for port, value in re.findall(r"\b(\d{1,2})\s+(\d{1,2}[.,]\d{1,2})\b", desc or ""):
        number = float(value.replace(",", "."))
        if 5 <= number <= 40 and 1 <= int(port) <= 64:
            powers[str(int(port))] = -abs(number)
    return powers


def _line_occupancy(desc: str) -> Dict[str, str]:
    """"FIBRA AZUL ATIVA CTO - 01 FIBRA BRANCA INATIVA ..." -> {"azul": "CTO-01", "branco": "inativa"}."""
    found: Dict[str, str] = {}
    pattern = rf"\bFIBRA\s+({_COLOR_RE})\b\s*(ATIVA\s+DE\s+LINK|ATIVA\s+(?:CTO|CDO)\s*-?\s*\d+|ATIVA|INATIVA)?"
    for color_word, state in re.findall(pattern, desc or "", flags=re.I):
        color = _norm_color(color_word)
        if not color:
            continue
        state = re.sub(r"\s+", " ", (state or "").upper()).strip()
        if state.startswith("ATIVA DE LINK"):
            found[color] = "link"
        elif state.startswith("ATIVA C"):
            found[color] = re.sub(r"\s*-\s*", "-", state.replace("ATIVA ", "")).replace(" ", "-")
        elif state == "ATIVA":
            found[color] = "ativa"
        elif state == "INATIVA":
            found[color] = "inativa"
        else:
            found.setdefault(color, "mencionada")
    return found


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------

def parse_network(raw: bytes) -> Dict[str, Any]:
    """KMZ -> lista de equipamentos e rotas (ainda sem ids), mais o relatorio."""
    placemarks = _placemarks(_read_kml(raw))
    devices: List[Dict[str, Any]] = []
    lines: List[Dict[str, Any]] = []
    report = {"lidos": len(placemarks), "ignorados": [], "avisos": []}

    def site_of(path: List[str]) -> str:
        top = path[1] if len(path) > 1 else (path[0] if path else "Projeto")
        return re.sub(r"^CAMERAS\s+", "", top, flags=re.I).strip() or "Projeto"

    for pm in placemarks:
        kind = _classify(pm)
        lat, lon = pm["coords"][0]
        base = {
            "key": len(devices), "site": site_of(pm["path"]), "lat": lat, "lon": lon,
            "name": (pm["name"] or "").strip(), "ramal": _folder_color(pm["path"]),
            "folder": " / ".join(pm["path"][1:]), "description": pm["description"],
        }
        if kind == "fiber":
            lines.append({**base, "coords": pm["coords"], "occupancy": _line_occupancy(pm["description"]),
                          "principal": "PRINCIPAL" in (base["folder"] + " " + base["name"]).upper()})
        elif kind == "camera":
            devices.append({**base, "type": "camera", **_camera_fields(pm["description"])})
        elif kind == "pole":
            devices.append({**base, "type": "pole", "name": base["name"] or "PT"})
        elif kind == "olt":
            devices.append({**base, "type": "olt"})
        elif kind == "cdo":
            devices.append({**base, "type": "cdo", "splitter": _splitter(base["name"] + " " + pm["description"])})
        elif kind == "cto":
            devices.append({**base, "type": "cto", "splitter": _splitter(base["name"] + " " + pm["description"]),
                            "feed": _cto_feed_color(pm["description"]), "powers": _port_powers(pm["description"])})
        elif kind == "label":
            report["ignorados"].append(f"Rotulo {base['name'] or '(sem nome)'}")
        else:
            report["ignorados"].append(f"{pm['geometry']} {base['name'] or '(sem nome)'} em {base['folder'] or 'raiz'}")
    return {"devices": devices, "lines": lines, "report": report}


def _nearest(point: Tuple[float, float], candidates: List[Dict[str, Any]], limit: float) -> Optional[Dict[str, Any]]:
    best, best_d = None, limit
    for item in candidates:
        d = _distance_m(point, (item["lat"], item["lon"]))
        if d <= best_d:
            best, best_d = item, d
    return best


def _parents_by_cable(paths: List[List[Optional[int]]], by_id: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
    """Percorre o cabo a partir das OLTs (busca em largura pelos vertices
    ligados a equipamento) e devolve {filho: pai}: CDO fica pendurado no CDO
    principal/OLT acima dele; CTO fica no CDO cujo splitter a alimenta (o
    cabo passa por outras CTOs no caminho, que nao sao o pai dela)."""
    graph: Dict[int, set] = {}
    for path in paths:
        known = [d for d in path if d is not None and d in by_id]
        for a, b in zip(known, known[1:]):
            if a != b:
                graph.setdefault(a, set()).add(b)
                graph.setdefault(b, set()).add(a)
    olts = [i for i, d in by_id.items() if d["type"] == "olt" and i in graph]
    came_from: Dict[int, Optional[int]] = {i: None for i in olts}
    queue = list(olts)
    while queue:
        node = queue.pop(0)
        for nxt in sorted(graph.get(node, ())):
            if nxt not in came_from:
                came_from[nxt] = node
                queue.append(nxt)
    parents: Dict[int, int] = {}
    for node, item in by_id.items():
        if node not in came_from or item["type"] not in ("cdo", "cto"):
            continue
        wanted = ("cdo",) if item["type"] == "cto" else ("cdo", "olt")
        up = came_from[node]
        while up is not None and by_id[up]["type"] not in wanted:
            up = came_from[up]
        if up is not None:
            parents[node] = up
    return parents


def import_network(raw: bytes, project_name: str = "", client_name: str = "") -> Dict[str, Any]:
    parsed = parse_network(raw)
    devices, lines, report = parsed["devices"], parsed["lines"], parsed["report"]
    if not devices and not lines:
        raise ValueError("Nao encontrei OLT, CDO, CTO, poste, camera nem linha de fibra neste arquivo")
    tenant = _current_tenant_slug()
    project = ps.save_project({"name": project_name.strip() or "Projeto importado", "client_name": client_name, "status": "planned"})
    project_id = int(project["id"])

    sites = sorted({d["site"] for d in devices} | {l["site"] for l in lines})
    site_ids = {name: int(ps.save_site(project_id, {"name": name[:120]})["id"]) for name in sites}

    network = [d for d in devices if d["type"] in ("olt", "cdo", "cto")]
    poles = [d for d in devices if d["type"] == "pole"]

    # --- ligacoes da arvore optica (aproximadas; marcadas como sugeridas) ---
    def same_site(item, pool):
        return [p for p in pool if p["site"] == item["site"]]

    for item in network:
        if item["type"] == "cdo":
            principal = "PRINCIPAL" in item["name"].upper()
            ups = [d for d in same_site(item, network) if d is not item and (
                d["type"] == "olt" or (d["type"] == "cdo" and "PRINCIPAL" in d["name"].upper() and not principal))]
            item["parent"] = min(ups, key=lambda d: _distance_m((item["lat"], item["lon"]), (d["lat"], d["lon"])), default=None)
        elif item["type"] == "cto":
            ups = [d for d in same_site(item, network) if d["type"] == "cdo" and d.get("ramal") == item.get("ramal")] \
                or [d for d in same_site(item, network) if d["type"] == "cdo"]
            item["parent"] = min(ups, key=lambda d: _distance_m((item["lat"], item["lon"]), (d["lat"], d["lon"])), default=None)

    # --- cameras agrupadas por ONU: uma caixa de CFTV por serial ---
    by_serial: Dict[str, List[Dict[str, Any]]] = {}
    for cam in (d for d in devices if d["type"] == "camera"):
        if cam.get("onu_serial"):
            by_serial.setdefault(cam["onu_serial"], []).append(cam)
    boxes: List[Dict[str, Any]] = []
    for serial, cams in by_serial.items():
        lat = sum(c["lat"] for c in cams) / len(cams)
        lon = sum(c["lon"] for c in cams) / len(cams)
        box = {"type": "box", "site": cams[0]["site"], "lat": lat, "lon": lon, "name": f"CX ONU {serial[-6:]}", "serial": serial,
               "pon": cams[0].get("pon", ""), "onu_position": cams[0].get("onu_position", "")}
        ctos = [d for d in network if d["type"] == "cto" and d["site"] == box["site"]]
        box["parent"] = _nearest((lat, lon), ctos, 250.0)
        boxes.append(box)
        for cam in cams:
            cam["box"] = box

    rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []  # (item, campos)
    order = {"olt": 0, "cdo": 1, "cto": 2, "pole": 3, "box": 4, "camera": 6}

    def fields_for(item: Dict[str, Any]) -> Dict[str, Any]:
        meta: Dict[str, Any] = {"origem": "kmz", "kmz_pasta": item.get("folder", "")}
        if item.get("description") and item["type"] in ("cdo", "cto"):
            meta["kmz_nota"] = item["description"][:1000]
        dtype, manufacturer, model, ip, pon, onu_pos = item["type"], "", "", "", "", ""
        if item["type"] == "cdo":
            dtype = "cto"
            meta.update({"papel": "splitter_primario", "port_capacity": item.get("splitter") or 8, "total_fo": 12})
            if item.get("ramal") and "PRINCIPAL" not in item["name"].upper():
                meta["cor_fibra"] = [item["ramal"]]
            if item.get("splitter"):
                meta["splitter"] = f"1x{item['splitter']}"
        elif item["type"] == "cto":
            ports = item.get("splitter") or (max((int(p) for p in item.get("powers") or {}), default=0) or 8)
            meta.update({"papel": "splitter_terminal", "port_capacity": ports, "splitter": f"1x{ports}", "total_fo": 12})
            if item.get("feed"):
                meta["cor_fibra"] = [item["feed"]]
            if item.get("ramal"):
                meta["ramal"] = item["ramal"]
            if item.get("powers"):
                meta["port_power_dbm"] = item["powers"]
        elif item["type"] == "olt":
            meta["pon_port_capacity"] = 16
        elif item["type"] == "box":
            meta["onu_serial"] = item.get("serial", "")
            meta["auto"] = True
        elif item["type"] == "camera":
            model, ip = item.get("model", ""), item.get("ip", "")
            manufacturer = "Intelbras" if model.upper().startswith("VIP") else ""
            pon, onu_pos = item.get("pon", ""), item.get("onu_position", "")
            for key in ("mac", "onu_serial"):
                if item.get(key):
                    meta[key if key != "onu_serial" else "serial"] = item[key]
            if item.get("status"):
                meta["kmz_status"] = item["status"]
        if item.get("parent") is not None:
            meta["ligacao_sugerida"] = True
        return {"device_type": dtype, "name": (item.get("name") or dtype.upper())[:120], "ip": ip,
                "manufacturer": manufacturer, "model": model[:80], "pon": pon, "onu_position": onu_pos,
                "latitude": item["lat"], "longitude": item["lon"], "metadata": meta}

    everything = [d for d in devices if d["type"] != "camera"] + boxes + [d for d in devices if d["type"] == "camera"]
    everything.sort(key=lambda d: order.get(d["type"], 5))
    with _conn() as c:
        for item in everything:
            fields = fields_for(item)
            ip = fields["ip"]
            if ip:
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    ip = ""
            key = uuid.uuid4().hex
            c.execute(
                """INSERT INTO planning_devices
                   (tenant_slug, device_key, project_id, site_id, parent_id, device_type, name, ip,
                    manufacturer, model, pon, onu_position, latitude, longitude, reference_image_url,
                    notes, metadata_json, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tenant, key, project_id, site_ids.get(item["site"]), None, fields["device_type"], fields["name"], ip,
                 fields["manufacturer"], fields["model"], str(fields["pon"]), str(fields["onu_position"]),
                 fields["latitude"], fields["longitude"], "", "", json.dumps(fields["metadata"], ensure_ascii=False), "planned"),
            )
            row = c.execute("SELECT id FROM planning_devices WHERE tenant_slug=? AND device_key=?", (tenant, key)).fetchone()
            item["id"] = int(row["id"])

        # ONU dentro de cada caixa (com serial/PON/ONU) e cameras ligadas nela.
        for box in boxes:
            key = uuid.uuid4().hex
            meta = {"serial": box["serial"], "eth_port_capacity": 4, "origem": "kmz"}
            c.execute(
                """INSERT INTO planning_devices
                   (tenant_slug, device_key, project_id, site_id, parent_id, device_type, name, ip, manufacturer, model,
                    pon, onu_position, latitude, longitude, reference_image_url, notes, metadata_json, status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tenant, key, project_id, site_ids.get(box["site"]), box["id"], "onu", f"ONU {box['serial']}", "", "", "",
                 str(box["pon"]), str(box["onu_position"]), box["lat"], box["lon"], "", "", json.dumps(meta), "planned"),
            )
            box["onu_id"] = int(c.execute("SELECT id FROM planning_devices WHERE tenant_slug=? AND device_key=?", (tenant, key)).fetchone()["id"])

        def link(child_id: int, parent_id: int) -> None:
            c.execute("UPDATE planning_devices SET parent_id=? WHERE id=? AND tenant_slug=? AND project_id=?",
                      (parent_id, child_id, tenant, project_id))

        for item in network + boxes:
            if item.get("parent") is not None and item["parent"].get("id"):
                link(item["id"], item["parent"]["id"])
        for cam in (d for d in devices if d["type"] == "camera" and d.get("box")):
            link(cam["id"], cam["box"]["onu_id"])

        # --- rotas: vertices grudam no poste/equipamento mais proximo ---
        equipment = [d for d in network if d.get("id")]
        made = 0
        drawn_paths: List[List[Optional[int]]] = []
        for line in lines:
            path = []
            coords = line["coords"]
            for index, (lat, lon) in enumerate(coords):
                ends = index in (0, len(coords) - 1)
                target = None
                if ends:
                    target = _nearest((lat, lon), equipment, EQUIPMENT_SNAP_M) or _nearest((lat, lon), poles, POLE_SNAP_M)
                else:
                    target = _nearest((lat, lon), poles, POLE_SNAP_M) or _nearest((lat, lon), equipment, POLE_SNAP_M)
                # Linha curta com as duas pontas perto do mesmo equipamento: a
                # ponta repetida fica livre (coordenada desenhada), nao some.
                if target and any(pt["device_id"] == target["id"] for pt in path):
                    target = None
                point = {"lat": lat, "lon": lon, "device_id": target["id"] if target else None}
                if path and ps._distance_m(path[-1]["lat"], path[-1]["lon"], lat, lon) < 0.5:
                    continue
                path.append(point)
            if len(path) < 2:
                report["avisos"].append(f"Linha {line['name']} ficou com menos de 2 pontos")
                continue
            drawn_paths.append([pt["device_id"] for pt in path])
            first, last = path[0]["device_id"], path[-1]["device_id"]
            length = sum(ps._distance_m(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(path, path[1:]))
            meta = {"origem": "kmz", "kmz_nome": line["name"], "ramal": line.get("ramal") or ("principal" if line["principal"] else ""),
                    "kmz_ocupacao": line["occupancy"]}
            c.execute(
                """INSERT INTO planning_routes (tenant_slug, route_key, project_id, kind, name, from_device_id, to_device_id,
                   path_json, length_m, cable_model, fiber_count, slack_m, notes, metadata_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tenant, uuid.uuid4().hex, project_id, "fiber_main", line["name"][:120], first,
                 last if last != first else None, json.dumps(path), round(length, 1),
                 "Cabo optico 12 FO autossustentado", 12, 0, "", json.dumps(meta, ensure_ascii=False)),
            )
            made += 1
        # Quem alimenta quem, seguindo o cabo desenhado a partir da OLT:
        # vale mais que a proximidade usada acima.
        by_id = {d["id"]: d for d in network + poles if d.get("id")}
        followed = _parents_by_cable(drawn_paths, by_id)
        for child_id, parent_id in followed.items():
            child = by_id[child_id]
            link(child_id, parent_id)
            child["parent"] = by_id[parent_id]
            child["ligacao"] = "cabo"
        report["ligados_pelo_cabo"] = len(followed)
        report["ligados_por_proximidade"] = sum(1 for d in network if d.get("parent") is not None and d.get("ligacao") != "cabo")
        report["sem_ligacao"] = [d["name"] for d in network if d["type"] != "olt" and d.get("parent") is None][:30]
        for item in network:
            meta_row = c.execute("SELECT metadata_json FROM planning_devices WHERE id=? AND tenant_slug=?", (item["id"], tenant)).fetchone()
            meta = json.loads(meta_row["metadata_json"] or "{}")
            meta.pop("ligacao_sugerida", None)
            if item.get("parent") is not None:
                meta["ligacao"] = item.get("ligacao") or "proximidade"
            c.execute("UPDATE planning_devices SET metadata_json=? WHERE id=? AND tenant_slug=?", (json.dumps(meta, ensure_ascii=False), item["id"], tenant))
        c.execute("UPDATE planning_projects SET updated_at=datetime('now') WHERE id=? AND tenant_slug=?", (project_id, tenant))
        c.commit()

    counts: Dict[str, int] = {}
    for item in devices:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    report.update({
        "projeto_id": project_id, "sites": len(sites), "caixas_por_onu": len(boxes), "rotas": made,
        "contagem": counts, "ignorados": report["ignorados"][:50], "total_ignorados": len(report["ignorados"]),
        "cameras_sem_onu": sum(1 for d in devices if d["type"] == "camera" and not d.get("onu_serial")),
        "ctos_sem_cor": sum(1 for d in devices if d["type"] == "cto" and not d.get("feed")),
    })
    return report
