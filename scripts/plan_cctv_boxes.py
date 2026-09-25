"""Gera uma proposta de caixas de CFTV a partir dos pontos de camera de um KML."""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


EARTH_RADIUS_M = 6_371_000.0
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def _tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def read_points(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    points: list[dict] = []
    for placemark in root.findall(".//{*}Placemark"):
        coordinates = placemark.find(".//{*}Point/{*}coordinates")
        if coordinates is None or not (coordinates.text or "").strip():
            continue
        values = [part.strip() for part in coordinates.text.strip().split(",")]
        if len(values) < 2:
            continue
        points.append({
            "name": (placemark.findtext("./{*}name") or f"Camera {len(points) + 1}").strip(),
            "lon": float(values[0]),
            "lat": float(values[1]),
        })
    if not points:
        raise ValueError("O KML nao possui pontos de camera")
    return points


def project(points: list[dict]) -> tuple[float, float, float]:
    lat0 = sum(point["lat"] for point in points) / len(points)
    lon0 = sum(point["lon"] for point in points) / len(points)
    cosine = math.cos(math.radians(lat0))
    for point in points:
        point["x"] = EARTH_RADIUS_M * math.radians(point["lon"] - lon0) * cosine
        point["y"] = EARTH_RADIUS_M * math.radians(point["lat"] - lat0)
    return lat0, lon0, cosine


def osrm_json(path: str, params: dict | None = None) -> dict:
    query = urllib.parse.urlencode(params or {})
    url = f"https://router.project-osrm.org/{path}" + (f"?{query}" if query else "")
    request = urllib.request.Request(url, headers={"User-Agent": "SightOps-CFTV-Planning/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if payload.get("code") != "Ok":
        raise RuntimeError(f"Servico de rotas retornou {payload.get('code', 'erro desconhecido')}")
    return payload


def road_distance_matrix(points: list[dict]) -> list[list[float | None]]:
    coordinates = ";".join(f"{point['lon']:.7f},{point['lat']:.7f}" for point in points)
    payload = osrm_json(f"table/v1/driving/{coordinates}", {"annotations": "distance"})
    raw = payload["distances"]
    snap = [float(item.get("distance") or 0) for item in payload.get("sources", [])]
    matrix: list[list[float | None]] = []
    for source in range(len(points)):
        row: list[float | None] = []
        for target in range(len(points)):
            if source == target:
                row.append(0.0)
                continue
            directed = [raw[source][target], raw[target][source]]
            available = [float(value) for value in directed if value is not None]
            row.append((min(available) + snap[source] + snap[target]) if available else None)
        matrix.append(row)
    return matrix


def group_points(points: list[dict], radius: float, max_cameras: int = 15) -> list[dict]:
    """Agrupa por percurso viario, sempre ancorando a caixa no ponto de uma camera."""
    matrix = road_distance_matrix(points)
    remaining = set(range(len(points)))
    groups: list[dict] = []
    while remaining:
        choices = []
        for anchor in remaining:
            reachable = [index for index in remaining if matrix[anchor][index] is not None and matrix[anchor][index] <= radius]
            reachable.sort(key=lambda index: (matrix[anchor][index] or 0, points[index]["name"]))
            indexes = reachable[:max_cameras]
            distances = [float(matrix[anchor][index] or 0) for index in indexes]
            choices.append((len(indexes), -max(distances), -sum(distances) / len(distances), -anchor, anchor, indexes))
        _, _, _, _, anchor, indexes = max(choices)
        groups.append({"anchor": anchor, "center": (points[anchor]["x"], points[anchor]["y"]),
                       "indexes": sorted(indexes), "route_distances": {index: matrix[anchor][index] for index in indexes}})
        remaining.difference_update(indexes)
    return groups


def equipment_for(camera_count: int) -> str:
    if camera_count == 1:
        return "ONU/ONT + injetor PoE"
    if camera_count <= 3:
        return "ONU/ONT + switch PoE 5 portas"
    if camera_count <= 7:
        return "ONU/ONT + switch PoE 8 portas"
    if camera_count <= 15:
        return "ONU/ONT + switch PoE 16 portas"
    return "ONU/ONT + switch PoE dimensionado"


def unproject(x: float, y: float, lat0: float, lon0: float, cosine: float) -> tuple[float, float]:
    lat = lat0 + math.degrees(y / EARTH_RADIUS_M)
    lon = lon0 + math.degrees(x / (EARTH_RADIUS_M * cosine))
    return lat, lon


def add_text(parent: ET.Element, name: str, value: str) -> ET.Element:
    node = ET.SubElement(parent, _tag(name))
    node.text = value
    return node


def add_style(document: ET.Element, style_id: str, color: str, scale: str) -> None:
    style = ET.SubElement(document, _tag("Style"), {"id": style_id})
    icon_style = ET.SubElement(style, _tag("IconStyle"))
    add_text(icon_style, "color", color)
    add_text(icon_style, "scale", scale)


def add_point(folder: ET.Element, name: str, lon: float, lat: float, style: str, description: str) -> None:
    placemark = ET.SubElement(folder, _tag("Placemark"))
    add_text(placemark, "name", name)
    add_text(placemark, "description", description)
    add_text(placemark, "styleUrl", f"#{style}")
    point = ET.SubElement(placemark, _tag("Point"))
    add_text(point, "coordinates", f"{lon:.8f},{lat:.8f},0")


def road_route(box: tuple[float, float], camera: dict) -> tuple[float, list[tuple[float, float]]]:
    if abs(box[0] - camera["lat"]) < 1e-10 and abs(box[1] - camera["lon"]) < 1e-10:
        return 0.0, [(box[1], box[0])]
    coordinates = f"{box[1]:.7f},{box[0]:.7f};{camera['lon']:.7f},{camera['lat']:.7f}"
    payload = osrm_json(f"route/v1/driving/{coordinates}", {"overview": "full", "geometries": "geojson"})
    route = payload["routes"][0]
    return float(route["distance"]), [(float(lon), float(lat)) for lon, lat in route["geometry"]["coordinates"]]


def add_line(folder: ET.Element, name: str, route: list[tuple[float, float]], distance: float) -> None:
    placemark = ET.SubElement(folder, _tag("Placemark"))
    add_text(placemark, "name", name)
    add_text(placemark, "description", f"Percurso estimado pela malha viaria: {distance:.1f} m. Validar postes e passagem em campo.")
    style = ET.SubElement(placemark, _tag("Style"))
    line_style = ET.SubElement(style, _tag("LineStyle"))
    add_text(line_style, "color", "ff00a86b")
    add_text(line_style, "width", "3")
    line = ET.SubElement(placemark, _tag("LineString"))
    add_text(line, "tessellate", "1")
    add_text(line, "coordinates", " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in route))


def write_outputs(points: list[dict], groups: list[dict], lat0: float, lon0: float, cosine: float, radius: float, output: Path) -> None:
    root = ET.Element(_tag("kml"))
    document = ET.SubElement(root, _tag("Document"))
    add_text(document, "name", "Proposta de caixas de CFTV - Telha")
    add_text(document, "description", f"Estudo pela malha viaria com percurso maximo de {radius:.0f} m. Caixas ancoradas em pontos de camera. Validar postes, passagem, energia e autorizacoes em campo.")
    add_style(document, "camera", "ff00a86b", "0.8")
    add_style(document, "box", "ff00a5ff", "1.1")
    cameras_folder = ET.SubElement(document, _tag("Folder")); add_text(cameras_folder, "name", "Cameras originais")
    boxes_folder = ET.SubElement(document, _tag("Folder")); add_text(boxes_folder, "name", "Caixas de CFTV propostas")
    cables_folder = ET.SubElement(document, _tag("Folder")); add_text(cables_folder, "name", "Cabos CAT5e estimados")

    for camera in points:
        add_point(cameras_folder, camera["name"], camera["lon"], camera["lat"], "camera", "Ponto original do arquivo recebido.")

    distance_rows = []
    planning_rows = []
    for number, group in enumerate(groups, start=1):
        box_name = f"CX-{number:02d} - CFTV"
        center_x, center_y = group["center"]
        box_lat, box_lon = unproject(center_x, center_y, lat0, lon0, cosine)
        cameras = [points[index] for index in group["indexes"]]
        straight_distances = [math.hypot(camera["x"] - center_x, camera["y"] - center_y) for camera in cameras]
        routes = [road_route((box_lat, box_lon), camera) for camera in cameras]
        distances = [route[0] for route in routes]
        equipment = equipment_for(len(cameras))
        description = (
            f"{len(cameras)} camera(s). {equipment}. Maior percurso viario estimado: {max(distances):.1f} m. "
            "Caixa ancorada no ponto de uma camera; validar poste/local acessivel."
        )
        add_point(boxes_folder, box_name, box_lon, box_lat, "box", description)
        terminal_name = f"{box_name} - ONU 1"
        distribution_type = "injector" if len(cameras) == 1 else "switch"
        distribution_name = f"{box_name} - {'INJETOR POE' if distribution_type == 'injector' else 'SWITCH POE'} 1"
        port_capacity = 1 if distribution_type == "injector" else (5 if len(cameras) <= 3 else (8 if len(cameras) <= 7 else 16))
        common = {"ip": "", "site": "TELHA", "fabricante": "", "pon": "", "onu": "", "imagem": ""}
        planning_rows.extend([
            {**common, "tipo": "box", "nome": box_name, "modelo": "Caixa hermetica", "equipamento_pai": "",
             "latitude": f"{box_lat:.7f}", "longitude": f"{box_lon:.7f}",
             "metadata": json.dumps({"assembly": "cctv_box", "camera_count": len(cameras)}, ensure_ascii=False),
             "observacoes": "Coordenada proposta; validar poste e acesso em campo."},
            {**common, "tipo": "onu", "nome": terminal_name, "modelo": "", "equipamento_pai": box_name,
             "latitude": f"{box_lat:.7f}", "longitude": f"{box_lon:.7f}",
             "metadata": json.dumps({"container_name": box_name, "role": "optical_terminal"}, ensure_ascii=False),
             "observacoes": "Fabricante, modelo, PON e posicao serao definidos no projeto executivo."},
            {**common, "tipo": distribution_type, "nome": distribution_name, "modelo": "", "equipamento_pai": box_name,
             "latitude": f"{box_lat:.7f}", "longitude": f"{box_lon:.7f}",
             "metadata": json.dumps({"container_name": box_name, "uplink_name": terminal_name, "port_capacity": port_capacity, "poe": True}, ensure_ascii=False),
             "observacoes": equipment},
        ])
        for camera, straight, route_result in zip(cameras, straight_distances, routes):
            distance, route = route_result
            add_line(cables_folder, f"{box_name} -> {camera['name']}", route, distance)
            distance_rows.append({
                "caixa": box_name, "latitude_caixa": f"{box_lat:.7f}", "longitude_caixa": f"{box_lon:.7f}",
                "equipamento_sugerido": equipment, "camera": camera["name"], "latitude_camera": f"{camera['lat']:.7f}",
                "longitude_camera": f"{camera['lon']:.7f}", "distancia_reta_m": f"{straight:.1f}",
                "percurso_viario_m": f"{distance:.1f}",
            })
            planning_rows.append({
                **common, "tipo": "camera", "nome": camera["name"], "modelo": "", "equipamento_pai": distribution_name,
                "latitude": f"{camera['lat']:.7f}", "longitude": f"{camera['lon']:.7f}",
                "metadata": json.dumps({"container_name": box_name, "power_device_name": distribution_name,
                                          "distance_to_box_m": round(distance, 1), "route_distance_m": round(distance, 1),
                                          "straight_distance_m": round(straight, 1), "route_source": "OSM/OSRM",
                                          "coordinates_inherited": False}, ensure_ascii=False),
                "observacoes": f"Percurso viario estimado em {distance:.1f} m; distancia aerea {straight:.1f} m. Validar passagem em campo.",
            })

    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["tipo", "nome", "ip", "site", "fabricante", "modelo", "equipamento_pai", "pon", "onu", "latitude", "longitude", "imagem", "metadata", "observacoes"])
        writer.writeheader(); writer.writerows(planning_rows)
    distance_path = output.with_name(f"{output.stem}-distancias.csv")
    with distance_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(distance_rows[0]))
        writer.writeheader(); writer.writerows(distance_rows)
    kmz_path = output.with_suffix(".kmz")
    with zipfile.ZipFile(kmz_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(output, "doc.kml")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--radius", type=float, default=100.0, help="Percurso viario maximo entre caixa e camera")
    args = parser.parse_args()
    points = read_points(args.input)
    lat0, lon0, cosine = project(points)
    groups = group_points(points, args.radius)
    write_outputs(points, groups, lat0, lon0, cosine, args.radius, args.output)
    shared = sum(len(group["indexes"]) > 1 for group in groups)
    single = len(groups) - shared
    print(f"{len(points)} cameras; {len(groups)} caixas; {shared} compartilhadas; {single} individuais")
    for number, group in enumerate(groups, start=1):
        names = ", ".join(points[index]["name"].split("-C-")[0] for index in group["indexes"])
        print(f"CX-{number:02d}: {len(group['indexes'])} camera(s) [{names}]")


if __name__ == "__main__":
    main()
