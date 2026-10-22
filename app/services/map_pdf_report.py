"""Relatorio do Mapa em PDF: onde estao as cameras e como elas estao.

Feito para apresentar em reuniao. Pagina 1 e o mapa inteiro com um pino por
camera, colorido pelo status; depois um mapa ampliado por area (quadra/local),
com a tabela daquela area; a galeria de fotos; e as pendencias -- ponto do mapa
sem camera, camera sem posicao, camera fora do ar.

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


def renderizar_mapa(pontos: List[Tuple[float, float, str, str]], largura: int, altura: int,
                    margem: int = 70, zoom_max: int = _ZOOM_MAX, raio: int = 17) -> Optional[Image.Image]:
    """Imagem do mapa com um pino por ponto: [(lat, lon, rotulo, cor_hex)].

    Escolhe o maior zoom em que todos os pontos cabem dentro da margem. Tile que
    nao baixar vira fundo liso -- o mapa sai sem o desenho daquele pedaco, mas
    os pinos (que sao o que importa) continuam no lugar certo.
    """
    pts = [(la, lo, rot, cor) for la, lo, rot, cor in pontos if la is not None and lo is not None]
    if not pts:
        return None
    z = zoom_max
    for z in range(zoom_max, 0, -1):
        xs, ys = zip(*(_px(la, lo, z) for la, lo, _, _ in pts))
        if max(xs) - min(xs) <= largura - 2 * margem and max(ys) - min(ys) <= altura - 2 * margem:
            break
    xs, ys = zip(*(_px(la, lo, z) for la, lo, _, _ in pts))
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
    fonte = _fonte(int(raio * 0.95))
    # offline por ultimo: em cima dos outros, que e o que precisa aparecer
    ordem = sorted(pts, key=lambda p: (p[3] == COR_OFFLINE, p[3] == COR_OUTROS))
    reais = [(_px(la, lo, z)[0] - ox, _px(la, lo, z)[1] - oy) for la, lo, _, _ in ordem]
    desenho = _afastar(reais, 2 * raio + 6, largura, altura, raio + 4)
    # Pino que saiu do lugar ganha uma linha ate a posicao real: cameras a poucos
    # metros (entrada, portaria) ficavam uma em cima da outra mesmo no zoom maximo.
    for (rx, ry), (x, y) in zip(reais, desenho):
        if math.hypot(x - rx, y - ry) > 3:
            d.line((rx, ry, x, y), fill=(40, 40, 40), width=3)
            d.ellipse((rx - 4, ry - 4, rx + 4, ry + 4), fill=(40, 40, 40))
    for (la, lo, rot, cor), (x, y) in zip(ordem, desenho):
        d.ellipse((x - raio - 3, y - raio - 3, x + raio + 3, y + raio + 3), fill="white")
        d.ellipse((x - raio, y - raio, x + raio, y + raio), fill=cor)
        if rot:
            d.text((x, y), str(rot)[:3], fill="white", font=fonte, anchor="mm")
    fa = _fonte(14)
    w = d.textlength(ATRIBUICAO, font=fa)
    d.rectangle((largura - w - 14, altura - 24, largura, altura), fill=(255, 255, 255))
    d.text((largura - w - 7, altura - 12), ATRIBUICAO, fill=(70, 70, 70), font=fa, anchor="lm")
    return mapa


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


def _pontos_do_mapa() -> List[Dict[str, Any]]:
    """Todos os pontos das camadas do Mapa do cliente atual (nome, posicao, cor dos 'outros')."""
    from app.core.tenant_context import get_current_tenant_slug, tenant_kmz_input_dir

    if not get_current_tenant_slug():
        return []
    from app.core import permissions

    liberadas = None
    if permissions.sites_da_sessao() is not None:
        # usuario com restricao de site: so as camadas que o Mapa mostra a ele
        from app.api.endpoints.tools import _list_kmz_import_layers

        liberadas = {str(l.get("id") or "") for l in _list_kmz_import_layers(include_features=False)}
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
        cor = str(meta.get("cor_outros") or "") or COR_OUTROS
        camada = str(meta.get("label") or meta.get("original_name") or geo.stem)
        motivos = meta.get("motivos") if isinstance(meta.get("motivos"), dict) else {}
        for f in dados.get("features") or []:
            g = (f or {}).get("geometry") or {}
            if g.get("type") != "Point" or len(g.get("coordinates") or []) < 2:
                continue
            c = _coordenadas({"lat": g["coordinates"][1], "lon": g["coordinates"][0]})
            if c:
                nome = _to_text(((f or {}).get("properties") or {}).get("name"))
                out.append({"nome": nome, "pos": c, "camada": camada, "cor": cor,
                            "motivo": motivos.get(nome.strip().lower()) or {}})
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


def _legenda(styles, largura: float, tem_outros: bool, cor_outros: str) -> Table:
    itens = [(COR_ONLINE, "Online"), (COR_OFFLINE, "Offline"), (COR_SEM_STATUS, "Sem status")]
    if tem_outros:
        itens.append((cor_outros, "Ponto do mapa sem camera"))
    celulas = []
    for cor, txt in itens:
        celulas += [_p("", styles["small"], fallback=""), _p(txt, styles["small"])]
    t = Table([celulas], colWidths=[10, 120] * len(itens), hAlign="LEFT")
    cmds = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3)]
    for i, (cor, _) in enumerate(itens):
        cmds.append(("BACKGROUND", (2 * i, 0), (2 * i, 0), colors.HexColor(cor)))
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
    pontos = _pontos_do_mapa()
    titulos = {_to_text(c.get("titulo")).strip().lower() for c in cams}
    for c in cams:
        c["_pos"] = _posicao_camera(c, mapa_nomes)
        c["_status"] = _status(c)
        c["_num"] = _numero(_to_text(c.get("titulo")))
        if c["_pos"]:
            c["lat"], c["lon"] = c["_pos"]
        conn = _to_text(c.get("remote_connector_id") or c.get("connector_id"))
        c["_rec"] = gravacao.get((conn, _to_text(c.get("ip")))) or gravacao.get(("", _to_text(c.get("ip"))))
        c["_foto"] = _pick_image_path(c)
    sem_camera = [p for p in pontos if p["nome"].strip().lower() not in titulos]
    cor_outros = sem_camera[0]["cor"] if sem_camera else COR_OUTROS
    com_pos = [c for c in cams if c["_pos"]]
    areas = agrupar_areas(cams)

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
    n_mapas = 1 + len(areas)
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
    story.append(Spacer(1, 3 * mm))
    geral = renderizar_mapa(
        [(c["_pos"][0], c["_pos"][1], c["_num"], _cor_status(c["_status"])) for c in com_pos]
        + [(p["pos"][0], p["pos"][1], _numero(p["nome"]), p["cor"]) for p in sem_camera],
        1800, 860, raio=15)
    passo(1, n_mapas, "mapas")
    if geral is not None:
        story.append(_imagem_pdf(geral, util))
        story.append(Spacer(1, 2 * mm))
        story.append(_legenda(styles, util, bool(sem_camera), cor_outros))
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

    # ---- uma pagina por area
    for i, a in enumerate(areas, 1):
        story.append(PageBreak())
        ac = a["cams"]
        on = sum(1 for c in ac if c["_status"] == "online")
        story.append(_p(f"Area {i}  |  {a['nome']}", styles["title"]))
        story.append(_p(f"{len(ac)} camera{'s' if len(ac) != 1 else ''}  -  {on} online  -  {len(ac) - on} fora",
                        styles["subtitle"]))
        img = renderizar_mapa([(c["_pos"][0], c["_pos"][1], c["_num"], _cor_status(c["_status"])) for c in ac],
                              1800, 620, raio=19)
        passo(1 + i, n_mapas, "mapas")
        if img is not None:
            story.append(_imagem_pdf(img, util))
            story.append(Spacer(1, 3 * mm))
        linhas = []
        for c in ac:
            rec = c["_rec"]
            sufixo = {"sim": " - gravando", "nao": " - NAO GRAVA"}.get(rec["gravando"], "") if rec else ""
            rec_txt = f"{rec['gravador']} canal {rec['canal']}{sufixo}" if rec else "fora de gravador"
            linhas.append([
                _p(c["_num"] or "-", styles["small_b"]), _p(c.get("titulo"), styles["small_b"]),
                _p(c.get("ip"), styles["mono"]),
                _p(c["_status"].upper(), styles["small_b"], color=OK if c["_status"] == "online" else BAD),
                _p(rec_txt, styles["small"]), _p("sim" if c["_foto"] is not None else "nao", styles["small"]),
                _p(c.get("modelo") or c.get("model"), styles["small"]), _p_localizacao(c, styles["mono"]),
            ])
        story.append(_tabela(["N", "CAMERA", "IP", "STATUS", "GRAVADOR", "FOTO", "MODELO", "LOCALIZACAO"],
                             linhas, [5, 34, 15, 11, 34, 7, 18, 16], styles, accent, util))

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
