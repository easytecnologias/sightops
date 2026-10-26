"""Video ao vivo no app instalado: sem cookie, o WebSocket leva um bilhete
curto (`t=`) emitido em /api/auth/video-ticket. O bilhete vale 60 s, para UM
stream e UM cliente; a sessao do navegador continua valendo como antes."""
import pytest
from fastapi import HTTPException

from app.api.endpoints import auth
from app.services import live_stream_service as L
from app.services import video_ticket as V


class _Req:
    def __init__(self, uri):
        self.headers = {"x-original-uri": uri}


@pytest.fixture(autouse=True)
def _chave_fixa(monkeypatch):
    monkeypatch.setattr(V, "_chave", lambda: b"k" * 32)
    monkeypatch.setattr(L, "_dono_stream", {"cam_10_0_0_1_1": "rads", "cam_10_0_0_2_1": "sierra"})
    monkeypatch.setattr(V, "_usados", {})


def test_bilhete_valido_so_para_o_stream_e_o_cliente():
    b = V.emitir("cam_10_0_0_1_1", "rads", agora=1000)
    assert V.validar("cam_10_0_0_1_1", b, agora=1030, consumir=False) == "rads"
    assert V.validar("cam_10_0_0_2_1", b, agora=1030) is None       # outro stream
    assert V.validar("cam_10_0_0_1_1", b, agora=1061) is None       # vencido
    exp, cli, sig = b.split(".", 2)
    assert V.validar("cam_10_0_0_1_1", f"{exp}.sierra.{sig}", agora=1030) is None   # trocou o cliente
    assert V.validar("cam_10_0_0_1_1", f"{int(exp) + 3600}.{cli}.{sig}", agora=1030) is None  # esticou a validade
    assert V.validar("cam_10_0_0_1_1", "lixo", agora=1030) is None


def test_video_ok_aceita_bilhete_sem_sessao():
    b = V.emitir("cam_10_0_0_1_1", "rads")
    assert auth.api_auth_video_ok(_Req(f"/go2rtc/api/ws?src=cam_10_0_0_1_1&t={b}"), None).status_code == 204


def test_video_ok_recusa_sem_sessao_e_sem_bilhete_ou_com_bilhete_de_outro():
    with pytest.raises(HTTPException) as e:
        auth.api_auth_video_ok(_Req("/go2rtc/api/ws?src=cam_10_0_0_1_1"), None)
    assert e.value.status_code == 401
    # bilhete do proprio cliente, mas de stream que e de OUTRO cliente
    b = V.emitir("cam_10_0_0_2_1", "rads")
    with pytest.raises(HTTPException) as e:
        auth.api_auth_video_ok(_Req(f"/go2rtc/api/ws?src=cam_10_0_0_2_1&t={b}"), None)
    assert e.value.status_code == 403


def test_sessao_continua_valendo_como_antes():
    uri = "/go2rtc/api/ws?src=cam_10_0_0_1_1"
    assert auth.api_auth_video_ok(_Req(uri), {"tenant_slug": "rads"}).status_code == 204
    with pytest.raises(HTTPException):
        auth.api_auth_video_ok(_Req(uri), {"tenant_slug": "sierra"})


def test_bilhete_so_sai_para_stream_do_proprio_cliente():
    r = auth.api_auth_video_ticket("cam_10_0_0_1_1", {"tenant_slug": "rads"})
    assert V.validar("cam_10_0_0_1_1", r["ticket"]) == "rads"
    for src in ("cam_10_0_0_2_1", "cam_9_9_9_9_1", ""):
        with pytest.raises(HTTPException) as e:
            auth.api_auth_video_ticket(src, {"tenant_slug": "rads"})
        assert e.value.status_code == 403


def test_middleware_deixa_video_ok_chegar_na_rota():
    from app.core.security import ApiAuthMiddleware

    m = ApiAuthMiddleware.__new__(ApiAuthMiddleware)
    ApiAuthMiddleware.__init__(m, app=None, settings=None)
    assert m._is_public_path("/api/auth/video-ok")
    assert not m._is_public_path("/api/auth/video-ticket")


def test_bilhete_vale_uma_vez_so():
    b = V.emitir("cam_10_0_0_1_1", "rads")
    uri = f"/go2rtc/api/ws?src=cam_10_0_0_1_1&t={b}"
    assert auth.api_auth_video_ok(_Req(uri), None).status_code == 204
    with pytest.raises(HTTPException) as e:      # o mesmo bilhete lido do log
        auth.api_auth_video_ok(_Req(uri), None)
    assert e.value.status_code == 403
