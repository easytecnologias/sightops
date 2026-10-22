"""Relatorio do Mapa em PDF: onde estao as cameras e como elas estao.

Feito para apresentar em reuniao. Pagina 1 e o mapa inteiro com um pino por
camera, colorido pelo status; depois um mapa ampliado por area (quadra/local),
com a tabela daquela area; a infraestrutura (caixas de CFTV, materiais, CTOs,
linhas do KMZ) e uma pagina por caixa com as portas; a galeria de fotos; e as
pendencias -- ponto do mapa sem camera, camera sem posicao, camera fora do ar,
camera sem cabo, cabo acima do limite, caixa vazia ou com nome repetido.

Posicao de cada camera: a do Mapa (camadas KMZ do cliente, casando pelo NOME,
como a tela do Mapa faz). Detalhes em recorder_pdf_report._coordenadas_do_mapa.

O fundo e o OpenStreetMap, montado aqui no servidor a partir dos tiles. Os
tiles sao publicos (nao carregam dado de cliente), por isso o cache em disco e
compartilhado entre clientes; a politica de uso do OSM pede User-Agent proprio
e cache, e e o que este modulo faz.
"""
from __future__ import annotations

import json
import math
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    Image as RLImage,
    LongTable,
    PageBreak,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.paths import OUTPUT_DIR
from app.services.pdf_inventory_report import _camera_online, _pick_image_path, _recorder_recording_text, _to_text
from app.services.recorder_pdf_report import (
    BAD,
    BORDER,
    INK,
    MUTED,
    OK,
    PROPORCAO_FOTO,
    STRIPE,
    _accent,
    _coordenadas,
    _foto_padronizada,
    _header_footer_factory,
    _kpis,
    _p,
    _p_localizacao,
    _styles,
)

ProgressCb = Optional[Callable[[int, int, str], None]]

# --------------------------------------------------------------------- cores
COR_ONLINE = "#16a34a"
COR_OFFLINE = "#dc2626"
COR_SEM_STATUS = "#64748b"
COR_OUTROS = "#d97706"   # ponto do mapa sem camera (mesmo laranja da legenda "outros" do Mapa)
COR_CAIXA = "#92400e"    # caixa de CFTV (quadrado, como o pino do Mapa)
COR_CTO = "#7c3aed"      # CTO (losango)
COR_LINHA = "#0e7490"    # linhas do KMZ (fibra/rota)
# cabos: mesmas cores e nomes do Mapa (frontend/js/mapaCaixas.js CX_CABOS)
CABOS = {
    "utp5e": ("UTP Cat5e", "#1971c2", False, 100), "utp6": ("UTP Cat6", "#1864ab", False, 100),
    "drop": ("Fibra drop", "#0ea5e9", True, None), "coaxial": ("Coaxial", "#7950f2", False, None),
    "outro": ("Outro", "#64748b", False, None),
}
TIPOS_CAIXA = {"switch": "Com switch", "onu": "Direto na ONU", "passagem": "So passagem / fonte"}
ITENS_CAIXA = {"switch_poe": "Switch PoE", "switch": "Switch", "onu": "ONU", "fonte": "Fonte", "nobreak": "Nobreak",
               "dio": "DIO", "roteador": "Roteador", "injetor_poe": "Injetor PoE", "outro": "Outro"}
ALIMENTACAO = {"fonte12": "Fonte 12V", "injetor_poe": "Injetor PoE", "poe_switch": "PoE do switch", "outro": "Outra"}

# --------------------------------------------------------------------- tiles
TILE = 256
_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_USER_AGENT = "SightOps/3 (relatorio do mapa; suporte@easytecnologias.com.br)"
_ZOOM_MAX = 19
_FUNDO_SEM_TILE = (229, 227, 223)
ATRIBUICAO = "(c) OpenStreetMap contributors"


def _cache_tiles() -> Path:
    p = OUTPUT_DIR / "tile_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _px(lat: float, lon: float, z: int) -> Tuple[float, float]:
    """Coordenada -> pixel no mapa-mundi do zoom z (projecao Web Mercator)."""
    n = (2 ** z) * TILE
    s = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
    return (lon + 180.0) / 360.0 * n, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n


def _tile(z: int, x: int, y: int, sessao: requests.Session) -> Optional[Image.Image]:
    n = 2 ** z
    if y < 0 or y >= n:
        return None
    x %= n
    arq = _cache_tiles() / str(z) / str(x) / f"{y}.png"
    if arq.exists() and arq.stat().st_size > 0:
        try:
            with Image.open(arq) as im:
                return im.convert("RGB")
        except Exception:
            pass
    try:
        r = sessao.get(_TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": _USER_AGENT}, timeout=12)
        if r.status_code != 200 or not r.content:
            return None
        im = Image.open(BytesIO(r.content)).convert("RGB")
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(r.content)
        tmp.replace(arq)
        return im
    except Exception:
        return None


def _fonte(tamanho: int) -> ImageFont.ImageFont:
    """Vera Bold, que vem com o ReportLab: a imagem nao depende de fonte do sistema."""
    import reportlab
    try:
        return ImageFont.truetype(os.path.join(os.path.dirname(reportlab.__file__), "fonts", "VeraBd.ttf"), tamanho)
    except Exception:
        return ImageFont.load_default()


def renderizar_mapa(pontos: List[tuple], largura: int, altura: int,
                    margem: int = 70, zoom_max: int = _ZOOM_MAX, raio: int = 17,
                    linhas: Optional[List[tuple]] = None) -> Optional[Image.Image]:
    """Imagem do mapa com um pino por ponto: [(lat, lon, rotulo, cor_hex[, forma])].

    forma: "circulo" (camera, padrao), "quadrado" (caixa de CFTV) ou "losango"
    (CTO). linhas: [([(lat, lon), ...], cor_hex, largura_px, tracejado)] --
    cabos e fibra, desenhados por baixo dos pinos.

    Escolhe o maior zoom em que todos os pontos (e as linhas) cabem dentro da
    margem. Tile que nao baixar vira fundo liso -- o mapa sai sem o desenho
    daquele pedaco, mas os pinos (que sao o que importa) continuam no lugar certo.
    """
    pts = [(p[0], p[1], p[2], p[3], p[4] if len(p) > 4 else "circulo") for p in pontos
           if p[0] is not None and p[1] is not None]
    if not pts:
        return None
    trechos = [(list(c), cor, larg, trac) for c, cor, larg, trac in (linhas or []) if c and len(c) >= 2]
    todos = [(p[0], p[1]) for p in pts] + [xy for t in trechos for xy in t[0]]
    z = zoom_max
    for z in range(zoom_max, 0, -1):
        xs, ys = zip(*(_px(la, lo, z) for la, lo in todos))
        if max(xs) - min(xs) <= largura - 2 * margem and max(ys) - min(ys) <= altura - 2 * margem:
            break
    xs, ys = zip(*(_px(la, lo, z) for la, lo in todos))
    ox = (max(xs) + min(xs)) / 2 - largura / 2
    oy = (max(ys) + min(ys)) / 2 - altura / 2

    tiles = [(tx, ty) for tx in range(int(ox // TILE), int((ox + largura) // TILE) + 1)
             for ty in range(int(oy // TILE), int((oy + altura) // TILE) + 1)]
    sessao = requests.Session()
    with ThreadPoolExecutor(max_workers=4) as pool:
        imagens = list(pool.map(lambda t: _tile(z, t[0], t[1], sessao), tiles))
    mapa = Image.new("RGB", (largura, altura), _FUNDO_SEM_TILE)
    for (tx, ty), im in zip(tiles, imagens):
        if im is not None:
            mapa.paste(im, (int(tx * TILE - ox), int(ty * TILE - oy)))

    d = ImageDraw.Draw(mapa)
    for coords, cor, larg, trac in trechos:
        pix = [(_px(la, lo, z)[0] - ox, _px(la, lo, z)[1] - oy) for la, lo in coords]
        if trac:
            _linha_tracejada(d, pix, cor, larg)
        else:
            d.line(pix, fill=cor, width=larg, joint="curve")
    fonte = _fonte(int(raio * 0.95))
    # offline por ultimo: em cima dos outros, que e o que precisa aparecer
    ordem = sorted(pts, key=lambda p: (p[3] == COR_OFFLINE, p[3] == COR_OUTROS))
    reais = [(_px(p[0], p[1], z)[0] - ox, _px(p[0], p[1], z)[1] - oy) for p in ordem]
    desenho = _afastar(reais, 2 * raio + 6, largura, altura, raio + 4)
    # Pino que saiu do lugar ganha uma linha ate a posicao real: cameras a poucos
    # metros (entrada, portaria) ficavam uma em cima da outra mesmo no zoom maximo.
    for (rx, ry), (x, y) in zip(reais, desenho):
        if math.hypot(x - rx, y - ry) > 3:
            d.line((rx, ry, x, y), fill=(40, 40, 40), width=3)
            d.ellipse((rx - 4, ry - 4, rx + 4, ry + 4), fill=(40, 40, 40))
    for (_, _, rot, cor, forma), (x, y) in zip(ordem, desenho):
        if forma == "quadrado":
            d.rounded_rectangle((x - raio - 3, y - raio - 3, x + raio + 3, y + raio + 3), radius=6, fill="white")
            d.rounded_rectangle((x - raio, y - raio, x + raio, y + raio), radius=4, fill=cor)
        elif forma == "losango":
            r = raio + 4
            d.polygon([(x, y - r - 3), (x + r + 3, y), (x, y + r + 3), (x - r - 3, y)], fill="white")
            d.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=cor)
        else:
            d.ellipse((x - raio - 3, y - raio - 3, x + raio + 3, y + raio + 3), fill="white")
            d.ellipse((x - raio, y - raio, x + raio, y + raio), fill=cor)
        if rot:
            d.text((x, y), str(rot)[:3], fill="white", font=fonte, anchor="mm")
    fa = _fonte(14)
    w = d.textlength(ATRIBUICAO, font=fa)
    d.rectangle((largura - w - 14, altura - 24, largura, altura), fill=(255, 255, 255))
    d.text((largura - w - 7, altura - 12), ATRIBUICAO, fill=(70, 70, 70), font=fa, anchor="lm")
    return mapa


def _linha_tracejada(d: ImageDraw.ImageDraw, pix: List[Tuple[float, float]], cor: str, larg: int,
                     traco: float = 16, vao: float = 10) -> None:
    for (x1, y1), (x2, y2) in zip(pix, pix[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        t = 0.0
        while t < seg:
            t2 = min(t + traco, seg)
            d.line((x1 + (x2 - x1) * t / seg, y1 + (y2 - y1) * t / seg,
                    x1 + (x2 - x1) * t2 / seg, y1 + (y2 - y1) * t2 / seg), fill=cor, width=larg)
            t += traco + vao


def _afastar(pontos: List[Tuple[float, float]], minimo: float, largura: int, altura: int,
             borda: float) -> List[Tuple[float, float]]:
    """Empurra os pinos que se sobrepoem ate ficarem a `minimo` px um do outro.

    Relaxacao simples aos pares: cada par proximo demais se afasta pela reta que
    os une. Pinos no mesmo pixel saem em leque. Ninguem sai da imagem.
    """
    pos = [list(p) for p in pontos]
    n = len(pos)
    for _ in range(80):
        mexeu = False
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = pos[j][0] - pos[i][0], pos[j][1] - pos[i][1]
                dist = math.hypot(dx, dy)
                if dist >= minimo:
                    continue
                if dist < 1e-3:
                    ang = 2 * math.pi * j / max(n, 1)
                    dx, dy, dist = math.cos(ang), math.sin(ang), 1.0
                passo = (minimo - dist) / 2 + 0.5
                ux, uy = dx / dist, dy / dist
                pos[i][0] -= ux * passo
                pos[i][1] -= uy * passo
                pos[j][0] += ux * passo
                pos[j][1] += uy * passo
                mexeu = True
        for p in pos:
            p[0] = min(max(p[0], borda), largura - borda)
            p[1] = min(max(p[1], borda), altura - borda)
        if not mexeu:
            break
    return [(p[0], p[1]) for p in pos]


def _imagem_pdf(mapa: Image.Image, largura_pt: float) -> RLImage:
    buf = BytesIO()
    mapa.save(buf, "JPEG", quality=82, optimize=True)
    buf.seek(0)
    return RLImage(buf, width=largura_pt, height=largura_pt * mapa.height / mapa.width)


# --------------------------------------------------------------------- dados
def _numero(titulo: str) -> str:
    m = re.match(r"\s*(\d+)", titulo or "")
    return m.group(1) if m else ""


def _chave_area(titulo: str) -> str:
    """"13 - P. LDD - 01" -> "P. LDD": tira o numero da camera e o sufixo de sequencia."""
    t = re.sub(r"^\s*\d+\s*-\s*", "", titulo or "")
    t = re.sub(r"\s*-\s*\d+\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip().upper() or "SEM NOME"


def _metros(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def agrupar_areas(cams: List[Dict[str, Any]], juntar_ate_m: float = 60) -> List[Dict[str, Any]]:
    """Areas do relatorio: cameras com o mesmo nome-base ("QD. S", "P. LDD").

    Grupo de 1 ou 2 cameras ("PORTARIA") vira uma pagina quase vazia; ele e
    juntado ao grupo que tiver uma camera a ate `juntar_ate_m` metros de alguma
    das dele. A distancia e camera a camera, nao entre centros: pelo centro, as
    juncoes encadeavam e a entrada da SIERRA acabou na mesma area do muro da
    quadra E, a centenas de metros -- o mapa ampliado perdia o sentido.
    """
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for c in cams:
        if c.get("_pos"):
            grupos.setdefault(_chave_area(c.get("titulo") or ""), []).append(c)
    areas = [{"chaves": [k], "cams": v} for k, v in grupos.items()]
    for pequena in sorted([a for a in areas if len(a["cams"]) <= 2], key=lambda a: len(a["cams"])):
        if pequena not in areas:
            continue
        outras = [a for a in areas if a is not pequena]
        if not outras:
            break
        def _perto(a: Dict[str, Any]) -> float:
            return min(_metros(c["_pos"], o["_pos"]) for c in pequena["cams"] for o in a["cams"])

        alvo = min(outras, key=_perto)
        if _perto(alvo) <= juntar_ate_m:
            alvo["cams"] += pequena["cams"]
            alvo["chaves"] += pequena["chaves"]
            areas.remove(pequena)

    def _ord(c):
        n = _numero(c.get("titulo") or "")
        return (int(n) if n else 10 ** 6, c.get("titulo") or "")

    for a in areas:
        a["cams"].sort(key=_ord)
        # nome pelo grupo maior primeiro: "QD. S / PORTARIA", nao o contrario
        tam = {k: sum(1 for c in a["cams"] if _chave_area(c.get("titulo") or "") == k) for k in a["chaves"]}
        chaves = sorted(dict.fromkeys(a["chaves"]), key=lambda k: -tam[k])
        a["nome"] = " / ".join(chaves[:3]) + (f" (+{len(chaves) - 3})" if len(chaves) > 3 else "")
    areas.sort(key=lambda a: _ord(a["cams"][0]))
    return areas


def _ler_json(caminho: Path) -> List[Dict[str, Any]]:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError):
        return []
    d = d.get("rows", d) if isinstance(d, dict) else d
    return [r for r in d if isinstance(r, dict)] if isinstance(d, list) else []


def _gravacao_por_camera() -> Dict[Tuple[str, str], Dict[str, Any]]:
    """(conector, ip da camera) -> {gravador, canal, gravando}, dos NVR/DVR do cliente atual."""
    from app.core.tenant_context import get_current_tenant_slug, tenant_recorder_inventory_path

    if not get_current_tenant_slug():
        return {}
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for fonte in ("nvr", "dvr"):
        for r in _ler_json(tenant_recorder_inventory_path(fonte)):
            ip = _to_text(r.get("camera_ip"))
            if not ip:
                continue
            conn = _to_text(r.get("remote_connector_id") or r.get("connector_id"))
            info = {"gravador": _to_text(r.get("recorder_name") or r.get("host")),
                    "canal": r.get("channel"), "gravando": _recorder_recording_text(r)}
            out.setdefault((conn, ip), info)
            out.setdefault(("", ip), info)
    return out


def _camadas_do_relatorio(site: str = "") -> List[Dict[str, Any]]:
    """Camadas importadas do Mapa do cliente atual: [{id, label, meta, features}].

    So as que o Mapa mostra a quem pediu (restricao de site da sessao); com
    `site`, so as daquele site (mesma conta de site da camada do Mapa)."""
    from app.core import permissions
    from app.core.tenant_context import get_current_tenant_slug, tenant_kmz_input_dir

    if not get_current_tenant_slug():
        return []
    from app.api.endpoints import tools

    liberadas = None
    if permissions.sites_da_sessao() is not None:
        liberadas = {str(l.get("id") or "") for l in tools._list_kmz_import_layers(include_features=False)}
    indice = tools._indice_sites_inventario() if _to_text(site) else None
    pasta = tenant_kmz_input_dir().parent / "kmz_layers"
    out: List[Dict[str, Any]] = []
    for geo in sorted(pasta.glob("*.geojson")):
        meta_p, kmz_p = pasta / f"{geo.stem}.meta.json", pasta / f"{geo.stem}.kmz"
        if not meta_p.exists() or not kmz_p.exists():
            continue
        if liberadas is not None and geo.stem not in liberadas:
            continue
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8") or "{}")
            dados = json.loads(geo.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            continue
        features = [f for f in (dados.get("features") or []) if isinstance(f, dict)]
        if indice is not None and tools._chave_site(site) not in tools._sites_da_camada(meta, features, indice):
            continue
        out.append({"id": geo.stem, "label": str(meta.get("label") or meta.get("original_name") or geo.stem),
                    "meta": meta, "features": features})
    return out


# Tipo de um ponto do KMZ que nao casou com camera: a mesma leitura do Mapa
# (frontend/js/cameras.js mapFeatureType). So "camera" sem cadastro e pendencia.
_RE_POSTE = re.compile(r"^pt[-\s]?\d+\b|\bpostes?\b|\bpole\b", re.I)
_RE_CAIXA = re.compile(r"caixa\s*herm[eé]tica|caixa\s*cftv|herm[eé]tica|^(cai|cx)(\s*[-_]?\s*\d+)?$", re.I)
_RE_CTO = re.compile(r"\bcto\b|^cto", re.I)
_RE_CDO = re.compile(r"\bcdo\b|^cdo|emenda|splice", re.I)


def _tipo_do_ponto(nome: str) -> str:
    n = _to_text(nome).strip()
    for tipo, rx in (("poste", _RE_POSTE), ("caixa", _RE_CAIXA), ("cto", _RE_CTO), ("cdo", _RE_CDO)):
        if rx.search(n):
            return tipo
    return "camera"


def _perto(a: Optional[tuple], b: Optional[tuple]) -> bool:
    return bool(a and b) and abs(a[0] - b[0]) < 3e-5 and abs(a[1] - b[1]) < 3e-5


def _pos_feature(f: Dict[str, Any]) -> Optional[tuple]:
    g = f.get("geometry") or {}
    if g.get("type") != "Point" or len(g.get("coordinates") or []) < 2:
        return None
    return _coordenadas({"lat": g["coordinates"][1], "lon": g["coordinates"][0]})


def _pontos_caixa(meta: Dict[str, Any], features: List[Dict[str, Any]]) -> List[tuple]:
    """(nome minusculo, posicao) dos pontos que sao caixa cadastrada."""
    out = []
    for cx in (meta.get("caixas") or {}).values():
        if isinstance(cx, dict):
            out.append((_to_text(cx.get("ponto")).strip().lower(), _posicao_da_caixa(cx, meta, features)))
    return out


def _posicao_da_caixa(cx: Dict[str, Any], meta: Dict[str, Any], features: List[Dict[str, Any]]) -> Optional[tuple]:
    """Mesma regra do Mapa (cxPosDaCaixa): a gravada; senao o inicio do primeiro
    cabo dela; senao o ponto com o nome."""
    c = _coordenadas({"lat": cx.get("lat"), "lon": cx.get("lng")}) if cx.get("lat") is not None else None
    if c:
        return c
    for cb in (meta.get("cabos") or {}).values():
        if isinstance(cb, dict) and cb.get("caixa") == cx.get("id") and len(cb.get("caminho") or []) >= 2:
            return _coordenadas({"lat": cb["caminho"][0][0], "lon": cb["caminho"][0][1]})
    nome = _to_text(cx.get("ponto")).strip().lower()
    return next((p for f in features
                 if _to_text((f.get("properties") or {}).get("name")).strip().lower() == nome
                 for p in [_pos_feature(f)] if p), None)


def _pontos_do_mapa(site: str = "", camadas: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Pontos das camadas do Mapa (nome, posicao, tipo, cor dos 'outros'); o
    ponto que e caixa cadastrada sai como tipo "caixa"."""
    out: List[Dict[str, Any]] = []
    for cam in (camadas if camadas is not None else _camadas_do_relatorio(site)):
        meta = cam["meta"]
        cor = str(meta.get("cor_outros") or "") or COR_OUTROS
        motivos = meta.get("motivos") if isinstance(meta.get("motivos"), dict) else {}
        caixas = _pontos_caixa(meta, cam["features"])
        for f in cam["features"]:
            c = _pos_feature(f)
            if not c:
                continue
            nome = _to_text((f.get("properties") or {}).get("name"))
            chave = nome.strip().lower()
            tipo = "caixa" if any(n == chave and _perto(p, c) for n, p in caixas) else _tipo_do_ponto(nome)
            out.append({"nome": nome, "pos": c, "camada": cam["label"], "cor": cor, "tipo": tipo,
                        "motivo": motivos.get(chave) or {}})
    return out


def _rotulo_caixa(nome: str) -> str:
    """"C-CFTV-14" -> "14" (o numero cabe no pino); sem numero, as iniciais."""
    nums = re.findall(r"\d+", nome or "")
    return nums[-1][-3:] if nums else _to_text(nome)[:2].upper()


def _cadastro_da_cto(meta: Dict[str, Any], nome: str, pos) -> Optional[Dict[str, Any]]:
    """Cadastro da CTO (meta.ctos) do ponto: pelo nome E posicao, como no Mapa."""
    doNome = [c for c in (meta.get("ctos") or {}).values()
              if isinstance(c, dict) and _to_text(c.get("ponto")).strip().lower() == nome.strip().lower()]
    for c in doNome:
        if c.get("lat") is not None and pos and abs(float(c["lat"]) - pos[0]) < 3e-5 and abs(float(c["lng"]) - pos[1]) < 3e-5:
            return c
    return doNome[0] if len(doNome) == 1 and doNome[0].get("lat") is None else None


def _onus_do_monitoramento() -> Dict[str, Dict[str, Any]]:
    """entity_key -> ONU do monitoramento (status e sinal) para as portas das CTOs.

    So dos sites do usuario (a mesma regra de /api/monitoring/entities): ONU de
    outro site ligada na CTO sai no PDF so com o nome anotado, sem sinal."""
    try:
        from app.core import permissions
        from app.services.monitoring_service import list_entities
        saida = {}
        for e in permissions.filtrar_por_site(list_entities(entity_type="onu", limit=2000), ("site",)):
            det = e.get("detail_json")
            if isinstance(det, str):
                try:
                    det = json.loads(det)
                except ValueError:
                    det = {}
            saida[_to_text(e.get("entity_key"))] = {**e, "det": det if isinstance(det, dict) else {}}
        return saida
    except Exception:
        return {}


def _infra_do_mapa(camadas: List[Dict[str, Any]], cams: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Caixas de CFTV, cabos, CTOs e linhas das camadas, com a camera de cada
    cabo (do inventario ja filtrado do relatorio: pelo IP, senao pelo nome)."""
    por_ip = {_to_text(c.get("ip")): c for c in cams if _to_text(c.get("ip"))}
    por_nome = {_to_text(c.get("titulo")).strip().lower(): c for c in cams if _to_text(c.get("titulo"))}
    caixas: List[Dict[str, Any]] = []
    ctos: List[Dict[str, Any]] = []
    linhas: List[Dict[str, Any]] = []
    contagem = {"poste": 0, "cdo": 0}
    for cam in camadas:
        meta, features = cam["meta"], cam["features"]
        cabos = [v for v in (meta.get("cabos") or {}).values() if isinstance(v, dict)]
        ctos_da_camada: Dict[str, Dict[str, Any]] = {}
        for f in features:
            nome = _to_text((f.get("properties") or {}).get("name"))
            g = f.get("geometry") or {}
            if g.get("type") == "LineString":
                coords = [(float(x[1]), float(x[0])) for x in g.get("coordinates") or [] if len(x) >= 2]
                if len(coords) >= 2:
                    metros = sum(_metros(a, b) for a, b in zip(coords, coords[1:]))
                    linhas.append({"nome": nome, "coords": coords, "metros": metros, "camada": cam["label"]})
                continue
            pos = _pos_feature(f)
            tipo = _tipo_do_ponto(nome) if pos else ""
            if tipo == "cto":
                cto = {"nome": nome, "pos": pos, "camada": cam["label"], "caixas": [],
                       "cad": _cadastro_da_cto(meta, nome, pos)}
                ctos.append(cto)
                ctos_da_camada.setdefault(nome.strip().lower(), cto)
            elif tipo in contagem:
                contagem[tipo] += 1
        for cx in (meta.get("caixas") or {}).values():
            if not isinstance(cx, dict):
                continue
            tipo = cx.get("tipo") if cx.get("tipo") in TIPOS_CAIXA else "switch"
            ligacoes = []
            for cb in sorted((c for c in cabos if c.get("caixa") == cx.get("id") and not c.get("cto")),
                             key=lambda c: (int(c.get("porta") or 999), _to_text((c.get("camera") or {}).get("ponto")))):
                destino = cb.get("camera") or {}
                camera = por_ip.get(_to_text(destino.get("ip"))) or por_nome.get(_to_text(destino.get("ponto")).strip().lower())
                ligacoes.append({**cb, "_cam": camera})
            cto_cabo = next((c for c in cabos if c.get("caixa") == cx.get("id") and c.get("cto")), None)
            item = {"cx": cx, "nome": _to_text(cx.get("nome") or cx.get("ponto")) or "Caixa", "tipo": tipo,
                    "pos": _posicao_da_caixa(cx, meta, features), "camada": cam["label"],
                    "cabos": ligacoes, "cto": cto_cabo}
            caixas.append(item)
            if cto_cabo:
                cto = ctos_da_camada.get(_to_text((cto_cabo.get("cto") or {}).get("ponto")).strip().lower())
                if cto:
                    cto["caixas"].append(item)
    caixas.sort(key=lambda c: (int(_rotulo_caixa(c["nome"])) if _rotulo_caixa(c["nome"]).isdigit() else 10 ** 6, c["nome"]))
    return {"caixas": caixas, "ctos": ctos, "linhas": linhas, "contagem": contagem}


def _loc_caixa(caixa: Dict[str, Any]) -> Dict[str, Any]:
    return {"lat": caixa["pos"][0], "lon": caixa["pos"][1]} if caixa.get("pos") else {}


def _rotulo_porta(caixa: Dict[str, Any], porta: Any) -> str:
    if not porta:
        return "-"
    return f"LAN{porta}" if caixa["tipo"] == "onu" else f"P{porta}"


def _equipamento_da_caixa(caixa: Dict[str, Any]) -> str:
    cx = caixa["cx"]
    nome, modelo = _to_text(cx.get("switch_nome")), _to_text(cx.get("switch_modelo"))
    if caixa["tipo"] == "passagem":
        return "-"
    base = "ONU" if caixa["tipo"] == "onu" else "Switch"
    return " ".join(x for x in (base, nome, f"({modelo})" if modelo else "") if x)


def _cabo_txt(cb: Dict[str, Any]) -> Tuple[str, str]:
    nome = CABOS.get(cb.get("tipo"), CABOS["outro"])[0]
    m = float(cb.get("metros") or 0)
    mf = float(cb.get("metros_com_folga") or m)
    return nome, f"{m:.0f} m ({mf:.0f} m c/ folga)"


def _linhas_dos_cabos(caixas: List[Dict[str, Any]], so_cams: Optional[set] = None) -> List[tuple]:
    """Cabos das caixas para o renderizar_mapa (so os das cameras em `so_cams`, se dado)."""
    out = []
    for cx in caixas:
        for cb in cx["cabos"] + ([cx["cto"]] if cx["cto"] else []):
            if so_cams is not None and id(cb.get("_cam")) not in so_cams:
                continue
            nome, cor, trac, _ = CABOS.get(cb.get("tipo"), CABOS["outro"])
            coords = [(float(p[0]), float(p[1])) for p in cb.get("caminho") or [] if len(p) >= 2]
            if len(coords) >= 2:
                out.append((coords, cor, 6, trac))
    return out


def _cameras_do_cliente(site: str = "") -> List[Dict[str, Any]]:
    from app.core import permissions
    from app.services.inventory_json import load_inventory_json

    vistas, out = set(), []
    alvo = _to_text(site).lower()
    for modo in ("olt", "basic", "switch"):
        try:
            # restricao de site da sessao (o job roda no contexto de quem pediu)
            linhas = permissions.filtrar_por_site(load_inventory_json(mode=modo) or [])
        except Exception:
            continue
        for r in linhas:
            if not isinstance(r, dict) or not _to_text(r.get("ip")):
                continue
            chave = (_to_text(r.get("remote_connector_id") or r.get("connector_id")), _to_text(r.get("ip")))
            if chave in vistas:
                continue
            # o site e o PRIMEIRO campo preenchido (nao a uniao: editar o
            # "local" nao muda de site -- ver permissions.site_da_linha)
            if alvo and permissions.site_da_linha(r).lower() != alvo:
                continue
            vistas.add(chave)
            out.append(dict(r))
    return out


def _texto_motivo(m: Dict[str, Any]) -> str:
    """Motivo informado no Mapa ("camera retirada em 10/2026 - por joao em 17/10/2026")."""
    motivo = _to_text((m or {}).get("motivo"))
    if not motivo:
        return "sem motivo informado: o nome do ponto nao corresponde a nenhuma camera do inventario"
    quem = _to_text(m.get("por"))
    try:
        quando = datetime.fromisoformat(_to_text(m.get("em"))).strftime("%d/%m/%Y")
    except ValueError:
        quando = ""
    extra = " ".join(x for x in (f"por {quem}" if quem else "", f"em {quando}" if quando else "") if x)
    return f"{motivo} ({extra})" if extra else motivo


def _status(c: Dict[str, Any]) -> str:
    s = _to_text(c.get("status")).lower()
    if s in ("online", "offline"):
        return s
    return "online" if _camera_online(c) else "sem status"


def _cor_status(status: str) -> str:
    return {"online": COR_ONLINE, "offline": COR_OFFLINE}.get(status, COR_SEM_STATUS)


# --------------------------------------------------------------------- pdf
def _tabela(cabec: List[str], linhas: List[List[Any]], pesos: List[int], styles, accent, largura: float) -> LongTable:
    soma = sum(pesos) or 1
    data = [[_p(h, styles["th"]) for h in cabec]] + linhas
    t = LongTable(data, colWidths=[largura * p / soma for p in pesos], repeatRows=1, splitByRow=1, hAlign="LEFT")
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
    ]
    cmds += [("BACKGROUND", (0, i), (-1, i), STRIPE) for i in range(2, len(data), 2)]
    t.setStyle(TableStyle(cmds))
    return t


def _legenda(styles, largura: float, tem_outros: bool, cor_outros: str,
             extras: Iterable[Tuple[str, str]] = ()) -> Table:
    itens = [(COR_ONLINE, "Online"), (COR_OFFLINE, "Offline"), (COR_SEM_STATUS, "Sem status")]
    if tem_outros:
        itens.append((cor_outros, "Ponto do mapa sem camera"))
    itens += list(extras)
    celulas = []
    for cor, txt in itens:
        celulas += [_p("", styles["small"], fallback=""), _p(txt, styles["small"])]
    t = Table([celulas], colWidths=[10, min(120, largura / len(itens) - 10)] * len(itens), hAlign="LEFT")
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3)]
    for i, (cor, _) in enumerate(itens):
        cmds.append(("BACKGROUND", (2 * i, 0), (2 * i, 0), colors.HexColor(cor)))
    t.setStyle(TableStyle(cmds))
    return t


def _grade_portas(cx: Dict[str, Any], portas: int, styles, largura: float) -> Table:
    """As portas da caixa como no painel do Mapa: verde/vermelho/cinza = camera
    online/fora/sem status, branco = livre; UP (switch) ou PON (ONU) no fim."""
    por_porta = {int(cb["porta"]): cb for cb in cx["cabos"] if cb.get("porta")}
    celulas, cores = [], []
    for n in range(1, portas + 1):
        cb = por_porta.get(n)
        cam = cb["_cam"] if cb else None
        celulas.append(_rotulo_porta(cx, n))
        cores.append(None if not cb else _cor_status(cam["_status"]) if cam is not None else COR_SEM_STATUS)
    if cx["tipo"] == "onu":
        celulas.append("PON")
        cores.append(COR_CTO if cx["cto"] else "#cbd5e1")
    else:
        for u in range(int(cx["cx"].get("uplinks") or 0)):
            celulas.append("UP" if int(cx["cx"].get("uplinks") or 0) == 1 else f"UP{u + 1}")
            cores.append("#475569")
    larg = min(16 * mm, largura / max(len(celulas), 1))
    t = Table([[_p(c, styles["small_b"], color=colors.white if cor else INK) for c, cor in zip(celulas, cores)]],
              colWidths=[larg] * len(celulas), rowHeights=[9 * mm], hAlign="LEFT")
    cmds = [("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER)]
    cmds += [("BACKGROUND", (i, 0), (i, 0), colors.HexColor(cor)) for i, cor in enumerate(cores) if cor]
    t.setStyle(TableStyle(cmds))
    return t


def build_map_pdf_report(site: str = "", company_name: str = "", report_color: str = "",
                         include_photos: bool = True, progress_cb: ProgressCb = None) -> Path:
    """Relatorio do Mapa do cliente atual (contexto de tenant obrigatorio)."""
    def passo(feito: int, total: int, etapa: str) -> None:
        if progress_cb:
            progress_cb(feito, total, etapa)

    from app.services.recorder_pdf_report import _coordenadas_do_mapa, _posicao_camera

    passo(0, 1, "preparando")
    site_label = _to_text(site) or "Todos os sites"
    accent = _accent(report_color)
    styles = _styles()
    page_w, _ = landscape(A4)
    margem = 14 * mm
    util = page_w - 2 * margem

    cams = _cameras_do_cliente(site)
    mapa_nomes = _coordenadas_do_mapa()
    gravacao = _gravacao_por_camera()
    camadas = _camadas_do_relatorio(site)
    pontos = _pontos_do_mapa(camadas=camadas)
    titulos = {_to_text(c.get("titulo")).strip().lower() for c in cams}
    # Ponto so com o numero ("51") e a camera "51 - ESTADIO", como o Mapa casa
    # (mapNumeroDoTitulo): so quando o numero e unico nos dois lados.
    so_numero: Dict[str, List[tuple]] = {}
    for p in pontos:
        if p["tipo"] == "camera" and re.fullmatch(r"\d+", p["nome"].strip()):
            so_numero.setdefault(str(int(p["nome"].strip())), []).append(p["pos"])
    nums_cam: Dict[str, int] = {}
    for c in cams:
        n = _numero(_to_text(c.get("titulo")))
        if n:
            nums_cam[str(int(n))] = nums_cam.get(str(int(n)), 0) + 1
    casados_por_numero = {n for n, ps in so_numero.items() if len(ps) == 1 and nums_cam.get(n) == 1}
    for c in cams:
        c["_pos"] = _posicao_camera(c, mapa_nomes)
        n = _numero(_to_text(c.get("titulo")))
        if not c["_pos"] and n and str(int(n)) in casados_por_numero:
            c["_pos"] = so_numero[str(int(n))][0]
        c["_status"] = _status(c)
        c["_num"] = _numero(_to_text(c.get("titulo")))
        if c["_pos"]:
            c["lat"], c["lon"] = c["_pos"]
        conn = _to_text(c.get("remote_connector_id") or c.get("connector_id"))
        c["_rec"] = gravacao.get((conn, _to_text(c.get("ip")))) or gravacao.get(("", _to_text(c.get("ip"))))
        c["_foto"] = _pick_image_path(c)
    # so ponto com cara de camera e pendencia: caixa, CTO, poste e CDO sao infraestrutura
    sem_camera = [p for p in pontos if p["tipo"] == "camera" and p["nome"].strip().lower() not in titulos
                  and not (re.fullmatch(r"\d+", p["nome"].strip()) and str(int(p["nome"].strip())) in casados_por_numero)]
    cor_outros = sem_camera[0]["cor"] if sem_camera else COR_OUTROS
    com_pos = [c for c in cams if c["_pos"]]
    areas = agrupar_areas(cams)
    infra = _infra_do_mapa(camadas, cams)
    caixas, ctos, linhas_kmz = infra["caixas"], infra["ctos"], infra["linhas"]
    caixa_da_cam: Dict[int, str] = {}
    for cx in caixas:
        for cb in cx["cabos"]:
            if cb["_cam"] is not None:
                caixa_da_cam[id(cb["_cam"])] = f"{cx['nome']} {_rotulo_porta(cx, cb.get('porta'))}".replace(" -", "")
    pinos_caixa = [(cx["pos"][0], cx["pos"][1], _rotulo_caixa(cx["nome"]), COR_CAIXA, "quadrado")
                   for cx in caixas if cx["pos"]]
    pinos_cto = [(c["pos"][0], c["pos"][1], "", COR_CTO, "losango") for c in ctos if c["pos"]]
    linhas_cabos = _linhas_dos_cabos(caixas)
    linhas_rede = [(l["coords"], COR_LINHA, 4, False) for l in linhas_kmz]
    extras_legenda = ([(COR_CAIXA, "Caixa de CFTV")] if caixas else []) + ([(COR_CTO, "CTO")] if ctos else []) \
        + ([(CABOS["utp5e"][1], "Cabo UTP")] if linhas_cabos else []) + ([(COR_LINHA, "Linha do KMZ")] if linhas_rede else [])

    total = len(cams)
    online = sum(1 for c in cams if c["_status"] == "online")
    offline = sum(1 for c in cams if c["_status"] == "offline")
    com_foto = sum(1 for c in cams if c["_foto"] is not None)
    gravando = sum(1 for c in cams if c["_rec"] and c["_rec"]["gravando"] == "sim")
    # "n/c" = o gravador nao informou: entra so em "Em gravador", nunca como
    # "nao grava" -- "Gravando 0 de 48" com tudo gravando foi o primeiro rascunho.
    grav_conhecida = sum(1 for c in cams if c["_rec"] and c["_rec"]["gravando"] in ("sim", "nao"))
    em_gravador = sum(1 for c in cams if c["_rec"])

    reports_dir = OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    # Id aleatorio no nome: a pasta e de todos os clientes, e dois relatorios
    # pedidos no mesmo segundo gravariam o mesmo arquivo -- um cliente baixaria
    # o mapa do outro (o job confere o dono, o arquivo nao).
    out = reports_dir / (f"map-report-{site_label.replace(' ', '_').replace('/', '_')}-"
                         f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:12]}.pdf")
    agora = datetime.now()
    header = _header_footer_factory("Relatorio do mapa", accent,
                                    f"{site_label}  -  {agora.strftime('%d/%m/%Y %H:%M')}",
                                    cabecalho="RELATORIO DO MAPA")
    doc = SimpleDocTemplate(str(out), pagesize=landscape(A4), leftMargin=margem, rightMargin=margem,
                            topMargin=18 * mm, bottomMargin=14 * mm, title=f"Relatorio do mapa - {site_label}",
                            author="SightOps", subject="Mapa das cameras")
    story: List[Any] = []
    n_mapas = 1 + len(areas) + len(caixas)
    passo(0, n_mapas, "mapas")

    # ---- pagina 1: visao geral
    comp = f"  -  {company_name}" if _to_text(company_name) else ""
    story.append(_p("Relatorio do mapa", styles["title"]))
    story.append(_p(f"Gerado em {agora.strftime('%d/%m/%Y as %H:%M')}  -  Site: {site_label}  -  "
                    f"{total} camera{'s' if total != 1 else ''}{comp}", styles["subtitle"]))
    story.append(_kpis([
        ("Cameras", str(total), INK), ("Online", str(online), OK), ("Offline", str(offline), BAD),
        ("No mapa", f"{len(com_pos)}", INK), ("Com foto", str(com_foto), INK),
        ("Gravando", f"{gravando} de {grav_conhecida}", INK) if grav_conhecida
        else ("Em gravador", f"{em_gravador} de {total}", INK),
    ], styles, util))
    portas_total = sum(int(cx["cx"].get("portas") or 0) for cx in caixas if cx["tipo"] != "passagem")
    portas_uso = sum(1 for cx in caixas if cx["tipo"] != "passagem" for cb in cx["cabos"] if cb.get("porta"))
    metros_por_tipo: Dict[str, float] = {}
    for cx in caixas:
        for cb in cx["cabos"] + ([cx["cto"]] if cx["cto"] else []):
            t = cb.get("tipo") if cb.get("tipo") in CABOS else "outro"
            metros_por_tipo[t] = metros_por_tipo.get(t, 0) + float(cb.get("metros_com_folga") or cb.get("metros") or 0)
    if caixas or ctos:
        ligadas = len(caixa_da_cam)
        story.append(Spacer(1, 2 * mm))
        story.append(_kpis([
            ("Caixas de CFTV", str(len(caixas)), INK),
            ("Portas em uso", f"{portas_uso} de {portas_total}", INK),
            ("Cameras com cabo", f"{ligadas} de {total}", OK if ligadas == total else INK),
            ("Cabo UTP", f"{metros_por_tipo.get('utp5e', 0) + metros_por_tipo.get('utp6', 0):,.0f} m".replace(",", "."), INK),
            ("CTOs", str(len(ctos)), INK),
        ], styles, util))
    story.append(Spacer(1, 3 * mm))
    geral = renderizar_mapa(
        [(c["_pos"][0], c["_pos"][1], c["_num"], _cor_status(c["_status"])) for c in com_pos]
        + [(p["pos"][0], p["pos"][1], _numero(p["nome"]), p["cor"]) for p in sem_camera]
        + pinos_caixa + pinos_cto,
        # com a 2a linha de numeros, o mapa encolhe para caber na pagina 1
        1800, 700 if (caixas or ctos) else 860, raio=15, linhas=linhas_rede + linhas_cabos)
    passo(1, n_mapas, "mapas")
    if geral is not None:
        story.append(_imagem_pdf(geral, util))
        story.append(Spacer(1, 2 * mm))
        story.append(_legenda(styles, util, bool(sem_camera), cor_outros, extras_legenda))
    else:
        story.append(_p("Nenhuma camera com posicao no mapa.", styles["small"]))

    # ---- resumo por area
    story.append(PageBreak())
    story.append(_p("Resumo por area", styles["title"]))
    story.append(_p("Area = cameras com o mesmo nome-base (ex.: QD. S); grupos de ate 2 cameras entram "
                    "na area mais proxima.", styles["subtitle"]))
    linhas = []
    for i, a in enumerate(areas, 1):
        ac = a["cams"]
        linhas.append([
            _p(str(i), styles["small_b"]), _p(a["nome"], styles["small_b"]), _p(str(len(ac)), styles["small"]),
            _p(str(sum(1 for c in ac if c["_status"] == "online")), styles["small"], color=OK),
            _p(str(sum(1 for c in ac if c["_status"] == "offline")), styles["small"], color=BAD),
            _p(str(sum(1 for c in ac if c["_foto"] is None)), styles["small"]),
            _p(str(sum(1 for c in ac if c["_rec"] and c["_rec"]["gravando"] == "nao")), styles["small"]),
            _p(str(sum(1 for c in ac if not c["_rec"])), styles["small"]),
        ])
    story.append(_tabela(["AREA", "NOME", "CAMERAS", "ONLINE", "OFFLINE", "SEM FOTO", "SEM GRAVACAO", "FORA DE GRAVADOR"],
                         linhas, [6, 46, 12, 12, 12, 12, 14, 16], styles, accent, util))
    sites: Dict[str, List[Dict[str, Any]]] = {}
    modelos: Dict[str, int] = {}
    for c in cams:
        sites.setdefault(_to_text(c.get("site") or c.get("local")) or "-", []).append(c)
        m = _to_text(c.get("modelo") or c.get("model")) or "-"
        modelos[m] = modelos.get(m, 0) + 1
    story.append(Spacer(1, 5 * mm))
    lado = (util - 6 * mm) / 2
    t_site = _tabela(["SITE", "CAMERAS", "ONLINE", "OFFLINE"],
                     [[_p(s, styles["small_b"]), _p(str(len(v)), styles["small"]),
                       _p(str(sum(1 for c in v if c["_status"] == "online")), styles["small"], color=OK),
                       _p(str(sum(1 for c in v if c["_status"] == "offline")), styles["small"], color=BAD)]
                      for s, v in sorted(sites.items())], [40, 14, 14, 14], styles, accent, lado)
    t_mod = _tabela(["MODELO", "CAMERAS"],
                    [[_p(m, styles["small"]), _p(str(n), styles["small"])]
                     for m, n in sorted(modelos.items(), key=lambda x: -x[1])], [40, 14], styles, accent, lado)
    dupla = Table([[t_site, t_mod]], colWidths=[lado + 3 * mm, lado + 3 * mm], hAlign="LEFT")
    dupla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(dupla)

    # ---- infraestrutura: caixas, materiais, CTOs e o resto do mapa
    if caixas or ctos or linhas_kmz or any(infra["contagem"].values()):
        story.append(PageBreak())
        story.append(_p("Infraestrutura de CFTV", styles["title"]))
        story.append(_p("Caixas, cabos e CTOs desenhados no Mapa. Metragem pelo tracado, com a folga de cada cabo.",
                        styles["subtitle"]))
        if caixas:
            story.append(_p(f"Caixas de CFTV ({len(caixas)})", styles["h2"]))
            linhas = []
            for cx in caixas:
                c_cams = [cb["_cam"] for cb in cx["cabos"]]
                fora = sum(1 for c in c_cams if c is not None and c["_status"] != "online")
                usadas = sum(1 for cb in cx["cabos"] if cb.get("porta"))
                portas = int(cx["cx"].get("portas") or 0)
                if cx["cto"]:
                    nome_cto = (cx["cto"].get("cto") or {})
                    lig = f"CTO {nome_cto.get('ponto')}{' porta ' + str(nome_cto['porta']) if nome_cto.get('porta') else ''}" \
                          f" - {float(cx['cto'].get('metros_com_folga') or cx['cto'].get('metros') or 0):.0f} m"
                elif cx["tipo"] == "switch" and int(cx["cx"].get("uplinks") or 0):
                    lig = f"uplink -> {_to_text(cx['cx'].get('uplink_para') or 'onu').upper()}"
                else:
                    lig = "-"
                itens = ", ".join(f"{int(i.get('qtd') or 1)}x {ITENS_CAIXA.get(i.get('tipo'), 'Outro')}"
                                  f"{' ' + _to_text(i.get('modelo')) if _to_text(i.get('modelo')) else ''}"
                                  for i in cx["cx"].get("itens") or [] if isinstance(i, dict))
                linhas.append([
                    _p(cx["nome"], styles["small_b"]), _p(TIPOS_CAIXA[cx["tipo"]], styles["small"]),
                    _p(_equipamento_da_caixa(cx), styles["small"]),
                    _p("-" if cx["tipo"] == "passagem" else f"{usadas} de {portas}", styles["small"]),
                    _p(f"{len(c_cams)}" + (f" ({fora} fora)" if fora else ""), styles["small_b"] if fora else styles["small"],
                       color=BAD if fora else None),
                    _p(lig, styles["small"]), _p(itens, styles["small"]),
                    _p_localizacao(_loc_caixa(cx), styles["mono"]),
                ])
            story.append(_tabela(["CAIXA", "TIPO", "EQUIPAMENTO", "PORTAS", "CAMERAS", "LIGACAO", "ITENS", "LOCALIZACAO"],
                                 linhas, [14, 11, 20, 8, 9, 16, 21, 14], styles, accent, util))
        # materiais: o que foi lancado no mapa, para conferir com o almoxarifado
        cabos_tab = []
        for t, (nome, _, _, _) in CABOS.items():
            todos = [cb for cx in caixas for cb in cx["cabos"] + ([cx["cto"]] if cx["cto"] else []) if (cb.get("tipo") or "outro") == t]
            if todos:
                tracado = sum(float(cb.get("metros") or 0) for cb in todos)
                cabos_tab.append([_p(nome, styles["small_b"]), _p(str(len(todos)), styles["small"]),
                                  _p(f"{tracado:,.0f} m".replace(",", "."), styles["small"]),
                                  _p(f"{metros_por_tipo.get(t, 0):,.0f} m".replace(",", "."), styles["small_b"])])
        equip: Dict[Tuple[str, str], int] = {}
        for cx in caixas:
            itens = [i for i in cx["cx"].get("itens") or [] if isinstance(i, dict)]
            tipos = {i.get("tipo") for i in itens}
            # o switch/ONU da caixa conta mesmo sem estar na lista de itens
            if cx["tipo"] == "switch" and not tipos & {"switch", "switch_poe"}:
                itens.append({"tipo": "switch_poe", "modelo": cx["cx"].get("switch_modelo"), "qtd": 1})
            if cx["tipo"] == "onu" and "onu" not in tipos:
                itens.append({"tipo": "onu", "modelo": cx["cx"].get("switch_modelo"), "qtd": 1})
            for i in itens:
                k = (ITENS_CAIXA.get(i.get("tipo"), "Outro"), _to_text(i.get("modelo")) or "-")
                equip[k] = equip.get(k, 0) + int(i.get("qtd") or 1)
        alim: Dict[str, int] = {}
        for cx in caixas:
            for cb in cx["cabos"]:
                if cb.get("alimentacao"):
                    a = ALIMENTACAO.get(cb["alimentacao"], cb["alimentacao"])
                    alim[a] = alim.get(a, 0) + 1
        equip_tab = [[_p(k[0], styles["small_b"]), _p(k[1], styles["small"]), _p(str(n), styles["small"])]
                     for k, n in sorted(equip.items(), key=lambda x: (-x[1], x[0]))]
        equip_tab += [[_p(f"{a} (camera)", styles["small_b"]), _p("-", styles["small"]), _p(str(n), styles["small"])]
                      for a, n in sorted(alim.items())]
        if cabos_tab or equip_tab:
            story.append(CondPageBreak(40 * mm))
            story.append(_p("Materiais lancados no mapa", styles["h2"]))
            t_cab = _tabela(["CABO", "TRECHOS", "TRACADO", "COM FOLGA"], cabos_tab or [[_p("-", styles["small"])] * 4],
                            [30, 14, 18, 18], styles, accent, lado)
            t_eq = _tabela(["EQUIPAMENTO", "MODELO", "QTD"], equip_tab or [[_p("-", styles["small"])] * 3],
                           [30, 30, 10], styles, accent, lado)
            mat = Table([[t_cab, t_eq]], colWidths=[lado + 3 * mm, lado + 3 * mm], hAlign="LEFT")
            mat.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(mat)
        if ctos:
            story.append(CondPageBreak(40 * mm))
            story.append(_p(f"CTOs no mapa ({len(ctos)})", styles["h2"]))
            onus = _onus_do_monitoramento() if any(c.get("cad") for c in ctos) else {}

            def _portas_da_cto(c: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
                """porta -> {caixa, onu, obs}: caixa pelo cabo drop, ONU/obs pelo cadastro."""
                portas: Dict[int, Dict[str, Any]] = {}
                for cx in c["caixas"]:
                    n = (cx["cto"].get("cto") or {}).get("porta")
                    if n:
                        portas.setdefault(int(n), {})["caixa"] = cx
                for n, info in ((c.get("cad") or {}).get("portas_info") or {}).items():
                    if isinstance(info, dict) and str(n).isdigit():
                        portas.setdefault(int(n), {}).update({"onu": info, "obs": _to_text(info.get("obs"))})
                return portas

            def _origem(cad: Dict[str, Any]) -> str:
                partes = [_to_text(cad.get("olt_nome")), f"PON {cad['pon']}" if cad.get("pon") else "",
                          f"de {cad['vem_de']}" if cad.get("vem_de") else ""]
                return " - ".join(x for x in partes if x) or "-"

            linhas_cto = []
            for c in ctos:
                cad = c.get("cad") or {}
                usadas = len([n for n, v in _portas_da_cto(c).items() if v.get("caixa") or (v.get("onu") or {}).get("onu_key")])
                total = int(cad.get("portas") or 0)
                linhas_cto.append([
                    _p(_to_text(cad.get("nome")) or c["nome"], styles["small_b"]),
                    _p(" ".join(x for x in (_to_text(cad.get("splitter")), {"primario": "primario", "secundario": "secundario"}.get(cad.get("nivel"), "")) if x) or "-", styles["small"]),
                    _p(_origem(cad) if cad else "sem cadastro", styles["small"]),
                    _p(f"{usadas}/{total}" if total else str(usadas or "-"), styles["small"]),
                    _p(", ".join(f"{cx['nome']}{' (porta ' + str(cx['cto']['cto']['porta']) + ')' if (cx['cto'].get('cto') or {}).get('porta') else ''}"
                                 for cx in c["caixas"]) or "nenhuma", styles["small"]),
                    _p(f"{sum(float(cx['cto'].get('metros_com_folga') or 0) for cx in c['caixas']):.0f} m" if c["caixas"] else "-", styles["small"]),
                    _p_localizacao({"lat": c["pos"][0], "lon": c["pos"][1]}, styles["mono"])])
            story.append(_tabela(
                ["CTO", "SPLITTER", "ORIGEM", "PORTAS", "CAIXAS LIGADAS", "DROP", "LOCALIZACAO"],
                linhas_cto, [13, 9, 18, 7, 25, 8, 20], styles, accent, util))
            # porta a porta, so das CTOs cadastradas
            for c in ctos:
                cad = c.get("cad")
                if not cad:
                    continue
                portas = _portas_da_cto(c)
                total = int(cad.get("portas") or 0)
                livres = [str(n) for n in range(1, total + 1) if n not in portas or not (portas[n].get("caixa") or (portas[n].get("onu") or {}).get("onu_key"))]
                story.append(CondPageBreak(30 * mm))
                story.append(_p(f"{_to_text(cad.get('nome')) or c['nome']} - portas"
                                f"{'  (' + cad['splitter'] + ')' if cad.get('splitter') else ''}", styles["small_b"]))
                linhas_p = []
                for n in sorted(portas):
                    v = portas[n]
                    info = v.get("onu") or {}
                    onu = onus.get(_to_text(info.get("onu_key")))
                    det = (onu or {}).get("det") or {}
                    try:
                        rx = f"{float(det.get('onu_rx')):.2f} dBm" if det.get("onu_rx") not in (None, "", 0, "0") else "-"
                    except (TypeError, ValueError):
                        rx = "-"
                    st = {"up": "no ar", "down": "fora do ar"}.get(_to_text((onu or {}).get("status")).lower(), "-") if onu else "-"
                    linhas_p.append([_p(str(n), styles["small_b"]),
                                     _p(v["caixa"]["nome"] if v.get("caixa") else "-", styles["small"]),
                                     _p(_to_text(info.get("onu_nome")) or "-", styles["small"]),
                                     _p(rx, styles["small"]), _p(st, styles["small"]),
                                     _p(_to_text(v.get("obs")) or "-", styles["small"])])
                if not linhas_p:
                    linhas_p = [[_p("-", styles["small"])] * 6]
                story.append(_tabela(["PORTA", "CAIXA", "ONU", "SINAL", "STATUS", "OBS"], linhas_p,
                                     [8, 20, 28, 12, 12, 20], styles, accent, util))
                if livres:
                    story.append(_p(f"Livres: {', '.join(livres)}", styles["small"]))
        if linhas_kmz or any(infra["contagem"].values()):
            story.append(CondPageBreak(30 * mm))
            story.append(_p("Outros elementos do mapa", styles["h2"]))
            outros = []
            if linhas_kmz:
                outros.append([_p("Linhas (fibra / rota)", styles["small_b"]), _p(str(len(linhas_kmz)), styles["small"]),
                               _p(f"{sum(l['metros'] for l in linhas_kmz):,.0f} m".replace(",", "."), styles["small"])])
            for tipo, nome in (("poste", "Postes"), ("cdo", "CDO / emendas")):
                if infra["contagem"][tipo]:
                    outros.append([_p(nome, styles["small_b"]), _p(str(infra["contagem"][tipo]), styles["small"]),
                                   _p("-", styles["small"])])
            story.append(_tabela(["ELEMENTO", "QUANTIDADE", "EXTENSAO"], outros, [30, 14, 18], styles, accent, lado))

    # ---- uma pagina por area
    for i, a in enumerate(areas, 1):
        story.append(PageBreak())
        ac = a["cams"]
        on = sum(1 for c in ac if c["_status"] == "online")
        story.append(_p(f"Area {i}  |  {a['nome']}", styles["title"]))
        story.append(_p(f"{len(ac)} camera{'s' if len(ac) != 1 else ''}  -  {on} online  -  {len(ac) - on} fora",
                        styles["subtitle"]))
        # cabos das cameras da area e as caixas de onde eles saem
        ids_area = {id(c) for c in ac}
        cx_area = [cx for cx in caixas if cx["pos"] and any(id(cb["_cam"]) in ids_area for cb in cx["cabos"])]
        img = renderizar_mapa([(c["_pos"][0], c["_pos"][1], c["_num"], _cor_status(c["_status"])) for c in ac]
                              + [(cx["pos"][0], cx["pos"][1], _rotulo_caixa(cx["nome"]), COR_CAIXA, "quadrado") for cx in cx_area],
                              1800, 620, raio=19, linhas=_linhas_dos_cabos(cx_area, ids_area))
        passo(1 + i, n_mapas, "mapas")
        if img is not None:
            story.append(_imagem_pdf(img, util))
            story.append(Spacer(1, 3 * mm))
        linhas = []
        for c in ac:
            rec = c["_rec"]
            sufixo = {"sim": " - gravando", "nao": " - NAO GRAVA"}.get(rec["gravando"], "") if rec else ""
            rec_txt = f"{rec['gravador']} canal {rec['canal']}{sufixo}" if rec else "fora de gravador"
            linha = [
                _p(c["_num"] or "-", styles["small_b"]), _p(c.get("titulo"), styles["small_b"]),
                _p(c.get("ip"), styles["mono"]),
                _p(c["_status"].upper(), styles["small_b"], color=OK if c["_status"] == "online" else BAD),
                _p(rec_txt, styles["small"]), _p("sim" if c["_foto"] is not None else "nao", styles["small"]),
                _p(c.get("modelo") or c.get("model"), styles["small"]), _p_localizacao(c, styles["mono"]),
            ]
            if caixas:
                linha.insert(5, _p(caixa_da_cam.get(id(c), "sem cabo"), styles["small"]))
            linhas.append(linha)
        if caixas:
            story.append(_tabela(["N", "CAMERA", "IP", "STATUS", "GRAVADOR", "CAIXA / PORTA", "FOTO", "MODELO", "LOCALIZACAO"],
                                 linhas, [5, 30, 14, 10, 28, 15, 6, 14, 16], styles, accent, util))
        else:
            story.append(_tabela(["N", "CAMERA", "IP", "STATUS", "GRAVADOR", "FOTO", "MODELO", "LOCALIZACAO"],
                                 linhas, [5, 34, 15, 11, 34, 7, 18, 16], styles, accent, util))

    # ---- uma pagina por caixa de CFTV: o que tem dentro e cada porta
    for k, cx in enumerate(caixas, 1):
        story.append(PageBreak())
        c_cams = [cb["_cam"] for cb in cx["cabos"] if cb["_cam"] is not None]
        fora = sum(1 for c in c_cams if c["_status"] != "online")
        portas = 0 if cx["tipo"] == "passagem" else int(cx["cx"].get("portas") or 0)
        usadas = sum(1 for cb in cx["cabos"] if cb.get("porta"))
        story.append(_p(f"Caixa {cx['nome']}  |  {TIPOS_CAIXA[cx['tipo']]}", styles["title"]))
        partes = [_equipamento_da_caixa(cx) if cx["tipo"] != "passagem" else "",
                  f"{usadas} de {portas} portas em uso" if portas else "",
                  f"{len(cx['cabos'])} camera{'s' if len(cx['cabos']) != 1 else ''}" + (f" ({fora} fora do ar)" if fora else ""),
                  f"VLAN {cx['cx']['switch_vlan']}" if _to_text(cx["cx"].get("switch_vlan")) else "", cx["camada"]]
        story.append(_p("  -  ".join(x for x in partes if x), styles["subtitle"]))
        dentro = ", ".join(f"{int(i.get('qtd') or 1)}x {ITENS_CAIXA.get(i.get('tipo'), 'Outro')}"
                           f"{' ' + _to_text(i.get('modelo')) if _to_text(i.get('modelo')) else ''}"
                           for i in cx["cx"].get("itens") or [] if isinstance(i, dict))
        # localizacao clicavel (Google Maps), como a das cameras
        loc = Table([[_p("Localizacao:", styles["small_b"]), _p_localizacao(_loc_caixa(cx), styles["mono"]),
                      _p(f"Dentro da caixa: {dentro}" if dentro else "", styles["small"])]],
                    colWidths=[24 * mm, 32 * mm, util - 56 * mm], hAlign="LEFT")
        loc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(loc)
        story.append(Spacer(1, 2 * mm))
        pinos = [(c["_pos"][0], c["_pos"][1], c["_num"], _cor_status(c["_status"])) for c in c_cams if c["_pos"]]
        if cx["pos"]:
            pinos.append((cx["pos"][0], cx["pos"][1], _rotulo_caixa(cx["nome"]), COR_CAIXA, "quadrado"))
        cto_pos = None
        if cx["cto"] and len(cx["cto"].get("caminho") or []) >= 2:
            cto_pos = tuple(float(v) for v in cx["cto"]["caminho"][-1][:2])
            pinos.append((cto_pos[0], cto_pos[1], "", COR_CTO, "losango"))
        # 8 portas + mapa + localizacao cabem numa pagina
        img = renderizar_mapa(pinos, 1800, 490, raio=19, linhas=_linhas_dos_cabos([cx])) if pinos else None
        passo(1 + len(areas) + k, n_mapas, "mapas")
        if img is not None:
            story.append(_imagem_pdf(img, util))
            story.append(Spacer(1, 3 * mm))
        if portas:
            story.append(_grade_portas(cx, portas, styles, util))
            story.append(Spacer(1, 3 * mm))
        linhas = []
        for cb in cx["cabos"]:
            c = cb["_cam"]
            st = c["_status"] if c is not None else "sem cadastro"
            nome_cabo, metros = _cabo_txt(cb)
            longe = (CABOS.get(cb.get("tipo"), CABOS["outro"])[3] or 10 ** 9) < float(cb.get("metros_com_folga") or cb.get("metros") or 0)
            destino = cb.get("camera") or {}
            linhas.append([
                _p(_rotulo_porta(cx, cb.get("porta")), styles["small_b"]),
                _p(c.get("titulo") if c is not None else (destino.get("ponto") or destino.get("ip")), styles["small_b"]),
                _p(c.get("ip") if c is not None else destino.get("ip"), styles["mono"]),
                _p(st.upper(), styles["small_b"], color=OK if st == "online" else BAD),
                _p(_to_text(cb.get("vlan")) or _to_text(cx["cx"].get("switch_vlan")) or "-", styles["small"]),
                _p(nome_cabo, styles["small"]),
                _p(metros + (" - acima do limite" if longe else ""), styles["small_b"] if longe else styles["small"],
                   color=BAD if longe else None),
                _p(ALIMENTACAO.get(cb.get("alimentacao"), "PoE do switch" if cx["tipo"] == "switch" and cb.get("porta") else "-"),
                   styles["small"]),
            ])
        if linhas:
            story.append(_tabela(["PORTA", "CAMERA", "IP", "STATUS", "VLAN", "CABO", "METRAGEM", "ALIMENTACAO"],
                                 linhas, [8, 32, 14, 11, 7, 11, 20, 13], styles, accent, util))
        else:
            story.append(_p("Nenhuma camera ligada nesta caixa.", styles["small"]))
        if cx["cto"]:
            alvo = cx["cto"].get("cto") or {}
            story.append(Spacer(1, 2 * mm))
            story.append(_p(f"ONU ligada a CTO {alvo.get('ponto')}{', porta ' + str(alvo['porta']) if alvo.get('porta') else ''}: "
                            f"{_cabo_txt(cx['cto'])[0]}, {_cabo_txt(cx['cto'])[1]}.", styles["small"]))
        if _to_text(cx["cx"].get("obs")):
            story.append(Spacer(1, 2 * mm))
            story.append(_p(f"Observacao: {cx['cx']['obs']}", styles["small"]))

    # ---- galeria
    if include_photos:
        cards = []
        cols = 4
        cel = util / cols
        img_w = cel - 8
        area_de = {id(c): a["nome"] for a in areas for c in a["cams"]}
        com = [c for c in sorted(cams, key=lambda c: (int(c["_num"]) if c["_num"] else 10 ** 6, _to_text(c.get("titulo"))))
               if c["_foto"] is not None]
        for k, c in enumerate(com, 1):
            foto = _foto_padronizada(c["_foto"], img_w)
            if foto is None:
                continue
            st = c["_status"]
            linha = " - ".join(x for x in (area_de.get(id(c), ""), st.upper()) if x)
            cards.append([_p(c.get("titulo"), styles["cap"]),
                          RLImage(foto, width=img_w, height=img_w * PROPORCAO_FOTO),
                          _p(linha, styles["small"], color=OK if st == "online" else BAD)])
            passo(k, len(com), "fotos")
        if cards:
            story.append(PageBreak())
            story.append(_p("Fotos das cameras", styles["title"]))
            story.append(_p(f"{len(cards)} foto{'s' if len(cards) != 1 else ''}", styles["subtitle"]))
            grade = [cards[i:i + cols] + [""] * (cols - len(cards[i:i + cols])) for i in range(0, len(cards), cols)]
            g = Table(grade, colWidths=[cel] * cols)
            g.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            story.append(g)

    # ---- pendencias
    story.append(PageBreak())
    story.append(_p("Pendencias", styles["title"]))
    story.append(_p("O que precisa de acao para o mapa e o monitoramento ficarem completos.", styles["subtitle"]))
    fora = [c for c in cams if c["_status"] != "online"]
    sem_pos = [c for c in cams if not c["_pos"]]
    sem_grav = [c for c in cams if c["_rec"] and c["_rec"]["gravando"] == "nao"]
    blocos = [
        (f"Cameras fora do ar ({len(fora)})", fora,
         lambda c: [_p(c.get("titulo"), styles["small_b"]), _p(c.get("ip"), styles["mono"]),
                    _p(c["_status"].upper(), styles["small_b"], color=BAD), _p_localizacao(c, styles["mono"])],
         ["CAMERA", "IP", "STATUS", "LOCALIZACAO"], [40, 16, 12, 20]),
        (f"Pontos do mapa sem camera cadastrada ({len(sem_camera)})", sem_camera,
         lambda p: [_p(p["nome"], styles["small_b"]), _p(p["camada"], styles["small"]),
                    _p_localizacao({"lat": p["pos"][0], "lon": p["pos"][1]}, styles["mono"]),
                    _p(_texto_motivo(p["motivo"]), styles["small"])],
         ["PONTO", "CAMADA", "LOCALIZACAO", "MOTIVO"], [22, 22, 16, 40]),
        (f"Cameras sem posicao no mapa ({len(sem_pos)})", sem_pos,
         lambda c: [_p(c.get("titulo"), styles["small_b"]), _p(c.get("ip"), styles["mono"]),
                    _p("marque a camera no Mapa (nome igual ao do inventario)", styles["small"])],
         ["CAMERA", "IP", "O QUE FAZER"], [40, 16, 44]),
        (f"Cameras em gravador que nao estao gravando ({len(sem_grav)})", sem_grav,
         lambda c: [_p(c.get("titulo"), styles["small_b"]), _p(c.get("ip"), styles["mono"]),
                    _p(f"{c['_rec']['gravador']} canal {c['_rec']['canal']}", styles["small"])],
         ["CAMERA", "IP", "GRAVADOR"], [40, 16, 44]),
    ]
    if caixas:
        # infraestrutura: so quando o mapa ja tem caixas (sem elas, tudo seria pendencia)
        sem_cabo = [c for c in com_pos if id(c) not in caixa_da_cam]
        longos = [(cx, cb) for cx in caixas for cb in cx["cabos"]
                  if (CABOS.get(cb.get("tipo"), CABOS["outro"])[3] or 10 ** 9) < float(cb.get("metros_com_folga") or cb.get("metros") or 0)]
        vazias = [cx for cx in caixas if not cx["cabos"]]
        n_nome: Dict[str, int] = {}
        for cx in caixas:
            n_nome[cx["nome"].strip().upper()] = n_nome.get(cx["nome"].strip().upper(), 0) + 1
        repetidas = [cx for cx in caixas if n_nome[cx["nome"].strip().upper()] > 1]
        blocos += [
            (f"Cameras no mapa sem cabo ate uma caixa ({len(sem_cabo)})", sem_cabo,
             lambda c: [_p(c.get("titulo"), styles["small_b"]), _p(c.get("ip"), styles["mono"]),
                        _p("no Mapa: abra a caixa e use Ligar camera", styles["small"])],
             ["CAMERA", "IP", "O QUE FAZER"], [40, 16, 44]),
            (f"Cabos acima do limite do UTP/PoE ({len(longos)})", longos,
             lambda x: [_p(x[0]["nome"], styles["small_b"]),
                        _p((x[1]["_cam"] or {}).get("titulo") or (x[1].get("camera") or {}).get("ponto"), styles["small"]),
                        _p(_cabo_txt(x[1])[1], styles["small_b"], color=BAD),
                        _p(f"acima de {CABOS.get(x[1].get('tipo'), CABOS['outro'])[3]} m o sinal e o PoE caem", styles["small"])],
             ["CAIXA", "CAMERA", "METRAGEM", "PROBLEMA"], [18, 34, 20, 28]),
            (f"Caixas sem camera ligada ({len(vazias)})", vazias,
             lambda cx: [_p(cx["nome"], styles["small_b"]), _p(TIPOS_CAIXA[cx["tipo"]], styles["small"]),
                         _p(cx["camada"], styles["small"]), _p_localizacao(_loc_caixa(cx), styles["mono"])],
             ["CAIXA", "TIPO", "CAMADA", "LOCALIZACAO"], [26, 24, 30, 20]),
            (f"Caixas com nome repetido ({len(repetidas)})", repetidas,
             lambda cx: [_p(cx["nome"], styles["small_b"]), _p(_equipamento_da_caixa(cx), styles["small"]),
                         _p(f"{len(cx['cabos'])} camera(s)", styles["small"]),
                         _p_localizacao(_loc_caixa(cx), styles["mono"])],
             ["CAIXA", "EQUIPAMENTO", "CAMERAS", "LOCALIZACAO"], [22, 34, 16, 28]),
        ]
        if ctos:
            sem_cto = [cx for cx in caixas if not cx["cto"] and cx["tipo"] != "passagem"]
            blocos.append((f"Caixas com ONU sem ligacao a CTO ({len(sem_cto)})", sem_cto,
                           lambda cx: [_p(cx["nome"], styles["small_b"]), _p(TIPOS_CAIXA[cx["tipo"]], styles["small"]),
                                       _p("no Mapa: abra a caixa e use Ligar a CTO", styles["small"]),
                                       _p_localizacao(_loc_caixa(cx), styles["mono"])],
                           ["CAIXA", "TIPO", "O QUE FAZER", "LOCALIZACAO"], [24, 22, 34, 20]))
    for titulo, itens, linha, cabec, pesos in blocos:
        story.append(CondPageBreak(30 * mm))
        story.append(_p(titulo, styles["h2"]))
        if itens:
            story.append(_tabela(cabec, [linha(x) for x in itens], pesos, styles, accent, util))
        else:
            story.append(_p("Nada pendente.", styles["small"], color=OK))

    passo(1, 1, "finalizando")
    doc.build(story, onFirstPage=header, onLaterPages=header)
    return out
