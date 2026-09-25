"""Edicao de ponto direto no KMZ: criar, mover e remover.

Marcar uma camera no Google Earth e reimportar o KMZ inteiro so para acertar um
ponto e trabalho demais. Estas operacoes gravam no proprio KMZ, que segue sendo
a fonte de verdade -- o geojson que o mapa le e regerado dele, entao mapa e
arquivo baixado nunca divergem.
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

KML_BASE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Mapa de teste</name>
    <Folder>
      <name>Cameras</name>
      <Placemark>
        <name>01 - PORTARIA</name>
        <description>IP: 10.10.8.11</description>
        <Point><coordinates>-36.670000,-9.760000,0</coordinates></Point>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


def montar_kmz(destino: Path) -> Path:
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", KML_BASE)
    return destino


def pontos(kmz: Path) -> dict[str, tuple[float, float]]:
    from app.services.kmz_ops import kmz_to_geojson

    saida = {}
    for f in kmz_to_geojson(kmz).get("features", []):
        if (f.get("geometry") or {}).get("type") != "Point":
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        saida[str((f.get("properties") or {}).get("name") or "")] = (round(lat, 6), round(lon, 6))
    return saida


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services.kmz_ops import editar_ponto_no_kmz

    with tempfile.TemporaryDirectory() as tmp:
        kmz = montar_kmz(Path(tmp) / "mapa.kmz")

        # --- estado inicial
        assert pontos(kmz) == {"01 - PORTARIA": (-9.76, -36.67)}, pontos(kmz)

        # --- criar um ponto novo, sem tocar no que ja existia
        r = editar_ponto_no_kmz(kmz, nome="02 - PRACA", lat=-9.77, lon=-36.68,
                                descricao="IP: 10.10.8.12")
        assert r["acao"] == "criado", r
        atual = pontos(kmz)
        assert atual["02 - PRACA"] == (-9.77, -36.68), atual
        assert atual["01 - PORTARIA"] == (-9.76, -36.67), "ponto existente foi alterado"

        # --- mover: mesma quantidade de pontos, coordenada nova
        r = editar_ponto_no_kmz(kmz, nome="01 - PORTARIA", lat=-9.5, lon=-36.5)
        assert r["acao"] == "movido", r
        atual = pontos(kmz)
        assert atual["01 - PORTARIA"] == (-9.5, -36.5), atual
        assert len(atual) == 2, atual

        # --- mover casa sem depender de acento nem caixa
        editar_ponto_no_kmz(kmz, nome="02 - praca", lat=-9.9, lon=-36.9)
        assert pontos(kmz)["02 - PRACA"] == (-9.9, -36.9), pontos(kmz)

        # --- a descricao do ponto criado sobrevive (e por ela que o mapa acha o IP)
        from app.services.kmz_ops import kmz_to_geojson
        descs = {
            (f["properties"] or {}).get("name"): (f["properties"] or {}).get("description")
            for f in kmz_to_geojson(kmz).get("features", [])
        }
        assert "10.10.8.12" in str(descs.get("02 - PRACA")), descs

        # --- remover
        r = editar_ponto_no_kmz(kmz, nome="02 - PRACA", remover=True)
        assert r["acao"] == "removido", r
        assert "02 - PRACA" not in pontos(kmz), pontos(kmz)
        assert "01 - PORTARIA" in pontos(kmz), "removeu o ponto errado"

        # --- remover o que nao existe nao quebra nem apaga nada
        r = editar_ponto_no_kmz(kmz, nome="99 - INEXISTENTE", remover=True)
        assert r["acao"] == "inalterado", r
        assert len(pontos(kmz)) == 1, pontos(kmz)

        # --- nome vazio e recusado: sem nome o ponto nao casa com camera nenhuma
        for ruim in ({"nome": "", "lat": -9.0, "lon": -36.0},
                     {"nome": "03 - SEM COORD"}):
            try:
                editar_ponto_no_kmz(kmz, **ruim)
                raise AssertionError(f"deveria ter recusado: {ruim}")
            except ValueError:
                pass

        # --- renomear sozinho, sem mover: nao exige lat/lon
        r = editar_ponto_no_kmz(kmz, nome="01 - PORTARIA", novo_nome="01 - PORTARIA PRINCIPAL")
        assert r["acao"] == "renomeado", r
        assert r["nome"] == "01 - PORTARIA PRINCIPAL", r
        atual = pontos(kmz)
        assert "01 - PORTARIA" not in atual, "nome antigo deveria ter sumido"
        assert atual["01 - PORTARIA PRINCIPAL"] == (-9.5, -36.5), "coordenada nao pode mudar so por renomear"

        # --- renomear casa sem depender de acento nem caixa, igual mover ja fazia
        editar_ponto_no_kmz(kmz, nome="01 - portaria principal", novo_nome="01 - ENTRADA")
        assert "01 - ENTRADA" in pontos(kmz), pontos(kmz)

        # --- mover e renomear ao mesmo tempo, numa chamada so
        r = editar_ponto_no_kmz(kmz, nome="01 - ENTRADA", novo_nome="01 - ENTRADA NOVA", lat=-9.1, lon=-36.1)
        assert r["acao"] == "movido e renomeado", r
        atual = pontos(kmz)
        assert atual["01 - ENTRADA NOVA"] == (-9.1, -36.1), atual
        assert "01 - ENTRADA" not in atual, atual

        # --- renomear ponto que nao existe: nao cria nada (criar exige coordenada)
        try:
            editar_ponto_no_kmz(kmz, nome="99 - FANTASMA", novo_nome="99 - NOVO NOME")
            raise AssertionError("deveria ter recusado renomear ponto inexistente sem coordenada")
        except ValueError:
            pass
        assert "99 - NOVO NOME" not in pontos(kmz), pontos(kmz)

        # --- o KMZ continua um zip valido e legivel
        with zipfile.ZipFile(kmz) as zf:
            assert "doc.kml" in zf.namelist(), zf.namelist()
            assert zf.testzip() is None

    print("kmz editar ponto: criar, mover e remover ok")


if __name__ == "__main__":
    main()
