"""O WebSocket do player (/go2rtc/api/ws) so abre para sessao do cliente que
registrou o stream (nginx auth_request -> /api/auth/video-ok). Antes abria
sem login nenhum: com o nome previsivel (cam_<ip>_<0|1>), qualquer um na
internet assistia a camera de outro cliente."""
import pytest
from fastapi import HTTPException

from app.api.endpoints import auth
from app.core import tenant_context as T
from app.services import live_stream_service as L


class _Req:
    def __init__(self, uri):
        self.headers = {"x-original-uri": uri}


def test_stream_fica_com_o_cliente_que_registrou(monkeypatch):
    monkeypatch.setattr(L, "_dono_stream", {})
    tok = T.set_current_tenant_slug("rads")
    try:
        L.marcar_dono("cam_10_211_128_112_1")
    finally:
        T.reset_current_tenant_slug(tok)
    assert L.dono_do_stream("cam_10_211_128_112_1") == "rads"


def test_video_ok_so_para_o_mesmo_cliente(monkeypatch):
    monkeypatch.setattr(L, "_dono_stream", {"cam_10_211_128_112_1": "rads"})
    uri = "/go2rtc/api/ws?src=cam_10_211_128_112_1"
    assert auth.api_auth_video_ok(_Req(uri), {"tenant_slug": "rads"}).status_code == 204
    # admin de plataforma operando como o cliente: vale o cliente efetivo
    assert auth.api_auth_video_ok(_Req(uri), {"tenant_slug": "default", "effective_tenant_slug": "rads"}).status_code == 204
    for user, u in (({"tenant_slug": "sierra"}, uri),                     # outro cliente
                    ({"tenant_slug": "rads"}, "/go2rtc/api/ws?src=cam_1_2_3_4_1"),  # nao registrado
                    ({"tenant_slug": "rads"}, "/go2rtc/api/ws")):          # sem src
        with pytest.raises(HTTPException) as e:
            auth.api_auth_video_ok(_Req(u), user)
        assert e.value.status_code == 403
