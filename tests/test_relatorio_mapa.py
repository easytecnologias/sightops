"""Relatorio do Mapa: areas, pinos que se sobrepoem e mapa sem internet."""
import math

import pytest

from app.services import map_pdf_report as M


def _cam(titulo, lat, lon, status="online"):
    return {"titulo": titulo, "ip": titulo, "status": status, "_pos": (lat, lon)}


def test_nome_base_da_area():
    assert M._chave_area("13 - P. LDD - 01") == "P. LDD"
    assert M._chave_area("21 -ROTATORIA - 02") == "ROTATORIA"
    assert M._chave_area("01 - ENTRADA SIERRA") == "ENTRADA SIERRA"
    assert M._chave_area("") == "SEM NOME"


def test_grupo_pequeno_so_junta_com_vizinho_de_verdade():
    # PORTARIA (1 camera) a ~15 m da entrada: junta. MURO (2) a ~500 m: fica sozinho.
    cams = [
        _cam("02 - ENT VISITANTE - 01", -9.73130, -36.63810),
        _cam("03 - ENT VISITANTE - 02", -9.73133, -36.63812),
        _cam("04 - ENT VISITANTE - 03", -9.73126, -36.63806),
        _cam("07 - PORTARIA", -9.73140, -36.63815),
        _cam("88 - MURO QD. E - 01", -9.73600, -36.63700),
        _cam("89 - MURO QD. E - 02", -9.73610, -36.63705),
    ]
    areas = M.agrupar_areas(cams)
    nomes = {a["nome"]: len(a["cams"]) for a in areas}
    assert nomes == {"ENT VISITANTE / PORTARIA": 4, "MURO QD. E": 2}


def test_pinos_no_mesmo_lugar_sao_afastados_e_ficam_na_imagem():
    pontos = [(100.0, 100.0)] * 5 + [(5.0, 5.0)]
    out = M._afastar(pontos, 40, 400, 300, 20)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            assert math.hypot(out[i][0] - out[j][0], out[i][1] - out[j][1]) >= 39
    assert all(20 <= x <= 380 and 20 <= y <= 280 for x, y in out)


def test_mapa_sai_mesmo_sem_baixar_tile(monkeypatch):
    monkeypatch.setattr(M, "_tile", lambda *a, **k: None)
    img = M.renderizar_mapa([(-9.7313, -36.6381, "1", M.COR_ONLINE), (-9.7280, -36.6352, "2", M.COR_OFFLINE)],
                            600, 400)
    assert img is not None and img.size == (600, 400)
    assert M.renderizar_mapa([], 600, 400) is None


def test_job_do_mapa_so_responde_para_o_cliente_que_pediu(monkeypatch):
    from fastapi import HTTPException

    from app.api.endpoints import tools
    tools._report_jobs["abc"] = {"kind": "mapa", "tenant": "sierra", "status": "done"}
    try:
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "outro-cliente")
        with pytest.raises(HTTPException):
            tools._map_report_job_do_cliente("abc")
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "sierra")
        assert tools._map_report_job_do_cliente("abc")["tenant"] == "sierra"
    finally:
        tools._report_jobs.pop("abc", None)


def test_rotas_antigas_do_relatorio_nao_entregam_job_do_mapa_nem_de_outro_cliente(monkeypatch):
    from fastapi import HTTPException

    from app.api.endpoints import tools
    tools._report_jobs["mapa1"] = {"kind": "mapa", "tenant": "sierra", "status": "done"}
    tools._report_jobs["inv1"] = {"kind": "inventario", "tenant": "sierra", "status": "done"}
    try:
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "sierra")
        with pytest.raises(HTTPException):
            tools._inventory_report_job_do_cliente("mapa1")
        assert tools._inventory_report_job_do_cliente("inv1")["kind"] == "inventario"
        monkeypatch.setattr(tools, "get_current_tenant_slug", lambda: "outro-cliente")
        with pytest.raises(HTTPException):
            tools._inventory_report_job_do_cliente("inv1")
    finally:
        tools._report_jobs.pop("mapa1", None)
        tools._report_jobs.pop("inv1", None)


def test_motivo_do_ponto_e_gravado_por_nome_e_vazio_apaga(tmp_path, monkeypatch):
    import json

    from app.api.endpoints import tools
    monkeypatch.setattr(tools, "_kmz_layers_dir", lambda: tmp_path)
    (tmp_path / "c1.kmz").write_bytes(b"x")
    (tmp_path / "c1.geojson").write_text('{"type": "FeatureCollection", "features": []}')
    (tmp_path / "c1.meta.json").write_text("{}")
    tools._motivo_do_ponto("c1", {"nome": "39 - QD. E - 01", "motivo": "  camera   retirada "}, por="joao")
    meta = json.loads((tmp_path / "c1.meta.json").read_text())
    assert meta["motivos"]["39 - qd. e - 01"]["motivo"] == "camera retirada"
    assert meta["motivos"]["39 - qd. e - 01"]["por"] == "joao"
    tools._motivo_do_ponto("c1", {"nome": "39 - QD. E - 01", "motivo": ""})
    assert json.loads((tmp_path / "c1.meta.json").read_text())["motivos"] == {}
    with pytest.raises(Exception):
        tools._motivo_do_ponto("c1", {"nome": " ", "motivo": "x"})


def test_texto_do_motivo_no_relatorio():
    assert M._texto_motivo({}).startswith("sem motivo informado")
    assert M._texto_motivo({"motivo": "camera retirada", "por": "joao", "em": "2026-10-17T21:30:00"}) ==         "camera retirada (por joao em 17/10/2026)"
    assert M._texto_motivo({"motivo": "previsto"}) == "previsto"


def test_tipo_do_ponto_so_camera_e_pendencia():
    assert M._tipo_do_ponto("CTO-07") == "cto"
    assert M._tipo_do_ponto("PT-12") == "poste"
    assert M._tipo_do_ponto("Caixa hermetica 3") == "caixa"
    assert M._tipo_do_ponto("CAI") == "caixa"
    assert M._tipo_do_ponto("CDO centro") == "cdo"
    assert M._tipo_do_ponto("14 - RUA A") == "camera"


def _camada_infra():
    meta = {
        "caixas": {
            "cx1": {"id": "cx1", "ponto": "CAI", "nome": "C.CFTV-14", "tipo": "onu", "portas": 4, "lat": -10.0, "lng": -36.0,
                    "itens": [{"tipo": "fonte", "qtd": 1}], "switch_modelo": "AN5506-04"},
            "cx2": {"id": "cx2", "ponto": "CAI", "nome": "C.CFTV-02", "portas": 8, "lat": -10.01, "lng": -36.01,
                    "switch_nome": "SW-2", "switch_modelo": "HIK", "uplinks": 1, "uplink_para": "onu"},
        },
        "cabos": {
            "k1": {"id": "k1", "caixa": "cx1", "camera": {"ponto": "14 - RUA A", "ip": "10.0.0.14"}, "tipo": "utp5e", "porta": 2,
                   "metros": 98.0, "metros_com_folga": 107.8, "alimentacao": "fonte12",
                   "caminho": [[-10.0, -36.0], [-10.0008, -36.0]]},
            "k2": {"id": "k2", "caixa": "cx1", "cto": {"ponto": "CTO-07", "porta": 3}, "camera": {}, "tipo": "drop",
                   "metros": 40.0, "metros_com_folga": 44.0, "caminho": [[-10.0, -36.0], [-10.0003, -36.0004]]},
        },
    }
    feats = [
        {"type": "Feature", "properties": {"name": "CTO-07"}, "geometry": {"type": "Point", "coordinates": [-36.0004, -10.0003]}},
        {"type": "Feature", "properties": {"name": "CAI"}, "geometry": {"type": "Point", "coordinates": [-36.0, -10.0]}},
        {"type": "Feature", "properties": {"name": "PT-1"}, "geometry": {"type": "Point", "coordinates": [-36.002, -10.002]}},
        {"type": "Feature", "properties": {"name": "Fibra 1"},
         "geometry": {"type": "LineString", "coordinates": [[-36.0, -10.0], [-36.0, -10.0009]]}},
    ]
    return [{"id": "c1", "label": "PORTO", "meta": meta, "features": feats}]


def test_infra_liga_cabo_a_camera_cto_e_conta_o_resto():
    cam = {"titulo": "14 - RUA A", "ip": "10.0.0.14", "_status": "online"}
    infra = M._infra_do_mapa(_camada_infra(), [cam])
    cx14 = next(c for c in infra["caixas"] if c["nome"] == "C.CFTV-14")
    assert cx14["tipo"] == "onu" and cx14["cabos"][0]["_cam"] is cam and cx14["cto"]["id"] == "k2"
    assert [c["nome"] for c in infra["caixas"]] == ["C.CFTV-02", "C.CFTV-14"]  # pelo numero
    assert next(c for c in infra["caixas"] if c["nome"] == "C.CFTV-02")["tipo"] == "switch"  # antiga sem tipo
    assert infra["ctos"][0]["caixas"] == [cx14]
    assert infra["contagem"]["poste"] == 1 and round(infra["linhas"][0]["metros"]) == 100
    assert M._rotulo_porta(cx14, 2) == "LAN2" and "AN5506-04" in M._equipamento_da_caixa(cx14)
    # pontos: a caixa cadastrada e caixa (nao pendencia), CTO e CTO
    tipos = {p["nome"]: p["tipo"] for p in M._pontos_do_mapa(camadas=_camada_infra())}
    assert tipos == {"CTO-07": "cto", "CAI": "caixa", "PT-1": "poste"}


def test_mapa_com_cabos_caixa_e_cto(monkeypatch):
    monkeypatch.setattr(M, "_tile", lambda *a, **k: None)
    infra = M._infra_do_mapa(_camada_infra(), [{"titulo": "14 - RUA A", "ip": "10.0.0.14", "_status": "online"}])
    linhas = M._linhas_dos_cabos(infra["caixas"])
    assert len(linhas) == 2 and linhas[1][3] is True  # drop tracejado
    img = M.renderizar_mapa([(-10.0, -36.0, "14", M.COR_CAIXA, "quadrado"), (-10.0003, -36.0004, "", M.COR_CTO, "losango"),
                             (-10.0008, -36.0, "14", M.COR_ONLINE)], 600, 400, linhas=linhas)
    assert img is not None and img.size == (600, 400)


def test_relatorio_completo_com_caixas(tmp_path, monkeypatch):
    """O PDF inteiro sai com caixas, CTO e pendencias novas (sem internet)."""
    import app.core.tenant_context as TC

    monkeypatch.setattr(M, "_tile", lambda *a, **k: None)
    monkeypatch.setattr(M, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(M, "_camadas_do_relatorio", lambda site="": _camada_infra())
    monkeypatch.setattr(M, "_gravacao_por_camera", lambda: {})
    monkeypatch.setattr(M, "_cameras_do_cliente", lambda site="": [
        {"titulo": "14 - RUA A", "ip": "10.0.0.14", "status": "online"},
        {"titulo": "15 - RUA B", "ip": "10.0.0.15", "status": "offline", "lat": -10.002, "lon": -36.0}])
    monkeypatch.setattr(TC, "get_current_tenant_slug", lambda: None)  # _coordenadas_do_mapa vazio
    fitz = pytest.importorskip("fitz")  # PyMuPDF so para ler o PDF no teste
    pdf = M.build_map_pdf_report(include_photos=False)

    texto = "\n".join(p.get_text() for p in fitz.open(pdf))
    for trecho in ("Infraestrutura de CFTV", "Caixa C.CFTV-14 | Direto na ONU", "LAN2", "Fonte 12V",
                   "CTO-07", "Cabos acima do limite do UTP/PoE (1)", "Cameras no mapa sem cabo ate uma caixa (1)",
                   "Caixas sem camera ligada (1)", "Pontos do mapa sem camera cadastrada (0)"):
        assert trecho in texto, trecho


def test_caixa_tem_localizacao_clicavel():
    infra = M._infra_do_mapa(_camada_infra(), [])
    cx = next(c for c in infra["caixas"] if c["nome"] == "C.CFTV-14")
    assert M._loc_caixa(cx) == {"lat": -10.0, "lon": -36.0}
    assert M._loc_caixa({"pos": None}) == {}


def test_relatorio_com_cto_cadastrada(tmp_path, monkeypatch):
    """CTO cadastrada no Mapa: splitter, origem e porta a porta (caixa do cabo + ONU com sinal)."""
    import app.core.tenant_context as TC

    camadas = _camada_infra()
    camadas[0]["meta"]["ctos"] = {"ct1": {
        "id": "ct1", "ponto": "CTO-07", "nome": "CTO VERDE 07", "lat": -10.0003, "lng": -36.0004, "splitter": "1:8",
        "nivel": "secundario", "portas": 8, "olt_nome": "OLT CENTRAL", "pon": "0/3", "vem_de": "CDO-01",
        "portas_info": {"5": {"onu_key": "onu:x|0/3|5", "onu_nome": "ONU ESCOLA", "obs": ""},
                        "8": {"onu_key": "", "onu_nome": "", "obs": "reservada"}}}}
    infra = M._infra_do_mapa(camadas, [])
    assert infra["ctos"][0]["cad"]["id"] == "ct1"
    monkeypatch.setattr(M, "_onus_do_monitoramento", lambda: {
        "onu:x|0/3|5": {"status": "up", "det": {"onu_rx": "-19.52"}}})
    monkeypatch.setattr(M, "_tile", lambda *a, **k: None)
    monkeypatch.setattr(M, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(M, "_camadas_do_relatorio", lambda site="": camadas)
    monkeypatch.setattr(M, "_gravacao_por_camera", lambda: {})
    monkeypatch.setattr(M, "_cameras_do_cliente", lambda site="": [{"titulo": "14 - RUA A", "ip": "10.0.0.14", "status": "online"}])
    monkeypatch.setattr(TC, "get_current_tenant_slug", lambda: None)
    fitz = pytest.importorskip("fitz")
    texto = "\n".join(p.get_text() for p in fitz.open(M.build_map_pdf_report(include_photos=False)))
    for trecho in ("CTO VERDE 07", "1:8 secundario", "OLT CENTRAL - PON 0/3 - de CDO-01", "2/8",
                   "CTO VERDE 07 - portas", "C.CFTV-14", "ONU ESCOLA", "-19.52 dBm", "no ar", "reservada",
                   "Livres: 1, 2, 4, 6, 7, 8"):
        assert trecho in texto, trecho


def test_cto_sem_cadastro_continua_no_relatorio():
    infra = M._infra_do_mapa(_camada_infra(), [])
    assert infra["ctos"][0]["cad"] is None and infra["ctos"][0]["nome"] == "CTO-07"


def test_onus_do_pdf_respeitam_sites_do_usuario(monkeypatch):
    from app.core import permissions
    from app.services import monitoring_service
    monkeypatch.setattr(monitoring_service, "list_entities", lambda **k: [
        {"entity_key": "onu:a", "site": "PORTO", "status": "up", "detail_json": '{"onu_rx": "-19"}'},
        {"entity_key": "onu:b", "site": "BARRA", "status": "up", "detail_json": "{}"}])
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: ["PORTO"])
    assert set(M._onus_do_monitoramento()) == {"onu:a"}
    assert M._onus_do_monitoramento()["onu:a"]["det"]["onu_rx"] == "-19"
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: None)
    assert set(M._onus_do_monitoramento()) == {"onu:a", "onu:b"}
