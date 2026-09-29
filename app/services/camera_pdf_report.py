"""Relatorio de inventario de Cameras IP em PDF DE VERDADE (ReportLab).

O gerador antigo (build_inventory_pdf_report, em pdf_inventory_report.py)
desenha cada pagina com PIL e salva como JPEG: o PDF sai sem uma unica fonte
embarcada. Nao da para selecionar um IP, nem pesquisar dentro do documento, e
qualquer zoom borra -- e literalmente uma foto de um relatorio. O usuario
descreveu exatamente assim: "ainda ta como foto".

Aqui o documento e vetorial, espelhando recorder_pdf_report.py, que e o
formato aprovado. Os auxiliares de estilo, cabecalho, KPI e tabela chave-valor
sao IMPORTADOS de la de proposito: se um dia o visual mudar, muda nos dois
relatorios junto, em vez de um envelhecer sem ninguem notar.

Sempre em paisagem. A tabela de inventario tem colunas demais (ate dez, com os
dados de switch ou de OLT) para caber em retrato sem cortar o titulo.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    LongTable,
    PageBreak,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.paths import OUTPUT_DIR
from app.services.pdf_inventory_report import (
    _camera_online,
    _camera_site,
    _col_value,
    _faixa_de_ips,
    _pick_image_path,
    _sort_inventory_rows,
    _to_text,
)
from app.services.recorder_pdf_report import (
    BAD,
    BORDER,
    INK,
    OK,
    STRIPE,
    _accent,
    _header_footer_factory,
    _kpis,
    _kv_table,
    _p,
    _styles,
)

ProgressCb = Optional[Callable[[int, int, str], None]]

# Nome da coluna -> peso da largura. O peso e relativo: a largura real sai da
# divisao proporcional do espaco util, entao a tabela se reajusta sozinha
# quando uma coluna vazia e descartada.
_PESOS: Dict[str, int] = {
    "IP": 20,
    "Titulo": 46,
    "Status": 14,
    "Local": 22,
    "Modelo": 26,
    "MAC": 30,
    "Switch": 26,
    "Switch IP": 20,
    "Porta": 10,
    "VLAN": 10,
    "PON": 9,
    "ONU ID": 10,
    "ONU Name": 24,
    "ONU Serial": 26,
}

_VAZIO = ("", "-", "--", "n/a", "none", "null")
_FIXAS = ("IP", "Titulo", "Status")


def _colunas(include_switch: bool, include_olt: bool, rows: List[Dict[str, Any]]) -> List[str]:
    """Colunas do modo, menos as que estao vazias em TODAS as linhas.

    Carregar quatro colunas de switch em branco num site que nao tem switch so
    espreme o resto da tabela.
    """
    base = ["IP", "Titulo", "Status", "Local", "Modelo", "MAC"]
    if include_switch:
        base += ["Switch", "Switch IP", "Porta", "VLAN"]
    elif include_olt:
        base += ["PON", "ONU ID", "ONU Name", "ONU Serial"]
    return [
        c for c in base
        if c in _FIXAS
        or any(_to_text(_col_value(r, c)).strip().lower() not in _VAZIO for r in rows)
    ]


def _tabela_inventario(
    rows: List[Dict[str, Any]],
    colunas: List[str],
    styles: Dict[str, ParagraphStyle],
    accent: colors.Color,
    usable_w: float,
) -> LongTable:
    pesos = [_PESOS.get(c, 20) for c in colunas]
    soma = sum(pesos) or 1
    larguras = [usable_w * p / soma for p in pesos]

    MONO = {"IP", "MAC", "Switch IP", "ONU Serial"}
    data: List[List[Any]] = [[_p(c.upper(), styles["th"]) for c in colunas]]
    for r in rows:
        online = _camera_online(r)
        linha: List[Any] = []
        for c in colunas:
            val = _col_value(r, c)
            if c == "Status":
                linha.append(_p((val or "-").upper(), styles["small_b"], color=OK if online else BAD))
            elif c == "Titulo":
                linha.append(_p(val, styles["small_b"]))
            elif c in MONO:
                linha.append(_p(val, styles["mono"]))
            else:
                linha.append(_p(val, styles["small"]))
        data.append(linha)

    table = LongTable(data, colWidths=larguras, repeatRows=1, splitByRow=1, hAlign="LEFT")
    cmds: List[Any] = [
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), STRIPE))
    table.setStyle(TableStyle(cmds))
    return table


def _miniatura(caminho, largura_pt: float):
    """Snapshot reduzido para a largura em que sera exibido, em memoria.

    `largura_pt` esta em pontos (1/72"). Multiplicamos por 2 para o zoom do
    leitor continuar nitido -- e ainda assim e uma fracao do arquivo original.
    Devolve (buffer JPEG, proporcao altura/largura) ou None se nao der. O
    buffer vai direto para o RLImage, que aceita qualquer objeto com .read();
    um ImageReader ele NAO aceita -- tenta fazer splitext no nome do arquivo.
    """
    from io import BytesIO

    from PIL import Image as PILImage

    try:
        with PILImage.open(caminho) as im:
            im = im.convert("RGB")
            proporcao = (im.height / im.width) if im.width else 0.5625
            alvo = max(320, int(largura_pt * 2))
            if im.width > alvo:
                im = im.resize((alvo, max(1, int(alvo * proporcao))), PILImage.LANCZOS)
            buf = BytesIO()
            im.save(buf, "JPEG", quality=72, optimize=True)
        buf.seek(0)
        return buf, proporcao
    except Exception:
        return None


def _galeria(rows: List[Dict[str, Any]], styles: Dict[str, ParagraphStyle], usable_w: float) -> List[Any]:
    """Snapshot de cada camera, quatro por linha. Camera sem foto nao entra."""
    from reportlab.platypus import Image as RLImage

    cols = 4
    cell_w = usable_w / cols
    img_w = cell_w - 8
    cards: List[Any] = []
    for r in rows:
        caminho = _pick_image_path(r)
        if caminho is None:
            continue
        legenda = f"{_to_text(r.get('titulo') or r.get('title'))} - {_to_text(r.get('ip'))}"
        inner: List[Any] = [_p(legenda, styles["cap"])]
        mini = _miniatura(caminho, img_w)
        if mini is None:
            inner.append(_p("sem imagem", styles["small"]))
        else:
            buf, ratio = mini
            inner.append(RLImage(buf, width=img_w, height=img_w * ratio))
        cards.append(inner)
    if not cards:
        return []
    grid: List[List[Any]] = []
    for i in range(0, len(cards), cols):
        linha = cards[i:i + cols]
        while len(linha) < cols:
            linha.append("")
        grid.append(linha)
    table = Table(grid, colWidths=[cell_w] * cols)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [table]


def build_inventory_pdf_report(
    rows: Iterable[Dict[str, Any]],
    site: str = "",
    company_name: str = "",
    logo_path: Optional[Path] = None,
    include_olt: bool = True,
    include_switch: bool = False,
    module_label: str = "Cameras IP",
    report_color: str = "",
    include_photos: bool = True,
    progress_cb: ProgressCb = None,
) -> Path:
    """Mesma assinatura do gerador antigo, para ser troca direta no endpoint."""
    rows_list = _sort_inventory_rows([dict(r) for r in rows if isinstance(r, dict)])
    site_label = _to_text(site) or "Todos os sites"
    accent = _accent(report_color)

    reports_dir = OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname_site = site_label.replace(" ", "_").replace("/", "_")
    out = reports_dir / f"inventory-report-{fname_site}-{ts}.pdf"

    styles = _styles()
    page_w, page_h = landscape(A4)
    margin = 14 * mm
    usable_w = page_w - 2 * margin

    header = _header_footer_factory(
        module_label or "Cameras IP", accent,
        f"{site_label}  -  {datetime.now().strftime('%d/%m/%Y %H:%M')}",
    )
    doc = SimpleDocTemplate(
        str(out), pagesize=landscape(A4), leftMargin=margin, rightMargin=margin,
        topMargin=18 * mm, bottomMargin=14 * mm,
        title=f"Relatorio de inventario - {site_label}",
        author="SightOps", subject="Relatorio tecnico de cameras IP",
    )

    total = len(rows_list)
    online = sum(1 for r in rows_list if _camera_online(r))
    com_foto = sum(1 for r in rows_list if _pick_image_path(r) is not None)

    story: List[Any] = []
    comp = f"  -  {company_name}" if _to_text(company_name) else ""
    story.append(_p(f"Relatorio tecnico | {module_label}", styles["title"]))
    story.append(_p(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y as %H:%M')}  -  Site: {site_label}  -  "
        f"{total} camera{'s' if total != 1 else ''}{comp}", styles["subtitle"]))
    story.append(_kpis([
        ("Cameras", str(total), INK), ("Online", str(online), OK),
        ("Offline", str(total - online), BAD), ("Com foto", str(com_foto), INK),
    ], styles, usable_w))
    story.append(Spacer(1, 5 * mm))

    # ---- Resumo por site ----
    sites: List[Tuple[str, List[Dict[str, Any]]]] = []
    indice: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows_list:
        chave = _camera_site(r)
        if chave not in indice:
            indice[chave] = []
            sites.append((chave, indice[chave]))
        indice[chave].append(r)

    if sites:
        story.append(_p("Resumo por site", styles["h2"]))
        for nome, itens in sites:
            n_on = sum(1 for r in itens if _camera_online(r))
            n_foto = sum(1 for r in itens if _pick_image_path(r) is not None)
            modelos = sorted({_to_text(r.get("modelo") or r.get("model")) for r in itens
                              if _to_text(r.get("modelo") or r.get("model"))})
            modelo_txt = ", ".join(modelos[:3]) + (f" (+{len(modelos) - 3})" if len(modelos) > 3 else "")
            pares = [
                ("Cameras", str(len(itens))),
                ("Online", f"{n_on} de {len(itens)}"),
                ("Offline", str(len(itens) - n_on)),
                ("Com foto", f"{n_foto} de {len(itens)}"),
                ("Faixa de IP", _faixa_de_ips(itens)),
                ("Modelos", modelo_txt or "-"),
            ]
            caixa = Table([[[_p(nome, styles["h2"]), _kv_table(pares, styles, usable_w - 12)]]],
                          colWidths=[usable_w])
            caixa.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ]))
            story.append(caixa)
            story.append(Spacer(1, 3 * mm))

    # ---- Inventario detalhado ----
    # Sem PageBreak forcado: a tabela flui logo abaixo do resumo e ocupa o
    # espaco que sobraria em branco. O CondPageBreak so evita titulo orfao.
    story.append(Spacer(1, 4 * mm))
    story.append(CondPageBreak(45 * mm))
    story.append(_p(f"Inventario detalhado | {module_label}", styles["title"]))
    story.append(_p(f"Site: {site_label}  -  {total} camera{'s' if total != 1 else ''}", styles["subtitle"]))
    if rows_list:
        colunas = _colunas(include_switch, include_olt, rows_list)
        story.append(_tabela_inventario(rows_list, colunas, styles, accent, usable_w))
    else:
        story.append(_p("Nenhuma camera encontrada para o filtro atual.", styles["small"]))

    if progress_cb:
        progress_cb(total, max(1, total), "tabela")

    # ---- Galeria de snapshots ----
    if include_photos:
        fotos = _galeria(rows_list, styles, usable_w)
        if fotos:
            story.append(PageBreak())
            story.append(_p(f"Galeria de snapshots | {module_label}", styles["title"]))
            story.append(_p(f"Site: {site_label}  -  {com_foto} foto{'s' if com_foto != 1 else ''}",
                            styles["subtitle"]))
            story.extend(fotos)

    if progress_cb:
        progress_cb(total, max(1, total), "pdf")

    doc.build(story, onFirstPage=header, onLaterPages=header)
    return out
