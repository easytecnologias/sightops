"""Gera icone e abertura do APK com a sigla e a cor do cliente (provisorio ate
ter o logo). Desenha em HTML e fotografa com o Playwright.

    CLIENTE=mega python scripts/gerar-icones.py
"""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
CFG = json.loads((RAIZ / "clientes" / os.environ.get("CLIENTE", "sightops") / "cliente.json").read_text(encoding="utf-8"))
RES = RAIZ / "android" / "app" / "src" / "main" / "res"
COR, SIGLA = CFG["marca"]["cor"], CFG["marca"]["sigla"]
DENS = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def letras(tam, cor="#fff"):
    return f'<div style="font:800 {tam}px Arial,sans-serif;color:{cor};letter-spacing:-.02em">{SIGLA}</div>'


def pagina(w, h, corpo):
    return f'<html><body style="margin:0;width:{w}px;height:{h}px;display:grid;place-items:center;overflow:hidden;background:transparent">{corpo}</body></html>'


def foto(pg, caminho, w, h, html):
    pg.set_viewport_size({"width": w, "height": h})
    pg.set_content(html)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(caminho), omit_background=True, clip={"x": 0, "y": 0, "width": w, "height": h})


with sync_playwright() as p:
    nav = p.chromium.launch()
    pg = nav.new_page()
    for nome, d in DENS.items():
        lado = round(48 * d)
        for arq, raio in (("ic_launcher.png", f"{lado * 0.22}px"), ("ic_launcher_round.png", "50%")):
            foto(pg, RES / f"mipmap-{nome}" / arq, lado, lado, pagina(lado, lado,
                 f'<div style="width:{lado}px;height:{lado}px;border-radius:{raio};background:{COR};display:grid;place-items:center">{letras(round(lado * .4))}</div>'))
        fg = round(108 * d)
        foto(pg, RES / f"mipmap-{nome}" / "ic_launcher_foreground.png", fg, fg, pagina(fg, fg, letras(round(fg * .3))))
        em = round(120 * d)
        foto(pg, RES / f"drawable-{nome}" / "abertura_emblema.png", em, em, pagina(em, em, letras(round(em * .4))))
    nav.close()
print("icones gerados:", CFG["appName"])
