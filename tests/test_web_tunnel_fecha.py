"""Ponte /ws/web-tunnel: quando o equipamento fecha a conexao, a ponte fecha o
websocket. Ruijie, ONTs e partes da UNV respondem HTTP/1.0 sem Content-Length
("Connection: close"): o navegador so sabe que a resposta acabou quando a
conexao fecha. Antes a ponte ficava esperando o navegador mandar mais bytes
e o navegador esperando o fim da resposta -- a pagina ficava branca."""
from __future__ import annotations

import socket
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import maintenance, nvr, ws as ws_mod


def _equipamento_http10() -> int:
    """Servidor TCP que responde como o eWeb do Ruijie: HTTP/1.0, sem tamanho, e fecha."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)

    def atender():
        c, _ = srv.accept()
        c.recv(65536)
        c.sendall(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{\"ok\":true}")
        c.close()
        srv.close()

    threading.Thread(target=atender, daemon=True).start()
    return srv.getsockname()[1]


def test_ponte_fecha_o_websocket_quando_o_equipamento_fecha(monkeypatch):
    async def aceitar(ws, min_role="operator"):
        await ws.accept()
        return True, {"username": "t", "role": "admin", "tenant_slug": "t"}, None

    monkeypatch.setattr(ws_mod, "_accept_ws_session", aceitar)
    monkeypatch.setattr(maintenance, "_is_proxy_allowed_host", lambda h: True)
    monkeypatch.setattr(maintenance, "_ip_belongs_to_current_tenant", lambda h: True)
    monkeypatch.setattr(maintenance, "web_liberada_para", lambda u, h, c="": (True, ""))
    monkeypatch.setattr(maintenance, "_ruijie_gateway_owner", lambda h: "")
    monkeypatch.setattr(maintenance, "_reach", lambda h, c="": "127.0.0.1")
    monkeypatch.setattr(nvr, "_recorder_connector_for_host", lambda h: "")

    porta = _equipamento_http10()
    app = FastAPI()
    app.include_router(ws_mod.router)
    with TestClient(app) as cli, cli.websocket_connect(f"/ws/web-tunnel/10.0.0.9?port={porta}") as wsc:
        wsc.send_bytes(b"GET /cgi-bin/luci/ HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        recebido = wsc.receive_bytes()
        assert recebido.startswith(b"HTTP/1.0 200 OK")
        # depois da resposta, a proxima coisa que chega tem de ser o FECHAMENTO
        fim: dict = {}

        def esperar():
            try:
                fim["msg"] = wsc.receive()
            except Exception as e:  # desconectado tambem serve
                fim["msg"] = {"type": "websocket.close", "erro": repr(e)}

        t = threading.Thread(target=esperar, daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "a ponte nao fechou o websocket depois que o equipamento fechou"
        assert fim["msg"]["type"] == "websocket.close"


def _equipamento_varias(n: int) -> int:
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def atender():
        for _ in range(n):
            c, _ = srv.accept()
            c.recv(65536)
            c.sendall(b"HTTP/1.0 200 OK\r\n\r\nok")
            c.close()
        srv.close()

    threading.Thread(target=atender, daemon=True).start()
    return srv.getsockname()[1]


def test_conferencia_vale_60s_por_cliente_usuario_ip(monkeypatch):
    """ONT abre uma conexao por arquivo: a conferencia (~0,5 s) nao pode se
    repetir em cada uma -- mas outro cliente/usuario confere de novo, e recusa
    nao fica guardada."""
    usuario = {"u": {"id": 1, "username": "a", "role": "operator", "tenant_slug": "t1"}}

    async def aceitar(ws, min_role="operator"):
        await ws.accept()
        return True, dict(usuario["u"]), None

    chamadas = []
    liberar = {"ok": True}

    def destino(user, host, port):
        chamadas.append((user.get("tenant_slug"), user.get("id"), host, port))
        return "127.0.0.1" if liberar["ok"] else ""

    monkeypatch.setattr(ws_mod, "_accept_ws_session", aceitar)
    monkeypatch.setattr(ws_mod, "_web_tunnel_destino", destino)
    monkeypatch.setattr(ws_mod, "_WEB_TUNNEL_CACHE", {})
    porta = _equipamento_varias(4)
    app = FastAPI()
    app.include_router(ws_mod.router)

    def abrir():
        with cli.websocket_connect(f"/ws/web-tunnel/10.0.0.9?port={porta}") as wsc:
            wsc.send_bytes(b"GET / HTTP/1.0\r\n\r\n")
            return wsc.receive_bytes()

    with TestClient(app) as cli:
        assert abrir().startswith(b"HTTP/1.0 200")
        assert abrir().startswith(b"HTTP/1.0 200")
        assert len(chamadas) == 1  # a segunda reaproveitou
        usuario["u"] = {"id": 2, "username": "b", "role": "operator", "tenant_slug": "t2"}
        assert abrir().startswith(b"HTTP/1.0 200")
        assert len(chamadas) == 2  # outro cliente/usuario confere de novo
        usuario["u"] = {"id": 3, "username": "c", "role": "operator", "tenant_slug": "t2"}
        liberar["ok"] = False
        for _ in range(2):
            with cli.websocket_connect(f"/ws/web-tunnel/10.0.0.9?port={porta}") as wsc:
                try:
                    wsc.receive_bytes()
                    assert False, "devia ter recusado"
                except Exception:
                    pass
        assert len(chamadas) == 4  # recusa nao fica guardada
