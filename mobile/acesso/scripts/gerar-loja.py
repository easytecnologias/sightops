"""Gera as imagens da ficha do SightOps Acesso no Google Play:
icone 512x512 e imagem de destaque 1024x500, no mesmo desenho do icone do app
(lente branca com o ponto verde sobre o fundo escuro).

    python scripts/gerar-loja.py      -> loja/icone-512.png, loja/destaque-1024x500.png
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

SAIDA = Path(__file__).resolve().parent.parent / "loja"
ESCURO = "#13252d"
VERDE = "#3fd09a"
LENTE = ('<svg viewBox="0 0 100 100" style="width:100%;height:100%;display:block">'
         '<circle cx="50" cy="52" r="24" fill="none" stroke="#fff" stroke-width="7"/>'
         f'<circle cx="50" cy="52" r="9" fill="{VERDE}"/>'
         f'<path d="M70 19a36 36 0 0 1 13 15" fill="none" stroke="{VERDE}" stroke-width="6" stroke-linecap="round"/></svg>')
FONTE = "font-family:'Segoe UI',Roboto,Arial,sans-serif"

ICONE = (f'<html><body style="margin:0;width:512px;height:512px;background:{ESCURO};display:grid;place-items:center">'
         f'<div style="width:340px;height:340px">{LENTE}</div></body></html>')

DESTAQUE = f'''<html><body style="margin:0;width:1024px;height:500px;background:{ESCURO};{FONTE};
  display:flex;align-items:center;gap:56px;padding:0 88px;box-sizing:border-box;color:#fff">
  <div style="width:230px;height:230px;flex:none">{LENTE}</div>
  <div>
    <div style="font-size:64px;font-weight:700;line-height:1.05">SightOps Acesso</div>
    <div style="font-size:30px;color:#cfe0e6;margin-top:18px;line-height:1.3">
      Cadastro de pessoas, visitantes<br>e portas na palma da mão</div>
    <div style="margin-top:26px;display:inline-block;background:{VERDE};color:{ESCURO};
      font-size:22px;font-weight:700;padding:6px 18px;border-radius:99px">Easy Tecnologia</div>
  </div>
</body></html>'''


def foto(pg, nome: str, w: int, h: int, html: str):
    pg.set_viewport_size({"width": w, "height": h})
    pg.set_content(html)
    SAIDA.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(SAIDA / nome), clip={"x": 0, "y": 0, "width": w, "height": h})


with sync_playwright() as p:
    nav = p.chromium.launch()
    pg = nav.new_page()
    foto(pg, "icone-512.png", 512, 512, ICONE)
    foto(pg, "destaque-1024x500.png", 1024, 500, DESTAQUE)
    nav.close()
print("imagens em", SAIDA)
