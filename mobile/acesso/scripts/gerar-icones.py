"""Gera o icone e a abertura do APK do SightOps Acesso a partir do desenho
aprovado (canvas "SightOps Rua", artboard "A · Icone do app"): a lente branca
com o ponto verde de "no ar" sobre o fundo escuro do cabecalho.

Desenha em HTML e fotografa com o Playwright. As imagens ficam versionadas em
android/app/src/main/res: o build do APK so usa, nao precisa do Playwright.

    python scripts/gerar-icones.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

RES = Path(__file__).resolve().parent.parent / "android" / "app" / "src" / "main" / "res"
ESCURO = "#13252d"
LENTE = ('<svg viewBox="0 0 100 100" style="width:100%;height:100%;display:block">'
         '<circle cx="50" cy="52" r="24" fill="none" stroke="#fff" stroke-width="7"/>'
         '<circle cx="50" cy="52" r="9" fill="#3fd09a"/>'
         '<path d="M70 19a36 36 0 0 1 13 15" fill="none" stroke="#3fd09a" stroke-width="6" stroke-linecap="round"/></svg>')

DENS = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}


def pagina(w, h, corpo, fundo="transparent"):
    return (f'<html><body style="margin:0;width:{w}px;height:{h}px;background:{fundo};display:grid;'
            f'place-items:center;overflow:hidden">{corpo}</body></html>')


def foto(pg, caminho: Path, w: int, h: int, html: str):
    pg.set_viewport_size({"width": w, "height": h})
    pg.set_content(html)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(caminho), omit_background=True, clip={"x": 0, "y": 0, "width": w, "height": h})


with sync_playwright() as p:
    nav = p.chromium.launch()
    pg = nav.new_page()
    for nome, d in DENS.items():
        lado = round(48 * d)
        quadrado = (f'<div style="width:{lado}px;height:{lado}px;border-radius:{lado * 0.22}px;background:{ESCURO};'
                    f'display:grid;place-items:center"><div style="width:86%;height:86%">{LENTE}</div></div>')
        redondo = (f'<div style="width:{lado}px;height:{lado}px;border-radius:50%;background:{ESCURO};'
                   f'display:grid;place-items:center"><div style="width:80%;height:80%">{LENTE}</div></div>')
        foto(pg, RES / f"mipmap-{nome}" / "ic_launcher.png", lado, lado, pagina(lado, lado, quadrado))
        foto(pg, RES / f"mipmap-{nome}" / "ic_launcher_round.png", lado, lado, pagina(lado, lado, redondo))
        # Adaptativo: 108 dp, com a arte dentro da zona segura de 66 dp.
        fg = round(108 * d)
        foto(pg, RES / f"mipmap-{nome}" / "ic_launcher_foreground.png", fg, fg,
             pagina(fg, fg, f'<div style="width:{round(fg * 0.56)}px;height:{round(fg * 0.56)}px">{LENTE}</div>'))
        emb = round(96 * d)
        foto(pg, RES / f"drawable-{nome}" / "abertura_emblema.png", emb, emb,
             pagina(emb, emb, f'<div style="width:{emb}px;height:{emb}px">{LENTE}</div>'))
    for arq in sorted(RES.glob("drawable*/splash.png")):
        from PIL import Image
        w, h = Image.open(arq).size
        lado = round(min(w, h) * 0.28)
        foto(pg, arq, w, h, pagina(w, h, f'<div style="width:{lado}px;height:{lado}px">{LENTE}</div>', ESCURO))
    nav.close()
print("icones gerados em", RES)
