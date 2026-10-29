"""PDF do relatorio de disponibilidade do Monitoramento (A4 retrato).

Um conceito so, em todas as tabelas: parte do tempo NO AR, FORA e SEM LEITURA
(somam 100%). Estrutura:

  Resumo                 tres numeros, uma barra e o que aconteceu em texto corrido
  1 Pendencias agora     o que nao esta no ar na emissao, e desde quando
  2 Ocorrencias          quedas de conector e de equipamento, da mais recente
  3 Dia a dia            as tres partes por dia
  4 Por site / por tipo  so quando ha mais de um
  5 Equipamentos         um por linha
  Como ler, assinatura

Recebe o dicionario de monitoring_relatorio.gerar e devolve os bytes."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.access_control_relatorios_pdf import (LARGURA, MARGEM, MUTED, TEXT, _assinatura, _br, _num,
                                                        _Paginas)

ESCURO = colors.HexColor("#2b3a42")
LINHA = colors.HexColor("#d5dce0")
COR_NO_AR = colors.HexColor("#3f7f6a")
COR_FORA = colors.HexColor("#b42318")
COR_SEM = colors.HexColor("#c4ccd2")
VERMELHO = "#b42318"

E = {
    "kicker": ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED),
    "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=TEXT),
    "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED),
    "dir": ParagraphStyle("d", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, alignment=2),
    "sec": ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=TEXT,
                          spaceBefore=16, spaceAfter=2),
    "secsub": ParagraphStyle("secsub", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, spaceAfter=6),
    "texto": ParagraphStyle("tx", fontName="Helvetica", fontSize=9.2, leading=13.8, textColor=TEXT),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=8.2, leading=10.6, textColor=TEXT),
    "num": ParagraphStyle("num", fontName="Helvetica", fontSize=8.2, leading=10.6, textColor=TEXT, alignment=2),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=6.9, leading=9, textColor=MUTED),
    "thn": ParagraphStyle("thn", fontName="Helvetica-Bold", fontSize=6.9, leading=9, textColor=MUTED, alignment=2),
    "kpirot": ParagraphStyle("kr", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=MUTED),
    "kpival": ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=TEXT),
    "kpisub": ParagraphStyle("ks", fontName="Helvetica", fontSize=7.6, leading=10, textColor=MUTED),
    "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=7.6, leading=10.6, textColor=MUTED),
}

CURTA = {"up": "No ar", "unstable": "No ar (instável)", "down": "Fora", "blind": "Sem leitura",
         "unknown": "Sem leitura", "maintenance": "Manutenção"}


# ---------------------------------------------------------------- formato

def _t(txt: Any) -> str:
    return escape(str(txt if txt not in (None, "") else "—"))


def _dur(seg: Any) -> str:
    seg = int(seg or 0)
    if seg <= 0:
        return "—"
    d, r = divmod(seg, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}min"
    return f"{m} min" if m else "< 1 min"


def _p(v: Any, zero_traco: bool = True) -> str:
    if v is None:
        return "—"
    if zero_traco and v == 0:
        return "—"
    return f"{v:.1f}%".replace(".", ",")


def _quando(iso: str, ano: bool = False) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M" if ano else "%d/%m %H:%M")
    except ValueError:
        return iso


def _c(html: str, estilo: str = "cel") -> Paragraph:
    return Paragraph(html, E[estilo])


def _n(txt: Any) -> Paragraph:
    return _c(_t(txt), "num")


def _fora(v: Any) -> Paragraph:
    """Fora > 0 em vermelho: e o desvio que o leitor procura."""
    return _c(f'<font color="{VERMELHO}"><b>{_p(v)}</b></font>' if v else _p(v), "num")


def _secao(rot: str, sub: str = "") -> List[Any]:
    return [Paragraph(_t(rot), E["sec"])] + ([Paragraph(_t(sub), E["secsub"])] if sub else [Spacer(1, 4)])


def _tabela(cab: List[str], linhas: List[List[Any]], larguras: List[float], numericas: tuple = ()) -> Table:
    dados = [[_c(escape(c.upper()), "thn" if i in numericas else "th") for i, c in enumerate(cab)]] + linhas
    t = Table(dados, colWidths=[LARGURA * f for f in larguras], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, ESCURO), ("LINEBELOW", (0, 0), (-1, 0), 0.6, ESCURO),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINHA), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _barra(no_ar: Any, fora: Any, sem: Any, largura: float, altura: float = 7) -> Drawing:
    d = Drawing(largura, altura)
    x = 0.0
    for v, cor in ((no_ar, COR_NO_AR), (fora, COR_FORA), (sem, COR_SEM)):
        w = largura * (v or 0) / 100
        if w > 0:
            d.add(Rect(x, 0, w, altura, fillColor=cor, strokeColor=None))
            x += w
    return d


def _legenda() -> str:
    q = lambda cor, txt: f'<font color="{cor}">■</font> {txt}'
    return " &nbsp;&nbsp; ".join([q("#3f7f6a", "no ar"), q(VERMELHO, "fora"), q("#9aa5ad", "sem leitura")])


# ---------------------------------------------------------------- blocos

def _cabecalho(r: Dict[str, Any], usuario: str, logo: Optional[Path]) -> Table:
    local = r["site"] or "Todos os sites"
    gerado = datetime.strptime(r["gerado_em"][:19], "%Y-%m-%d %H:%M:%S")
    periodo = f"{_br(r['de'])} a {_br(r['ate'])}" if r["de"] != r["ate"] else _br(r["de"])
    filtros = [f"Período: {periodo}"] + ([f"Tipo: {r['tipo_rotulo']}"] if r.get("tipo") else [])
    esquerda = [Paragraph("RELATÓRIO DE DISPONIBILIDADE", E["kicker"]), Spacer(1, 3), Paragraph(_t(local), E["titulo"]),
                Spacer(1, 2), Paragraph(_t(" · ".join(filtros)), E["sub"])]
    cab_esq: Any = esquerda
    if logo and Path(logo).is_file():
        try:
            img = Image(str(logo))
            prop = img.imageWidth / float(img.imageHeight or 1)
            img.drawHeight, img.drawWidth = 14 * mm, min(36 * mm, 14 * mm * prop)
            cab_esq = Table([[img, esquerda]], colWidths=[img.drawWidth + 5 * mm, None])
            cab_esq.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        except Exception:  # logo invalido nao derruba o relatorio
            cab_esq = esquerda
    direita = [Paragraph(_t(f"Emitido em {gerado.strftime('%d/%m/%Y às %H:%M')}"), E["dir"])]
    if usuario:
        direita.append(Paragraph(_t(f"por {usuario}"), E["dir"]))
    cab = Table([[cab_esq, direita]], colWidths=[LARGURA * 0.7, LARGURA * 0.3])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, ESCURO),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return cab


def _texto_resumo(r: Dict[str, Any]) -> str:
    rs, an = r["resumo"], r["anterior"]
    if not rs["equipamentos"]:
        return "Não há equipamentos monitorados com os filtros informados."
    frases = [f"{_num(rs['equipamentos'])} equipamentos monitorados de {_br(r['de'])} a {_br(r['ate'])}."]
    conectores = [o for o in r["ocorrencias"] if o["tipo"] == "conector"]
    for o in [o for o in conectores if o["aberta"]]:
        frases.append(f"O conector {o['equipamento']} está fora desde {_quando(o['inicio'], True)}: desde então os "
                      f"{_num(o['afetados'])} equipamentos atrás dele estão sem leitura.")
    fechados = [o for o in conectores if not o["aberta"]]
    if fechados:
        frases.append(f"O conector caiu e voltou {_num(len(fechados))} vez(es), somando "
                      f"{_dur(sum(o['no_periodo_s'] for o in fechados))} fora.")
    quedas = [o for o in r["ocorrencias"] if o["tipo"] == "equipamento"]
    novas = [o for o in quedas if not o["antes"]]
    if novas:
        frases.append(f"Houve {_num(len(novas))} queda(s) de equipamento no período.")
    for o in [o for o in quedas if o["antes"]][:3]:
        if o["aberta"]:
            frases.append(f"{o['equipamento']} está fora desde {_quando(o['inicio'], True)}, antes do início do "
                          f"período.")
        else:
            frases.append(f"{o['equipamento']} ficou fora de {_quando(o['inicio'], True)} (antes do período) "
                          f"até {_quando(o['fim'], True)}.")
    if not conectores and not quedas:
        frases.append("Nenhuma queda no período.")
    if an["no_ar_pct"] is not None:
        frases.append(f"No período anterior ({_br(r['anterior_de'])} a {_br(r['anterior_ate'])}): "
                      f"{_p(an['no_ar_pct'], False)} no ar, {_p(an['fora_pct'], False)} fora e "
                      f"{_p(an['sem_pct'], False)} sem leitura.")
    return " ".join(frases)


def _resumo(r: Dict[str, Any]) -> List[Any]:
    rs = r["resumo"]
    itens = [("NO AR", rs["no_ar_pct"], TEXT), ("FORA", rs["fora_pct"], COR_FORA if rs["fora_pct"] else TEXT),
             ("SEM LEITURA", rs["sem_pct"], TEXT)]
    cel = [[Paragraph(rot, E["kpirot"]), Spacer(1, 3),
            Paragraph(_p(v, False), ParagraphStyle("v", parent=E["kpival"], textColor=cor)),
            Paragraph("do tempo", E["kpisub"])] for rot, v, cor in itens]
    k = Table([cel], colWidths=[LARGURA / 3] * 3)
    k.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.6, ESCURO), ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINHA),
                           ("LINEAFTER", (0, 0), (1, 0), 0.4, LINHA), ("TOPPADDING", (0, 0), (-1, -1), 10),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 12)]))
    barra = _barra(rs["no_ar_pct"], rs["fora_pct"], rs["sem_pct"], LARGURA, 9)
    return [Spacer(1, 10), k, Spacer(1, 8), barra, Spacer(1, 3), Paragraph(_legenda(), E["nota"]), Spacer(1, 10),
            Paragraph(_t(_texto_resumo(r)), E["texto"])]


def _pendencias(r: Dict[str, Any]) -> List[Any]:
    h = _secao("1  Pendências agora", "O que não estava no ar na emissão deste relatório.")
    if not r["pendencias"]:
        return h + [Paragraph("Nenhuma pendência: todos os equipamentos estavam no ar.", E["texto"])]
    multi = not r["um_site"]
    linhas = []
    for p in r["pendencias"]:
        cor = VERMELHO if p["situacao"] == "Fora" else "#4a5a64"
        nome = f"<b>{_t(p['equipamento'])}</b>" + (f' <font color="#66747e">· {_t(p["tipo_item"])}</font>'
                                                   if p["tipo_item"] else "")
        linhas.append([_c(nome)] + ([_c(_t(p["site"]))] if multi else []) + [
            _c(f'<font color="{cor}"><b>{_t(p["situacao"])}</b></font>'), _c(_t(_quando(p["desde"], True)))])
    cab = ["Equipamento"] + (["Site"] if multi else []) + ["Situação", "Desde"]
    larg = [0.35, 0.23, 0.24, 0.18] if multi else [0.5, 0.3, 0.2]
    return h + [_tabela(cab, linhas, larg)]


def _agrupar(ocorrencias: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Equipamentos do mesmo site que cairam e voltaram no mesmo minuto sao UMA
    ocorrencia ("7 cameras"), nao sete linhas iguais."""
    grupos: Dict[tuple, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    for o in ocorrencias:
        if o["tipo"] != "equipamento":
            out.append(o)
            continue
        chave = (o["site"], o["inicio"][:16], o["fim"][:16], o["aberta"])
        if chave in grupos:
            grupos[chave]["nomes"].append(o["equipamento"])
            grupos[chave]["tipos"].add(o["tipo_item"])
            continue
        g = {**o, "nomes": [o["equipamento"]], "tipos": {o["tipo_item"]}}
        grupos[chave] = g
        out.append(g)
    return out


def _nome_grupo(o: Dict[str, Any]) -> str:
    nomes = o.get("nomes") or [o["equipamento"]]
    if len(nomes) == 1:
        return f"<b>{_t(nomes[0])}</b>"
    tipo = next(iter(o["tipos"])) if len(o["tipos"]) == 1 else "equipamento"
    plural = {"Câmera": "câmeras", "NVR": "NVRs", "DVR": "DVRs"}.get(tipo, "equipamentos")
    lista = ", ".join(nomes[:8]) + (f" e mais {len(nomes) - 8}" if len(nomes) > 8 else "")
    return f'<b>{len(nomes)} {plural}</b><br/><font size="7" color="#66747e">{_t(lista)}</font>'


def _ocorrencias(r: Dict[str, Any]) -> List[Any]:
    total = r["ocorrencias_total"]
    sub = "Da mais recente para a mais antiga. Quando o conector cai, tudo o que está atrás dele fica sem leitura."
    if total > len(r["ocorrencias"]):
        sub += f" Exibidas {len(r['ocorrencias'])} de {total}."
    h = _secao(f"2  Ocorrências no período ({_num(total)})", sub)
    if not r["ocorrencias"]:
        return h + [Paragraph("Nenhuma queda de conector ou de equipamento no período.", E["texto"])]
    multi = not r["um_site"]
    linhas = []
    for o in _agrupar(r["ocorrencias"]):
        if o["tipo"] == "conector":
            oque = f"<b>Conector fora</b><br/>{_num(o['afetados'])} sem leitura"
            nome = f"<b>{_t(o['equipamento'])}</b>"
        else:
            oque = "<b>Fora</b>"
            nome = _nome_grupo(o)
        fim = f'<font color="{VERMELHO}"><b>continua fora</b></font>' if o["aberta"] else _t(_quando(o["fim"]))
        linhas.append([_c(_t(_quando(o["inicio"], o["antes"]))), _c(fim), _n(_dur(o["duracao_s"])), _c(nome)] +
                      ([_c(_t(o["site"]))] if multi else []) + [_c(oque)])
    cab = ["Início", "Fim", "Duração", "Equipamento"] + (["Site"] if multi else []) + ["O que aconteceu"]
    larg = [0.13, 0.13, 0.09, 0.28, 0.21, 0.16] if multi else [0.15, 0.15, 0.1, 0.36, 0.24]
    return h + [_tabela(cab, linhas, larg, numericas=(2,))]


def _dia_a_dia(r: Dict[str, Any]) -> List[Any]:
    dias = [d for d in r["dias"] if d["no_ar_pct"] is not None]
    if not dias:
        return []
    larg_barra = LARGURA * 0.36 - 8
    linhas = [[_c(_t(d["rotulo"])), _n(_p(d["no_ar_pct"], False)), _fora(d["fora_pct"]), _n(_p(d["sem_pct"])),
               _n(_num(d["quedas"]) if d["quedas"] else "—"),
               _barra(d["no_ar_pct"], d["fora_pct"], d["sem_pct"], larg_barra)] for d in dias]
    return _secao("3  Dia a dia", "Parte do tempo de todos os equipamentos somados, em cada dia.") + [
        _tabela(["Dia", "No ar", "Fora", "Sem leitura", "Quedas", ""], linhas,
                [0.1, 0.12, 0.12, 0.14, 0.16, 0.36], numericas=(1, 2, 3, 4))]


def _grupo(rot: str, cab0: str, grupos: List[Dict[str, Any]]) -> List[Any]:
    if len(grupos) < 2:
        return []
    linhas = [[_c(f"<b>{_t(g['nome'])}</b>"), _n(_num(g["equipamentos"])), _n(_p(g["no_ar_pct"], False)),
               _fora(g["fora_pct"]), _n(_p(g["sem_pct"])), _n(_num(g["quedas"]) if g["quedas"] else "—"),
               _n(_num(g["fora_agora"]) if g["fora_agora"] else "—")] for g in grupos]
    return _secao(rot, "Da menor para a maior parte do tempo no ar.") + [
        _tabela([cab0, "Equip.", "No ar", "Fora", "Sem leitura", "Quedas", "Fora agora"], linhas,
                [0.34, 0.09, 0.11, 0.11, 0.13, 0.1, 0.12], numericas=(1, 2, 3, 4, 5, 6))]


def _equipamentos(r: Dict[str, Any], numero: int) -> List[Any]:
    eqs = r["equipamentos"]
    h = _secao(f"{numero}  Equipamentos ({_num(len(eqs))})", "Parte do período em cada situação e a situação na emissão.")
    if not eqs:
        return h
    multi = not r["um_site"]
    linhas = []
    for e in eqs:
        sit = CURTA.get(e["status"], "Sem leitura")
        sit_html = f'<font color="{VERMELHO}"><b>{sit}</b></font>' if e["status"] == "down" else _t(sit)
        linhas.append([_c(f"<b>{_t(e['equipamento'])}</b>")] + ([_c(_t(e["site"]))] if multi else []) + [
            _c(_t(e["tipo_item"])), _n(_p(e["no_ar_pct"], False)), _fora(e["fora_pct"]), _n(_p(e["sem_pct"])),
            _n(_num(e["quedas"]) if e["quedas"] else "—"), _c(sit_html)])
    cab = ["Equipamento"] + (["Site"] if multi else []) + ["Tipo", "No ar", "Fora", "Sem leitura", "Quedas", "Agora"]
    larg = [0.22, 0.21, 0.1, 0.08, 0.08, 0.1, 0.08, 0.13] if multi else [0.32, 0.14, 0.1, 0.1, 0.12, 0.08, 0.14]
    ini = 3 if multi else 2
    return h + [_tabela(cab, linhas, larg, numericas=tuple(range(ini, ini + 4)))]


def _como_ler(r: Dict[str, Any]) -> List[Any]:
    itens = [
        "<b>No ar</b>: o equipamento respondeu ao monitoramento (inclui respostas intermitentes).",
        "<b>Fora</b>: o equipamento não respondeu, confirmado por leituras seguidas. Uma falha isolada não conta.",
        "<b>Sem leitura</b>: não foi possível verificar o equipamento. O caso mais comum é o conector do site fora: "
        "sem ele não se alcança nada do que está atrás, e por isso esse tempo não é contado como fora. Também entra "
        f"aqui quem parou de responder até {r['margem_conector_min']} min antes da queda do conector ser confirmada "
        f"ou até {r['margem_retorno_min']} min depois de ele voltar (é a mesma falha).",
        "As três partes somam 100% do período de cada equipamento. Horários no fuso de Brasília.",
    ]
    corpo = [Paragraph(x, E["nota"], bulletText="•") for x in itens]
    return [KeepTogether([Spacer(1, 6)] + _secao("Como ler este relatório") + corpo +
                         [Spacer(1, 22), _assinatura("Responsável técnico")])]


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    local = r["site"] or "Todos os sites"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"Relatório de disponibilidade · {local}", author="SightOps",
                            subject="Relatório de disponibilidade")
    h: List[Any] = [_cabecalho(r, usuario, logo)] + _resumo(r)
    h += [CondPageBreak(35 * mm)] + _pendencias(r)
    h += [CondPageBreak(40 * mm)] + _ocorrencias(r)
    h += [CondPageBreak(40 * mm)] + _dia_a_dia(r)
    numero = 4
    for rot, cab0, lista in (("Por site", "Site", r["por_site"]), ("Por tipo de equipamento", "Tipo", r["por_tipo"])):
        bloco = _grupo(f"{numero}  {rot}", cab0, lista)
        if bloco:
            h += [CondPageBreak(40 * mm)] + bloco
            numero += 1
    h += [CondPageBreak(50 * mm)] + _equipamentos(r, numero)
    h += _como_ler(r)
    rodape = f"SightOps · Relatório de disponibilidade · {local} · {_br(r['de'])} a {_br(r['ate'])}"
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape, **k))
    return buf.getvalue()
