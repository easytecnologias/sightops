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
    store.salvar_camera(cam["id"], {"ativo": True, "regra": {"quadros_seguidos": 2}})
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
