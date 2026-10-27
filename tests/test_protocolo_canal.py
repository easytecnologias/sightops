"""Protocolo ao por camera no canal do gravador (recorder_write._gravar_com_modo):
Adaptativo (tenta e confere pela imagem do canal), Intelbras, ONVIF e
Personalizado (RTSP manual). Gravador simulado: nada vai a equipamento."""
import pytest

from app.services import recorder_write as W


@pytest.fixture
def grav(monkeypatch):
    estado = {"marca": "intelbras", "imagem": {}, "escritas": [], "ocupado": ""}
    monkeypatch.setattr(W, "_base", lambda host, porta, cid="": "http://10.209.193.122:8088")
    monkeypatch.setattr(W, "detectar_marca", lambda base, u, p: estado["marca"])
    monkeypatch.setattr(W, "_canal_ocupado", lambda *a: estado["ocupado"])

    def gravar(acao, proto, **k):
        estado["escritas"].append((acao, proto, k.get("url_principal")))
        estado["atual"] = proto
        return {"comando": "x"}
    monkeypatch.setattr(W, "_gravar_intelbras", gravar)
    monkeypatch.setattr(W, "_intelbras_imagem", lambda *a, **k: estado["imagem"].get(estado.get("atual")))
    return estado


def _rodar(modo, camera_hik=False, **k):
    return W._gravar_com_modo("adicionar", modo, host="10.10.9.122", user="admin", password="x", canal=32,
                              porta_gravador=8088, connector_id="c", ip="172.16.45.104", cam_user="user",
                              cam_senha="s", nome="04 - FRONTAL 02", porta=None, porta_http=None, porta_rtsp=None,
                              url_principal=k.get("url", ""), url_extra="", camera_hik=camera_hik)


def test_hikvision_no_adaptativo_comeca_pelo_onvif(grav):
    grav["imagem"] = {"Onvif": True}
    r = _rodar("adaptativo", camera_hik=True)
    assert grav["escritas"] == [("adicionar", "Onvif", "")]
    assert r["online"] is True and r["protocolo_usado"] == "ONVIF"


def test_adaptativo_troca_so_se_nao_vier_imagem(grav):
    grav["imagem"] = {"Private": False, "Onvif": True}
    r = _rodar("adaptativo")
    assert [e[:2] for e in grav["escritas"]] == [("adicionar", "Private"), ("editar", "Onvif")]
    assert r["protocolo_usado"] == "ONVIF" and r["online"] is True


def test_nada_deu_imagem_volta_ao_primeiro_e_avisa(grav):
    grav["imagem"] = {"Private": False, "Onvif": False}
    r = _rodar("adaptativo")
    assert [e[1] for e in grav["escritas"]] == ["Private", "Onvif", "Private"]
    assert r["online"] is False and "sem imagem" in r["aviso"]


def test_sem_como_conferir_nao_troca_as_cegas(grav):
    grav["imagem"] = {}            # snapshot nao respondeu (None)
    r = _rodar("adaptativo")
    assert [e[1] for e in grav["escritas"]] == ["Private"] and r["online"] is False


def test_escolhido_grava_so_ele(grav):
    grav["imagem"] = {"Onvif": True}
    r = _rodar("onvif")
    assert [e[1] for e in grav["escritas"]] == ["Onvif"] and r["online"] is True


def test_personalizado_exige_endereco_rtsp(grav):
    with pytest.raises(W.ErroGravador, match="RTSP"):
        _rodar("general", url="http://x")
    assert grav["escritas"] == []
    grav["imagem"] = {"General": True}
    r = _rodar("general", url="rtsp://172.16.45.104:554/Streaming/Channels/101")
    assert grav["escritas"] == [("adicionar", "General", "rtsp://172.16.45.104:554/Streaming/Channels/101")]
    assert r["protocolo_usado"] == "Personalizado (RTSP)"


def test_canal_ocupado_nao_grava(grav):
    grav["ocupado"] = "10.10.9.50"
    with pytest.raises(W.ErroGravador, match="ja tem a camera"):
        _rodar("adaptativo")
    assert grav["escritas"] == []


def test_gravador_hikvision_personalizado_recusa(grav):
    grav["marca"] = "hikvision"
    with pytest.raises(W.ErroGravador, match="so em gravador Intelbras"):
        _rodar("general", url="rtsp://x")


def test_fluxo_antigo_continua_sem_modo():
    for antigo in ("", "Private", "Onvif", "HIKVISION"):
        assert W._modo_protocolo(antigo) == ""
    assert [W._modo_protocolo(x) for x in ("adaptativo", "onvif", "private", "personalizado")] == \
        ["adaptativo", "onvif", "private", "general"]


def test_gravador_hikvision_onvif_usa_a_porta_http(grav, monkeypatch):
    grav["marca"] = "hikvision"
    vistos = {}
    monkeypatch.setitem(W._ACOES["hikvision"], "adicionar", lambda base, u, p, **k: vistos.update(k) or {"comando": "x"})
    W._gravar_com_modo("adicionar", "onvif", host="h", user="u", password="p", canal=3, porta_gravador=80,
                       connector_id="c", ip="10.0.0.5", cam_user="onvif", cam_senha="s", nome="", porta=37777,
                       porta_http=8080, porta_rtsp=None, url_principal="", url_extra="", camera_hik=True)
    assert vistos["protocolo"] == "ONVIF" and vistos["porta"] == 8080
