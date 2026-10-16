"""Importar rede FTTx desenhada no Google Earth (pastas por cor, CDO/CTO, postes)."""
from __future__ import annotations

import io
import zipfile

import pytest

from app.core import tenant_context
from app.services import db_store
from app.services import planning_kmz_network as kn
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


def _pm(name, lat, lon, desc="", style=""):
    return (f"<Placemark><name>{name}</name><styleUrl>#{style}</styleUrl><description><![CDATA[{desc}]]></description>"
            f"<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>")


def _line(name, pts, desc=""):
    coords = " ".join(f"{lon},{lat},0" for lat, lon in pts)
    return (f"<Placemark><name>{name}</name><description>{desc}</description>"
            f"<LineString><coordinates>{coords}</coordinates></LineString></Placemark>")


def _kmz():
    olt, pt1, cdo, pt2, cto = (-9.7600, -36.6900), (-9.7600, -36.6890), (-9.7600, -36.6880), (-9.7610, -36.6880), (-9.7620, -36.6880)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>BAIRRO</name>
<Folder><name>JARDINS</name>
  {_pm('OLT JARDINS', *olt)}
  <Folder><name>POSTES</name>{_pm('PT-1', *pt1)}{_pm('PT-2', *pt2)}</Folder>
  <Folder><name>FIBRA PRINCIPAL</name>{_line('FIBRA PRINCIPAL 01', [olt, pt1, cdo])}</Folder>
  <Folder><name>FIBRA VERDE</name>
    <Folder><name>CDO VERDE</name>{_pm('CDO VERDE 1X16', *cdo, style='msn_cx emenda_01')}</Folder>
    <Folder><name>CTO VERDE</name>{_pm('CTO-01', *cto, desc='FIBRA AZUL<br>1 19.14<br>2 19.46', style='msn_cto4')}</Folder>
    <Folder><name>FIBRA</name>{_line('FIBRA VERDE 01', [cdo, pt2, cto], 'FIBRA VERDE ATIVA DE LINK FIBRA AZUL ATIVA CTO - 01 FIBRA BRANCA INATIVA')}</Folder>
  </Folder>
  <Folder><name>RUAS</name>{_pm('QUADRA A', -9.7605, -36.6885)}</Folder>
  <Folder><name>CAMERAS JARDINS</name>
    {_pm('01 - PORTARIA', -9.7621, -36.6881, '01 - PORTARIA 📷 CAMERA: VIP-3220-B | 🧬 MAC: 18:0d:2c:e6:d6:10 | 🌐 IP: 10.10.10.20 | 🟢 STATUS: ONLINE | 🔑 ONU SERIAL: 2CB4B3F0 | 🛰️ PON/ONU: PON 3 / ONU 2', 'cam-online')}
    {_pm('02 - GUARITA', -9.7622, -36.6882, '02 - GUARITA 📷 CAMERA: VIP-1230-B | 🌐 IP: 10.10.10.21 | 🔴 STATUS: OFFLINE | 🔑 ONU SERIAL: 2CB4B3F0 | 🛰️ PON/ONU: PON 3 / ONU 2', 'cam-offline')}
  </Folder>
</Folder></Document></kml>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", kml)
    return buf.getvalue()


def test_importa_rede_com_cores_postes_e_cameras():
    report = kn.import_network(_kmz(), "BAIRRO")
    assert report["contagem"] == {"olt": 1, "pole": 2, "cdo": 1, "cto": 1, "camera": 2}
    assert report["rotas"] == 2 and report["caixas_por_onu"] == 1
    assert "Rotulo QUADRA A" in report["ignorados"]
    projeto = ps.get_project(report["projeto_id"])
    by_name = {d["name"]: d for d in projeto["devices"]}

    cdo, cto = by_name["CDO VERDE 1X16"], by_name["CTO-01"]
    assert (cdo["device_type"], cdo["metadata"]["papel"], cdo["metadata"]["splitter"]) == ("cto", "splitter_primario", "1x16")
    assert cdo["metadata"]["cor_fibra"] == ["verde"]
    assert cdo["parent_id"] == by_name["OLT JARDINS"]["id"]       # seguindo o cabo
    assert cto["metadata"]["cor_fibra"] == ["azul"]                # "FIBRA AZUL" na descricao
    assert cto["metadata"]["port_power_dbm"] == {"1": -19.14, "2": -19.46}
    assert cto["parent_id"] == cdo["id"] and cto["metadata"]["ligacao"] == "cabo"

    cam = by_name["01 - PORTARIA"]
    assert (cam["ip"], cam["model"], cam["pon"], cam["onu_position"]) == ("10.10.10.20", "VIP-3220-B", "3", "2")
    assert cam["metadata"]["mac"] == "18:0d:2c:e6:d6:10"
    onu = next(d for d in projeto["devices"] if d["id"] == cam["parent_id"])
    assert onu["device_type"] == "onu" and onu["metadata"]["serial"] == "2CB4B3F0"
    box = next(d for d in projeto["devices"] if d["id"] == onu["parent_id"])
    assert box["device_type"] == "box" and box["parent_id"] == cto["id"]

    ramal = next(r for r in projeto["routes"] if r["name"] == "FIBRA VERDE 01")
    assert [pt["device_id"] for pt in ramal["path"]] == [cdo["id"], by_name["PT-2"]["id"], cto["id"]]
    assert ramal["metadata"]["kmz_ocupacao"] == {"verde": "link", "azul": "CTO-01", "branco": "inativa"}
    assert ramal["metadata"]["ramal"] == "verde"


def test_kml_com_entity_e_recusado():
    evil = b'<?xml version="1.0"?><!DOCTYPE k [<!ENTITY a "aaaa">]><kml><Document>&a;</Document></kml>'
    with pytest.raises(ValueError, match="DOCTYPE"):
        kn.import_network(evil, "X")


def test_arquivo_sem_rede_e_recusado():
    vazio = b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>x</name></Document></kml>'
    with pytest.raises(ValueError, match="Nao encontrei"):
        kn.import_network(vazio, "X")


def test_projeto_importado_e_so_do_cliente():
    report = kn.import_network(_kmz(), "BAIRRO")
    tenant_context.set_current_tenant_slug("cliente-b")
    assert ps.get_project(report["projeto_id"]) is None
    assert ps.list_projects() == []
