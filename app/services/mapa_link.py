"""Coordenada a partir do que chega pelo WhatsApp (Localizar ocorrencia no mapa).

O navegador entende sozinho coordenada solta e link longo do Google Maps
(`?q=lat,lng`, `@lat,lng`). O link curto (`maps.app.goo.gl/...`), que e o que
o app do Google Maps manda ao compartilhar, so revela a coordenada depois de
seguir os redirecionamentos -- isso e feito aqui, no servidor.

So segue enderecos do Google: o parametro vem do usuario, e seguir qualquer
redirecionamento faria do servidor um proxy para a rede interna.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from urllib3.util import parse_url

_HOSTS_GOOGLE = ("goo.gl", "google.com", "google.com.br")
_MAX_SALTOS = 6
_MAX_CORPO = 600_000

# Ordem importa: !3d!4d e o pino do lugar; @lat,lng e so o centro da tela.
_PADROES = (
    re.compile(r"!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)"),
    re.compile(r"[?&](?:q|query|ll|destination|center)=(-?\d{1,2}\.\d+)(?:,|%2C)\s*(?:\+)?(-?\d{1,3}\.\d+)"),
    re.compile(r"/place/(-?\d{1,2}\.\d+),\+?(-?\d{1,3}\.\d+)"),
    re.compile(r"/search/(-?\d{1,2}\.\d+),\+?(-?\d{1,3}\.\d+)"),
    re.compile(r"@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)"),
)


def url_do_google(url: str) -> Optional[str]:
    r"""Endereco refeito so com host do Google + caminho + consulta, ou None.

    Nunca se usa o texto original na conexao: urlparse e o urllib3 discordam
    sobre `\` e `@` (`http://127.0.0.1:8000\@goo.gl/` passa no urlparse como
    goo.gl e conecta em 127.0.0.1:8000). Por isso: recusa `\`, `@`, credencial
    e porta fora de 80/443, confere o host nos dois parsers e remonta a URL.
    """
    url = (url or "").strip()
    if not url or "\\" in url or any(ord(c) < 33 for c in url):
        return None
    try:
        p = urlparse(url)
        u = parse_url(url)
        porta = p.port
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or "@" in p.netloc or p.username or p.password:
        return None
    if porta not in (None, 80, 443) or u.port not in (None, 80, 443):
        return None
    h = (p.hostname or "").lower().rstrip(".")
    if h != (u.host or "").lower().rstrip("."):
        return None
    if not any(h == d or h.endswith("." + d) for d in _HOSTS_GOOGLE):
        return None
    return f"https://{h}{p.path or '/'}" + (f"?{p.query}" if p.query else "")


def host_do_google(url: str) -> bool:
    return url_do_google(url) is not None


def coordenada_no_texto(texto: str) -> Optional[tuple[float, float]]:
    t = unquote(texto or "")
    for padrao in _PADROES:
        m = padrao.search(t)
        if not m:
            continue
        lat, lng = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0.0, 0.0):
            return lat, lng
    return None


def resolver_link(url: str, sessao=None, timeout: float = 8.0) -> dict:
    """Segue o link do Google ate achar a coordenada.

    Devolve {"ok": True, "lat", "lng", "url_final"} ou {"ok": False, "erro"}.
    """
    url = url_do_google(url)
    if not url:
        return {"ok": False, "erro": "So links do Google Maps."}
    direto = coordenada_no_texto(url)
    if direto:
        return {"ok": True, "lat": direto[0], "lng": direto[1], "url_final": url}

    s = sessao or requests.Session()
    atual = url
    try:
        for _ in range(_MAX_SALTOS):
            r = s.get(atual, allow_redirects=False, timeout=timeout,
                      headers={"User-Agent": "Mozilla/5.0 SightOps"}, stream=True)
            destino = r.headers.get("Location")
            if r.status_code in (301, 302, 303, 307, 308) and destino:
                r.close()
                atual = url_do_google(urljoin(atual, destino))
                if not atual:
                    return {"ok": False, "erro": "O link levou para fora do Google."}
                achou = coordenada_no_texto(atual)
                if achou:
                    return {"ok": True, "lat": achou[0], "lng": achou[1], "url_final": atual}
                continue
            # Sem mais redirecionamento: a pagina as vezes traz a coordenada no corpo.
            corpo = r.raw.read(_MAX_CORPO, decode_content=True) if r.status_code == 200 else b""
            r.close()
            achou = coordenada_no_texto(corpo.decode("utf-8", "ignore"))
            if achou:
                return {"ok": True, "lat": achou[0], "lng": achou[1], "url_final": atual}
            return {"ok": False, "erro": "O link abriu, mas nao trouxe coordenada. Peca a localizacao fixada (pino) no WhatsApp."}
    except requests.RequestException as e:
        return {"ok": False, "erro": f"Nao consegui abrir o link: {e.__class__.__name__}"}
    return {"ok": False, "erro": "Redirecionamentos demais."}
