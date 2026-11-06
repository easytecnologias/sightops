"""Alerta Termico: cadastro da camera so pelo inventario do cliente, regra,
horario armado, vigia de ponta a ponta (camera falsa que devolve a matriz real
da CAM P 03) e isolamento entre clientes. Nada sai para a rede."""
from array import array
from datetime import datetime
from pathlib import Path

import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug

FX = Path(__file__).parent / "fixtures" / "termico"
W, H = 256, 192


def _quadro(com_pessoa=False):
    from app.services.termico_deteccao import Quadro
    temps = array("f")
    temps.frombytes((FX / ("quadro2.temps.bin" if com_pessoa else "quadro1.temps.bin")).read_bytes())
    if com_pessoa:
        for y in range(90, 104):
            for x in range(170, 176):
                temps[y * W + x] = 34.0
    return Quadro(W, H, temps, b"\xff\xd8termico", b"", {})


INVENTARIO = {
    "cliente-a": [{"ip": "10.0.0.81", "mac": "a4:4c:62:30:18:a6", "modelo": "HM-TD2628-8/QA/BR", "site": "UFV-RODOANEL",
                   "nome": "03 - CAM P 03", "connector_id": "c1", "porta": 80}],
    "cliente-b": [{"ip": "10.0.0.81", "mac": "aa:bb:cc:00:00:01", "modelo": "HM-TD2628-8/QA/BR", "site": "OUTRA",
                   "nome": "CAM B", "connector_id": "c2", "porta": 80}],
}


class _Imediato:
    def submit(self, fn, *a):
        fn(*a)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    from app.services import db_store, termico_store
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    import app.core.tenant_context as tc
    monkeypatch.setattr(tc, "DATA_DIR", tmp_path)
    monkeypatch.setattr(termico_store, "_inventario_termico", lambda tenant: [dict(x) for x in INVENTARIO.get(tenant, [])])
    tok = set_current_tenant_slug("cliente-a")
    db_store.init_db()
    yield termico_store
    reset_current_tenant_slug(tok)


def _como(tenant):
    class _Ctx:
        def __enter__(self):
            self.t = set_current_tenant_slug(tenant)

        def __exit__(self, *a):
            reset_current_tenant_slug(self.t)
    return _Ctx()


def test_so_entra_camera_do_inventario_do_cliente(store):
    lista = store.listar_cameras()
    assert lista["cameras"] == [] and lista["no_inventario"][0]["ip"] == "10.0.0.81"
    with pytest.raises(LookupError):
        store.adicionar("10.9.9.9")
    cam = store.adicionar("10.0.0.81", "c1")
    assert cam["ativo"] is False and cam["nome"] == "03 - CAM P 03"
    with pytest.raises(ValueError):
        store.adicionar("10.0.0.81", "c1")
    assert store.listar_cameras()["no_inventario"] == []


def test_regra_e_validada(store):
    cam = store.adicionar("10.0.0.81", "c1")
    with pytest.raises(ValueError, match="dif_min"):
        store.salvar_camera(cam["id"], {"regra": {"dif_min": 0}})
    with pytest.raises(ValueError, match="mínima de corpo"):
        store.salvar_camera(cam["id"], {"regra": {"corpo_min": 40, "corpo_max": 30}})
    with pytest.raises(ValueError, match="fora da imagem"):
        store.salvar_camera(cam["id"], {"regra": {"areas": [[[0, 0], [1.5, 0], [1, 1]]]}})
    with pytest.raises(ValueError, match="início e fim"):
        store.salvar_camera(cam["id"], {"armado_de": "18:00"})
    ok = store.salvar_camera(cam["id"], {"ativo": True, "armado_de": "18:00", "armado_ate": "06:00",
                                         "regra": {"dif_min": 6, "areas": [[[0.55, 0], [1, 0], [1, 1], [0.55, 1]]]}})
    assert ok["ativo"] is True and ok["regra"]["dif_min"] == 6.0
    assert ok["regra"]["areas"] == [[(0.55, 0.0), (1.0, 0.0), (1.0, 1.0), (0.55, 1.0)]]


def test_horario_armado_que_vira_o_dia(store):
    from app.services.termico_store import FUSO, esta_armado
    cam = {"ativo": 1, "armado_de": "18:00", "armado_ate": "06:00"}
    assert esta_armado(cam, datetime(2026, 11, 5, 23, 0, tzinfo=FUSO))
    assert esta_armado(cam, datetime(2026, 11, 5, 3, 0, tzinfo=FUSO))
    assert not esta_armado(cam, datetime(2026, 11, 5, 12, 45, tzinfo=FUSO))
    assert esta_armado({"ativo": 1, "armado_de": "", "armado_ate": ""}, datetime(2026, 11, 5, 12, 45, tzinfo=FUSO))
    assert not esta_armado({"ativo": 0, "armado_de": "", "armado_ate": ""})


def _vigia(monkeypatch, quadros):
    from app.services import camera_credentials, termico_camera
    import app.core.destino as destino
    from app.services.termico_vigia import VigiaTermico
    monkeypatch.setattr(camera_credentials, "resolve_camera_credential", lambda mac, site: {"username": "admin", "password": "x"})
    monkeypatch.setattr(destino, "destino_permitido", lambda tenant, ip, exigir_dono=True: (True, ""))
    monkeypatch.setattr(termico_camera, "base_da_camera", lambda ip, porta, cid: f"http://virtual-{ip}")
    fila = list(quadros)
    monkeypatch.setattr(termico_camera, "buscar_quadro", lambda base, u, s, canal=2: fila.pop(0))
    monkeypatch.setattr(termico_camera, "buscar_foto", lambda base, u, s, canal_video=1: b"\xff\xd8visivel")
    v = VigiaTermico()
    v._pool = _Imediato()
    return v


def test_vigia_grava_alerta_com_fotos_e_isola_cliente(store, monkeypatch):
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True, "regra": {"quadros_seguidos": 2, "movimento_min": 0}})
    v = _vigia(monkeypatch, [_quadro(), _quadro(True), _quadro(True)])
    for t in (0, 2, 4):
        v.rodada(agora=t)

    lista = store.listar_alertas()
    assert lista["total"] == 1 and lista["por_situacao"]["novo"] == 1
    a = lista["alertas"][0]
    assert a["camera_nome"] == "03 - CAM P 03" and a["site"] == "UFV-RODOANEL"
    assert a["dif_c"] < -5 and a["mancha"]["pontos"] == 84 and a["mancha"]["quadros"] == 2
    assert store.caminho_foto(a["id"], "visivel").read_bytes() == b"\xff\xd8visivel"
    assert store.caminho_foto(a["id"], "termico").read_bytes() == b"\xff\xd8termico"
    assert store.listar_cameras()["cameras"][0]["leitura"] == "ok"

    with _como("cliente-b"):
        assert store.listar_alertas()["total"] == 0
        assert store.listar_cameras()["cameras"] == []
        with pytest.raises(LookupError):
            store.caminho_foto(a["id"], "visivel")
        with pytest.raises(LookupError):
            store.marcar(a["id"], "visto", "intruso")

    with pytest.raises(ValueError, match="motivo"):
        store.marcar(a["id"], "falso", "ana")
    f = store.marcar(a["id"], "falso", "ana", "animal", "cachorro")
    assert f["situacao"] == "falso" and f["visto_por"] == "ana" and f["motivo_falso"] == "animal"


def test_desarmada_le_mas_nao_alerta(store, monkeypatch):
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True, "armado_de": "00:00", "armado_ate": "00:01",
                                    "regra": {"quadros_seguidos": 1}})
    from app.services import termico_store
    monkeypatch.setattr(termico_store, "esta_armado", lambda camera, agora=None: False)
    v = _vigia(monkeypatch, [_quadro(), _quadro(True)])
    v.rodada(agora=0)
    v.rodada(agora=2)          # menos de 60 s: nem le
    v.rodada(agora=61)
    assert store.listar_alertas()["total"] == 0
    assert store.listar_cameras()["cameras"][0]["leitura"] == "ok"


def test_camera_sem_medicao_vira_erro_de_leitura(store, monkeypatch):
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    from app.services import termico_camera
    v = _vigia(monkeypatch, [])

    def falha(*a, **k):
        raise ValueError("a camera nao mandou a matriz de temperatura (medicao desligada?)")
    monkeypatch.setattr(termico_camera, "buscar_quadro", falha)
    v.rodada(agora=0)
    c = store.listar_cameras()["cameras"][0]
    assert c["leitura"] == "erro" and "medicao desligada" in c["leitura_erro"]
    assert store.resumo_para_zabbix("cliente-a")["10.0.0.81|c1"]["termico_leitura"] == 0


def test_zabbix_recebe_os_campos_so_na_camera_certa(store, monkeypatch):
    import json
    from app.services import zabbix_monitoring_service as Z
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    store.registrar_leitura(cam["id"], True, "", 51.234)
    store.registrar_alerta({**store.cameras_ativas()[0]}, {"temp_media": 34.0, "fundo_medio": 58.0, "dif": -24.0}, {})
    entidades = [
        {"entity_type": "camera", "connector_id": "c1", "detail_json": json.dumps({"ip": "10.0.0.81"})},
        {"entity_type": "camera", "connector_id": "c1", "detail_json": json.dumps({"ip": "10.0.0.18"})},
        {"entity_type": "nvr", "connector_id": "c1", "detail_json": json.dumps({"ip": "10.0.0.81"})},
    ]
    Z._juntar_termico("cliente-a", entidades)
    d0, d1, d2 = (json.loads(e["detail_json"]) for e in entidades)
    assert d0["termico_pendentes"] == 1 and d0["termico_leitura"] == 1 and d0["termico_fundo_c"] == 51.2
    assert "termico_pendentes" not in d1 and "termico_pendentes" not in d2
    # outro cliente com camera no MESMO IP nao recebe nada do cliente-a
    entidades_b = [{"entity_type": "camera", "connector_id": "c1", "detail_json": json.dumps({"ip": "10.0.0.81"})}]
    Z._juntar_termico("cliente-b", entidades_b)
    assert "termico_pendentes" not in json.loads(entidades_b[0]["detail_json"])


def test_mesmo_ip_em_duas_usinas_sao_cameras_diferentes(store, monkeypatch):
    from app.services import termico_store
    inv = [dict(INVENTARIO["cliente-a"][0]),
           {**INVENTARIO["cliente-a"][0], "connector_id": "c9", "site": "UFV-DEMERVAL-LOBAO", "nome": "CAM D", "mac": "aa:aa:aa:aa:aa:09"}]
    monkeypatch.setattr(termico_store, "_inventario_termico", lambda tenant: [dict(x) for x in inv])
    a = store.adicionar("10.0.0.81", "c1")
    b = store.adicionar("10.0.0.81", "c9")
    assert a["id"] != b["id"] and b["site"] == "UFV-DEMERVAL-LOBAO"
    store.salvar_camera(a["id"], {"ativo": True})
    store.registrar_leitura(a["id"], True, "", 50.0)
    r = store.resumo_para_zabbix("cliente-a")
    assert set(r) == {"10.0.0.81|c1"}        # a outra nunca leu: nada vai ao Zabbix


def test_leitura_parada_vira_zero_e_removida_vira_dois(store, monkeypatch):
    from app.services import db_store
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    store.registrar_leitura(cam["id"], True, "", 50.0)
    assert store.resumo_para_zabbix("cliente-a")["10.0.0.81|c1"]["termico_leitura"] == 1
    with db_store._conn() as c:    # laco morreu ha 10 min
        c.execute("UPDATE termico_cameras SET leitura_at='2026-11-05T10:00:00Z' WHERE id=?", (cam["id"],))
    z = store.resumo_para_zabbix("cliente-a")["10.0.0.81|c1"]
    assert z["termico_leitura"] == 0 and z["termico_fundo_c"] is None
    store.registrar_alerta(store.cameras_ativas()[0], {"temp_media": 34.0, "fundo_medio": 58.0, "dif": -24.0}, {})
    store.remover_camera(cam["id"])
    z = store.resumo_para_zabbix("cliente-a")["10.0.0.81|c1"]
    assert z["termico_leitura"] == 2 and z["termico_pendentes"] == 1     # responder ainda fecha o gatilho
    assert store.listar_cameras()["cameras"] == [] and store.listar_cameras()["no_inventario"]
    store.registrar_leitura(cam["id"], True, "", 50.0)                   # leitura atrasada nao ressuscita
    assert store.resumo_para_zabbix("cliente-a")["10.0.0.81|c1"]["termico_leitura"] == 2
    de_volta = store.adicionar("10.0.0.81", "c1")
    assert de_volta["id"] == cam["id"] and de_volta["ativo"] is False


def test_usuario_restrito_a_um_site_nao_ve_o_outro(store, monkeypatch):
    import app.core.permissions as P
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    a = store.registrar_alerta(store.cameras_ativas()[0], {"temp_media": 34.0, "fundo_medio": 58.0, "dif": -24.0}, {})
    monkeypatch.setattr(P, "sites_da_sessao", lambda: ["UFV-DEMERVAL-LOBAO"])
    assert store.listar_alertas()["total"] == 0
    assert store.listar_cameras()["cameras"] == [] and store.listar_cameras()["no_inventario"] == []
    with pytest.raises(LookupError):
        store.marcar(a["id"], "visto", "x")
    with pytest.raises(LookupError):
        store.salvar_camera(cam["id"], {"ativo": False})
    monkeypatch.setattr(P, "sites_da_sessao", lambda: ["ufv-rodoanel"])
    assert store.listar_alertas()["total"] == 1


def test_thread_do_vigia_nao_herda_conector_da_leitura_anterior(store, monkeypatch):
    from app.services import connector_routing_vnat as V
    from app.services import termico_camera
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    v = _vigia(monkeypatch, [_quadro()])
    vistos = []

    def base(ip, porta, cid):
        vistos.append(V._olt_reach_cid.get())
        V.set_olt_reach_connector("conector-velho")     # como o _base real faz
        return "http://x"
    monkeypatch.setattr(termico_camera, "base_da_camera", base)
    V.set_olt_reach_connector("conector-velho")
    v.rodada(agora=0)
    assert vistos == [""] and V._olt_reach_cid.get() == ""


def test_foto_agora_isola_cliente_e_segura_4_segundos(store, monkeypatch):
    from app.services import termico_camera
    v = _vigia(monkeypatch, [])
    cam = store.adicionar("10.0.0.81", "c1")
    pedidos = []
    monkeypatch.setattr(termico_camera, "buscar_foto", lambda base, u, s, canal_video=1: (pedidos.append(canal_video), b"jpg")[1])
    store._FOTOS_AGORA.clear()
    assert store.foto_agora(cam["id"], "termica") == b"jpg"
    store.foto_agora(cam["id"], "termica")
    store.foto_agora(cam["id"], "colorida")
    assert pedidos == [2, 1]
    with _como("cliente-b"):
        with pytest.raises(LookupError):
            store.foto_agora(cam["id"], "termica")
    with pytest.raises(LookupError):
        store.foto_agora(cam["id"], "outra")


class _RespCam:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status


def test_preparar_so_escreve_o_que_precisa(monkeypatch):
    from app.services import termico_camera as C
    feitos = []
    monkeypatch.setattr(C.requests, "get", lambda url, **k: _RespCam(
        "<id>2</id><enabled>false</enabled><streamOverlay>true</streamOverlay><x><enabled>false</enabled></x>" if "basicParam" in url
        else "<visiblePicEnabled>true</visiblePicEnabled>"))
    monkeypatch.setattr(C.requests, "put", lambda url, data=None, **k: (feitos.append((url, data.decode())), _RespCam())[1])
    r = C.preparar_medicao("http://cam", "u", "s")
    assert r == {"medicao": "ligada", "foto_colorida": "desligada"}
    assert "<id>2</id><enabled>true</enabled><streamOverlay>true</streamOverlay><x><enabled>false</enabled></x>" == feitos[0][1]
    assert "<visiblePicEnabled>false</visiblePicEnabled>" == feitos[1][1]


def test_preparar_camera_ja_pronta_nao_escreve(monkeypatch):
    from app.services import termico_camera as C
    feitos = []
    monkeypatch.setattr(C.requests, "get", lambda url, **k: _RespCam(
        "<enabled>true</enabled><streamOverlay>" if "basicParam" in url else "<visiblePicEnabled>false</visiblePicEnabled>"))
    monkeypatch.setattr(C.requests, "put", lambda *a, **k: feitos.append(1))
    assert C.preparar_medicao("http://cam", "u", "s") == {"medicao": "ja_ligada", "foto_colorida": "ja_desligada"}
    assert feitos == []


def test_vivo_abre_canal_certo_e_isola(store, monkeypatch):
    from app.services import automacao_store, camera_credentials, live_stream_service, termico_camera
    from app.core.tenant_context import get_current_tenant_slug
    eq = {"ip": "10.0.0.81", "connector_id": "c1", "mac": "aa", "site": "UFV-RODOANEL", "porta": 80, "modelo": "HM-TD2628-8/QA/BR"}
    monkeypatch.setattr(automacao_store, "equipamento_do_inventario",
                        lambda ip, cid="": dict(eq) if get_current_tenant_slug() == "cliente-a" and ip == eq["ip"] and cid == "c1" else None)
    monkeypatch.setattr(camera_credentials, "resolve_camera_credential", lambda m, s: {"username": "u", "password": "s"})
    monkeypatch.setattr(termico_camera, "base_da_camera", lambda ip, p, c: "http://10.208.128.81")
    canais = []
    monkeypatch.setattr(live_stream_service, "register_camera_canal_stream", lambda **k: (canais.append((k["host"], k["canal"])), f"cam_canal_{k['canal']}")[1])
    assert store.abrir_vivo("10.0.0.81", "c1", "termica")["stream_name"] == "cam_canal_202"
    store.abrir_vivo("10.0.0.81", "c1", "termica", True)
    store.abrir_vivo("10.0.0.81", "c1", "colorida")
    store.abrir_vivo("10.0.0.81", "c1", "colorida", True)
    assert canais == [("10.208.128.81", 202), ("10.208.128.81", 201), ("10.208.128.81", 102), ("10.208.128.81", 101)]
    with pytest.raises(LookupError):
        store.abrir_vivo("10.0.0.81", "c1", "outra")
    with _como("cliente-b"):
        with pytest.raises(LookupError):
            store.abrir_vivo("10.0.0.81", "c1", "termica")


def test_manchas_so_da_camera_do_cliente(store, monkeypatch):
    from app.services.termico_vigia import VigiaTermico
    import app.services.termico_vigia as TV
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True, "regra": {"quadros_seguidos": 1}})
    v = _vigia(monkeypatch, [_quadro(), _quadro(True)])
    monkeypatch.setattr(TV, "vigia_global", lambda: v)
    v.rodada(agora=0)
    v.rodada(agora=2)
    r = store.manchas_agora(cam["id"])
    assert r["lendo"] is True and r["manchas"][0]["pontos"] == 84
    with _como("cliente-b"):
        with pytest.raises(LookupError):
            store.manchas_agora(cam["id"])


def test_rota_de_video_nao_abre_cftv_comum(store, monkeypatch):
    from app.services import automacao_store, camera_credentials, db_store, live_stream_service, termico_camera
    comum = {"ip": "10.0.0.18", "connector_id": "c1", "mac": "bb", "site": "UFV-RODOANEL", "porta": 80, "modelo": "DS-2CD1047G2H-LIU"}
    speed = {**comum, "ip": "10.0.0.10", "modelo": "DS-2DE7A432IW-AEB"}
    monkeypatch.setattr(automacao_store, "equipamento_do_inventario", lambda ip, cid="": next((dict(e) for e in (comum, speed) if e["ip"] == ip), None))
    monkeypatch.setattr(camera_credentials, "resolve_camera_credential", lambda m, s: {"username": "u", "password": "s"})
    monkeypatch.setattr(termico_camera, "base_da_camera", lambda ip, p, c: f"http://{ip}")
    monkeypatch.setattr(live_stream_service, "register_camera_canal_stream", lambda **k: "cam_canal_x")
    with pytest.raises(LookupError):
        store.abrir_vivo("10.0.0.18", "c1", "colorida")
    with pytest.raises(LookupError):
        store.abrir_vivo("10.0.0.10", "c1", "colorida")      # speed sem automacao
    with db_store._conn() as c:
        c.execute("INSERT INTO automacoes(id, tenant_slug, acoes) VALUES(?,?,?)",
                  ("r" * 32, "cliente-a", '[{"tipo":"speed_preset","ip":"10.0.0.10","connector_id":"c1"}]'))
    assert store.abrir_vivo("10.0.0.10", "c1", "colorida")["stream_name"] == "cam_canal_x"
    with pytest.raises(LookupError):
        store.abrir_vivo("10.0.0.18", "c1", "colorida")


def test_stream_leva_o_cliente_e_o_dono_vem_depois_da_fonte(store, monkeypatch):
    from app.services import live_stream_service as L
    ordem = []
    monkeypatch.setattr(L, "_fontes_registradas", lambda n: None)
    monkeypatch.setattr(L, "marcar_dono", lambda n: ordem.append("dono"))
    monkeypatch.setattr(L.requests, "put", lambda *a, **k: (ordem.append("put"), _RespCam())[1])
    n = L.register_camera_canal_stream(host="200.1.1.1", user="u", password="s", canal=202)
    assert n == "cam_canal_clientea_200_1_1_1_202" and ordem == ["put", "dono"]
    with _como("cliente-b"):
        assert L.camera_canal_stream_name("200.1.1.1", 202) != n


def test_preparar_so_muda_o_primeiro_enabled(monkeypatch):
    from app.services import termico_camera as C
    feitos = []
    xml = "<id>2</id><enabled>true</enabled><x><enabled>false</enabled></x>"
    monkeypatch.setattr(C.requests, "get", lambda url, **k: _RespCam(xml if "basicParam" in url else ""))
    monkeypatch.setattr(C.requests, "put", lambda *a, **k: feitos.append(1))
    assert C.preparar_medicao("http://cam", "u", "s")["medicao"] == "ja_ligada" and feitos == []


def test_alarme_de_teste_passa_pelo_caminho_inteiro(store, monkeypatch):
    from app.services import camera_credentials, termico_camera, termico_vigia
    monkeypatch.setattr(camera_credentials, "resolve_camera_credential", lambda m, s: {"username": "u", "password": "s"})
    monkeypatch.setattr(termico_camera, "base_da_camera", lambda ip, p, c: "http://cam")
    monkeypatch.setattr(termico_camera, "buscar_foto", lambda b, u, s, canal_video=1: b"jpg" + bytes([canal_video]))
    avisos = []
    monkeypatch.setattr(termico_vigia, "avisar_alerta", lambda t, c, a: avisos.append((t, c["id"], a["mancha"].get("teste"), a["so_simular"])))
    from app.core import tenant_context
    papel = {"role": "operator"}
    monkeypatch.setattr(tenant_context, "get_current_user", lambda: papel)
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    r = store.alarme_de_teste(cam["id"])
    a = store.listar_alertas()["alertas"][0]
    assert a["id"] == r["id"] and a["mancha"]["teste"] is True and a["situacao"] == "novo"
    assert store.caminho_foto(a["id"], "termico").read_bytes() == b"jpg\x02"
    assert avisos == [("cliente-a", cam["id"], True, True)]
    papel["role"] = "admin"
    store.alarme_de_teste(cam["id"])
    assert avisos[-1][-1] is False
    with _como("cliente-b"):
        with pytest.raises(LookupError):
            store.alarme_de_teste(cam["id"])


def test_so_simular_nao_aciona_regra_valendo(monkeypatch):
    from app.services import automacao_acoes as A
    modos = []
    regra = {"id": "r", "nome": "x", "modo": "valer", "acoes": [{"tipo": "saida"}]}
    monkeypatch.setattr(A.automacao_store, "regras_da_camera", lambda c: [regra])
    monkeypatch.setattr(A, "_dentro_do_intervalo", lambda r: False)
    monkeypatch.setattr(A, "executar_acao", lambda t, a, m, **k: (modos.append(m), (True, "ok"))[1])
    monkeypatch.setattr(A.automacao_store, "registrar_execucao", lambda *a: modos.append(a[2]))
    assert A.disparar("cliente-a", "c", "a", so_simular=True) == 1
    assert modos == ["simular", "simular"]
    assert A.disparar("cliente-a", "c", "a") == 1
    assert modos[2:] == ["valer", "valer"]


def test_falha_de_aviso_e_de_automacao_vai_ao_zabbix(store):
    from app.services import db_store
    cam = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(cam["id"], {"ativo": True})
    store.registrar_leitura(cam["id"], True, "", 40.0)
    with db_store._conn() as c:
        linha = dict(c.execute("SELECT * FROM termico_cameras WHERE id=?", (cam["id"],)).fetchone())
    a = store.registrar_alerta(linha, {"temp_media": 34}, {})
    assert list(store.resumo_para_zabbix("cliente-a").values())[0]["termico_falhas"] == 0
    store.anotar_falha_aviso("cliente-a", a["id"], 2)
    with db_store._conn() as c:
        c.execute("INSERT INTO automacao_execucoes(id, tenant_slug, automacao_id, alerta_id, modo, acao, ok, resposta, criado_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)", ("e" * 32, "cliente-a", "r" * 32, a["id"], "valer", "{}", 0, "x", store._agora()))
    assert list(store.resumo_para_zabbix("cliente-a").values())[0]["termico_falhas"] == 3
    store.anotar_falha_aviso("cliente-b", a["id"], 9)      # outro cliente nao mexe
    assert list(store.resumo_para_zabbix("cliente-a").values())[0]["termico_falhas"] == 3


def test_camera_readicionada_e_parada_continua_no_zabbix(store):
    cam = store.adicionar("10.0.0.81", "c1")
    assert store.resumo_para_zabbix("cliente-a") == {}          # nunca leu: fica de fora
    store.salvar_camera(cam["id"], {"ativo": True})
    store.registrar_leitura(cam["id"], True, "", 40.0)
    store.remover_camera(cam["id"])
    store.adicionar("10.0.0.81", "c1")                          # voltou desligada
    assert list(store.resumo_para_zabbix("cliente-a").values())[0]["termico_leitura"] == 2


def test_enviar_agora_roda_no_contexto_do_cliente(monkeypatch):
    from app.core.tenant_context import get_current_tenant_slug
    from app.services import zabbix_monitoring_service as Z
    visto = []
    monkeypatch.setattr(Z, "_enviar_termico_agora", lambda t, i, c: visto.append(get_current_tenant_slug()) or True)
    assert Z.enviar_termico_agora("cliente-a", "1.1.1.1", "c") is True and visto == ["cliente-a"]


def test_video_do_alarme_grava_e_aparece_so_com_arquivo(store, monkeypatch):
    from app.services import db_store
    cam = store.adicionar("10.0.0.81", "c1")
    with db_store._conn() as c:
        linha = dict(c.execute("SELECT * FROM termico_cameras WHERE id=?", (cam["id"],)).fetchone())
    a = store.registrar_alerta(linha, {"temp_media": 34}, {"termico.jpg": b"x"})
    assert store.listar_alertas()["alertas"][0]["videos"] == {"termico": "", "visivel": ""}

    def falso(camera, tipo, destino):
        if tipo == "colorida":
            raise RuntimeError("camera fora")
        destino.write_bytes(b"mp4")
        return True
    monkeypatch.setattr(store, "_gravar_um_video", falso)
    assert store.gravar_videos("cliente-a", linha, a["id"]) == ["termico.mp4"]
    v = store.listar_alertas()["alertas"][0]
    assert v["videos"]["termico"].endswith("/video/termico") and v["videos"]["visivel"] == ""
    assert v["fotos"]["termico"]
    assert store.caminho_video(a["id"], "termico").read_bytes() == b"mp4"
    with pytest.raises(LookupError):
        store.caminho_video(a["id"], "visivel")
    with _como("cliente-b"):
        with pytest.raises(LookupError):
            store.caminho_video(a["id"], "termico")


def _alerta_real(store, situacao="novo", teste=False):
    from app.services import db_store
    cam = store.listar_cameras()["cameras"]
    cam = cam[0] if cam else store.adicionar("10.0.0.81", "c1")
    with db_store._conn() as c:
        linha = dict(c.execute("SELECT * FROM termico_cameras WHERE id=?", (cam["id"],)).fetchone())
    a = store.registrar_alerta(linha, {"temp_media": 34, "fundo_medio": 45, **({"teste": True} if teste else {})}, {})
    if situacao != "novo":
        store.marcar(a["id"], situacao, "ana", "animal" if situacao == "falso" else "", "")
    return a


def test_visao_geral_conta_a_usina_e_deixa_o_teste_de_fora(store):
    a = store.adicionar("10.0.0.81", "c1")
    store.salvar_camera(a["id"], {"ativo": True})
    store.registrar_leitura(a["id"], True, "", 40.0)
    _alerta_real(store)
    _alerta_real(store, teste=True)
    g = store.visao_geral()
    u = g["usinas"][0]
    assert (u["cameras"], u["lendo"], u["alarmes"], u["pendentes"]) == (1, 1, 1, 1)
    assert g["config"] == {"escalar_min": 10, "escalar_vezes": 2}
    with _como("cliente-b"):
        assert store.visao_geral()["usinas"] == []


def test_escalonamento_avisa_nas_horas_certas_e_para(store):
    from datetime import datetime, timedelta, timezone
    a = _alerta_real(store)
    agora = datetime.now(timezone.utc)
    assert store.a_escalar(agora) == []                                       # acabou de disparar
    assert [r["id"] for r in store.a_escalar(agora + timedelta(minutes=11))] == [a["id"]]
    assert store.a_escalar(agora + timedelta(minutes=12)) == []               # avisou agora ha pouco
    assert len(store.a_escalar(agora + timedelta(minutes=22))) == 1
    assert store.a_escalar(agora + timedelta(minutes=40)) == []               # ja deu as 2 vezes
    b = _alerta_real(store)
    store.salvar_config({"escalar_min": 0, "escalar_vezes": 2})
    assert store.a_escalar(agora + timedelta(minutes=11)) == []
    store.salvar_config({"escalar_min": 5, "escalar_vezes": 1})
    assert store.a_escalar(agora + timedelta(hours=7)) == []                  # velho demais
    with pytest.raises(ValueError):
        store.salvar_config({"escalar_min": 999, "escalar_vezes": 1})


def test_relatorio_conta_o_periodo_e_gera_pdf(store):
    from app.services import termico_relatorio as R
    from app.services.termico_relatorio_pdf import gerar_pdf
    _alerta_real(store)
    _alerta_real(store, "falso")
    _alerta_real(store, teste=True)
    r = R.gerar()
    assert r["resumo"]["alarmes"] == 2 and r["resumo"]["falsos"] == 1 and r["testes"] == 1 and sum(r["por_hora"]) == 2
    assert r["motivos"] == [{"rotulo": "Animal", "n": 1}] and len(r["lista"]) == 2
    assert gerar_pdf(r, "ana")[:5] == b"%PDF-"
    assert gerar_pdf(dict(R.gerar(de="2020-01-01", ate="2020-01-02")))[:5] == b"%PDF-"     # periodo vazio
    with pytest.raises(ValueError):
        R.gerar(de="2026-02-01", ate="2026-01-01")
    with _como("cliente-b"):
        assert R.gerar()["resumo"]["alarmes"] == 0


def test_faixas_sao_validadas_e_voltam_na_regra(store):
    import json
    cam = store.adicionar("10.0.0.81", "c1")
    p = [{"de": "18:00", "ate": "06:00", "dif_min": 3, "pontos_min": 6, "lixo": 1}]
    salvo = store.salvar_camera(cam["id"], {"regra": {"perfis": p}})
    assert salvo["regra"]["perfis"] == [{"de": "18:00", "ate": "06:00", "dif_min": 3.0, "pontos_min": 6}]
    assert store.regra_de({"regra": json.dumps(salvo["regra"])}).no_minuto(23 * 60).dif_min == 3.0
    assert store.salvar_camera(cam["id"], {"regra": {"perfis": []}})["regra"]["perfis"] == []
    for ruim in ([{"de": "18:00", "ate": "18:00"}], [{"de": "", "ate": "06:00"}], [{"de": "18:00", "ate": "06:00", "dif_min": 999}],
                 [{"de": "18:00", "ate": "06:00", "dif_min": "x"}], "nao", [{"de": "01:00", "ate": "02:00"}] * 9):
        with pytest.raises(ValueError):
            store.salvar_camera(cam["id"], {"regra": {"perfis": ruim}})
