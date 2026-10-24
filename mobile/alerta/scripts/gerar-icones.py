"""Gera o icone e a tela de abertura do APK de um cliente, no desenho aprovado
(mockup "RADS Alerta - app", 24/10/2026): o botao do app em miniatura (disco
branco com anel na cor de destaque e miolo na cor da marca, escudo branco) e,
na abertura, o emblema + o logo do cliente sobre a cor da marca.

Desenha em HTML e fotografa com o Playwright em cada tamanho do Android. As
imagens ficam em clientes/<cliente>/android-res/ (versionadas): o build do APK
so copia, nao precisa do Playwright.

    python scripts/gerar-icones.py rads
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
cliente = sys.argv[1] if len(sys.argv) > 1 else "rads"
pasta = RAIZ / "clientes" / cliente
cfg = json.loads((pasta / "cliente.json").read_text(encoding="utf-8"))
m = cfg["marca"]
saida = pasta / "android-res"
logo = (pasta / "logo-branco.svg").read_text(encoding="utf-8")
LOGO_FLUIDO = logo.replace("<svg ", '<svg style="width:100%;height:auto;display:block" ', 1)

ESCUDO = ('<svg viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.3" stroke-linecap="round" '
          'stroke-linejoin="round" style="width:58%;height:58%"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
          '<path d="M12 8v5"/><path d="M12 16h.01"/></svg>')


def emblema(diametro: float) -> str:
    """Disco branco + anel de destaque + miolo da marca + escudo (o botao do app)."""
    anel = diametro * 0.055
    miolo = diametro * 0.76
    return (f'<div style="width:{diametro}px;height:{diametro}px;border-radius:50%;background:#fff;display:grid;'
            f'place-items:center;box-shadow:0 0 0 {anel}px {m["destaque"]}">'
            f'<div style="width:{miolo}px;height:{miolo}px;border-radius:50%;background:{m["cor"]};display:grid;'
            f'place-items:center">{ESCUDO}</div></div>')


def pagina(corpo: str, w: int, h: int, fundo: str) -> str:
    return (f'<html><body style="margin:0;width:{w}px;height:{h}px;background:{fundo};display:grid;place-items:center;'
            f'overflow:hidden">{corpo}</body></html>')


def foto(pg, html: str, w: int, h: int, destino: Path, transparente: bool = False):
    destino.parent.mkdir(parents=True, exist_ok=True)
    pg.set_viewport_size({"width": w, "height": h})
    pg.set_content(html)
    pg.screenshot(path=str(destino), omit_background=transparente, clip={"x": 0, "y": 0, "width": w, "height": h})


DENS = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
SPLASH_PORT = {"mdpi": (320, 480), "hdpi": (480, 800), "xhdpi": (720, 1280), "xxhdpi": (960, 1600), "xxxhdpi": (1280, 1920)}

with sync_playwright() as p:
    nav = p.chromium.launch()
    pg = nav.new_page()
    for nome, k in DENS.items():
        # Icone adaptativo (Android 8+): fundo = cor da marca (colors.xml), frente =
        # so o emblema, dentro da area segura (66 de 108 dp).
        lado = round(108 * k)
        foto(pg, pagina(emblema(lado * 0.5), lado, lado, "transparent"), lado, lado,
             saida / f"mipmap-{nome}" / "ic_launcher_foreground.png", transparente=True)
        # Icone antigo (Android 7 e menos): quadrado arredondado e redondo.
        lado = round(48 * k)
        quadrado = (f'<div style="width:{lado}px;height:{lado}px;border-radius:{lado * 0.22}px;background:{m["cor"]};'
                    f'display:grid;place-items:center">{emblema(lado * 0.62)}</div>')
        foto(pg, pagina(quadrado, lado, lado, "transparent"), lado, lado, saida / f"mipmap-{nome}" / "ic_launcher.png", True)
        redondo = quadrado.replace(f"border-radius:{lado * 0.22}px", "border-radius:50%")
        foto(pg, pagina(redondo, lado, lado, "transparent"), lado, lado, saida / f"mipmap-{nome}" / "ic_launcher_round.png", True)
        # Abertura: emblema + logo + slogan sobre a cor da marca (retrato e paisagem).
        for orient, (w, h) in (("port", SPLASH_PORT[nome]), ("land", SPLASH_PORT[nome][::-1])):
            base = min(w, h)
            corpo = (f'<div style="display:flex;flex-direction:column;align-items:center;gap:{base * 0.07}px">'
                     f'{emblema(base * 0.3)}'
                     f'<div style="width:{base * 0.55}px">{LOGO_FLUIDO}</div>'
                     f'</div>')
            foto(pg, pagina(corpo, w, h, m["cor"]), w, h, saida / f"drawable-{orient}-{nome}" / "splash.png")
    w, h = SPLASH_PORT["mdpi"][::-1]
    corpo = f'<div style="display:flex;flex-direction:column;align-items:center;gap:22px">{emblema(96)}</div>'
    foto(pg, pagina(corpo, w, h, m["cor"]), w, h, saida / "drawable" / "splash.png")
    # Icone grande (loja / pagina de download).
    quadrado = (f'<div style="width:512px;height:512px;border-radius:112px;background:{m["cor"]};display:grid;'
                f'place-items:center">{emblema(318)}</div>')
    foto(pg, pagina(quadrado, 512, 512, "transparent"), 512, 512, pasta / "icone-512.png", True)
    nav.close()

print("ok:", sorted(str(x.relative_to(pasta)) for x in saida.rglob("*.png"))[:4], "...")
