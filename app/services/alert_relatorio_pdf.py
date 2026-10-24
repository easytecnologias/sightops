"""PDF do relatorio do Alerta (A4 retrato), no formato de relatorio analitico
de central (SOC / despacho de emergencia):

  pagina 1  conclusao do periodo numa frase, 4 indicadores com meta e
            comparacao com o periodo anterior, pedidos por dia, distribuicao
            do tempo para assumir (verde = no prazo), pedidos por hora e
            destaques;
  depois    o que conferir, por site e, como anexo, a lista de atendimentos.

Recebe o dicionario de alert_relatorio.gerar e devolve os bytes (nada vai
para disco)."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from app.services.access_control_relatorios_pdf import (AMBER, BORDER, DANGER, LARGURA, MARGEM, MUTED, PRIMARY,
                                                        PRIMARY_SOFT, SOFT, TEXT, _assinatura, _br, _num, _p,
                                                        _Paginas)

DANGER_SOFT = colors.HexColor("#fff0f0")
AMBER_SOFT = colors.HexColor("#fff6df")
ZEBRA = colors.HexColor("#fafbfc")
GRADE = colors.HexColor("#eef1f3")
BARRA = colors.HexColor("#3a7ca5")      # volume (neutro: nao e bom nem ruim)
VERDE = colors.HexColor("#2f9e44")
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

E = {
    "frase": ParagraphStyle("frase", fontName="Helvetica", fontSize=10.5, leading=15, textColor=TEXT),
    "sec": ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=TEXT, spaceBefore=14, spaceAfter=2),
    "secsub": ParagraphStyle("secsub", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, spaceAfter=6),
    "rot": ParagraphStyle("rot", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=MUTED),
    "val": ParagraphStyle("val", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=TEXT),
    "ctx": ParagraphStyle("ctx", fontName="Helvetica", fontSize=7.4, leading=9.6, textColor=MUTED),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=8.4, leading=11, textColor=TEXT),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED),
    "dia": ParagraphStyle("dia", fontName="Helvetica-Bold", fontSize=8.4, leading=11, textColor=TEXT),
    "chip": ParagraphStyle("chip", fontName="Helvetica-Bold", fontSize=8.2, leading=10, textColor=TEXT),
    "item": ParagraphStyle("item", fontName="Helvetica", fontSize=8.6, leading=12.5, textColor=TEXT, leftIndent=9, bulletIndent=0),
    "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=7.4, leading=10.2, textColor=MUTED),
}


# ---------------------------------------------------------------- texto

def _t(txt: Any) -> str:
    return escape(str(txt if txt not in (None, "") else "—"))


def _cel(html: str, estilo: str = "cel") -> Paragraph:
    """Celula com marcacao minima (<b>, <br/>, <font>); o texto ja vem escapado."""
    return Paragraph(html, E[estilo])


def _cinza(txt: str) -> str:
    return f'<font color="#66747e" size="7.4">{txt}</font>'


def _tempo(seg: Any) -> str:
    """Compacto ("1m 26s"): cabe na coluna sem quebrar."""
    if seg is None:
        return "—"
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s" if m else f"{s}s"


def _secao(titulo: str, sub: str = "") -> List[Any]:
    return [Paragraph(_t(titulo), E["sec"])] + ([Paragraph(_t(sub), E["secsub"])] if sub else [Spacer(1, 4)])


def _variacao(atual: Any, antes: Any, menor_melhor: bool = False, pct: bool = False, tempo: bool = False) -> str:
    """'▲ 3 vs anterior' com cor: verde quando melhorou, vermelho quando piorou."""
    if atual is None or antes is None:
        return _cinza("sem período anterior para comparar")
    dif = atual - antes
    if dif == 0:
        return _cinza("igual ao período anterior")
    melhor = dif < 0 if menor_melhor else dif > 0
    cor = "#2f9e44" if melhor else "#c92a2a"
    seta = "▲" if dif > 0 else "▼"
    valor = f"{abs(dif)} pp" if pct else (_tempo(abs(dif)) if tempo else _num(abs(dif)))
    return f'<font color="{cor}"><b>{seta} {valor}</b></font> ' + _cinza("vs período anterior")


# ---------------------------------------------------------------- graficos

def _barras(valores: List[int], rotulos: List[str], largura: float, altura: float,
            cores: Optional[List[Any]] = None, destaque: Optional[List[int]] = None,
            rotulo_cada: int = 1, mostrar_valor: bool = True) -> Drawing:
    """Grafico de barras simples e legivel: grade leve, valor em cima da barra,
    rotulos embaixo. `destaque` pinta a parte de baixo da barra (ex.: coacao)."""
    d = Drawing(largura, altura)
    base, topo, esq = 16, 12, 4
    alt_util = altura - base - topo
    maior = max(valores + [1])
    # Escala "redonda" para a grade (1, 2, 5, 10...).
    passo = next(p for p in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000) if maior / p <= 4)
    teto = passo * -(-maior // passo)
    for v in range(0, teto + 1, passo):
        y = base + alt_util * v / teto
        d.add(Line(esq, y, largura, y, strokeColor=GRADE if v else BORDER, strokeWidth=0.6))
    n = len(valores)
    vao = (largura - esq) / max(1, n)
    larg_barra = max(2.0, vao * 0.62)
    for i, v in enumerate(valores):
        x = esq + i * vao + (vao - larg_barra) / 2
        h = alt_util * v / teto
        if v:
            d.add(Rect(x, base, larg_barra, h, fillColor=(cores[i] if cores else BARRA), strokeColor=None))
            if destaque and destaque[i]:
                d.add(Rect(x, base, larg_barra, alt_util * destaque[i] / teto, fillColor=DANGER, strokeColor=None))
            if mostrar_valor:
                d.add(String(x + larg_barra / 2, base + h + 2.5, str(v), fontName="Helvetica-Bold", fontSize=6.6,
                             fillColor=TEXT, textAnchor="middle"))
        # O ultimo rotulo so entra se nao encostar no anterior.
        if i % rotulo_cada == 0 or (i == n - 1 and (n - 1) % rotulo_cada >= rotulo_cada / 2):
            d.add(String(x + larg_barra / 2, 5, rotulos[i], fontName="Helvetica", fontSize=6.2, fillColor=MUTED,
                         textAnchor="middle"))
    return d


def _quadro(titulo: str, sub: str, desenho: Drawing, legenda: str = "") -> Table:
    corpo = [_cel(f"<b>{_t(titulo)}</b>", "chip"), _cel(_cinza(_t(sub)), "ctx"), Spacer(1, 4), desenho]
    if legenda:
        corpo.append(_cel(legenda, "ctx"))
    t = Table([[corpo]], colWidths=[desenho.width + 20])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("TOPPADDING", (0, 0), (-1, -1), 9),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
    return t


# ---------------------------------------------------------------- blocos

def _cabecalho(r: Dict[str, Any], usuario: str, logo: Optional[Path]) -> Table:
    local = r["site"] or "Todos os sites"
    gerado = datetime.strptime(r["gerado_em"][:19], "%Y-%m-%d %H:%M:%S")
    periodo = f"{_br(r['de'])} a {_br(r['ate'])}" if r["de"] != r["ate"] else _br(r["de"])
    filtros = [f"Período {periodo}"]
    if r.get("tipo"):
        filtros.append(f"Tipo: {r['tipo_rotulo']}")
    if r.get("busca"):
        filtros.append(f"Busca: {r['busca']}")
    esquerda = [_p("RELATÓRIO GERENCIAL · ALERTA DE PÂNICO", "kicker"), Spacer(1, 3), _p(local, "titulo"),
                Spacer(1, 2), _p(" · ".join(filtros), "sub")]
    cab_esq: Any = esquerda
    if logo and Path(logo).is_file():
        try:
            img = Image(str(logo))
            prop = img.imageWidth / float(img.imageHeight or 1)
            img.drawHeight, img.drawWidth = 15 * mm, min(38 * mm, 15 * mm * prop)
            cab_esq = Table([[img, esquerda]], colWidths=[img.drawWidth + 5 * mm, None])
            cab_esq.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        except Exception:  # logo invalido nao derruba o relatorio
            cab_esq = esquerda
    direita = [_p(f"Gerado em {gerado.strftime('%d/%m/%Y às %H:%M')}", "dir")]
    if usuario:
        direita.append(_p(f"por {usuario}", "dir"))
    cab = Table([[cab_esq, direita]], colWidths=[LARGURA * 0.7, LARGURA * 0.3])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.6, PRIMARY),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return cab


def _conclusao(r: Dict[str, Any]) -> Paragraph:
    """A frase que um gestor le e ja sabe como foi o periodo."""
    rs, meta = r["resumo"], r["meta_assumir_s"] // 60
    if not rs["pedidos"]:
        return Paragraph("Nenhum pedido de ajuda no período. A central não precisou atender nenhum alerta.", E["frase"])
    partes = [f"No período houve <b>{_num(rs['pedidos'])} pedido(s) de ajuda</b> de {_num(rs['pessoas'])} pessoa(s)."]
    if rs["no_prazo_pct"] is not None:
        partes.append(f"<b>{rs['no_prazo_pct']}% foram assumidos em até {meta} min</b> (meta da central) e "
                      f"9 em cada 10 em até <b>{_tempo(rs['p90_assumir_s'])}</b>.")
    if rs["abertos"]:
        partes.append(f'<font color="#c92a2a"><b>{rs["abertos"]} ainda está(ão) aberto(s).</b></font>')
    else:
        partes.append("Nenhum ficou sem encerramento.")
    if rs["coacao"]:
        partes.append(f'<font color="#c92a2a"><b>{rs["coacao"]} foi(ram) coação.</b></font>')
    return Paragraph(" ".join(partes), E["frase"])


def _indicadores(r: Dict[str, Any]) -> Table:
    rs, an, meta = r["resumo"], r["anterior"], r["meta_assumir_s"]
    pct = rs["no_prazo_pct"]
    cor_pct = TEXT if pct is None else (VERDE if pct >= 90 else AMBER if pct >= 70 else DANGER)

    # Volume nao e "bom" nem "ruim": a seta vai sem cor, so com o numero anterior.
    dif = rs["pedidos"] - an["pedidos"]
    anterior_txt = f"vs {_num(an['pedidos'])} no período anterior"
    if dif:
        ctx_pedidos = f"<b>{'▲' if dif > 0 else '▼'} {_num(abs(dif))}</b> " + _cinza(anterior_txt)
    else:
        ctx_pedidos = _cinza(f"igual ao período anterior ({_num(an['pedidos'])})")

    prazo_txt = f"{_num(rs['no_prazo'])} de {_num(rs['assumidos'])} assumidos"
    ctx_prazo = _cinza(prazo_txt) + "<br/>" + _variacao(pct, an["no_prazo_pct"], pct=True)

    mediana_txt = f"mediana · 90% em até {_tempo(rs['p90_assumir_s'])}"
    ctx_tempo = _cinza(mediana_txt) + "<br/>" + _variacao(rs["mediana_assumir_s"], an["mediana_assumir_s"],
                                                           menor_melhor=True, tempo=True)
    ctx_equipe = _cinza(f"mediana · {_num(rs['com_chegada'])} chegada(s) marcada(s)")

    itens = [
        ("PEDIDOS DE AJUDA", _num(rs["pedidos"]), TEXT, ctx_pedidos),
        (f"ASSUMIDOS EM ATÉ {meta // 60} MIN", "—" if pct is None else f"{pct}%", cor_pct, ctx_prazo),
        ("TEMPO PARA ASSUMIR", _tempo(rs["mediana_assumir_s"]), TEXT, ctx_tempo),
        ("ATÉ A EQUIPE CHEGAR", _tempo(rs["mediana_chegada_s"]), TEXT, ctx_equipe),
    ]
    cel = [[_cel(_t(rot), "rot"), Spacer(1, 4), Paragraph(_t(val), ParagraphStyle("v", parent=E["val"], textColor=cor)),
            Spacer(1, 3), _cel(ctx, "ctx")] for rot, val, cor, ctx in itens]
    t = Table([cel], colWidths=[LARGURA / 4] * 4)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11), ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("LINEABOVE", (0, 0), (-1, 0), 2.4, PRIMARY),
    ]))
    return t


def _chips(r: Dict[str, Any]) -> Table:
    rs = r["resumo"]
    itens = [(f"{_num(rs['encerrados'])} encerrados", PRIMARY_SOFT, PRIMARY),
             (f"{_num(rs['cancelados'])} cancelados pela pessoa", SOFT, MUTED),
             (f"{_num(rs['coacao'])} coação", DANGER_SOFT if rs["coacao"] else SOFT, DANGER if rs["coacao"] else MUTED),
             (f"{_num(rs['escalados'])} com Telegram acionado", AMBER_SOFT if rs["escalados"] else SOFT,
              AMBER if rs["escalados"] else MUTED),
             (f"{_num(rs['abertos'])} abertos", DANGER_SOFT if rs["abertos"] else SOFT, DANGER if rs["abertos"] else MUTED)]
    cel = [Paragraph(_t(txt), ParagraphStyle("c", parent=E["chip"], textColor=cor)) for txt, _f, cor in itens]
    t = Table([cel], colWidths=[LARGURA / len(cel)] * len(cel))
    estilo = [("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
              ("LEFTPADDING", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for i, (_txt, fundo, _cor) in enumerate(itens):
        estilo += [("BACKGROUND", (i, 0), (i, 0), fundo), ("LINEAFTER", (i, 0), (i, 0), 3, colors.white)]
    t.setStyle(TableStyle(estilo))
    return t


def _graficos(r: Dict[str, Any]) -> List[Any]:
    h: List[Any] = []
    serie = r["serie"]
    if serie:
        cada = max(1, -(-len(serie) // 16))
        desenho = _barras([s["pedidos"] for s in serie], [s["rotulo"] for s in serie], LARGURA - 20, 46 * mm,
                          destaque=[s["coacao"] for s in serie], rotulo_cada=cada, mostrar_valor=len(serie) <= 40)
        titulo = "Pedidos por semana" if r.get("serie_semanal") else "Pedidos por dia"
        legenda = ""
        if any(s["coacao"] for s in serie):
            legenda = '<font color="#3a7ca5">■</font> pânico &nbsp;&nbsp; <font color="#c92a2a">■</font> coação'
        h += [Spacer(1, 12), _quadro(titulo, "Quantos pedidos de ajuda chegaram em cada dia do período.", desenho, legenda)]

    meio = (LARGURA - 8) / 2 - 20
    faixas = r["faixas_espera"]
    cores = [VERDE if f["no_prazo"] else (AMBER if i == 3 else DANGER) for i, f in enumerate(faixas)]
    d1 = _barras([f["pedidos"] for f in faixas], [f["rotulo"] for f in faixas], meio, 42 * mm, cores=cores)
    q1 = _quadro("Tempo para assumir", f"Verde = dentro da meta de {r['meta_assumir_s'] // 60} min.", d1)
    d2 = _barras(r["por_hora"], [f"{h_:02d}h" for h_ in range(24)], meio, 42 * mm, rotulo_cada=3, mostrar_valor=False)
    q2 = _quadro("Pedidos por hora do dia", "Ajuda a escalar quem fica de plantão em cada horário.", d2)
    lado = Table([[q1, q2]], colWidths=[LARGURA / 2, LARGURA / 2])
    lado.setStyle(TableStyle([("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 4),
                              ("LEFTPADDING", (1, 0), (1, 0), 4), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return h + [Spacer(1, 8), lado]


def _destaques(r: Dict[str, Any]) -> List[Any]:
    if not r["destaques"]:
        return []
    itens = [Paragraph(_t(x), E["item"], bulletText="•") for x in r["destaques"]]
    t = Table([[[_cel("<b>Destaques do período</b>", "chip"), Spacer(1, 4)] + itens]], colWidths=[LARGURA])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("TOPPADDING", (0, 0), (-1, -1), 10),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 12)]))
    return [Spacer(1, 10), t]


def _tabela(cab: List[str], linhas: List[List[Any]], larguras: List[float], extra: Optional[list] = None) -> Table:
    dados = [[_cel(_t(c.upper()), "th") for c in cab]] + linhas
    t = Table(dados, colWidths=[LARGURA * f for f in larguras], repeatRows=1)
    estilo = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, BORDER), ("LINEBELOW", (0, 1), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    t.setStyle(TableStyle(estilo + (extra or [])))
    return t


def _atencao(r: Dict[str, Any]) -> List[Any]:
    if not r["atencao"]:
        return _secao("O que conferir", "Nada fora do esperado: nenhum pedido aberto, coação, Telegram acionado ou "
                                        "espera acima da meta.")
    linhas, extra = [], []
    for i, a in enumerate(r["atencao"], start=1):
        alto = a["nivel"] == "alto"
        cor = "#c92a2a" if alto else "#b86b00"
        motivo = f'<font color="{cor}"><b>{_t(a["texto"])}</b></font>'
        linhas.append([_cel(_t(a["quando"])), _cel(f"<b>{_t(a['pessoa'])}</b>"), _cel(motivo)])
        extra.append(("BACKGROUND", (0, i), (-1, i), DANGER_SOFT if alto else AMBER_SOFT))
    return _secao(f"O que conferir ({len(r['atencao'])})", "Do mais grave ao mais leve.") + [
        _tabela(["Quando", "Pessoa", "Motivo"], linhas, [0.2, 0.28, 0.52], extra)]


def _por_site(r: Dict[str, Any]) -> List[Any]:
    if len(r["por_site"]) <= 1:
        return []
    meta = r["meta_assumir_s"] // 60
    linhas = []
    for g in r["por_site"]:
        pct = g["no_prazo_pct"]
        cor = "#66747e" if pct is None else ("#2f9e44" if pct >= 90 else "#b86b00" if pct >= 70 else "#c92a2a")
        pct_txt = "—" if pct is None else f"{pct}%"
        linhas.append([_cel(f"<b>{_t(g['site'])}</b>"), _cel(_num(g["pedidos"])),
                       _cel(_t(_num(g["coacao"]) if g["coacao"] else "—")),
                       _cel(f'<font color="{cor}"><b>{pct_txt}</b></font>'),
                       _cel(_t(_tempo(g["mediana_assumir_s"]))), _cel(_t(_tempo(g["p90_assumir_s"])))])
    return _secao("Por site", "Onde os pedidos acontecem e como cada site foi atendido.") + [
        _tabela(["Site", "Pedidos", "Coação", f"Em até {meta} min", "Mediana p/ assumir", "90% em até"], linhas,
                [0.3, 0.11, 0.11, 0.15, 0.17, 0.16])]


def _situacao(x: Dict[str, Any]) -> str:
    if x["aberto"]:
        rot, cor = "Aberto", "#c92a2a"
    elif x["status"] == "cancelled":
        rot, cor = "Cancelado pela pessoa", "#66747e"
    else:
        rot, cor = "Encerrado", "#087f5b"
    txt = f'<font color="{cor}"><b>{rot}</b></font>'
    if x["relato"]:
        txt += "<br/>" + _cinza(_t(x["relato"]))
    return txt


def _anexo(r: Dict[str, Any]) -> List[Any]:
    h: List[Any] = _secao(f"Anexo · Atendimentos ({len(r['linhas'])})", "Todos os pedidos do período, por dia.")
    if not r["linhas"]:
        return h
    meta = r["meta_assumir_s"]
    varios_sites = len({x["site"] for x in r["linhas"]}) > 1
    com_equipe = any(x["chegada_s"] is not None for x in r["linhas"])
    cab = ["Hora", "Pessoa", "Tipo", "Assumiu"] + (["Equipe"] if com_equipe else []) + ["Duração", "Situação"]
    larg = [0.08, 0.21, 0.095, 0.145] + ([0.09] if com_equipe else []) + [0.1]
    larg.append(1 - sum(larg))
    linhas: List[List[Any]] = []
    extra: list = []
    dia_atual, zebra = None, False
    for x in r["linhas"]:
        if x["data"] != dia_atual:
            dia_atual = x["data"]
            qtd = sum(1 for y in r["linhas"] if y["data"] == dia_atual)
            try:
                semana = DIAS[datetime.strptime(dia_atual, "%d/%m/%Y").weekday()]
            except ValueError:
                semana = ""
            n = len(linhas) + 1
            titulo_dia = f"{semana}, {_t(dia_atual)} · {qtd} pedido{'s' if qtd != 1 else ''}"
            linhas.append([_cel(titulo_dia, "dia")] + [""] * (len(cab) - 1))
            # NOSPLIT: o titulo do dia nunca fica sozinho no fim da pagina.
            extra += [("SPAN", (0, n), (-1, n)), ("BACKGROUND", (0, n), (-1, n), SOFT),
                      ("TOPPADDING", (0, n), (-1, n), 5), ("BOTTOMPADDING", (0, n), (-1, n), 5),
                      ("NOSPLIT", (0, n), (-1, n + 1))]
            zebra = False
        sub = " · ".join(v for v in (x["cargo"], x["site"] if varios_sites else "") if v)
        pessoa = f"<b>{_t(x['pessoa'])}</b>" + ("<br/>" + _cinza(_t(sub)) if sub else "")
        tipo = '<font color="#c92a2a"><b>Coação</b></font>' if x["tipo"] == "coacao" else "Pânico"
        espera = _t(_tempo(x["espera_s"]))
        if x["espera_s"] is not None and x["espera_s"] > meta:
            espera = f'<font color="#b86b00"><b>{espera}</b></font>'
        if x["assumido_por"]:
            espera += "<br/>" + _cinza(_t(x["assumido_por"]))
        if x["escalado"]:
            espera += '<br/><font color="#b86b00" size="7.4">Telegram acionado</font>'
        linha = [_cel(_t(x["hora"])), _cel(pessoa), _cel(tipo), _cel(espera)]
        if com_equipe:
            linha.append(_cel(_t(_tempo(x["chegada_s"]))))
        linha += [_cel(_t(_tempo(x["duracao_s"]))), _cel(_situacao(x))]
        if zebra:
            extra.append(("BACKGROUND", (0, len(linhas) + 1), (-1, len(linhas) + 1), ZEBRA))
        zebra = not zebra
        linhas.append(linha)
    return h + [_tabela(cab, linhas, larg, extra)]


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    local = r["site"] or "Todos os sites"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"Relatório do Alerta · {local}", author="SightOps",
                            subject="Relatório gerencial do Alerta de pânico")
    meta = r["meta_assumir_s"] // 60
    h: List[Any] = [_cabecalho(r, usuario, logo), Spacer(1, 12), _conclusao(r), Spacer(1, 12), _indicadores(r),
                    Spacer(1, 6), _chips(r)]
    if r["resumo"]["pedidos"]:
        h += _graficos(r) + _destaques(r)
    h += [PageBreak()] + _atencao(r) + _por_site(r) + [CondPageBreak(60 * mm)] + _anexo(r)
    como = ("Cada pedido é um acionamento do botão de pânico no app, no período escolhido (horário de Brasília). "
            "\"Tempo para assumir\" vai do disparo até um operador assumir; a meta da central é assumir em até "
            f"{meta} min. Mediana é o tempo do meio (metade foi mais rápida); \"90% em até\" é o tempo em que 9 de "
            "cada 10 pedidos foram assumidos, melhor que a média, que um único caso demorado distorce. "
            "\"Até a equipe chegar\" conta só os pedidos com chegada marcada. A comparação usa o período anterior "
            f"de mesmo tamanho ({_br(r['anterior_de'])} a {_br(r['anterior_ate'])}), com os mesmos filtros. "
            "Coação é quando a pessoa cancelou o alerta com a senha de coação. Tempos em formato curto: 1m 26s = "
            "1 minuto e 26 segundos.")
    h.append(KeepTogether([Spacer(1, 8), Paragraph("Como foi contado", E["sec"]), Paragraph(_t(como), E["nota"]),
                           Spacer(1, 16), _assinatura("Responsável pela central")]))
    rodape = f"SightOps · Relatório gerencial do Alerta · {local}"
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape, **k))
    return buf.getvalue()
