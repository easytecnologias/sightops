"""Mapa: caixa de CFTV (o que tem dentro, portas) e cabo caixa -> camera
gravados no meta da camada KMZ. Dados ficticios."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.api.endpoints import tools
from app.core import tenant_context as T


@pytest.fixture()
def camada(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    (tmp_path / "c1.kmz").write_bytes(b"kmz")
    (tmp_path / "c1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    (tmp_path / "c1.meta.json").write_text(json.dumps({"id": "c1", "label": "PORTO REAL", "cor_outros": "#123456"}), encoding="utf-8")
    return tmp_path


def _como(role):
    return T.set_current_user({"id": 9, "username": "u", "role": role, "tenant_slug": "x", "effective_tenant_slug": "x"})


def _caixa(**kw):
    base = {"ponto": "CAI", "nome": "CAI-01", "portas": 8,
            "itens": [{"tipo": "switch_poe", "modelo": "SG 800", "qtd": 1}, {"tipo": "onu", "modelo": "", "qtd": 1}]}
    base.update(kw)
    r = tools._caixa_da_camada("c1", base, "op")
    return next(iter(r["caixas"].values())) if "id" not in kw else r["caixas"][kw["id"]]


# dois pontos ~100 m um do outro (0,0009 grau de latitude)
_CAMINHO = [[-10.0, -36.0], [-10.0009, -36.0]]


def test_caixa_e_cabo(camada):
    cx = _caixa()
    assert cx["nome"] == "CAI-01" and cx["portas"] == 8 and [i["tipo"] for i in cx["itens"]] == ["switch_poe", "onu"]
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.246"}, "tipo": "utp5e",
                                     "porta": 1, "folga_pct": 10, "caminho": _CAMINHO}, "op")
    cabo = next(iter(r["cabos"].values()))
    assert 99 <= cabo["metros"] <= 101 and cabo["metros_com_folga"] == round(cabo["metros"] * 1.1, 1)
    meta = json.loads((camada / "c1.meta.json").read_text(encoding="utf-8"))
    assert meta["cor_outros"] == "#123456" and cx["id"] in meta["caixas"]  # nao perde o resto do meta
    # a mesma camera nao ganha segundo cabo
    with pytest.raises(HTTPException) as e:
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.246"}, "porta": 3, "caminho": _CAMINHO})
    assert "ja tem cabo" in e.value.detail and "porta 1" in e.value.detail
    # porta ocupada
    with pytest.raises(HTTPException) as e:
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "15"}, "porta": 1, "caminho": _CAMINHO})
    assert "ja tem cabo" in e.value.detail
    # porta alem do switch
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "15"}, "porta": 9, "caminho": _CAMINHO})
    # switch nao encolhe abaixo da porta usada
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "16"}, "porta": 6, "caminho": _CAMINHO})
    with pytest.raises(HTTPException):
        _caixa(id=cx["id"], portas=4)


def test_validacoes(camada):
    with pytest.raises(HTTPException):
        tools._caixa_da_camada("c1", {"ponto": ""})
    with pytest.raises(HTTPException):
        tools._caixa_da_camada("c1", {"ponto": "CAI", "itens": [{"tipo": "geladeira"}]})
    cx = _caixa()
    with pytest.raises(HTTPException):
        tools._caixa_da_camada("c1", {"ponto": "cai"})  # mesmo ponto, outra caixa
    for ruim in ({"caminho": [[-10, -36]]}, {"caminho": [["x", 1], [1, 2]]}, {"caminho": _CAMINHO, "tipo": "laser"},
                 {"caminho": _CAMINHO, "camera": {}}):
        dados = {"caixa": cx["id"], "camera": {"ponto": "14"}, **ruim}
        with pytest.raises(HTTPException):
            tools._cabo_da_camada("c1", dados)
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": "outra", "camera": {"ponto": "14"}, "caminho": _CAMINHO})


def test_excluir_so_admin_e_caixa_leva_os_cabos(camada):
    cx = _caixa()
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14"}, "porta": 2, "caminho": _CAMINHO})
    kid = next(iter(r["cabos"]))
    tok = _como("operator")
    try:
        with pytest.raises(HTTPException) as e:
            tools._cabo_da_camada("c1", {"id": kid, "excluir": True})
        assert e.value.status_code == 403
        with pytest.raises(HTTPException):
            tools._caixa_da_camada("c1", {"id": cx["id"], "excluir": True})
    finally:
        T.reset_current_user(tok)
    tok = _como("admin")
    try:
        r = tools._caixa_da_camada("c1", {"id": cx["id"], "excluir": True})
    finally:
        T.reset_current_user(tok)
    assert r["caixas"] == {} and r["cabos"] == {}


def test_trocar_camera_do_cabo_e_excluir(camada):
    cx = _caixa()
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.14"}, "porta": 1, "caminho": _CAMINHO})
    kid = next(iter(r["cabos"]))
    # mudar so o tracado/porta do mesmo cabo: edicao normal
    tools._cabo_da_camada("c1", {"id": kid, "caixa": cx["id"], "camera": {"ponto": "14", "ip": "10.45.0.14"}, "porta": 2, "caminho": _CAMINHO})
    tok = _como("operator")
    try:
        with pytest.raises(HTTPException) as e:  # trocar a camera = excluir + criar
            tools._cabo_da_camada("c1", {"id": kid, "caixa": cx["id"], "camera": {"ponto": "17", "ip": "10.45.0.17"}, "caminho": _CAMINHO})
        assert e.value.status_code == 403
    finally:
        T.reset_current_user(tok)


def test_id_da_camada_saneado_no_meta(camada):
    tools._caixa_da_camada('c1.<img src=x onerror=alert(1)>', {"ponto": "CAI"})
    assert json.loads((camada / "c1.meta.json").read_text(encoding="utf-8"))["id"] == "c1"


@pytest.fixture()
def inventario(monkeypatch):
    linhas = {"switch": [{"ip": "10.45.0.104", "titulo": "4 - SAIDA CIDADE"}, {"ip": "10.45.0.105", "titulo": "5"}],
              "olt": [{"ip": "10.45.0.104", "titulo": "4 - SAIDA CIDADE"}], "basico": []}
    monkeypatch.setattr(tools, "load_inventory_json", lambda mode="olt": [dict(r) for r in linhas[mode]])
    monkeypatch.setattr(tools, "save_inventory_json", lambda rows, mode="olt": linhas.__setitem__(mode, [dict(r) for r in rows]))
    return linhas


def test_cabo_vai_para_o_inventario(camada, inventario):
    cx = _caixa(switch_nome="SW-CFTV-01", switch_modelo="Hikvision PoE", switch_ip="10.45.0.2", uplinks=1, uplink_para="onu", portas=5)
    assert cx["switch_nome"] == "SW-CFTV-01" and cx["uplinks"] == 1 and cx["uplink_para"] == "onu"
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 1, "caminho": _CAMINHO})
    kid = next(iter(r["cabos"]))
    for modo in ("switch", "olt"):
        linha = next(x for x in inventario[modo] if x["ip"] == "10.45.0.104")
        assert (linha["switch_name"], linha["switch_port"], linha["switch_ip"]) == ("SW-CFTV-01", "1", "10.45.0.2")
    assert "switch_name" not in inventario["switch"][1]  # outra camera intacta
    # renomear o switch atualiza as cameras dele
    _caixa(id=cx["id"], switch_nome="SW-PORTO-01", switch_ip="10.45.0.2", portas=5)
    assert inventario["switch"][0]["switch_name"] == "SW-PORTO-01"
    # excluir o cabo limpa (admin)
    tok = _como("admin")
    try:
        tools._cabo_da_camada("c1", {"id": kid, "excluir": True})
    finally:
        T.reset_current_user(tok)
    assert "switch_name" not in inventario["switch"][0] and "switch_port" not in inventario["olt"][0]


def test_validacao_do_switch(camada):
    with pytest.raises(HTTPException):
        _caixa(switch_ip="300.1.1.1")
    with pytest.raises(HTTPException):
        _caixa(uplink_para="satelite")


def test_salvar_caixa_preenche_cabos_antigos(camada, inventario):
    cx = _caixa(portas=5)  # caixa antiga, sem switch
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 3, "caminho": _CAMINHO})
    _caixa(id=cx["id"], portas=5, switch_nome="SW-CFTV-01")
    assert (inventario["switch"][0]["switch_name"], inventario["switch"][0]["switch_port"]) == ("SW-CFTV-01", "3")


def test_inventario_so_nos_sites_do_usuario(camada, inventario, monkeypatch):
    from app.core import permissions as P

    inventario["switch"][0]["site"] = "PORTO REAL"
    inventario["switch"][1]["site"] = "SANTANA"
    monkeypatch.setattr(P, "sites_da_sessao", lambda: ["PORTO REAL"])
    cx = _caixa(portas=5, switch_nome="SW-1")
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "5", "ip": "10.45.0.105"}, "porta": 2, "caminho": _CAMINHO})
    assert "switch_name" not in inventario["switch"][1]  # SANTANA: fora dos sites do usuario


def test_vlan_e_onu_na_cto(camada, inventario):
    cx = _caixa(portas=5, switch_nome="SW-1", switch_vlan="120")
    assert cx["switch_vlan"] == "120"
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 1, "caminho": _CAMINHO})
    assert inventario["switch"][0]["switch_vlan"] == "120"
    # VLAN da porta vale sobre a da caixa; invalida e recusada
    kid = next(iter(tools._read_kmz_layer_meta(tools._kmz_layer_paths("c1")[2])["cabos"]))
    tools._cabo_da_camada("c1", {"id": kid, "caixa": cx["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 1, "caminho": _CAMINHO, "vlan": "200"})
    assert inventario["switch"][0]["switch_vlan"] == "200"
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"id": kid, "caixa": cx["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 1, "caminho": _CAMINHO, "vlan": "abc"})
    with pytest.raises(HTTPException):
        _caixa(id=cx["id"], portas=5, switch_vlan="5000")
    # ONU da caixa na CTO: fibra drop, porta da CTO, um por caixa, nao ocupa porta do switch
    r = tools._cabo_da_camada("c1", {"caixa": cx["id"], "cto": {"ponto": "CTO-07", "porta": 3}, "tipo": "drop", "caminho": _CAMINHO})
    cto = next(c for c in r["cabos"].values() if c.get("cto"))
    assert cto["cto"] == {"ponto": "CTO-07", "porta": 3} and cto["tipo"] == "drop" and cto["porta"] is None
    with pytest.raises(HTTPException) as e:
        tools._cabo_da_camada("c1", {"caixa": cx["id"], "cto": {"ponto": "CTO-08"}, "caminho": _CAMINHO})
    assert "ja esta ligada na CTO" in e.value.detail
    # cabo de camera continua aceitando outra camera na porta 2 (a CTO nao ocupa porta)
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "5", "ip": "10.45.0.105"}, "porta": 2, "caminho": _CAMINHO})


def test_mesmo_nome_em_lugares_diferentes_sao_caixas_diferentes(camada):
    # Porto Real: "Caixa - S 8P" em 4 lugares; renomear uma nao pode mudar as outras
    a = tools._caixa_da_camada("c1", {"ponto": "Caixa - S 8P", "nome": "C.CFTV-02", "lat": -10.1, "lng": -36.1}, "op")
    b = tools._caixa_da_camada("c1", {"ponto": "Caixa - S 8P", "nome": "C.CFTV-03", "lat": -10.2, "lng": -36.2}, "op")
    assert sorted(c["nome"] for c in b["caixas"].values()) == ["C.CFTV-02", "C.CFTV-03"]
    # o mesmo ponto (mesmo lugar) continua nao virando duas caixas
    with pytest.raises(HTTPException) as e:
        tools._caixa_da_camada("c1", {"ponto": "Caixa - S 8P", "nome": "X", "lat": -10.1, "lng": -36.1}, "op")
    assert "ja e uma caixa" in e.value.detail
    # salvar sem posicao mantem a gravada
    cid = next(k for k, c in a["caixas"].items() if c["nome"] == "C.CFTV-02")
    r = tools._caixa_da_camada("c1", {"id": cid, "ponto": "Caixa - S 8P", "nome": "C.CFTV-02b"}, "op")
    assert (r["caixas"][cid]["lat"], r["caixas"][cid]["lng"]) == (-10.1, -36.1)


def _kmz_com_linhas(path):
    import zipfile
    def pm(nome, lon, lat):
        return (f"<Placemark><name>{nome}</name><LineString><coordinates>{lon},{lat},0 {lon + 0.001},{lat},0"
                "</coordinates></LineString></Placemark>")
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder>'
           + pm("69m", -36.1, -10.1) + pm("69m", -36.2, -10.2) + pm("107m", -36.3, -10.3)
           + "<Placemark><name>CAI</name><Point><coordinates>-36.1,-10.1,0</coordinates></Point></Placemark>"
           + "</Folder></Document></kml>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("doc.kml", kml)


def test_excluir_linha_so_a_pedida_e_so_admin(camada):
    from app.services.kmz_ops import kmz_to_geojson
    _kmz_com_linhas(camada / "c1.kmz")
    _como("operator")
    with pytest.raises(HTTPException) as e:
        tools._remover_linhas_da_camada("c1", {"remover": [{"nome": "69m", "lat": -10.2, "lon": -36.2}]})
    assert e.value.status_code == 403
    _como("admin")
    r = tools._remover_linhas_da_camada("c1", {"remover": [{"nome": "69m", "lat": -10.2, "lon": -36.2}]})
    assert r["removidas"] == 1
    feats = kmz_to_geojson(camada / "c1.kmz")["features"]
    linhas = [(f["properties"]["name"], f["geometry"]["coordinates"][0][1]) for f in feats if f["geometry"]["type"] == "LineString"]
    assert linhas == [("69m", -10.1), ("107m", -10.3)]  # o outro "69m" ficou
    assert any(f["geometry"]["type"] == "Point" for f in feats)  # ponto nao e tocado
    geo = json.loads((camada / "c1.geojson").read_text(encoding="utf-8"))
    assert len([f for f in geo["features"] if f["geometry"]["type"] == "LineString"]) == 2


def _kmz_com_pontos(path, pontos):
    import zipfile
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           + "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
                     for n, lat, lon in pontos)
           + "</Document></kml>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("doc.kml", kml)


def test_mover_caixa_so_a_dela_e_cabos_acompanham(camada):
    from app.services.kmz_ops import kmz_to_geojson
    _kmz_com_pontos(camada / "c1.kmz", [("Caixa - S 8P", -10.0, -36.0), ("Caixa - S 8P", -10.5, -36.5)])
    r = tools._caixa_da_camada("c1", {"ponto": "Caixa - S 8P", "nome": "C.CFTV-02", "lat": -10.0, "lng": -36.0}, "op")
    cid = next(iter(r["caixas"]))
    tools._cabo_da_camada("c1", {"caixa": cid, "camera": {"ponto": "14"}, "porta": 1, "caminho": _CAMINHO})
    r = tools._caixa_da_camada("c1", {"id": cid, "de": {"lat": -10.0, "lng": -36.0}, "mover": {"lat": -10.0009, "lng": -36.0}}, "op")
    assert (r["caixas"][cid]["lat"], r["caixas"][cid]["lng"]) == (-10.0009, -36.0)
    cabo = next(iter(r["cabos"].values()))
    assert cabo["caminho"][0] == [-10.0009, -36.0] and cabo["metros"] < 1  # agora a caixa esta na ponta da camera
    pts = sorted((f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) for f in kmz_to_geojson(camada / "c1.kmz")["features"])
    assert pts == [(-10.5, -36.5), (-10.0009, -36.0)]  # a outra "Caixa - S 8P" nao andou
    # posicao antiga errada (mapa desatualizado): recusa, nao cria ponto novo
    with pytest.raises(HTTPException) as e:
        tools._caixa_da_camada("c1", {"id": cid, "de": {"lat": -10.0, "lng": -36.0}, "mover": {"lat": -10.1, "lng": -36.1}}, "op")
    assert "nessa posicao" in e.value.detail
    assert len(kmz_to_geojson(camada / "c1.kmz")["features"]) == 2


def test_arrastar_ponto_com_nome_repetido_move_so_um(tmp_path):
    from app.services.kmz_ops import editar_ponto_no_kmz, kmz_to_geojson
    k = tmp_path / "x.kmz"
    _kmz_com_pontos(k, [("Caixa - S 4P", -10.0, -36.0), ("Caixa - S 4P", -10.5, -36.5)])
    editar_ponto_no_kmz(k, nome="Caixa - S 4P", lat=-10.2, lon=-36.2, lat_atual=-10.5, lon_atual=-36.5)
    pts = sorted(f["geometry"]["coordinates"][1] for f in kmz_to_geojson(k)["features"])
    assert pts == [-10.2, -10.0]


def test_excluir_e_renomear_ponto_com_nome_repetido_so_o_do_lugar(tmp_path):
    from app.services.kmz_ops import editar_ponto_no_kmz, kmz_to_geojson
    k = tmp_path / "x.kmz"
    _kmz_com_pontos(k, [("Caixa - S 4P", -10.0, -36.0), ("Caixa - S 4P", -10.5, -36.5), ("Caixa - S 4P", -10.7, -36.7)])
    editar_ponto_no_kmz(k, nome="Caixa - S 4P", remover=True, lat_atual=-10.5, lon_atual=-36.5)
    editar_ponto_no_kmz(k, nome="Caixa - S 4P", novo_nome="C-CFTV-09", lat_atual=-10.7, lon_atual=-36.7)
    pts = sorted((f["properties"]["name"], f["geometry"]["coordinates"][1]) for f in kmz_to_geojson(k)["features"])
    assert pts == [("C-CFTV-09", -10.7), ("Caixa - S 4P", -10.0)]


def test_tipo_da_caixa_onu_e_passagem(camada, inventario):
    # caixa antiga (sem tipo) continua sendo de switch
    cx = _caixa(portas=5)
    assert cx["tipo"] == "switch"
    # direto na ONU: portas = LAN, padrao 4, maximo 8; sem uplink de switch
    onu = tools._caixa_da_camada("c1", {"ponto": "C14", "nome": "C.CFTV-14", "tipo": "onu", "lat": -10.1, "lng": -36.1}, "op")
    onu = next(c for c in onu["caixas"].values() if c["nome"] == "C.CFTV-14")
    assert onu["tipo"] == "onu" and onu["portas"] == 4 and onu["uplinks"] == 0
    with pytest.raises(HTTPException):
        _caixa(id=onu["id"], ponto="C14", lat=-10.1, lng=-36.1, tipo="onu", portas=12)
    r = tools._cabo_da_camada("c1", {"caixa": onu["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 2,
                                     "alimentacao": "fonte12", "caminho": _CAMINHO})
    kid = next(k for k, c in r["cabos"].items() if c["caixa"] == onu["id"])
    assert r["cabos"][kid]["alimentacao"] == "fonte12"
    linha = inventario["switch"][0]
    assert (linha["switch_name"], linha["switch_port"]) == ("ONU C.CFTV-14", "LAN2")
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": onu["id"], "camera": {"ponto": "5"}, "porta": 5, "caminho": _CAMINHO})
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": onu["id"], "camera": {"ponto": "5"}, "alimentacao": "bateria", "caminho": _CAMINHO})
    # salvar o traçado sem o campo nao apaga a alimentacao
    r = tools._cabo_da_camada("c1", {"id": kid, "caixa": onu["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "porta": 2, "caminho": _CAMINHO})
    assert r["cabos"][kid]["alimentacao"] == "fonte12"
    # a ONU com nome proprio renomeia no inventario
    _caixa(id=onu["id"], ponto="C14", nome="C.CFTV-14", lat=-10.1, lng=-36.1, switch_nome="ONU-FH-14")
    assert inventario["switch"][0]["switch_name"] == "ONU-FH-14"
    # virar passagem com camera na porta: recusa (tire o cabo da porta antes)
    with pytest.raises(HTTPException) as e:
        _caixa(id=onu["id"], ponto="C14", lat=-10.1, lng=-36.1, tipo="passagem")
    assert "porta 2" in e.value.detail
    # passagem: sem portas, camera ligada sem porta, nada no inventario
    ps = tools._caixa_da_camada("c1", {"ponto": "P1", "nome": "PASSAGEM-1", "tipo": "passagem", "portas": 8, "lat": -10.2, "lng": -36.2}, "op")
    ps = next(c for c in ps["caixas"].values() if c["nome"] == "PASSAGEM-1")
    assert ps["portas"] == 0
    with pytest.raises(HTTPException):
        tools._cabo_da_camada("c1", {"caixa": ps["id"], "camera": {"ponto": "5", "ip": "10.45.0.105"}, "porta": 1, "caminho": _CAMINHO})
    tools._cabo_da_camada("c1", {"caixa": ps["id"], "camera": {"ponto": "5", "ip": "10.45.0.105"}, "alimentacao": "fonte12", "caminho": _CAMINHO})
    assert "switch_name" not in inventario["switch"][1]
    with pytest.raises(HTTPException):
        _caixa(tipo="armario")


def test_trocar_tipo_limpa_o_inventario_antigo(camada, inventario):
    cx = _caixa(portas=5, switch_nome="")
    tools._cabo_da_camada("c1", {"caixa": cx["id"], "camera": {"ponto": "4", "ip": "10.45.0.104"}, "caminho": _CAMINHO})
    assert inventario["switch"][0]["switch_name"] == "CAI-01"
    # switch -> passagem (o cabo nao tinha porta): o inventario deixa de dizer switch
    _caixa(id=cx["id"], tipo="passagem")
    assert "switch_name" not in inventario["switch"][0]
    # passagem -> ONU: volta como ONU
    _caixa(id=cx["id"], tipo="onu", portas=4)
    assert inventario["switch"][0]["switch_name"] == "ONU CAI-01"
