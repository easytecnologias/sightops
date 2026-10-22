"""Mapa: usuario com restricao de site so ve (e so mexe em) camada KMZ do
site dele. O site da camada sai das cameras do inventario completo que casam
com os pontos. Dados ficticios."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.core import permissions as P


def _ponto(nome, desc=""):
    return {"type": "Feature", "properties": {"name": nome, "description": desc},
            "geometry": {"type": "Point", "coordinates": [-36.0, -10.0]}}


def _camada(base, lid, label, feats, **meta):
    (base / f"{lid}.kmz").write_bytes(b"kmz")
    (base / f"{lid}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    (base / f"{lid}.meta.json").write_text(json.dumps({"id": lid, "label": label, **meta}), encoding="utf-8")


@pytest.fixture()
def mapa(tmp_path, monkeypatch):
    imp, gen = tmp_path / "imp", tmp_path / "gen"
    imp.mkdir()
    gen.mkdir()
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: imp)
    monkeypatch.setattr(tools, "_kmz_generated_layers_dir", lambda: gen)
    inv = {
        "switch": [{"ip": "10.45.0.14", "titulo": "14 - RUA A", "local": "PORTO REAL DO COLÉGIO"},
                   {"ip": "10.9.0.1", "titulo": "1 - PRACA", "local": "SANTANA"}],
        "olt": [{"ip": "10.8.0.2", "titulo": "2 - ORLA", "site": "BARRA DE SAO MIGUEL"}],
        "basico": [],
    }
    monkeypatch.setattr(tools, "load_inventory_json", lambda mode="olt": [dict(r) for r in inv[mode]])
    _camada(imp, "porto", "Porto Real outubro", [_ponto("14 - RUA A"), _ponto("CAI")])
    _camada(imp, "santana", "SANTANA", [_ponto("1 - PRACA"), _ponto("x", "ip 10.9.0.1")])
    _camada(imp, "barra", "mapa da orla", [_ponto("cam", "IP: 10.8.0.2")])
    _camada(imp, "japaratinga", "JAPARATINGA", [_ponto("sem cadastro")])
    _camada(imp, "pelo-nome", "Santana fase 2", [_ponto("poste")])
    _camada(gen, "gerada-santana", "SANTANA gerada", [_ponto("1 - PRACA")])
    return imp


def _sites(monkeypatch, sites):
    monkeypatch.setattr(P, "sites_da_sessao", lambda: sites)


def test_sem_restricao_ve_todas(mapa, monkeypatch):
    _sites(monkeypatch, None)
    assert {l["id"] for l in tools._list_kmz_import_layers(False)} == {"porto", "santana", "barra", "japaratinga", "pelo-nome"}
    tools._exigir_camada_liberada("santana")
    tools._exigir_sem_restricao_de_site()


def test_restrito_so_ve_a_camada_do_site_dele(mapa, monkeypatch):
    # acento e caixa nao importam ("COLÉGIO" no inventario, "Colegio" no perfil)
    _sites(monkeypatch, ["Porto Real do Colegio", "ESCOLA PRESIDENTE DUTRA"])
    assert [l["id"] for l in tools._list_kmz_import_layers(True)] == ["porto"]
    assert tools._list_kmz_generated_layers(False) == []
    _sites(monkeypatch, ["SANTANA"])
    # pelo IP da descricao, e pelo nome da camada quando nenhuma camera casa
    assert {l["id"] for l in tools._list_kmz_import_layers(False)} == {"santana", "pelo-nome"}
    assert [l["id"] for l in tools._list_kmz_generated_layers(False)] == ["gerada-santana"]


def test_rotas_da_camada_alheia_dao_404(mapa, monkeypatch):
    _sites(monkeypatch, ["PORTO REAL DO COLEGIO"])
    tools._exigir_camada_liberada("porto")
    for chamada in (
        lambda: tools.api_kmz_import_layer_download("santana"),
        lambda: tools.api_kmz_import_layer_download_enriched("barra"),
        lambda: tools.api_kmz_import_layer_delete("japaratinga"),
        lambda: tools.api_kmz_generated_layer_download("gerada-santana"),
        lambda: tools.api_kmz_generated_layer_delete("gerada-santana"),
    ):
        with pytest.raises(HTTPException) as e:
            asyncio.run(chamada())
        assert e.value.status_code == 404
    assert (mapa / "japaratinga.kmz").exists()  # nada apagado
    # rotas antigas do "ultimo importado" nao sabem o site
    for chamada in (tools.api_kmz_import_geojson, tools.api_kmz_import_download,
                    tools.api_kmz_generated_geojson, tools.api_kmz_generated_download):
        with pytest.raises(HTTPException) as e:
            asyncio.run(chamada())
        assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        asyncio.run(tools.api_kmz_import_locations_apply({"dry_run": True}))
    with pytest.raises(HTTPException) as e:
        asyncio.run(tools.api_kmz_generate({"layer_id": "santana"}))
    assert e.value.status_code == 404


def test_camada_nova_de_restrito_nasce_com_os_sites_dele(mapa, monkeypatch):
    _sites(monkeypatch, ["PORTO REAL DO COLEGIO"])
    import app.services.kmz_ops as K

    monkeypatch.setattr(K, "criar_kmz_vazio", lambda path, label: path.write_bytes(b"kmz"))
    monkeypatch.setattr(tools, "kmz_to_geojson", lambda path: {"type": "FeatureCollection", "features": []})
    r = asyncio.run(tools.api_kmz_import_layer_create({"label": "Rascunho Porto"}))
    assert r["layer"] is not None  # ele ve a camada que criou
    meta = json.loads((mapa / f"{r['id']}.meta.json").read_text(encoding="utf-8"))
    assert meta["sites"] == ["PORTO REAL DO COLEGIO"]
    _sites(monkeypatch, ["SANTANA"])
    assert r["id"] not in {l["id"] for l in tools._list_kmz_import_layers(False)}


def test_relatorio_do_mapa_restrito_so_com_o_que_e_dele(mapa, monkeypatch):
    monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "rads")
    _sites(monkeypatch, ["PORTO REAL DO COLÉGIO"])  # como no inventario
    with pytest.raises(HTTPException) as e:
        asyncio.run(tools.api_map_report_job_start(site="SANTANA"))
    assert e.value.status_code == 403
    # o relatorio em si: cameras e pontos de camada so dos sites dele
    import app.services.inventory_json as IJ
    from app.services import map_pdf_report as M
    import app.core.tenant_context as TC

    monkeypatch.setattr(IJ, "load_inventory_json", tools.load_inventory_json)
    assert {c["ip"] for c in M._cameras_do_cliente("")} == {"10.45.0.14"}
    monkeypatch.setattr(TC, "get_current_tenant_slug", lambda: "rads")
    monkeypatch.setattr(TC, "tenant_kmz_input_dir", lambda: mapa.parent / "kmz")
    (mapa.parent / "kmz_layers").mkdir()
    for f in mapa.iterdir():
        (mapa.parent / "kmz_layers" / f.name).write_bytes(f.read_bytes())
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: mapa.parent / "kmz_layers")
    assert {p["camada"] for p in M._pontos_do_mapa()} == {"Porto Real outubro"}
    _sites(monkeypatch, None)
    assert len({p["camada"] for p in M._pontos_do_mapa()}) == 5


def test_camada_mista_so_para_quem_acessa_todos_os_sites(mapa, monkeypatch):
    _camada(mapa, "mista", "Porto e Santana", [_ponto("14 - RUA A"), _ponto("14 - RUA A"), _ponto("1 - PRACA")])
    _sites(monkeypatch, ["PORTO REAL DO COLEGIO"])
    assert "mista" not in {l["id"] for l in tools._list_kmz_import_layers(False)}
    _sites(monkeypatch, ["PORTO REAL DO COLEGIO", "SANTANA"])
    assert "mista" in {l["id"] for l in tools._list_kmz_import_layers(False)}


def test_aplicar_localizacoes_restrito_nao_toca_outro_site(mapa, monkeypatch):
    # camada DELE com pontos nomeados como cameras de Santana (tentativa)
    _camada(mapa, "dele", "rascunho", [_ponto("14 - RUA A"), _ponto("1 - PRACA")], sites=["PORTO REAL DO COLEGIO"])
    linhas = [{"ip": "10.45.0.14", "titulo": "14 - RUA A", "local": "PORTO REAL DO COLEGIO"},
              {"ip": "10.9.0.1", "titulo": "1 - PRACA", "local": "SANTANA"}]
    salvo = {}
    monkeypatch.setattr(tools, "_load_rows_by_source", lambda source, mode="": [dict(r) for r in linhas])
    monkeypatch.setattr(tools, "_save_rows_by_source", lambda source, rows, mode="": salvo.setdefault("rows", rows))
    monkeypatch.setattr(tools, "tenant_locations_apply_report_path", lambda: mapa / "relatorio.json")
    _sites(monkeypatch, ["PORTO REAL DO COLEGIO"])
    with pytest.raises(HTTPException) as e:
        asyncio.run(tools.api_kmz_import_locations_apply({"layer_id": "dele", "dry_run": True, "site": "SANTANA"}))
    assert e.value.status_code == 403
    r = asyncio.run(tools.api_kmz_import_locations_apply({"layer_id": "dele", "dry_run": True}))
    assert "10.9.0.1" not in json.dumps(r)  # previa nao mostra camera de Santana
    asyncio.run(tools.api_kmz_import_locations_apply({"layer_id": "dele", "dry_run": False, "overwrite": True}))
    santana = next(x for x in salvo["rows"] if x["ip"] == "10.9.0.1")
    assert santana == linhas[1]  # intacta
    assert len(salvo["rows"]) == 2  # nada some ao salvar
