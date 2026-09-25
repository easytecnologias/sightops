"""O mapa de um site nao pode carimbar coordenada em camera de outro site.

Bug real, medido no cliente rads em 20/08/2026: o KMZ de JAPARATINGA (61 pontos)
casou com 61 cameras de SANTANA, 61 de BARRA DE SAO MIGUEL e 25 de ESCOLA MEDEA
-- 147 cameras de outros municipios foram parar no mapa de Japaratinga. A causa
nao era o match por nome (esse nunca vazou), e sim os criterios fracos: o numero
no inicio do titulo. "1 - ESCOLA NOSSA SENHORA SANTANA" casava com
"1 - SPEED ORLA" so porque ambos comecam com 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.kmz_ops import apply_locations_to_inventory, detect_kmz_site


def ponto(nome: str, lat: float, lon: float) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": nome},
    }


# KMZ de Japaratinga, com os nomes reais do cliente
KMZ_JAPARATINGA = {
    "type": "FeatureCollection",
    "features": [
        ponto("1 - SPEED ORLA", -9.0679, -35.2413),
        ponto("2 - SPEED PRACA DOS IDOSOS", -9.0690, -35.2420),
        ponto("3 - LPR PONTAL", -9.0701, -35.2431),
    ],
}

INVENTARIO = [
    # Japaratinga: devem receber as coordenadas do mapa
    {"ip": "100.66.11.28", "titulo": "1 - SPEED ORLA", "local": "JAPARATINGA"},
    {"ip": "100.66.11.29", "titulo": "2 - SPEED PRACA DOS IDOSOS", "local": "JAPARATINGA"},
    # Santana: mesmo numero no inicio, outro municipio -- nao pode casar
    {"ip": "100.64.11.1", "titulo": "1 - ESCOLA NOSSA SENHORA SANTANA", "local": "SANTANA"},
    {"ip": "100.64.11.3", "titulo": "3 - ESTACIONAMENTO ESCOLA SRA SANTANA", "local": "SANTANA"},
    # Barra: idem, e esta com coordenada propria que nao pode ser sobrescrita
    {"ip": "100.65.11.2", "titulo": "2 - ORLA BARRA", "local": "BARRA DE SAO MIGUEL",
     "lat": -9.8300, "lon": -35.9000},
]


def falhas() -> list[str]:
    erros: list[str] = []

    # 1) o site do mapa e deduzido pelos nomes, sem ninguem informar
    site = detect_kmz_site(INVENTARIO, KMZ_JAPARATINGA)
    if site != "japaratinga":
        erros.append(f"deteccao de site: veio {site!r}, esperado 'japaratinga'")

    # 2) com overwrite ligado (o modo que causou o estrago), so Japaratinga muda
    novas, resumo, _ = apply_locations_to_inventory(
        INVENTARIO, KMZ_JAPARATINGA, dry_run=False, overwrite=True,
    )
    por_ip = {r["ip"]: r for r in novas}

    if not por_ip["100.66.11.28"].get("lat"):
        erros.append("camera de Japaratinga nao recebeu coordenada")
    if resumo["updated"] != 2:
        erros.append(f"esperava 2 atualizadas (as de Japaratinga), veio {resumo['updated']}")

    for ip, site_esperado in (("100.64.11.1", "SANTANA"), ("100.64.11.3", "SANTANA")):
        if por_ip[ip].get("lat") or por_ip[ip].get("lon"):
            erros.append(f"{ip} ({site_esperado}) recebeu coordenada do mapa de Japaratinga")

    barra = por_ip["100.65.11.2"]
    if (barra.get("lat"), barra.get("lon")) != (-9.8300, -35.9000):
        erros.append(f"camera de Barra teve a coordenada propria sobrescrita: {barra.get('lat')}, {barra.get('lon')}")

    # 3) nenhuma linha pode sumir -- o inventario nao encolhe
    if len(novas) != len(INVENTARIO):
        erros.append(f"o apply devolveu {len(novas)} linhas de {len(INVENTARIO)}: inventario encolheu")

    # 4) as de fora do site sao contadas como tal, nao como "sem match"
    if resumo.get("fora_do_site") != 3:
        erros.append(f"fora_do_site = {resumo.get('fora_do_site')}, esperado 3")

    # 5) pedir o site errado tem de FALHAR, nao carimbar coordenada de outro
    #    municipio calado. Foi assim que 147 cameras se perderam.
    try:
        apply_locations_to_inventory(
            INVENTARIO, KMZ_JAPARATINGA, dry_run=False, overwrite=True, site="SANTANA",
        )
        erros.append("aplicar o mapa de Japaratinga pedindo SANTANA passou sem erro")
    except ValueError as exc:
        if "japaratinga" not in str(exc).lower():
            erros.append(f"erro de site divergente nao diz qual e o site certo: {exc}")

    # 6) mapa que nao casa por nome com ninguem nao pode cair no criterio fraco
    #    (numero), senao volta a espalhar coordenada entre sites
    desconhecido = {
        "type": "FeatureCollection",
        "features": [ponto("1 - PONTO DE OUTRO CLIENTE", -3.1, -60.0)],
    }
    _, resumo3, _ = apply_locations_to_inventory(
        INVENTARIO, desconhecido, dry_run=True, overwrite=True,
    )
    if resumo3["updated"] != 0:
        erros.append(f"mapa sem site reconhecido casou {resumo3['updated']} camera(s) pelo numero")

    return erros


def main() -> int:
    erros = falhas()
    for e in erros:
        print("FALHOU:", e)
    if not erros:
        print("OK: o mapa de um site nao encosta em camera de outro site")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
