from __future__ import annotations

import csv
import io
import ipaddress
import json
import struct
import uuid
import zipfile
import zlib
from html import escape as html_escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from typing import Any, Dict, Iterable, List

from app.services.db_store import _conn, _current_tenant_slug


PROJECT_STATUSES = {"draft", "planned", "approved", "deploying", "completed"}
DEVICE_TYPES = {"camera", "onu", "ont", "olt", "switch", "injector", "cto", "recorder", "box", "pole", "rack", "dio", "other"}

KNOWN_CATALOG: Dict[str, Dict[str, List[str]]] = {
    "camera": {
        "Intelbras": ["VIP 1130 B G2", "VIP 1230 B G2", "VIP 3220 B", "VIP 3230 B", "VIP 3240 Z G2", "VIP 5230 SD"],
        "Hikvision": ["DS-2CD1023G0-I", "DS-2CD1123G0E-I", "DS-2CD2143G2-I"],
        "Dahua": ["IPC-HFW1230S", "IPC-HDW1230T", "IPC-HFW2431S-S2"],
        "Giga Security": ["GS0045", "GS0052"],
    },
    "onu": {
        "Intelbras": ["R1", "R1v2", "110Gi", "121W"],
        "Huawei": ["EG8010H", "EG8120L", "HG8245H"],
        "ZTE": ["F601", "F660", "F670L"],
    },
    "ont": {
        "Intelbras": ["110Gi", "121W"],
        "Huawei": ["EG8120L", "HG8245H"],
        "ZTE": ["F660", "F670L"],
    },
    "olt": {
        "Intelbras": ["8820i", "4840E"],
        "Huawei": ["MA5608T", "MA5800-X7"],
        "ZTE": ["C320", "C600"],
    },
    "switch": {
        "Intelbras": ["S1026F-P", "S2328G-B", "SG 2404 PoE L2+"],
        "MikroTik": ["CRS112-8P-4S-IN", "CRS328-24P-4S+RM"],
        "Ubiquiti": ["USW-24-POE", "USW-Pro-24-POE"],
        "TP-Link": ["TL-SG2428P", "TL-SG3428XMP"],
    },
    "injector": {
        "Intelbras": ["Injetor PoE 15 W", "Injetor PoE 30 W"],
        "Ubiquiti": ["POE-24-12W", "U-POE-AF", "U-POE-AT"],
        "TP-Link": ["TL-POE150S", "TL-POE160S"],
    },
    "cto": {
        "Generica": ["CTO 1x8", "CTO 1x16"],
    },
    "recorder": {
        "Intelbras": ["NVD 1232", "NVD 1432", "NVD 3116 P", "MHDX 1216", "MHDX 1232"],
        "Hikvision": ["DS-7616NI-K2", "DS-7732NI-K4"],
        "Dahua": ["NVR4216-4KS2", "NVR4232-4KS2"],
    },
}


def _planning_box_icon_png() -> bytes:
    """Icone PNG autocontido: fundo laranja e desenho branco de caixa."""
    size = 64
    pixels = bytearray(size * size * 4)

    def put(x: int, y: int, color: tuple[int, int, int, int]) -> None:
        if 0 <= x < size and 0 <= y < size:
            offset = (y * size + x) * 4
            pixels[offset:offset + 4] = bytes(color)

    orange = (232, 132, 18, 255)
    white = (255, 255, 255, 255)
    for y in range(size):
        for x in range(size):
            if (x - 32) ** 2 + (y - 32) ** 2 <= 29 ** 2:
                put(x, y, orange)

    def line(x0: int, y0: int, x1: int, y1: int, width: int = 3) -> None:
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        error = dx + dy
        while True:
            radius = width // 2
            for yy in range(y0 - radius, y0 + radius + 1):
                for xx in range(x0 - radius, x0 + radius + 1):
                    put(xx, yy, white)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    for start, end in (
        ((15, 24), (32, 15)), ((32, 15), (49, 24)), ((49, 24), (32, 34)),
        ((32, 34), (15, 24)), ((15, 24), (15, 43)), ((15, 43), (32, 53)),
        ((32, 53), (49, 43)), ((49, 43), (49, 24)), ((32, 34), (32, 53)),
    ):
        line(*start, *end)

    raw = b"".join(b"\x00" + bytes(pixels[y * size * 4:(y + 1) * size * 4]) for y in range(size))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _project_row(row: Any) -> Dict[str, Any]:
    item = dict(row)
    item["id"] = int(item["id"])
    return item


def _require_project(c: Any, project_id: int, tenant: str) -> Dict[str, Any]:
    row = c.execute(
        "SELECT * FROM planning_projects WHERE id=? AND tenant_slug=?",
        (int(project_id), tenant),
    ).fetchone()
    if not row:
        raise LookupError("Projeto nao encontrado")
    return _project_row(row)


def list_projects() -> List[Dict[str, Any]]:
    tenant = _current_tenant_slug()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT p.*,
                   COUNT(DISTINCT s.id) AS sites_count,
                   COUNT(DISTINCT d.id) AS devices_count,
                   COUNT(DISTINCT CASE WHEN d.device_type='camera' THEN d.id END) AS cameras_count,
                   COUNT(DISTINCT CASE WHEN d.device_type IN ('onu','ont') THEN d.id END) AS onus_count
            FROM planning_projects p
            LEFT JOIN planning_project_sites s ON s.project_id=p.id AND s.tenant_slug=p.tenant_slug
            LEFT JOIN planning_devices d ON d.project_id=p.id AND d.tenant_slug=p.tenant_slug
            WHERE p.tenant_slug=?
            GROUP BY p.id
            ORDER BY p.updated_at DESC, p.id DESC
            """,
            (tenant,),
        ).fetchall()
    return [_project_row(row) for row in rows]


def list_equipment_catalog() -> List[Dict[str, str]]:
    """Une sugestoes conhecidas com fabricante/modelo ja usados pelo tenant."""
    tenant = _current_tenant_slug()
    values: set[tuple[str, str, str, str]] = set()
    for device_type, manufacturers in KNOWN_CATALOG.items():
        for manufacturer, models in manufacturers.items():
            for model in models:
                values.add((device_type, manufacturer, model, "known"))

    with _conn() as c:
        queries = (
            ("SELECT device_type, manufacturer, model FROM planning_devices WHERE tenant_slug=?", (tenant,), "project"),
            ("SELECT 'camera' AS device_type, fabricante AS manufacturer, modelo AS model FROM ip_cameras WHERE tenant_slug=?", (tenant,), "inventory"),
            ("SELECT 'olt' AS device_type, vendor AS manufacturer, model FROM olts WHERE tenant_slug=?", (tenant,), "inventory"),
            ("SELECT 'recorder' AS device_type, fabricante AS manufacturer, modelo AS model FROM recorders WHERE tenant_slug=?", (tenant,), "inventory"),
        )
        for query, params, source in queries:
            try:
                for row in c.execute(query, params).fetchall():
                    item = dict(row)
                    device_type = str(item.get("device_type") or "other").strip().lower()
                    manufacturer = str(item.get("manufacturer") or "").strip()
                    model = str(item.get("model") or "").strip()
                    if manufacturer or model:
                        values.add((device_type, manufacturer, model, source))
            except Exception:
                continue
    return [
        {"device_type": dtype, "manufacturer": manufacturer, "model": model, "source": source}
        for dtype, manufacturer, model, source in sorted(values, key=lambda value: (value[0], value[1].lower(), value[2].lower()))
    ]


def get_project(project_id: int) -> Dict[str, Any] | None:
    tenant = _current_tenant_slug()
    with _conn() as c:
        try:
            project = _require_project(c, project_id, tenant)
        except LookupError:
            return None
        sites = [dict(row) for row in c.execute(
            "SELECT * FROM planning_project_sites WHERE project_id=? AND tenant_slug=? ORDER BY name",
            (int(project_id), tenant),
        ).fetchall()]
        devices = [dict(row) for row in c.execute(
            """
            SELECT d.*, s.name AS site_name, p.name AS parent_name
            FROM planning_devices d
            LEFT JOIN planning_project_sites s ON s.id=d.site_id AND s.tenant_slug=d.tenant_slug
            LEFT JOIN planning_devices p ON p.id=d.parent_id AND p.tenant_slug=d.tenant_slug
            WHERE d.project_id=? AND d.tenant_slug=?
            ORDER BY CASE d.device_type WHEN 'olt' THEN 1 WHEN 'onu' THEN 2 WHEN 'ont' THEN 2
                     WHEN 'switch' THEN 3 WHEN 'camera' THEN 4 ELSE 5 END, d.name
            """,
            (int(project_id), tenant),
        ).fetchall()]
    for device in devices:
        try:
            device["metadata"] = json.loads(device.get("metadata_json") or "{}")
        except (TypeError, ValueError):
            device["metadata"] = {}
    project["sites"] = sites
    project["devices"] = devices
    return project


def save_project(payload: Dict[str, Any], project_id: int | None = None) -> Dict[str, Any]:
    tenant = _current_tenant_slug()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o nome do projeto")
    status = str(payload.get("status") or "draft").strip().lower()
    if status not in PROJECT_STATUSES:
        raise ValueError("Situacao do projeto invalida")
    fields = {
        "name": name,
        "client_name": str(payload.get("client_name") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "status": status,
        "kmz_layer_id": str(payload.get("kmz_layer_id") or "").strip(),
    }
    with _conn() as c:
        if project_id:
            _require_project(c, project_id, tenant)
            c.execute(
                """UPDATE planning_projects SET name=?, client_name=?, description=?, status=?,
                   kmz_layer_id=?, updated_at=datetime('now') WHERE id=? AND tenant_slug=?""",
                (*fields.values(), int(project_id), tenant),
            )
            saved_id = int(project_id)
        else:
            key = uuid.uuid4().hex
            c.execute(
                """INSERT INTO planning_projects
                   (tenant_slug, project_key, name, client_name, description, status, kmz_layer_id)
                   VALUES(?,?,?,?,?,?,?)""",
                (tenant, key, *fields.values()),
            )
            row = c.execute(
                "SELECT id FROM planning_projects WHERE tenant_slug=? AND project_key=?",
                (tenant, key),
            ).fetchone()
            saved_id = int(row["id"])
        c.commit()
    return get_project(saved_id) or {}


def delete_project(project_id: int) -> bool:
    tenant = _current_tenant_slug()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM planning_projects WHERE id=? AND tenant_slug=?",
            (int(project_id), tenant),
        )
        c.commit()
        return bool(cur.rowcount)


def save_site(project_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _current_tenant_slug()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o site/local")
    notes = str(payload.get("notes") or "").strip()
    with _conn() as c:
        _require_project(c, project_id, tenant)
        c.execute(
            """INSERT INTO planning_project_sites(tenant_slug, project_id, name, notes)
               VALUES(?,?,?,?) ON CONFLICT(tenant_slug, project_id, name)
               DO UPDATE SET notes=excluded.notes""",
            (tenant, int(project_id), name, notes),
        )
        row = c.execute(
            "SELECT * FROM planning_project_sites WHERE tenant_slug=? AND project_id=? AND name=?",
            (tenant, int(project_id), name),
        ).fetchone()
        c.commit()
    return dict(row)


def update_site(project_id: int, site_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _current_tenant_slug()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o site/local")
    notes = str(payload.get("notes") or "").strip()
    with _conn() as c:
        _require_project(c, project_id, tenant)
        existing = c.execute(
            "SELECT id FROM planning_project_sites WHERE id=? AND project_id=? AND tenant_slug=?",
            (int(site_id), int(project_id), tenant),
        ).fetchone()
        if not existing:
            raise LookupError("Site nao encontrado")
        conflict = c.execute(
            "SELECT id FROM planning_project_sites WHERE tenant_slug=? AND project_id=? AND name=? AND id<>?",
            (tenant, int(project_id), name, int(site_id)),
        ).fetchone()
        if conflict:
            raise ValueError("Ja existe um site com esse nome neste projeto")
        c.execute(
            "UPDATE planning_project_sites SET name=?, notes=? WHERE id=? AND project_id=? AND tenant_slug=?",
            (name, notes, int(site_id), int(project_id), tenant),
        )
        row = c.execute(
            "SELECT * FROM planning_project_sites WHERE id=? AND project_id=? AND tenant_slug=?",
            (int(site_id), int(project_id), tenant),
        ).fetchone()
        c.commit()
    return dict(row)


def delete_site(project_id: int, site_id: int) -> bool:
    tenant = _current_tenant_slug()
    with _conn() as c:
        _require_project(c, project_id, tenant)
        cur = c.execute(
            "DELETE FROM planning_project_sites WHERE id=? AND project_id=? AND tenant_slug=?",
            (int(site_id), int(project_id), tenant),
        )
        c.commit()
        return bool(cur.rowcount)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace(",", "."))


def save_device(project_id: int, payload: Dict[str, Any], device_id: int | None = None) -> Dict[str, Any]:
    tenant = _current_tenant_slug()
    dtype = str(payload.get("device_type") or "camera").strip().lower()
    if dtype not in DEVICE_TYPES:
        raise ValueError("Tipo de equipamento invalido")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Informe o nome do equipamento")
    ip = str(payload.get("ip") or "").strip()
    if ip:
        ipaddress.ip_address(ip)
    site_id = int(payload["site_id"]) if payload.get("site_id") else None
    parent_id = int(payload["parent_id"]) if payload.get("parent_id") else None
    values = (
        site_id, parent_id, dtype, name, ip,
        str(payload.get("manufacturer") or "").strip(),
        str(payload.get("model") or "").strip(),
        str(payload.get("pon") or "").strip(),
        str(payload.get("onu_position") or "").strip(),
        _optional_float(payload.get("latitude")), _optional_float(payload.get("longitude")),
        str(payload.get("reference_image_url") or "").strip(),
        str(payload.get("notes") or "").strip(),
        json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
        str(payload.get("status") or "planned").strip().lower(),
    )
    with _conn() as c:
        _require_project(c, project_id, tenant)
        if site_id:
            site = c.execute(
                "SELECT id FROM planning_project_sites WHERE id=? AND project_id=? AND tenant_slug=?",
                (site_id, int(project_id), tenant),
            ).fetchone()
            if not site:
                raise ValueError("Site nao pertence a este projeto")
        if device_id:
            row = c.execute(
                "SELECT id FROM planning_devices WHERE id=? AND project_id=? AND tenant_slug=?",
                (int(device_id), int(project_id), tenant),
            ).fetchone()
            if not row:
                raise LookupError("Equipamento planejado nao encontrado")
            c.execute(
                """UPDATE planning_devices SET site_id=?, parent_id=?, device_type=?, name=?, ip=?,
                   manufacturer=?, model=?, pon=?, onu_position=?, latitude=?, longitude=?,
                   reference_image_url=?, notes=?, metadata_json=?, status=?, updated_at=datetime('now')
                   WHERE id=? AND project_id=? AND tenant_slug=?""",
                (*values, int(device_id), int(project_id), tenant),
            )
            saved_id = int(device_id)
        else:
            key = uuid.uuid4().hex
            c.execute(
                """INSERT INTO planning_devices
                   (tenant_slug, device_key, project_id, site_id, parent_id, device_type, name, ip,
                    manufacturer, model, pon, onu_position, latitude, longitude, reference_image_url,
                    notes, metadata_json, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tenant, key, int(project_id), *values),
            )
            row = c.execute(
                "SELECT id FROM planning_devices WHERE tenant_slug=? AND device_key=?",
                (tenant, key),
            ).fetchone()
            saved_id = int(row["id"])
        c.execute(
            "UPDATE planning_projects SET updated_at=datetime('now') WHERE id=? AND tenant_slug=?",
            (int(project_id), tenant),
        )
        saved = c.execute(
            "SELECT * FROM planning_devices WHERE id=? AND tenant_slug=?",
            (saved_id, tenant),
        ).fetchone()
        c.commit()
    return dict(saved)


def delete_device(project_id: int, device_id: int) -> bool:
    tenant = _current_tenant_slug()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM planning_devices WHERE id=? AND project_id=? AND tenant_slug=?",
            (int(device_id), int(project_id), tenant),
        )
        c.commit()
        return bool(cur.rowcount)


def generate_devices(project_id: int, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    count = max(1, min(int(payload.get("count") or 1), 500))
    first_number = int(payload.get("first_number") or 1)
    digits = max(1, min(int(payload.get("digits") or 2), 4))
    template = str(payload.get("name_template") or "{number} - CAMERA").strip()
    start_ip = str(payload.get("start_ip") or "").strip()
    base_ip = int(ipaddress.ip_address(start_ip)) if start_ip else None
    rows: List[Dict[str, Any]] = []
    for offset in range(count):
        number = str(first_number + offset).zfill(digits)
        item = dict(payload)
        name = template.replace("{number}", number).replace("{n}", str(first_number + offset))
        if count > 1 and name == template:
            # Padrao sem {number}/{n} geraria nome identico pra todos os equipamentos.
            name = f"{name} {number}"
        item["name"] = name
        item["ip"] = str(ipaddress.ip_address(base_ip + offset)) if base_ip is not None else ""
        for key in ("count", "first_number", "digits", "name_template", "start_ip"):
            item.pop(key, None)
        rows.append(save_device(project_id, item))
    return rows


def assemble_gpon_box(project_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria a hierarquia fisica e logica de uma caixa GPON planejada."""
    box_name = str(payload.get("box_name") or "").strip()
    if not box_name:
        raise ValueError("Informe o nome da caixa de CFTV")
    site_id = int(payload["site_id"]) if payload.get("site_id") else None
    latitude = _optional_float(payload.get("latitude"))
    longitude = _optional_float(payload.get("longitude"))
    onu_count = max(1, min(int(payload.get("onu_count") or 1), 4))
    distribution_count = max(1, min(int(payload.get("distribution_count") or 1), 4))
    distribution_type = str(payload.get("distribution_type") or "switch").strip().lower()
    if distribution_type not in {"switch", "injector"}:
        raise ValueError("Distribuicao deve ser switch ou injetor PoE")
    port_capacity = max(1, min(int(payload.get("port_capacity") or 5), 48))
    # Switch PoE reserva 1 porta pra uplink (liga no ONU/rede) -- essa porta
    # nao alimenta camera. Injetor PoE e passthrough de porta unica, sem uplink.
    uplink_ports = 1 if distribution_type == "switch" and port_capacity > 1 else 0
    poe_port_capacity = max(1, port_capacity - uplink_ports)
    camera_count = max(0, min(int(payload.get("camera_count") or 0), 100))
    total_ports = distribution_count * poe_port_capacity
    if camera_count > total_ports:
        raise ValueError(f"A caixa possui {total_ports} porta(s) PoE disponivel(is) ({port_capacity} porta(s) por switch, 1 reservada pra uplink), mas recebeu {camera_count} camera(s)")

    start_ip = str(payload.get("camera_start_ip") or "").strip()
    base_ip = int(ipaddress.ip_address(start_ip)) if start_ip else None
    first_number = int(payload.get("camera_first_number") or 1)
    name_template = str(payload.get("camera_name_template") or "{number} - CAMERA").strip()
    created: List[Dict[str, Any]] = []
    try:
        box = save_device(project_id, {
            "device_type": "box", "name": box_name, "site_id": site_id,
            "latitude": latitude, "longitude": longitude, "notes": payload.get("box_notes") or "",
            "metadata": {"assembly": "gpon_box", "member_count": onu_count + distribution_count + camera_count + (1 if payload.get("include_cto") else 0)},
        })
        created.append(box)

        onus: List[Dict[str, Any]] = []
        for index in range(onu_count):
            onu_type = str(payload.get("onu_type") or "onu").lower()
            onu = save_device(project_id, {
                "device_type": onu_type, "name": f"{box_name} - {onu_type.upper()} {index + 1}",
                "site_id": site_id, "parent_id": box["id"], "manufacturer": payload.get("onu_manufacturer") or "",
                "model": payload.get("onu_model") or "", "pon": payload.get("pon") or "", "onu_position": payload.get("onu_position") or "",
                "latitude": latitude, "longitude": longitude, "metadata": {"container_id": box["id"], "role": "optical_terminal"},
            })
            created.append(onu)
            onus.append(onu)

        cto = None
        if payload.get("include_cto"):
            cto = save_device(project_id, {
                "device_type": "cto", "name": str(payload.get("cto_name") or f"{box_name} - CTO").strip(),
                "site_id": site_id, "parent_id": box["id"], "model": payload.get("cto_model") or "",
                "latitude": latitude, "longitude": longitude, "metadata": {"container_id": box["id"], "optional": True},
            })
            created.append(cto)

        distributors: List[Dict[str, Any]] = []
        for index in range(distribution_count):
            label = "SWITCH POE" if distribution_type == "switch" else "INJETOR POE"
            distributor = save_device(project_id, {
                "device_type": distribution_type, "name": f"{box_name} - {label} {index + 1}",
                "site_id": site_id, "parent_id": box["id"], "manufacturer": payload.get("distribution_manufacturer") or "",
                "model": payload.get("distribution_model") or "", "latitude": latitude, "longitude": longitude,
                "metadata": {"container_id": box["id"], "uplink_device_id": onus[0]["id"], "port_capacity": port_capacity, "poe_port_capacity": poe_port_capacity, "uplink_ports": uplink_ports, "poe": True},
            })
            created.append(distributor)
            distributors.append(distributor)

        cameras: List[Dict[str, Any]] = []
        for index in range(camera_count):
            number = str(first_number + index).zfill(2)
            distributor = distributors[min(index // poe_port_capacity, len(distributors) - 1)]
            name = name_template.replace("{number}", number).replace("{n}", str(first_number + index))
            if camera_count > 1 and name == name_template:
                # Padrao sem {number}/{n} geraria nome identico pra todas as cameras.
                name = f"{name} {number}"
            camera = save_device(project_id, {
                "device_type": "camera", "name": name,
                "ip": str(ipaddress.ip_address(base_ip + index)) if base_ip is not None else "",
                "site_id": site_id, "parent_id": distributor["id"], "manufacturer": payload.get("camera_manufacturer") or "",
                "model": payload.get("camera_model") or "", "latitude": latitude, "longitude": longitude,
                "reference_image_url": payload.get("camera_image_url") or "",
                "metadata": {"container_id": box["id"], "power_device_id": distributor["id"], "port_number": (index % poe_port_capacity) + 1, "coordinates_inherited": True},
            })
            created.append(camera)
            cameras.append(camera)
        return {"box": box, "onus": onus, "cto": cto, "distributors": distributors, "cameras": cameras, "items": created}
    except Exception:
        for item in reversed(created):
            delete_device(project_id, int(item["id"]))
        raise


def import_csv(project_id: int, raw: bytes, defaults: Dict[str, Any]) -> Dict[str, Any]:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    aliases = {
        "tipo": "device_type", "equipamento": "device_type", "nome": "name", "titulo": "name",
        "fabricante": "manufacturer", "modelo": "model", "pon": "pon", "onu": "onu_position",
        "latitude": "latitude", "lat": "latitude", "longitude": "longitude", "lon": "longitude",
        "imagem": "reference_image_url", "foto": "reference_image_url", "observacoes": "notes",
        "observacao": "notes", "ip": "ip", "site": "site", "local": "site",
        "equipamento_pai": "parent_name", "pai": "parent_name", "ligado_a": "parent_name",
        "metadata": "metadata_json", "metadados": "metadata_json",
    }
    headers = {str(value or "").strip().lower() for value in (reader.fieldnames or [])}
    if not headers.intersection({"nome", "titulo"}):
        if {"caixa", "camera"}.issubset(headers) and any("distancia" in value for value in headers):
            raise ValueError(
                "Este arquivo e um relatorio de distancias. Importe o CSV principal de equipamentos, sem o sufixo -distancias."
            )
        raise ValueError('CSV incompatível: falta a coluna obrigatoria "nome"')
    errors: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for line_number, row in enumerate(reader, start=2):
        normalized = dict(defaults)
        for key, value in row.items():
            clean = str(key or "").strip().lower()
            normalized[aliases.get(clean, clean)] = str(value or "").strip()
        if not normalized.get("name"):
            errors.append({"line": line_number, "error": "nome ausente"})
            continue
        try:
            site_name = str(normalized.pop("site", "") or "").strip()
            if site_name:
                normalized["site_id"] = save_site(project_id, {"name": site_name}).get("id")
            parent_name = str(normalized.pop("parent_name", "") or "").strip()
            metadata_json = str(normalized.pop("metadata_json", "") or "").strip()
            if metadata_json:
                metadata = json.loads(metadata_json)
                if not isinstance(metadata, dict):
                    raise ValueError("metadata precisa ser um objeto JSON")
                normalized["metadata"] = metadata
            pending.append({"line": line_number, "parent_name": parent_name, "payload": normalized})
        except Exception as exc:
            errors.append({"line": line_number, "error": str(exc)})

    imported: List[Dict[str, Any]] = []
    detail = get_project(project_id) or {}
    ids_by_name = {
        str(item.get("name") or "").strip().casefold(): int(item["id"])
        for item in detail.get("devices") or [] if str(item.get("name") or "").strip()
    }
    while pending:
        deferred: List[Dict[str, Any]] = []
        progress = 0
        for item in pending:
            parent_name = item["parent_name"]
            parent_id = ids_by_name.get(parent_name.casefold()) if parent_name else None
            if parent_name and not parent_id:
                deferred.append(item)
                continue
            try:
                payload = dict(item["payload"])
                if parent_id:
                    payload["parent_id"] = parent_id
                saved = save_device(project_id, payload)
                imported.append(saved)
                ids_by_name[str(saved["name"]).strip().casefold()] = int(saved["id"])
                progress += 1
            except Exception as exc:
                errors.append({"line": item["line"], "error": str(exc)})
        if not deferred:
            break
        if progress == 0:
            for item in deferred:
                errors.append({"line": item["line"], "error": f"equipamento pai nao encontrado: {item['parent_name']}"})
            break
        pending = deferred
    return {"ok": not errors, "imported": len(imported), "errors": errors, "items": imported}


def export_project_kmz(project_id: int) -> tuple[str, bytes]:
    """Exporta o projeto planejado como KMZ sem alterar inventario ou equipamentos reais."""
    project = get_project(project_id)
    if not project:
        raise LookupError("Projeto nao encontrado")

    devices = project.get("devices") or []
    type_labels = {
        "camera": "Camera", "onu": "ONU", "ont": "ONT", "olt": "OLT", "switch": "Switch",
        "injector": "Injetor PoE", "cto": "CTO", "recorder": "Gravador", "box": "Caixa de CFTV",
        "pole": "Poste", "rack": "Rack", "dio": "DIO", "other": "Outro",
    }
    type_icons = {
        "camera": "📷", "onu": "📡", "ont": "📶", "olt": "🛰️", "switch": "🔀",
        "injector": "⚡", "cto": "🧷", "recorder": "💾", "box": "📦", "pole": "🗼", "rack": "🗄️", "dio": "🔗", "other": "⚙️",
    }
    # Mesma regra do frontend (planningItemHasNoIp): esses tipos nao tem IP
    # proprio, entao a linha de IP so polui o balao sem informacao real.
    types_without_ip = {"box", "pole", "cto", "onu", "injector", "rack", "dio"}

    def has_ip(item: Dict[str, Any]) -> bool:
        dtype = str(item.get("device_type") or "other")
        if dtype in types_without_ip:
            return False
        if dtype == "switch":
            return (item.get("metadata") or {}).get("switch_mode", "normal") == "smart"
        return True

    # Cores ABNT do cabo 12FO (mesmas do calculo de fibra/planning.js), em
    # formato KML (aabbggrr, nao rgb) -- assim o tracado da fibra no Google
    # Earth sai na mesma cor da CTO/DIO quando o metadata "cor" existe.
    fiber_colors = {
        "verde": "ff559d1f", "amarelo": "ff19c4f0", "branco": "ffe2dbd7", "azul": "ffae3f1c",
        "vermelho": "ff2b35d1", "lilas": "ffd99cb1", "lilás": "ffd99cb1", "marrom": "ff2b4a7b", "rosa": "ff9948ec",
    }
    fiber_default_color = "ff1a6aff"
    fiber_styles = "".join(
        f'<Style id="fiber-{name}"><LineStyle><color>{color}</color><width>3</width></LineStyle></Style>'
        for name, color in fiber_colors.items()
    ) + f'<Style id="fiber-default"><LineStyle><color>{fiber_default_color}</color><width>3</width></LineStyle></Style>'

    styles = (
        '<Style id="camera"><IconStyle><scale>0.82</scale><Icon><href>files/icons/cctv-green.png</href></Icon>'
        '</IconStyle><LabelStyle><scale>0.8</scale></LabelStyle></Style>'
        '<Style id="box"><IconStyle><scale>0.9</scale>'
        '<Icon><href>files/icons/cctv-box.png</href></Icon>'
        '</IconStyle><LabelStyle><scale>0.85</scale></LabelStyle></Style>'
        f'{fiber_styles}'
    )
    children_by_parent: Dict[int, List[Dict[str, Any]]] = {}
    for device in devices:
        if device.get("parent_id"):
            children_by_parent.setdefault(int(device["parent_id"]), []).append(device)

    def descendants(parent_id: int) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        for child in children_by_parent.get(int(parent_id), []):
            found.append(child)
            found.extend(descendants(int(child["id"])))
        return found

    def esc(value: Any) -> str:
        return html_escape(str(value), quote=False)

    def field_row(icon: str, label: str, value: Any) -> str:
        if value in (None, ""):
            return ""
        return (
            '<tr>'
            f'<td style="padding:4px 8px 4px 0;color:#5f6368;white-space:nowrap;vertical-align:top;">{icon} {esc(label)}</td>'
            f'<td style="padding:4px 0;color:#202124;vertical-align:top;">{esc(value)}</td>'
            '</tr>'
        )

    def field_block(icon: str, label: str, value: Any) -> str:
        # Pra texto longo (frase, lista) -- rotulo em cima, valor embaixo
        # ocupando a largura toda, em vez de espremer numa coluna estreita
        # de tabela (era o que deixava os baloes ilegiveis no Google Earth).
        if value in (None, ""):
            return ""
        return (
            '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #f1f3f4;">'
            f'<div style="color:#5f6368;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:4px;">{icon} {esc(label)}</div>'
            f'<div style="color:#202124;font-size:12px;line-height:1.5;">{esc(value)}</div>'
            '</div>'
        )

    def field_block_chips(icon: str, label: str, values: Any) -> str:
        if not values:
            return ""
        chips = "".join(
            f'<span style="display:inline-block;background:#f1f3f4;border-radius:10px;padding:2px 8px;margin:0 4px 4px 0;font-size:11px;color:#202124;">{esc(v)}</span>'
            for v in values
        )
        return (
            '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #f1f3f4;">'
            f'<div style="color:#5f6368;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;margin-bottom:4px;">{icon} {esc(label)}</div>'
            f'<div>{chips}</div>'
            '</div>'
        )

    def device_fields(item: Dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        model = " / ".join(filter(None, [item.get("manufacturer"), item.get("model")]))
        port_capacity = metadata.get("port_capacity") or metadata.get("pon_port_capacity")
        table_rows = [
            field_row("📍", "Site", item.get("site_name")),
            field_row("🌐", "IP", item.get("ip") if has_ip(item) else None),
            field_row("🏷️", "Fabricante/modelo", model),
            field_row("🔖", "Patrimonio", metadata.get("patrimonio")),
            field_row("🔗", "Ligado a", item.get("parent_name")),
            field_row("🧷", "Papel", metadata.get("papel")),
            field_row("🎨", "Cor (banner do projeto)", metadata.get("cor")),
            field_row("🧬", "Total de FO no tronco", metadata.get("total_fo")),
            field_row("🔢", "Capacidade de portas", port_capacity),
            field_row("🔌", "PON", item.get("pon")),
            field_row("#️⃣", "Posicao ONU", item.get("onu_position")),
            field_row("🔢", "Serial", metadata.get("serial")),
            field_row("🖧", "MAC", metadata.get("mac")),
            field_row("🧩", "VLAN", metadata.get("vlan")),
            field_row("📏", "Percurso ate a caixa", f"{metadata['route_distance_m']} m" if metadata.get("route_distance_m") not in (None, "") else None),
            field_row("📐", "Distancia ate a caixa", f"{metadata['distance_to_box_m']} m" if metadata.get("distance_to_box_m") not in (None, "") else None),
        ]
        table_html = "".join(table_rows)
        blocks_html = (
            field_block_chips("🔀", "Fibra fundida nesta caixa", metadata.get("cor_fibra"))
            + field_block_chips("📋", "Fibras mencionadas neste ponto (KMZ)", metadata.get("fibras_mencionadas"))
            + field_block("⚠️", "Nota de fusao", metadata.get("fibras_nota"))
            + field_block("📝", "Observacoes", item.get("notes"))
        )
        table_part = f'<table style="width:100%;border-collapse:collapse;font-size:12px;">{table_html}</table>' if table_html else ""
        return table_part + blocks_html

    def card_html(item: Dict[str, Any], extra_sections: str = "") -> str:
        dtype = str(item.get("device_type") or "other")
        icon = type_icons.get(dtype, "⚙️")
        label = type_labels.get(dtype, dtype)
        name = esc(item.get("name") or "Equipamento")
        return (
            '<div style="font-family:Roboto,Arial,sans-serif;width:280px;">'
            '<div style="background:#0f9d58;color:#fff;padding:10px 12px;border-radius:8px 8px 0 0;">'
            f'<div style="font-size:15px;font-weight:700;">{icon} {name}</div>'
            f'<div style="font-size:11px;opacity:.9;letter-spacing:.03em;text-transform:uppercase;">{esc(label)}</div>'
            '</div>'
            '<div style="border:1px solid #e0e0e0;border-top:0;border-radius:0 0 8px 8px;padding:8px 10px;">'
            f'{device_fields(item)}'
            f'{extra_sections}'
            '</div>'
            '</div>'
        )

    def item_chip(item: Dict[str, Any], sub: str) -> str:
        dtype = str(item.get("device_type") or "other")
        icon = type_icons.get(dtype, "⚙️")
        return (
            '<div style="display:flex;gap:6px;align-items:flex-start;padding:5px 0;border-top:1px solid #f1f3f4;">'
            f'<span>{icon}</span>'
            '<div style="min-width:0;">'
            f'<div style="font-weight:600;color:#202124;">{esc(item.get("name") or "Equipamento")}</div>'
            f'<div style="color:#5f6368;">{esc(sub)}</div>'
            '</div></div>'
        )

    def section_header(title: str, count: int) -> str:
        return (
            '<div style="margin-top:10px;padding-top:8px;border-top:2px solid #e8f5e9;'
            'font-size:11px;font-weight:700;color:#0f9d58;text-transform:uppercase;letter-spacing:.03em;">'
            f'{esc(title)} ({count})</div>'
        )

    def placemark(item: Dict[str, Any], style: str, extra_sections: str = "") -> str:
        lat = item.get("latitude")
        lon = item.get("longitude")
        if lat in (None, "") or lon in (None, ""):
            return ""
        return (
            "<Placemark>"
            f"<name>{xml_escape(str(item.get('name') or 'Equipamento'))}</name>"
            f"<styleUrl>#{style}</styleUrl>"
            f"<description><![CDATA[{card_html(item, extra_sections)}]]></description>"
            f"<Point><coordinates>{float(lon):.7f},{float(lat):.7f},0</coordinates></Point>"
            "</Placemark>"
        )

    cameras = [item for item in devices if item.get("device_type") == "camera"]
    boxes = [item for item in devices if item.get("device_type") == "box"]
    camera_placemarks = "".join(placemark(item, "camera") for item in cameras)
    box_placemarks: List[str] = []
    for box in boxes:
        members = descendants(int(box["id"]))
        internal = [item for item in members if item.get("device_type") != "camera"]
        linked_cameras = [item for item in members if item.get("device_type") == "camera"]
        extra = section_header("Equipamentos internos", len(internal))
        extra += "".join(
            item_chip(item, " / ".join(filter(None, [item.get("manufacturer"), item.get("model")])) or "Modelo a definir")
            for item in internal
        ) or '<div style="padding:5px 0;color:#5f6368;">Nenhum equipamento interno</div>'
        extra += section_header("Cameras atendidas", len(linked_cameras))
        extra += "".join(
            item_chip(
                item,
                f"IP {item.get('ip') or 'a definir'} · "
                f"{(item.get('metadata') or {}).get('route_distance_m') or (item.get('metadata') or {}).get('distance_to_box_m') or 'distancia a definir'} m",
            )
            for item in linked_cameras
        ) or '<div style="padding:5px 0;color:#5f6368;">Nenhuma camera vinculada</div>'
        box_placemarks.append(placemark(box, "box", extra))

    racks = [item for item in devices if item.get("device_type") == "rack"]
    rack_placemarks: List[str] = []
    for rack in racks:
        members = descendants(int(rack["id"]))
        extra = section_header("Equipamentos internos", len(members))
        extra += "".join(
            item_chip(item, " / ".join(filter(None, [item.get("manufacturer"), item.get("model")])) or "Modelo a definir")
            for item in members
        ) or '<div style="padding:5px 0;color:#5f6368;">Nenhum equipamento interno</div>'
        rack_placemarks.append(placemark(rack, "box", extra))

    # Rede PON (backbone): OLT, DIO e CTO/splitters -- projetos que modelam so
    # a arvore de fibra (sem CFTV) nao tinham nenhuma dessas categorias
    # exportadas, entao o KMZ saia vazio mesmo com dispositivos no projeto.
    def backbone_placemarks(device_type: str) -> List[str]:
        items = [item for item in devices if item.get("device_type") == device_type]
        out: List[str] = []
        for item in items:
            members = descendants(int(item["id"]))
            direct_cameras = [m for m in members if m.get("device_type") == "camera"]
            other_members = [m for m in members if m.get("device_type") != "camera"]
            extra = section_header("Equipamentos ligados", len(other_members))
            extra += "".join(
                item_chip(m, type_labels.get(str(m.get("device_type") or "other"), "Equipamento"))
                for m in other_members
            ) or '<div style="padding:5px 0;color:#5f6368;">Nenhum equipamento ligado</div>'
            if direct_cameras:
                extra += section_header("Cameras na arvore", len(direct_cameras))
                extra += "".join(item_chip(m, m.get("ip") or "IP a definir") for m in direct_cameras)
            out.append(placemark(item, "box", extra))
        return out

    olt_placemarks = backbone_placemarks("olt")
    dio_placemarks = backbone_placemarks("dio")
    cto_placemarks = backbone_placemarks("cto")

    # Tracado da fibra: uma linha reta de cada DIO/CTO ate o equipamento pai
    # (OLT, DIO ou outro CTO acima), igual ao trecho que "Calcular fibra
    # (backbone)" ja calcula no planejamento -- aqui so desenha no mapa.
    by_id = {int(d["id"]): d for d in devices}
    total_fo = next(
        (d.get("metadata", {}).get("total_fo") for d in devices if d.get("device_type") == "olt" and d.get("metadata", {}).get("total_fo")),
        None,
    )
    fiber_lines: List[str] = []
    for item in devices:
        if str(item.get("device_type") or "") not in ("cto", "dio"):
            continue
        parent_id = item.get("parent_id")
        if not parent_id:
            continue
        parent = by_id.get(int(parent_id))
        if not parent:
            continue
        lat1, lon1 = item.get("latitude"), item.get("longitude")
        lat2, lon2 = parent.get("latitude"), parent.get("longitude")
        if lat1 in (None, "") or lon1 in (None, "") or lat2 in (None, "") or lon2 in (None, ""):
            continue
        item_meta = item.get("metadata") or {}
        color_key = str(item_meta.get("cor") or "").strip().lower()
        style_id = f"fiber-{color_key}" if color_key in fiber_colors else "fiber-default"
        line_name = f"{parent.get('name') or 'Equipamento'} -> {item.get('name') or 'Equipamento'}"
        # Balao do trecho: mostra o que se sabe sobre ocupacao de fibra nesse
        # cabo -- fundida (spliced pra essa caixa/CTO) vs mencionada/livre,
        # conforme registrado no KMZ de origem (pode nao ser um inventario
        # completo, ver "Nota de fusao"). Rotulo em cima / valor embaixo pro
        # texto longo, senao o balao do Google Earth fica ilegivel.
        cor_fibra = item_meta.get("cor_fibra")
        fibras_mencionadas = item_meta.get("fibras_mencionadas")
        occupancy_blocks = (
            field_block("🧬", "Total de FO no cabo", total_fo)
            + field_block_chips("🔀", "Fibra fundida neste trecho (usada)", cor_fibra)
            + field_block_chips("🟢", "Fibras livres/mencionadas a partir daqui", fibras_mencionadas)
            + field_block("⚠️", "Nota de fusao", item_meta.get("fibras_nota"))
        )
        if not occupancy_blocks:
            occupancy_blocks = '<div style="color:#5f6368;font-size:12px;">Ocupacao de fibra nao registrada no KMZ de origem para este trecho.</div>'
        line_description = (
            '<div style="font-family:Roboto,Arial,sans-serif;width:280px;">'
            '<div style="background:#ff6a1a;color:#fff;padding:10px 12px;border-radius:8px 8px 0 0;">'
            f'<div style="font-size:14px;font-weight:700;">🧵 {esc(parent.get("name") or "")} → {esc(item.get("name") or "")}</div>'
            '<div style="font-size:11px;opacity:.9;letter-spacing:.03em;text-transform:uppercase;">Trecho de fibra</div>'
            '</div>'
            '<div style="border:1px solid #e0e0e0;border-top:0;border-radius:0 0 8px 8px;padding:8px 10px;">'
            f'{occupancy_blocks}'
            '</div>'
            '</div>'
        )
        fiber_lines.append(
            "<Placemark>"
            f"<name>{xml_escape(str(line_name))}</name>"
            f"<styleUrl>#{style_id}</styleUrl>"
            f"<description><![CDATA[{line_description}]]></description>"
            "<LineString><tessellate>1</tessellate><coordinates>"
            f"{float(lon2):.7f},{float(lat2):.7f},0 {float(lon1):.7f},{float(lat1):.7f},0"
            "</coordinates></LineString>"
            "</Placemark>"
        )

    folders = (
        '<Folder><name>Fibra (tracado)</name><open>1</open>' + ''.join(fiber_lines) + '</Folder>'
        '<Folder><name>Cameras</name><open>0</open>' + camera_placemarks + '</Folder>'
        '<Folder><name>Caixas de CFTV</name><open>1</open>' + ''.join(box_placemarks) + '</Folder>'
        '<Folder><name>Racks</name><open>1</open>' + ''.join(rack_placemarks) + '</Folder>'
        '<Folder><name>OLT</name><open>1</open>' + ''.join(olt_placemarks) + '</Folder>'
        '<Folder><name>DIO</name><open>1</open>' + ''.join(dio_placemarks) + '</Folder>'
        '<Folder><name>CTO / Splitters</name><open>1</open>' + ''.join(cto_placemarks) + '</Folder>'
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{xml_escape(str(project.get('name') or 'Projeto de CFTV'))}</name>"
        f"{styles}{folders}</Document></kml>"
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", document)
        camera_icon = Path(__file__).resolve().parent / "camsnapshot" / "assets" / "icons" / "cctv-green.png"
        if camera_icon.is_file():
            archive.write(camera_icon, "files/icons/cctv-green.png")
        archive.writestr("files/icons/cctv-box.png", _planning_box_icon_png())
    safe_name = "".join(char if char.isascii() and (char.isalnum() or char in "-_") else "-" for char in str(project.get("name") or "projeto-cftv")).strip("-")
    return f"{safe_name or 'projeto-cftv'}.kmz", output.getvalue()
