"""Maquete 3D -- PDF do projeto (relatorio) e do orcamento, A4 retrato.

A tela calcula tudo (cabos pelo caminho da calha, portas, rack) e manda aqui
os dados ja prontos + as imagens da maquete (JPEG tirado do 3D). Este modulo
so diagrama. Os totais do orcamento sao refeitos aqui, nunca confiados.

Relatorio:  cabecalho, resumo, 1 vistas, 2 cameras, 3 cabos, 4 rack,
            5 orcamento (opcional), observacao, assinatura.
Orcamento:  cabecalho, itens por grupo, subtotal/desconto/total, condicoes.
"""
from __future__ import annotations

import base64
import io
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.access_control_relatorios_pdf import LARGURA, MARGEM, MUTED, TEXT, _assinatura, _Paginas

ESCURO = colors.HexColor("#2b3a42")
LINHA = colors.HexColor("#d5dce0")
SUAVE = colors.HexColor("#f3f5f7")
VERDE = colors.HexColor("#087f5b")

MAX_IMAGENS = 40          # capa + 1 por pavimento + 1 por câmera
MAX_IMAGEM = 4 * 1024 * 1024
MAX_LINHAS = 600

E = {
    "kicker": ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=VERDE),
    "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=TEXT),
    "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED),
    "dir": ParagraphStyle("d", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, alignment=2),
    "sec": ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=TEXT,
                          spaceBefore=14, spaceAfter=2),
    "secsub": ParagraphStyle("secsub", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, spaceAfter=6),
    "texto": ParagraphStyle("tx", fontName="Helvetica", fontSize=9, leading=13, textColor=TEXT),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=8, leading=10.4, textColor=TEXT),
    "celind": ParagraphStyle("celind", fontName="Helvetica", fontSize=8, leading=10.4, textColor=TEXT, leftIndent=8),
    "celb": ParagraphStyle("celb", fontName="Helvetica-Bold", fontSize=8, leading=10.4, textColor=TEXT),
    "num": ParagraphStyle("num", fontName="Helvetica", fontSize=8, leading=10.4, textColor=TEXT, alignment=2),
    "numb": ParagraphStyle("numb", fontName="Helvetica-Bold", fontSize=8, leading=10.4, textColor=TEXT, alignment=2),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=6.9, leading=9, textColor=MUTED),
    "thn": ParagraphStyle("thn", fontName="Helvetica-Bold", fontSize=6.9, leading=9, textColor=MUTED, alignment=2),
    "kpirot": ParagraphStyle("kr", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=MUTED),
    "kpival": ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=TEXT),
    "kpisub": ParagraphStyle("ks", fontName="Helvetica", fontSize=7.4, leading=9.6, textColor=MUTED),
    "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=7.6, leading=10.4, textColor=MUTED),
    "legenda": ParagraphStyle("leg", fontName="Helvetica", fontSize=7.6, leading=10, textColor=MUTED, spaceBefore=3),
    "total": ParagraphStyle("tot", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=TEXT, alignment=2),
}


def _t(v: Any, limite: int = 400) -> str:
    return escape(str(v if v is not None else "")[:limite])


def _c(v: Any, estilo: str = "cel") -> Paragraph:
    return Paragraph(_t(v), E[estilo])


def _num(v: Any, casas: int = 1) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    s = f"{n:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _rs(v: Any) -> str:
    return "R$ " + _num(v, 2)


def _f(v: Any, padrao: float = 0.0) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else padrao
    except (TypeError, ValueError):
        return padrao


def _secao(rot: str, sub: str = "") -> List[Any]:
    out: List[Any] = [Paragraph(_t(rot), E["sec"])]
    if sub:
        out.append(Paragraph(_t(sub), E["secsub"]))
    return out


def _tabela(cab: List[str], linhas: List[List[Any]], larguras: List[float], numericas: tuple = (),
            negrito_ultima: bool = False) -> Table:
    th = [Paragraph(_t(c), E["thn"] if i in numericas else E["th"]) for i, c in enumerate(cab)]
    corpo = []
    for ln in linhas[:MAX_LINHAS]:
        corpo.append([x if not isinstance(x, (str, int, float)) else _c(x, "num" if i in numericas else "cel")
                      for i, x in enumerate(ln)])
    t = Table([th] + corpo, colWidths=larguras, repeatRows=1)
    estilo = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, ESCURO),
              ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINHA), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5), ("LEFTPADDING", (0, 0), (-1, -1), 3),
              ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if negrito_ultima and corpo:
        estilo.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, ESCURO))
    t.setStyle(TableStyle(estilo))
    return t


def _kpis(itens: List[tuple]) -> Table:
    cel = []
    for rot, val, sub in itens:
        cel.append([Paragraph(_t(rot), E["kpirot"]), Paragraph(_t(val), E["kpival"]), Paragraph(_t(sub), E["kpisub"])])
    larg = LARGURA / len(itens)
    t = Table([cel], colWidths=[larg] * len(itens))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.4, LINHA),
                           ("INNERGRID", (0, 0), (-1, -1), 0.4, LINHA), ("BACKGROUND", (0, 0), (-1, -1), SUAVE),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _cabecalho(kicker: str, titulo: str, sub: str, usuario: str, logo: Optional[Path]) -> Table:
    esquerda: Any = [Paragraph(_t(kicker), E["kicker"]), Spacer(1, 3), Paragraph(_t(titulo, 160), E["titulo"]),
                     Spacer(1, 2), Paragraph(_t(sub), E["sub"])]
    if logo and Path(logo).is_file():
        try:
            img = Image(str(logo))
            prop = img.imageWidth / float(img.imageHeight or 1)
            img.drawHeight, img.drawWidth = 14 * mm, min(36 * mm, 14 * mm * prop)
            esq = Table([[img, esquerda]], colWidths=[img.drawWidth + 5 * mm, None])
            esq.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            esquerda = esq
        except Exception:  # logo invalido nao derruba o PDF
            pass
    direita = [Paragraph(_t(f"Emitido em {datetime.now().strftime('%d/%m/%Y às %H:%M')}"), E["dir"])]
    if usuario:
        direita.append(Paragraph(_t(f"por {usuario}"), E["dir"]))
    cab = Table([[esquerda, direita]], colWidths=[LARGURA * 0.7, LARGURA * 0.3])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, ESCURO),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return cab


def _imagem(b64: str, largura: float, altura_max: float) -> Optional[Image]:
    try:
        raw = base64.b64decode(str(b64 or "").split(",")[-1], validate=False)
    except Exception:
        return None
    if not raw or len(raw) > MAX_IMAGEM or not (raw[:3] == b"\xff\xd8\xff" or raw[:8] == b"\x89PNG\r\n\x1a\n"):
        return None
    try:
        img = Image(io.BytesIO(raw))
        prop = img.imageHeight / float(img.imageWidth or 1)
        w = largura
        hh = w * prop
        if hh > altura_max:
            hh, w = altura_max, altura_max / prop
        img.drawWidth, img.drawHeight = w, hh
        return img
    except Exception:
        return None


# ---------------------------------------------------------------- orcamento

def calcular_orcamento(orc: Dict[str, Any]) -> Dict[str, Any]:
    """Refaz os totais do orcamento (quantidade x preco, desconto)."""
    itens = []
    for it in (orc.get("itens") or [])[:MAX_LINHAS]:
        if not isinstance(it, dict):
            continue
        qtd, preco = max(0.0, _f(it.get("qtd"))), max(0.0, _f(it.get("preco")))
        if qtd <= 0:
            continue
        itens.append({"grupo": str(it.get("grupo") or "Outros")[:60], "descricao": str(it.get("descricao") or "")[:200],
                      "qtd": qtd, "un": str(it.get("un") or "un")[:10], "preco": preco, "total": round(qtd * preco, 2)})
    subtotal = round(sum(i["total"] for i in itens), 2)
    desc_pct = min(100.0, max(0.0, _f(orc.get("desconto_pct"))))
    desconto = round(subtotal * desc_pct / 100, 2)
    return {"itens": itens, "subtotal": subtotal, "desconto_pct": desc_pct, "desconto": desconto,
            "total": round(subtotal - desconto, 2), "condicoes": str(orc.get("condicoes") or "")[:2000],
            "validade_dias": int(max(0, min(365, _f(orc.get("validade_dias"), 15)))),
            "sem_preco": sum(1 for i in itens if i["preco"] <= 0)}


def _bloco_orcamento(orc: Dict[str, Any], numero: str = "") -> List[Any]:
    o = calcular_orcamento(orc)
    h: List[Any] = _secao(f"{numero}Orçamento".strip(), f"Válido por {o['validade_dias']} dias a partir da emissão.")
    if not o["itens"]:
        return h + [Paragraph("Nenhum item com quantidade.", E["nota"])]
    larg = [LARGURA * 0.50, LARGURA * 0.1, LARGURA * 0.08, LARGURA * 0.15, LARGURA * 0.17]
    linhas: List[List[Any]] = []
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for it in o["itens"]:
        grupos.setdefault(it["grupo"], []).append(it)
    for g, its in grupos.items():
        soma = sum(i["total"] for i in its)
        linhas.append([_c(g, "celb"), "", "", "", _c(_rs(soma) if soma else "—", "numb")])
        for it in its:
            q = _num(it["qtd"], 0 if float(it["qtd"]).is_integer() else 2)
            linhas.append([_c(it["descricao"], "celind"), q, it["un"], _rs(it["preco"]) if it["preco"] else "a definir", _rs(it["total"]) if it["preco"] else "—"])
    t = _tabela(["Item", "Qtd", "Un", "Preço unit.", "Total"], linhas, larg, numericas=(1, 3, 4))
    h.append(t)
    tot = [["Subtotal", _rs(o["subtotal"])]]
    if o["desconto"]:
        tot.append([f"Desconto ({_num(o['desconto_pct'], 1)}%)", "− " + _rs(o["desconto"])])
    tot.append(["Total", _rs(o["total"])])
    tt = Table([[_c(a, "num"), _c(b, "numb")] for a, b in tot[:-1]] + [[Paragraph("Total", E["total"]), Paragraph(_t(tot[-1][1]), E["total"])]],
               colWidths=[LARGURA * 0.83, LARGURA * 0.17])
    tt.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 1, ESCURO), ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    h += [Spacer(1, 4), tt]
    if o["sem_preco"]:
        h.append(Paragraph(_t(f"{o['sem_preco']} item(ns) sem preço, marcados \"a definir\", não entram no total."), E["nota"]))
    if o["condicoes"]:
        h += [Spacer(1, 6), Paragraph("<b>Condições</b>", E["texto"])]
        h += [Paragraph(_t(ln, 500) or "&nbsp;", E["texto"]) for ln in o["condicoes"].splitlines()[:40]]
    return h


# ---------------------------------------------------------------- relatorio

def _sub_projeto(p: Dict[str, Any]) -> str:
    partes = [p.get("local") or "", p.get("arquivo") or "", ("escala " + p["escala"]) if p.get("escala") else "",
              ", ".join(p.get("pisos") or [])]
    return " · ".join(x for x in partes if x)


def gerar_pdf(projeto: Dict[str, Any], dados: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    tipo = "orcamento" if dados.get("tipo") == "orcamento" else "relatorio"
    nome = projeto.get("nome") or "Projeto"
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"{'Orçamento' if tipo == 'orcamento' else 'Projeto de CFTV'} · {nome}",
                            author="SightOps", subject="Maquete 3D")
    if tipo == "orcamento":
        h = [_cabecalho("ORÇAMENTO · PROJETO DE CFTV", nome, _sub_projeto(projeto), usuario, logo)]
        r = dados.get("resumo") or {}
        h += [Spacer(1, 10), _kpis([
            ("CÂMERAS", _num(r.get("cameras"), 0), "no projeto"),
            ("CABO UTP", _num(r.get("metros"), 0) + " m", str(r.get("categoria") or "")),
            ("RACK", str(r.get("rack") or "—"), str(r.get("rackUsado") or "")),
            ("TOTAL", _rs(calcular_orcamento(dados.get("orcamento") or {})["total"]), "com desconto"),
        ])]
        h += _bloco_orcamento(dados.get("orcamento") or {})
        h += [Spacer(1, 22), _assinatura("Responsável pelo orçamento")]
        rodape = f"SightOps · Orçamento · {nome}"
    else:
        h = _relatorio(projeto, dados, usuario, logo)
        rodape = f"SightOps · Projeto de CFTV · {nome}"
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape[:120], **k))
    return buf.getvalue()


def _relatorio(projeto: Dict[str, Any], dados: Dict[str, Any], usuario: str, logo: Optional[Path]) -> List[Any]:
    nome = projeto.get("nome") or "Projeto"
    r = dados.get("resumo") or {}
    h: List[Any] = [_cabecalho("PROJETO DE CFTV · MAQUETE 3D", nome, _sub_projeto(projeto), usuario, logo)]
    imgs = [i for i in (dados.get("imagens") or [])[:MAX_IMAGENS] if isinstance(i, dict)]
    capa = next((i for i in imgs if i.get("tipo") == "capa"), None)
    if capa:
        img = _imagem(capa.get("jpg") or "", LARGURA, 128 * mm)
        if img:
            h += [Spacer(1, 8), img]
    h += [Spacer(1, 10), _kpis([
        ("CÂMERAS", _num(r.get("cameras"), 0), f"{_num(r.get('online'), 0)} online · {_num(r.get('projeto'), 0)} de projeto"),
        ("CABO UTP " + str(r.get("categoria") or ""), _num(r.get("metros"), 0) + " m",
         f"{_num(r.get('caixas305'), 0)} caixa(s) de 305 m · maior lance {_num(r.get('maior'), 1)} m"),
        ("CAIXAS DE PASSAGEM", _num(r.get("caixasPassagem"), 0), f"eletrocalha {_num(r.get('eletrocalha'), 0)} m"),
        ("RACK", str(r.get("rack") or "—"), str(r.get("rackUsado") or "")),
    ])]
    if projeto.get("observacao"):
        h += [Spacer(1, 8), Paragraph("<b>Observação:</b> " + _t(projeto["observacao"], 1000), E["texto"])]
    n = 1
    plantas = [i for i in imgs if i.get("tipo") in ("planta", None, "")]
    if plantas:
        h += [CondPageBreak(75 * mm)] + _secao(f"{n}  Pavimentos vistos de cima",
                                               "Câmeras com o campo de visão e o caminho dos cabos; a cor mostra a situação no momento da emissão.")
        for im in plantas:
            img = _imagem(im.get("jpg") or "", LARGURA, 100 * mm)
            if img:
                h.append(KeepTogether([img, Paragraph(_t(im.get("titulo") or ""), E["legenda"]), Spacer(1, 8)]))
        n += 1
    povs = [i for i in imgs if i.get("tipo") == "pov"]
    if povs:
        h += [CondPageBreak(80 * mm)] + _secao(f"{n}  Área coberta por cada câmera", "Campo de visão calculado pela posição, direção e lente de cada câmera na maquete.")
        col = 3
        larg = (LARGURA - (col - 1) * 4 * mm) / col
        celulas = []
        for im in povs:
            img = _imagem(im.get("jpg") or "", larg, larg * 0.625)
            celulas.append([img, Paragraph(_t(im.get("titulo") or "", 120), E["legenda"])] if img else [Paragraph(_t(im.get("titulo") or ""), E["legenda"])])
        linhas = [celulas[i:i + col] + [""] * (col - len(celulas[i:i + col])) for i in range(0, len(celulas), col)]
        grade = Table(linhas, colWidths=[larg + 4 * mm] * (col - 1) + [larg])
        grade.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        h.append(grade)
        n += 1
    cams = [c for c in (dados.get("cameras") or []) if isinstance(c, dict)]
    h += [CondPageBreak(50 * mm)] + _secao(f"{n}  Câmeras", "Identifica rosto ≈ 250 px/m; reconhece pessoa ≈ 125 px/m (valores de catálogo).")
    if cams:
        larg = [LARGURA * x for x in (0.06, 0.25, 0.12, 0.2, 0.07, 0.09, 0.09, 0.12)]
        h.append(_tabela(["Cabo", "Câmera", "Pavimento", "Modelo", "Abert.", "Rosto até", "Situação", "Porta"],
                         [[c.get("cabo"), c.get("nome"), c.get("piso"), c.get("modelo"), c.get("abertura"),
                           c.get("ident"), c.get("situacao"), c.get("porta")] for c in cams], larg, numericas=(4, 5)))
    else:
        h.append(Paragraph("Nenhuma câmera posicionada.", E["nota"]))
    n += 1
    if cams:
        h += [CondPageBreak(50 * mm)] + _secao(f"{n}  Cabos", "Medido pelo caminho da eletrocalha, com 3 m de folga no rack e 0,5 m na câmera.")
        larg = [LARGURA * x for x in (0.07, 0.3, 0.5, 0.13)]
        linhas = [[c.get("cabo"), c.get("nome"), c.get("via") or "direto no rack", _num(c.get("metros"), 1)] for c in cams]
        linhas.append([_c("", "celb"), _c("Total", "celb"), _c(f"Com 10% de perda: {_num(r.get('metros10'), 0)} m", "cel"),
                       _c(_num(r.get("metros"), 1), "numb")])
        h.append(_tabela(["Cabo", "Câmera", "Passa por", "Metros"], linhas, larg, numericas=(3,), negrito_ultima=True))
        n += 1
    rack = [x for x in (dados.get("rack") or []) if isinstance(x, dict)]
    if rack:
        h += [CondPageBreak(60 * mm)] + _secao(f"{n}  Rack · {r.get('rack') or ''}", f"{r.get('rackUsado') or ''} · PoE {r.get('poe') or '—'}")
        h.append(_tabela(["Posição", "Equipamento", "Uso"], [[x.get("u"), x.get("nome"), x.get("uso") or ""] for x in rack],
                         [LARGURA * 0.14, LARGURA * 0.56, LARGURA * 0.3]))
        n += 1
    if dados.get("incluirOrcamento") and dados.get("orcamento"):
        h += [CondPageBreak(70 * mm)] + _bloco_orcamento(dados["orcamento"], f"{n}  ")
    h += [Spacer(1, 22), _assinatura("Responsável técnico")]
    return h
