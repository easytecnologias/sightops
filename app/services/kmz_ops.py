from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from app.services.camsnapshot.kmz_enricher import enrich_single_kmz

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}
_AUTO_NS_URI = "http://www.w3.org/2005/Atom"


def sanitize_kml_xml(data: bytes | str) -> bytes:
    """Make Google Earth KML variants parseable by ElementTree.

    Some KMZ files exported by Google Earth include ns2/ns3-prefixed Atom tags
    without declaring those prefixes. Google Earth accepts them, but Python's
    XML parser rejects the whole file with "unbound prefix".
    """
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
    fixed = text[:end - 1] + additions + text[end - 1:]
    return fixed.encode("utf-8")


def _norm_text(v: Any) -> str:
    s = str(v or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return s


_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos",
    "e", "em", "na", "no", "nas", "nos", "pra", "para",
}


def _singularize_token(tok: str) -> str:
    t = str(tok or "").strip()
    if len(t) <= 3:
        return t
    if t.endswith("oes"):
        return t[:-3] + "ao"
    if t.endswith("aes"):
        return t[:-3] + "ao"
    if t.endswith("is") and len(t) > 4:
        return t[:-2] + "l"
    if t.endswith("es") and len(t) > 4:
        return t[:-2]
    if t.endswith("s") and len(t) > 4:
        return t[:-1]
    return t


def _extract_leading_num(s: str) -> str:
    m = re.match(r"^\s*(\d{1,4})\b", str(s or ""))
    if not m:
        return ""
    try:
        return str(int(m.group(1)))
    except Exception:
        return m.group(1).lstrip("0") or "0"


def _name_variants(v: Any) -> set[str]:
    base = _norm_text(v)
    if not base:
        return set()
    toks = [t for t in base.split() if t]
    out: set[str] = {base}
    if toks:
        out.add(" ".join(toks))
        no_sw = [t for t in toks if t not in _STOPWORDS]
        if no_sw:
            out.add(" ".join(no_sw))
        sing = [_singularize_token(t) for t in toks]
        out.add(" ".join(sing))
        sing_no_sw = [t for t in sing if t not in _STOPWORDS]
        if sing_no_sw:
            out.add(" ".join(sing_no_sw))
    return {x.strip() for x in out if x and x.strip()}


def _best_fuzzy_hit(
    key: str,
    idx: dict[str, list[tuple[float, float]]],
    num_hint: str = "",
    min_ratio: float = 0.88,
) -> tuple[float, float] | None:
    if not key or not idx:
        return None
    best_k = ""
    best_ratio = 0.0
    for k in idx.keys():
        if num_hint:
            nk = _extract_leading_num(k)
            if nk and nk != num_hint:
                continue
        ratio = SequenceMatcher(None, key, k).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_k = k
    if best_k and best_ratio >= min_ratio:
        vals = idx.get(best_k) or []
        if vals:
            return vals[0]
    return None


def _parse_coord_tuple(token: str) -> list[float] | None:
    parts = [p for p in token.strip().split(",") if p != ""]
    if len(parts) < 2:
        return None
    try:
        lon = float(parts[0])
        lat = float(parts[1])
        return [lon, lat]
    except Exception:
        return None


def _parse_coords_text(text: str | None) -> list[list[float]]:
    if not text:
        return []
    out: list[list[float]] = []
    for token in re.split(r"\s+", text.strip()):
        c = _parse_coord_tuple(token)
        if c:
            out.append(c)
    return out


def _parse_placemark_geometry(pm: ET.Element) -> dict[str, Any] | None:
    point = pm.find(".//kml:Point/kml:coordinates", KML_NS)
    if point is not None:
        coords = _parse_coords_text(point.text)
        if coords:
            return {"type": "Point", "coordinates": coords[0]}

    line = pm.find(".//kml:LineString/kml:coordinates", KML_NS)
    if line is not None:
        coords = _parse_coords_text(line.text)
        if coords:
            return {"type": "LineString", "coordinates": coords}

    poly = pm.find(".//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS)
    if poly is not None:
        coords = _parse_coords_text(poly.text)
        if coords:
            return {"type": "Polygon", "coordinates": [coords]}

    return None


def kmz_to_geojson(kmz_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(kmz_path, "r") as zf:
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError("KMZ sem arquivo KML.")
        # Preferir doc.kml quando existir.
        kml_name = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
        kml_bytes = zf.read(kml_name)

    root = ET.fromstring(sanitize_kml_xml(kml_bytes))
    features: list[dict[str, Any]] = []

    for pm in root.findall(".//kml:Placemark", KML_NS):
        geom = _parse_placemark_geometry(pm)
        if not geom:
            continue
        name = (pm.findtext("kml:name", default="", namespaces=KML_NS) or "").strip()
        desc = (pm.findtext("kml:description", default="", namespaces=KML_NS) or "").strip()
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "name": name,
                    "description": desc,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def _point_index_from_geojson(geojson: dict[str, Any]) -> tuple[dict[str, list[tuple[float, float]]], int]:
    idx: dict[str, list[tuple[float, float]]] = {}
    total_points = 0
    for f in (geojson.get("features") or []):
        if not isinstance(f, dict):
            continue
        g = f.get("geometry") or {}
        if (g.get("type") or "").lower() != "point":
            continue
        coords = g.get("coordinates") or []
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except Exception:
            continue

        p = f.get("properties") or {}
        name = str(p.get("name") or "").strip()
        variants = _name_variants(name)
        if not variants:
            continue
        for key in variants:
            idx.setdefault(key, []).append((lat, lon))
        total_points += 1
    return idx, total_points


def _point_number_index_from_geojson(geojson: dict[str, Any]) -> dict[str, list[tuple[float, float, str]]]:
    idx: dict[str, list[tuple[float, float, str]]] = {}
    for f in (geojson.get("features") or []):
        if not isinstance(f, dict):
            continue
        g = f.get("geometry") or {}
        if (g.get("type") or "").lower() != "point":
            continue
        coords = g.get("coordinates") or []
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except Exception:
            continue
        p = f.get("properties") or {}
        name = str(p.get("name") or "").strip()
        num = _extract_leading_num(name)
        if num:
            idx.setdefault(num, []).append((lat, lon, name))
    return idx


def _best_number_hit(
    num_hint: str,
    candidates: list[str],
    by_num: dict[str, list[tuple[float, float, str]]],
) -> tuple[float, float] | None:
    if not num_hint:
        return None
    points = by_num.get(num_hint) or []
    if not points:
        return None
    if len(points) == 1:
        lat, lon, _name = points[0]
        return lat, lon

    candidate_keys = [c for c in (_norm_text(v) for v in candidates) if c]
    best: tuple[float, float] | None = None
    best_ratio = 0.0
    for lat, lon, name in points:
        key = _norm_text(name)
        if not key:
            continue
        ratio = max((SequenceMatcher(None, c, key).ratio() for c in candidate_keys), default=0.0)
        if ratio > best_ratio:
            best_ratio = ratio
            best = (lat, lon)
    return best if best and best_ratio >= 0.74 else None


def _row_site(row: dict[str, Any]) -> str:
    return _norm_text(str(row.get("site") or row.get("local") or "").strip())


def detect_kmz_site(inventory_rows: list[dict[str, Any]], geojson: dict[str, Any]) -> str:
    """Descobre a que site pertence o KMZ, pelo nome dos pontos.

    Um KMZ e sempre de um site so, mas o inventario tem todos juntos. Sem saber
    o site, os criterios fracos de match (numero no inicio do nome) casam entre
    sites diferentes: "1 - ESCOLA SANTANA" casa com "1 - SPEED ORLA" so porque
    ambos comecam com 1 -- e a camera de um municipio vai parar no mapa de
    outro. Aconteceu de verdade: 147 cameras de tres sites foram carimbadas com
    as coordenadas de Japaratinga.

    So o match FORTE (nome inteiro) vota, porque e o unico que nao vaza entre
    sites: medido no cliente rads, o KMZ de Japaratinga deu 60 votos nela e
    zero em qualquer outro site.
    """
    by_name, _ = _point_index_from_geojson(geojson)
    if not by_name:
        return ""
    votos: dict[str, int] = {}
    for row in (inventory_rows or []):
        if not isinstance(row, dict):
            continue
        site = _row_site(row)
        if not site:
            continue
        local = str(row.get("local") or "").strip()
        titulo = str(row.get("titulo") or "").strip()
        for chave in list(_name_variants(local)) + list(_name_variants(titulo)):
            if chave in by_name:
                votos[site] = votos.get(site, 0) + 1
                break
    if not votos:
        return ""
    return max(votos.items(), key=lambda item: item[1])[0]


def apply_locations_to_inventory(
    inventory_rows: list[dict[str, Any]],
    geojson: dict[str, Any],
    dry_run: bool = True,
    overwrite: bool = False,
    site: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    # Site do mapa: o informado por quem chamou, conferido contra o que os nomes
    # dos pontos dizem. Linhas de outro site passam intactas -- ver
    # detect_kmz_site(). Divergencia e erro, nao palpite: aplicar um mapa no site
    # errado espalha coordenada de um municipio no outro, em silencio.
    site_pedido = _norm_text(str(site or "").strip())
    site_detectado = detect_kmz_site(inventory_rows, geojson)
    if site_pedido and site_detectado and site_pedido != site_detectado:
        raise ValueError(
            f"Este mapa e do site '{site_detectado}', nao de '{site_pedido}'. "
            "Importe o KMZ do site certo ou corrija o site selecionado."
        )
    site_alvo = site_pedido or site_detectado

    # Sem saber o site, o criterio de casar so pelo numero do inicio do nome fica
    # proibido: e justamente ele que casa "1 - ESCOLA SANTANA" com
    # "1 - SPEED ORLA". Nome inteiro e IP continuam valendo, porque nao vazam.
    permitir_numero = bool(site_alvo)
    by_name, points_total = _point_index_from_geojson(geojson)
    by_num = _point_number_index_from_geojson(geojson)
    by_ip: dict[str, tuple[float, float]] = {}
    for f in (geojson.get("features") or []):
        if not isinstance(f, dict):
            continue
        g = f.get("geometry") or {}
        if (g.get("type") or "").lower() != "point":
            continue
        coords = g.get("coordinates") or []
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except Exception:
            continue
        p = f.get("properties") or {}
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        ips = re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", name)
        for ip in ips:
            if ip not in by_ip:
                by_ip[ip] = (lat, lon)

    out_rows: list[dict[str, Any]] = []
    updated = 0
    skipped_has_loc = 0
    no_match = 0
    no_match_rows: list[dict[str, Any]] = []

    fora_do_site = 0
    for row in (inventory_rows or []):
        if not isinstance(row, dict):
            continue
        r = dict(row)
        if site_alvo and _row_site(r) and _row_site(r) != site_alvo:
            # Camera de outro site nao pode receber coordenada deste mapa.
            fora_do_site += 1
            out_rows.append(r)
            continue
        local = str(r.get("local") or "").strip()
        titulo = str(r.get("titulo") or "").strip()
        ip = str(r.get("ip") or "").strip()

        local_variants = list(_name_variants(local))
        titulo_variants = list(_name_variants(titulo))
        num_hint = _extract_leading_num(local) or _extract_leading_num(titulo)
        hit: tuple[float, float] | None = None

        for key_local in local_variants:
            if key_local in by_name:
                hit = by_name[key_local][0]
                break
        if not hit:
            for key_titulo in titulo_variants:
                if key_titulo in by_name:
                    hit = by_name[key_titulo][0]
                    break
        if not hit:
            for k in local_variants + titulo_variants:
                hit = _best_fuzzy_hit(k, by_name, num_hint=num_hint, min_ratio=0.88)
                if hit:
                    break
        if not hit and num_hint:
            hit = _best_fuzzy_hit(_norm_text(f"{num_hint} {titulo}"), by_name, num_hint=num_hint, min_ratio=0.84)
        if not hit and num_hint:
            hit = _best_fuzzy_hit(_norm_text(f"{num_hint} {local}"), by_name, num_hint=num_hint, min_ratio=0.84)
        if not hit and num_hint and permitir_numero:
            hit = _best_number_hit(num_hint, [local, titulo], by_num)
        if not hit and (local_variants or titulo_variants):
            # ultimo fallback: aceita sem numero, mas com limite mais alto para evitar falso positivo
            for k in local_variants + titulo_variants:
                hit = _best_fuzzy_hit(k, by_name, num_hint="", min_ratio=0.92)
                if hit:
                    break
        if not hit and ip and ip in by_ip:
            hit = by_ip[ip]

        if not hit:
            no_match += 1
            no_match_rows.append(
                {
                    "ip": ip,
                    "titulo": titulo,
                    "local": local,
                }
            )
            out_rows.append(r)
            continue

        # Quando há mais de um ponto para a mesma chave, usamos o primeiro.
        lat, lon = hit
        has_latlon = bool(str(r.get("lat") or "").strip()) and bool(str(r.get("lon") or "").strip())
        if has_latlon and not overwrite:
            skipped_has_loc += 1
            out_rows.append(r)
            continue

        if not dry_run:
            r["lat"] = round(lat, 8)
            r["lon"] = round(lon, 8)
        updated += 1
        out_rows.append(r)

    summary = {
        "ok": True,
        "points_total": points_total,
        "updated": updated,
        "no_match": no_match,
        "skipped_has_loc": skipped_has_loc,
        "fora_do_site": fora_do_site,
        "site": site_alvo,
        "dry_run": bool(dry_run),
        "overwrite": bool(overwrite),
    }
    return out_rows, summary, no_match_rows


def generate_enriched_kmz(imported_kmz: Path, inventory_rows: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out = enrich_single_kmz(str(imported_kmz), inventory_rows, str(output_dir))
    return Path(out)


def read_geojson_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


# --- edicao de pontos direto no mapa -----------------------------------------
# Marcar uma camera no Google Earth e reimportar o KMZ inteiro so para acertar
# um ponto e trabalho demais. Aqui o ponto e gravado no proprio KMZ, que segue
# sendo a fonte de verdade: o geojson que o mapa le e regerado dele, entao mapa
# e arquivo baixado nunca divergem.

def _mesmo_ponto(pm: ET.Element, nome_alvo: str) -> bool:
    nome = (pm.findtext("kml:name", default="", namespaces=KML_NS) or "").strip()
    return _norm_text(nome) == _norm_text(nome_alvo)


def editar_ponto_no_kmz(
    kmz_path: Path,
    *,
    nome: str,
    lat: float | None = None,
    lon: float | None = None,
    descricao: str = "",
    remover: bool = False,
    novo_nome: str = "",
) -> dict[str, Any]:
    """Adiciona, move, renomeia ou remove um ponto no KMZ, casando pelo nome.

    Devolve o que aconteceu para a tela poder dizer ao usuario. Nome vazio e
    recusado: sem ele o ponto nao casa com camera nenhuma e vira pino solto.
    Renomear sozinho (sem lat/lon) so vale pra ponto que ja existe -- criar
    um ponto novo exige coordenada, entao nao ha "so nome" possivel ali.
    """
    nome = str(nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome do ponto.")
    novo_nome = str(novo_nome or "").strip()
    tem_coord = lat is not None and lon is not None
    if not remover and not tem_coord and not novo_nome:
        raise ValueError("Informe latitude e longitude do ponto.")
    if not kmz_path.exists():
        raise ValueError("Camada nao encontrada.")

    with zipfile.ZipFile(kmz_path, "r") as zf:
        nomes = zf.namelist()
        kml_names = [n for n in nomes if n.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError("KMZ sem arquivo KML.")
        kml_name = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
        conteudo = {n: zf.read(n) for n in nomes}

    ET.register_namespace("", KML_NS["kml"])
    root = ET.fromstring(sanitize_kml_xml(conteudo[kml_name]))

    # o Placemark pode estar dentro de qualquer Folder; procura o pai real
    pai_de: dict[ET.Element, ET.Element] = {f: p for p in root.iter() for f in p}
    existentes = [pm for pm in root.findall(".//kml:Placemark", KML_NS) if _mesmo_ponto(pm, nome)]

    if remover:
        if not existentes:
            return {"acao": "inalterado", "motivo": "ponto nao encontrado"}
        for pm in existentes:
            pai_de[pm].remove(pm)
        acao = "removido"
    elif existentes:
        # mover e/ou renomear: preserva estilo e descricao do original, so
        # troca o que foi pedido
        moveu = False
        renomeou = False
        for pm in existentes:
            if tem_coord:
                coord = pm.find(".//kml:Point/kml:coordinates", KML_NS)
                if coord is None:
                    ponto = ET.SubElement(pm, f"{{{KML_NS['kml']}}}Point")
                    coord = ET.SubElement(ponto, f"{{{KML_NS['kml']}}}coordinates")
                coord.text = f"{float(lon):.8f},{float(lat):.8f},0"
                moveu = True
            if novo_nome and novo_nome != nome:
                nome_el = pm.find("kml:name", KML_NS)
                if nome_el is None:
                    nome_el = ET.SubElement(pm, f"{{{KML_NS['kml']}}}name")
                nome_el.text = novo_nome
                renomeou = True
        acao = "movido e renomeado" if moveu and renomeou else "renomeado" if renomeou else "movido"
        nome = novo_nome if renomeou else nome
    else:
        # criar: exige coordenada de verdade -- "so renomear" nao faz sentido
        # pra um ponto que ainda nao existe
        if not tem_coord:
            raise ValueError("Ponto nao encontrado. Informe latitude e longitude para criar um novo.")
        # pendura no primeiro Document/Folder disponivel
        destino = root.find(".//kml:Document", KML_NS) or root
        pm = ET.SubElement(destino, f"{{{KML_NS['kml']}}}Placemark")
        ET.SubElement(pm, f"{{{KML_NS['kml']}}}name").text = nome
        if descricao:
            ET.SubElement(pm, f"{{{KML_NS['kml']}}}description").text = descricao
        ponto = ET.SubElement(pm, f"{{{KML_NS['kml']}}}Point")
        ET.SubElement(ponto, f"{{{KML_NS['kml']}}}coordinates").text = (
            f"{float(lon):.8f},{float(lat):.8f},0"
        )
        acao = "criado"

    conteudo[kml_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    # regrava o zip inteiro: alterar um membro no lugar nao e suportado
    tmp = kmz_path.with_suffix(".kmz.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, dados in conteudo.items():
            zf.writestr(n, dados)
    tmp.replace(kmz_path)

    return {"acao": acao, "nome": nome}
