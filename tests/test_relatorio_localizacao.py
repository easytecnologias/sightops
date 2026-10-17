"""Localizacao (lat/lon) das cameras nos relatorios de Cameras IP e de Gravadores."""
from app.services import recorder_pdf_report as R
from app.services.camera_pdf_report import _colunas


def test_coordenada_valida_vira_link_do_maps():
    estilo = R._styles()["mono"]
    p = R._p_localizacao({"lat": "-9.73125164", "lon": "-36.63809935"}, estilo)
    # o ReportLab guarda o link de cada trecho como lista de (tipo, alvo, ...)
    alvos = {str(item) for f in p.frags for item in (getattr(f, "link", None) or [])}
    assert alvos and all("https://www.google.com/maps?q=-9.731252,-36.638099" in a for a in alvos)
    assert "-9.731252" in p.getPlainText() and "-36.638099" in p.getPlainText()


def test_coordenada_vazia_ou_zero_nao_conta():
    assert R._coordenadas({}) is None
    assert R._coordenadas({"lat": "", "lon": ""}) is None
    assert R._coordenadas({"lat": 0, "lon": 0}) is None          # sobra de formulario vazio
    assert R._coordenadas({"lat": "95", "lon": "10"}) is None    # fora da faixa
    assert R._coordenadas({"latitude": "-9,5", "longitude": "-36,6"}) == (-9.5, -36.6)


def test_coluna_so_aparece_quando_alguma_camera_tem_coordenada():
    sem = [{"ip": "10.0.0.1", "titulo": "A", "status": "online"}]
    com = sem + [{"ip": "10.0.0.2", "titulo": "B", "status": "online", "lat": -9.7, "lon": -36.6}]
    assert "Localizacao" not in _colunas(False, True, sem)
    assert "Localizacao" in _colunas(False, True, com)


def _camada(tmp_path, monkeypatch, pontos):
    """Camada do Mapa do cliente: [(nome, descricao, lat, lon)]."""
    import json

    from app.core import tenant_context
    pasta = tmp_path / "input" / "kmz_layers"
    pasta.mkdir(parents=True)
    feats = [{"type": "Feature", "properties": {"name": n, "description": d},
              "geometry": {"type": "Point", "coordinates": [lon, lat]}} for n, d, lat, lon in pontos]
    (pasta / "c1.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    (pasta / "c1.meta.json").write_text("{}")
    (pasta / "c1.kmz").write_bytes(b"x")
    monkeypatch.setattr(tenant_context, "get_current_tenant_slug", lambda: "cliente")
    monkeypatch.setattr(tenant_context, "tenant_kmz_input_dir", lambda slug="": tmp_path / "input" / "kmz")


def test_posicao_vem_do_mapa_pelo_nome_e_ignora_ip_velho_da_descricao(tmp_path, monkeypatch):
    # Na SIERRA o ponto "64 - ACADEMIA - 02" ainda dizia o IP da .61 (troca de IP do dia).
    _camada(tmp_path, monkeypatch, [
        ("64 - ACADEMIA - 02", "IP 10.200.1.61", -9.72873684, -36.63586377),
        ("61 - QD. O e P - 01", "IP 10.200.1.58", -9.72585579, -36.63660607),
        ("REPETIDO", "", -9.1, -36.1), ("REPETIDO", "", -9.2, -36.2),
    ])
    linhas = [
        {"ip": "10.200.1.61", "titulo": "61 - QD. O e P - 01"},
        {"ip": "10.200.1.64", "titulo": "64 - ACADEMIA - 02", "lat": -1.0, "lon": -1.0},  # mapa vence
        {"ip": "10.200.1.70", "titulo": "repetido", "lat": -9.5, "lon": -36.5},           # ambiguo: fica o do inventario
        {"ip": "10.200.1.71", "titulo": "fora do mapa"},
    ]
    R._aplicar_posicoes(linhas)
    assert R._coordenadas(linhas[0]) == (-9.7258558, -36.6366061)
    assert R._coordenadas(linhas[1]) == (-9.7287368, -36.6358638)
    assert R._coordenadas(linhas[2]) == (-9.5, -36.5)
    assert R._coordenadas(linhas[3]) is None


def test_sem_cliente_nao_le_mapa_nenhum(monkeypatch):
    from app.core import tenant_context
    monkeypatch.setattr(tenant_context, "get_current_tenant_slug", lambda: "")
    assert R._coordenadas_do_mapa() == {}


def test_canal_do_gravador_herda_a_coordenada_da_camera_do_mesmo_conector(monkeypatch):
    camera_a = {"ip": "10.200.1.5", "remote_connector_id": "conA", "lat": -9.7, "lon": -36.6}
    camera_b = {"ip": "10.200.1.5", "remote_connector_id": "conB", "lat": -8.0, "lon": -35.0}
    import app.services.inventory_json as inv
    monkeypatch.setattr(inv, "load_inventory_json", lambda mode="olt", site="": [camera_a, camera_b] if mode == "olt" else [])
    canais = [
        {"camera_ip": "10.200.1.5", "remote_connector_id": "conB"},
        {"camera_ip": "10.200.1.5"},          # sem conector e IP ambiguo: nao chuta
        {"camera_ip": "10.200.1.9", "remote_connector_id": "conA"},
    ]
    R._completar_coordenadas(canais)
    assert R._coordenadas(canais[0]) == (-8.0, -35.0)
    assert R._coordenadas(canais[1]) is None
    assert R._coordenadas(canais[2]) is None
