import io

from app.services.mapa_link import coordenada_no_texto, host_do_google, resolver_link


class _Resp:
    def __init__(self, status, location=None, corpo=b""):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.raw = io.BytesIO(corpo)
        self.raw.read = (lambda f: (lambda n, decode_content=True: f(n)))(self.raw.read)

    def close(self):
        pass


class _Sessao:
    def __init__(self, respostas):
        self.respostas = respostas
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        return self.respostas[url]


def test_formatos_de_link_longo():
    assert coordenada_no_texto("https://maps.google.com/?q=-9.731420,-36.638560") == (-9.73142, -36.63856)
    assert coordenada_no_texto("https://www.google.com/maps/@-9.7314,-36.6385,17z") == (-9.7314, -36.6385)
    # pino do lugar vence o centro da tela
    assert coordenada_no_texto(
        "https://www.google.com/maps/place/X/@-9.70,-36.60,17z/data=!3m1!4b1!4m6!3m5!8m2!3d-9.7315!4d-36.6385"
    ) == (-9.7315, -36.6385)
    assert coordenada_no_texto("https://www.google.com/maps/search/-9.7315,+-36.6385") == (-9.7315, -36.6385)
    assert coordenada_no_texto("sem coordenada") is None


def test_so_segue_google():
    assert host_do_google("https://maps.app.goo.gl/x7Hq2")
    assert host_do_google("https://www.google.com.br/maps")
    assert not host_do_google("http://10.0.0.1/")
    assert not host_do_google("https://google.com.evil.io/")
    assert not host_do_google("https://maps.google.com:8080/")
    assert resolver_link("http://127.0.0.1:8000/api")["ok"] is False


def test_link_curto_segue_ate_a_coordenada():
    s = _Sessao({
        "https://maps.app.goo.gl/x7Hq2": _Resp(302, "https://maps.google.com/maps?q=-9.7315,-36.6385&ftid=1"),
    })
    r = resolver_link("https://maps.app.goo.gl/x7Hq2", sessao=s)
    assert r["ok"] and (r["lat"], r["lng"]) == (-9.7315, -36.6385)


def test_redirecionamento_para_fora_do_google_para():
    s = _Sessao({"https://maps.app.goo.gl/mal": _Resp(302, "http://192.168.0.1/admin")})
    r = resolver_link("https://maps.app.goo.gl/mal", sessao=s)
    assert r["ok"] is False and s.urls == ["https://maps.app.goo.gl/mal"]


def test_coordenada_no_corpo_da_pagina():
    s = _Sessao({
        "https://maps.app.goo.gl/c": _Resp(302, "https://www.google.com/maps/place/Praca"),
        "https://www.google.com/maps/place/Praca": _Resp(200, corpo=b'...[null,null,-9.7315,-36.6385]...@-9.7315,-36.6385,17z'),
    })
    r = resolver_link("https://maps.app.goo.gl/c", sessao=s)
    assert r["ok"] and r["lat"] == -9.7315


def test_barra_invertida_e_arroba_nao_enganam():
    # urlparse ve goo.gl, mas requests conectaria em 127.0.0.1:8000
    for u in (r"http://127.0.0.1:8000\@goo.gl:80/", r"https://127.0.0.1\@maps.google.com/x",
              "https://user@maps.google.com/", "https://10.0.0.1@goo.gl/x", "https://lh3.googleusercontent.com/x"):
        assert not host_do_google(u), u
        assert resolver_link(u)["ok"] is False


def test_redirecionamento_com_barra_invertida_para():
    s = _Sessao({"https://maps.app.goo.gl/b": _Resp(302, r"http://127.0.0.1:8000\@www.google.com/maps")})
    r = resolver_link("https://maps.app.goo.gl/b", sessao=s)
    assert r["ok"] is False and len(s.urls) == 1


def test_conecta_sempre_no_endereco_refeito():
    s = _Sessao({"https://maps.app.goo.gl/x?a=1": _Resp(302, "https://maps.google.com/?q=-9.7,-36.6")})
    assert resolver_link("http://MAPS.APP.GOO.GL:80/x?a=1", sessao=s)["ok"]
    assert s.urls == ["https://maps.app.goo.gl/x?a=1"]
