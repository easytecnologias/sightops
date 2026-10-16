"""Rotas de cabo do projeto: metragem pelo tracado, validacao e isolamento."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import db_store
from app.services import planning_service as ps


@pytest.fixture(autouse=True)
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "sightops.db")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("cliente-a")
    db_store.init_db()
    yield
    tenant_context.reset_current_tenant_slug(token)


def _projeto():
    p = ps.save_project({"name": "JARDINS", "status": "planned"})
    olt = ps.save_device(p["id"], {"device_type": "olt", "name": "OLT", "latitude": -9.6650, "longitude": -35.7400})
    poste = ps.save_device(p["id"], {"device_type": "pole", "name": "P-01", "latitude": -9.6650, "longitude": -35.7380})
    cto = ps.save_device(p["id"], {"device_type": "cto", "name": "CTO-01", "parent_id": olt["id"], "latitude": -9.6640, "longitude": -35.7380})
    return p, olt, poste, cto


def _ponto(device=None, lat=None, lon=None):
    if device:
        return {"lat": device["latitude"], "lon": device["longitude"], "device_id": device["id"]}
    return {"lat": lat, "lon": lon}


def test_rota_mede_o_tracado_de_poste_em_poste():
    p, olt, poste, cto = _projeto()
    rota = ps.save_route(p["id"], {
        "kind": "fiber_main", "from_device_id": olt["id"], "to_device_id": cto["id"],
        "path": [_ponto(olt), _ponto(poste), _ponto(cto)], "fiber_count": 12, "slack_m": 20,
    })
    # OLT -> poste ~219 m (0,002 grau de longitude), poste -> CTO ~111 m (0,001 grau de latitude)
    assert rota["segments_m"][0] == pytest.approx(219.3, abs=1.5)
    assert rota["segments_m"][1] == pytest.approx(111.2, abs=1.0)
    assert rota["length_m"] == pytest.approx(sum(rota["segments_m"]), abs=0.2)
    assert [pt["device_id"] for pt in rota["path"]] == [olt["id"], poste["id"], cto["id"]]
    projeto = ps.get_project(p["id"])
    assert [r["id"] for r in projeto["routes"]] == [rota["id"]]


def test_rota_acompanha_o_poste_quando_ele_e_movido():
    p, olt, poste, cto = _projeto()
    rota = ps.save_route(p["id"], {"kind": "fiber_main", "path": [_ponto(olt), _ponto(poste), _ponto(cto)]})
    antes = rota["length_m"]
    ps.move_device(p["id"], poste["id"], -9.6660, -35.7380)
    depois = ps.get_project(p["id"])["routes"][0]
    assert depois["path"][1]["lat"] == pytest.approx(-9.6660)
    assert depois["length_m"] > antes


def test_mover_equipamento_so_muda_a_posicao():
    p, olt, poste, cto = _projeto()
    ps.save_device(p["id"], {"device_type": "cto", "name": "CTO-01", "parent_id": olt["id"], "model": "CTO 1x8",
                             "metadata": {"port_capacity": 8}, "latitude": -9.6640, "longitude": -35.7380}, cto["id"])
    ps.move_device(p["id"], cto["id"], -9.6641, -35.7381)
    salvo = next(d for d in ps.get_project(p["id"])["devices"] if d["id"] == cto["id"])
    assert (salvo["model"], salvo["metadata"], salvo["parent_id"]) == ("CTO 1x8", {"port_capacity": 8}, olt["id"])
    assert (salvo["latitude"], salvo["longitude"]) == (-9.6641, -35.7381)


def test_apagar_poste_nao_quebra_a_rota():
    p, olt, poste, cto = _projeto()
    ps.save_route(p["id"], {"kind": "fiber_main", "path": [_ponto(olt), _ponto(poste), _ponto(cto)]})
    ps.delete_device(p["id"], poste["id"])
    rota = ps.get_project(p["id"])["routes"][0]
    assert len(rota["path"]) == 3
    assert rota["path"][1]["device_id"] is None


@pytest.mark.parametrize("payload, erro", [
    ({"kind": "cabo", "path": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}]}, "Tipo de rota"),
    ({"kind": "utp", "path": [{"lat": 0, "lon": 0}]}, "dois pontos"),
    ({"kind": "utp", "path": [{"lat": 95, "lon": 0}, {"lat": 0, "lon": 1}]}, "Coordenada"),
    ({"kind": "utp", "path": [{"lat": "", "lon": 0}, {"lat": 0, "lon": 1}]}, "Coordenada"),
    ({"kind": "fiber_main", "fiber_count": 500, "path": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}]}, "fibras"),
])
def test_rota_invalida_e_recusada(payload, erro):
    p, *_ = _projeto()
    with pytest.raises(ValueError, match=erro):
        ps.save_route(p["id"], payload)


def test_rota_nao_aceita_equipamento_de_outro_projeto():
    p, olt, *_ = _projeto()
    outro = ps.save_project({"name": "OUTRO"})
    estranho = ps.save_device(outro["id"], {"device_type": "pole", "name": "P-99", "latitude": -9.0, "longitude": -35.0})
    with pytest.raises(ValueError, match="outro projeto"):
        ps.save_route(p["id"], {"kind": "fiber_main", "path": [_ponto(olt), _ponto(estranho)]})
    with pytest.raises(ValueError, match="nao pertence"):
        ps.save_route(p["id"], {"kind": "fiber_main", "to_device_id": estranho["id"], "path": [_ponto(olt), _ponto(lat=-9.0, lon=-35.0)]})


def test_cliente_nao_ve_nem_apaga_rota_do_outro():
    p, olt, poste, cto = _projeto()
    rota = ps.save_route(p["id"], {"kind": "fiber_main", "path": [_ponto(olt), _ponto(cto)]})
    tenant_context.set_current_tenant_slug("cliente-b")
    assert ps.get_project(p["id"]) is None
    assert ps.delete_route(p["id"], rota["id"]) is False
    with pytest.raises(LookupError):
        ps.save_route(p["id"], {"kind": "utp", "path": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}]})
    with pytest.raises(LookupError):
        ps.move_device(p["id"], poste["id"], 0, 0)
    tenant_context.set_current_tenant_slug("cliente-a")
    assert len(ps.get_project(p["id"])["routes"]) == 1


def test_apagar_projeto_leva_as_rotas_junto():
    p, olt, poste, cto = _projeto()
    ps.save_route(p["id"], {"kind": "fiber_main", "path": [_ponto(olt), _ponto(cto)]})
    assert ps.delete_project(p["id"])
    with db_store._conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM planning_routes").fetchone()["n"] == 0


def test_kmz_leva_o_tracado_e_os_postes():
    import io
    import zipfile

    p, olt, poste, cto = _projeto()
    cam = ps.save_device(p["id"], {"device_type": "camera", "name": "CAM 01", "latitude": -9.6641, "longitude": -35.7379})
    ps.save_route(p["id"], {"kind": "fiber_main", "from_device_id": olt["id"], "to_device_id": cto["id"],
                            "path": [_ponto(olt), _ponto(poste), _ponto(cto)]})
    ps.save_route(p["id"], {"kind": "utp", "from_device_id": cto["id"], "to_device_id": cam["id"],
                            "path": [_ponto(cto), _ponto(cam)], "cable_model": "Cabo UTP CAT5e externo"})
    _nome, data = ps.export_project_kmz(p["id"])
    with zipfile.ZipFile(io.BytesIO(data)) as kmz:
        kml = kmz.read("doc.kml").decode("utf-8")
    # A fibra OLT -> CTO segue pelo poste (3 pontos), nao em linha reta.
    assert "OLT -&gt; CTO-01 (330 m tracados)" in kml or "OLT -> CTO-01 (330 m tracados)" in kml
    assert "-35.7380000,-9.6650000,0" in kml
    assert "#route-utp" in kml and "Cabo UTP CAT5e externo" in kml
    assert "<name>P-01</name>" in kml
