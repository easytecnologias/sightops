"""O SDK da Intelbras vai na porta que o gravador informa (DVRIP.TCPPort).

Caso real: NVD 7132 do PERUCABA com a 37777 fechada -- excluir canal dava
"o gravador nao respondeu na porta 37777".
"""
from app.services import recorder_write as rw


def test_usa_a_porta_que_o_gravador_informa(monkeypatch):
    pedidos = []
    def falso(metodo, url, user, password, **kw):
        pedidos.append((metodo, url))
        return 200, "table.DVRIP.MaxConnections=10\r\ntable.DVRIP.TCPPort=30777\r\ntable.DVRIP.SSLPort=37778\r\n"
    monkeypatch.setattr(rw, "_req", falso)
    assert rw._porta_sdk_intelbras("http://10.209.193.122:8088", "admin", "x") == 30777
    assert pedidos == [("GET", "http://10.209.193.122:8088/cgi-bin/configManager.cgi?action=getConfig&name=DVRIP")]


def test_sem_leitura_fica_a_padrao(monkeypatch):
    monkeypatch.setattr(rw, "_req", lambda *a, **k: (401, ""))
    assert rw._porta_sdk_intelbras("http://x", "a", "b") == 37777
    def explode(*a, **k):
        raise rw.ErroGravador("sem rede")
    monkeypatch.setattr(rw, "_req", explode)
    assert rw._porta_sdk_intelbras("http://x", "a", "b") == 37777


def test_excluir_pelo_sdk_passa_a_porta(monkeypatch):
    from app.services import intelbras_canal_sdk as sdk
    monkeypatch.setattr(rw, "_porta_sdk_intelbras", lambda *a: 30777)
    visto = {}
    def soltar(host, user, password, canal, connector_id="", porta=37777):
        visto.update(host=host, canal=canal, porta=porta)
        return {"ok": True}
    monkeypatch.setattr(sdk, "soltar_canal", soltar)
    rw._intelbras_pelo_sdk("excluir", base="http://v:8088", host="10.10.9.122", user="a", password="b",
                           canal=32, connector_id="c1", ip="", cam_user="", cam_senha="", nome="",
                           protocolo="", porta=None, porta_http=None, porta_rtsp=None)
    assert visto == {"host": "10.10.9.122", "canal": 32, "porta": 30777}
