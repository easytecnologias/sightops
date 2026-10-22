"""PDF dos relatorios do Painel de Acesso (A4 retrato), no formato aprovado no
mockup de 22/10/2026: logo do cliente, local, periodo, quem gerou, resumo,
tabelas, "como foi contado", assinatura e "Pagina x de y".

Recebe o dicionario pronto de access_control_relatorios.gerar e devolve os
bytes: nada vai para disco (o PDF de um cliente nao fica numa pasta comum).
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

# Paleta do SightOps (frontend/styles.css :root)
TEXT = colors.HexColor("#172026")
MUTED = colors.HexColor("#66747e")
BORDER = colors.HexColor("#dfe4e8")
SOFT = colors.HexColor("#f3f5f7")
PRIMARY = colors.HexColor("#087f5b")
PRIMARY_SOFT = colors.HexColor("#dff5ec")
AMBER = colors.HexColor("#b86b00")
DANGER = colors.HexColor("#c92a2a")
CALOR = ["#ffffff", "#dff5ec", "#9fd9bf", "#3fae84", "#087f5b"]

MARGEM = 16 * mm
LARGURA = A4[0] - 2 * MARGEM
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

S = {
    "kicker": ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=PRIMARY),
    "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=TEXT),
    "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED),
    "dir": ParagraphStyle("d", fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED, alignment=TA_RIGHT),
    "h2": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=TEXT, spaceBefore=10, spaceAfter=5),
    "td": ParagraphStyle("td", fontName="Helvetica", fontSize=8, leading=10, textColor=TEXT),
    "tdb": ParagraphStyle("tdb", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=TEXT),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=MUTED),
    "kl": ParagraphStyle("kl", fontName="Helvetica", fontSize=7.2, leading=9, textColor=MUTED),
    "kv": ParagraphStyle("kv", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=TEXT),
    "nota": ParagraphStyle("n", fontName="Helvetica", fontSize=7.6, leading=10.5, textColor=MUTED),
    "mono": ParagraphStyle("m", fontName="Courier", fontSize=7.4, leading=9.5, textColor=TEXT),
}


def _p(txt: Any, estilo: str = "td", cor: Optional[colors.Color] = None) -> Paragraph:
    st = S[estilo] if cor is None else ParagraphStyle(estilo + "c", parent=S[estilo], textColor=cor)
    return Paragraph(escape(str(txt if txt not in (None, "") else "—")), st)


def _br(iso: str) -> str:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(iso or "")


def _hm(txt: str) -> str:
    return str(txt or "")[11:16] or "—"


def _num(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _pct(v: Any) -> str:
    return "—" if v is None else f"{v}%"


def _dur(minutos: Any) -> str:
    if minutos is None:
        return "—"
    h, m = divmod(int(minutos), 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


# ---------------------------------------------------------------- blocos

def _tabela(cab: List[str], linhas: List[List[Any]], larguras: List[float], total: bool = False,
            alertas: Optional[List[int]] = None) -> Table:
    dados = [[Paragraph(escape(c.upper()), S["th"]) for c in cab]] + [
        [c if isinstance(c, Paragraph) else _p(c) for c in linha] for linha in linhas]
    t = Table(dados, colWidths=[LARGURA * f for f in larguras], repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if total and linhas:
        estilo.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, TEXT))
    t.setStyle(TableStyle(estilo))
    return t


def _kpis(itens: List[tuple]) -> Table:
    """itens: (rotulo, valor, destaque?)"""
    cel = [[_p(r, "kl"), Paragraph(escape(str(v)), ParagraphStyle("kvx", parent=S["kv"], textColor=AMBER if d else TEXT))]
           for r, v, d in itens]
    t = Table([cel], colWidths=[LARGURA / len(cel)] * len(cel))
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _assinatura(rotulo: str) -> Table:
    t = Table([[Spacer(1, 1), ""], [_p(rotulo, "nota"), ""]], colWidths=[LARGURA * 0.42, LARGURA * 0.58],
              rowHeights=[16 * mm, None])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (0, 0), 0.7, TEXT), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


# ---------------------------------------------------------------- por motor

def _presenca(r: Dict[str, Any]) -> List[Any]:
    v, res, evento = r["vocab"], r["resumo"], r["modo"] == "evento"
    out: List[Any] = []
    if evento:
        out.append(_kpis([(f"{v['pessoas'].capitalize()} credenciados", _num(res["pessoas"]), False),
                          ("Vieram", _num(res["vieram"]), False), ("Não vieram", _num(res["nao_vieram"]), bool(res["nao_vieram"])),
                          ("Dias do evento", _num(res["dias"]), False)]))
    else:
        out.append(_kpis([("Presença média", _pct(res["pct"]), False), ("Faltas no período", _num(res["faltas"]), False),
                          (f"Com {r['faltas_alerta']}+ faltas", _num(res["criticos"]), bool(res["criticos"])),
                          ("Dias contados", _num(res["dias"]), False)]))
    out.append(_p(f"1. Por {v['grupo'].lower()}", "h2"))
    linhas = [[g["grupo"], _num(g["pessoas"]), _pct(g["pct"]),
               _num(g["vieram"]) if evento else _num(g["faltas"]),
               _num(g["pessoas"] - g["vieram"]) if evento else _num(g["criticos"])] for g in r["grupos"]]
    linhas.append([_p("Total", "tdb"), _p(_num(res["pessoas"]), "tdb"), _p(_pct(res["pct"]), "tdb"),
                   _p(_num(res["vieram"] if evento else res["faltas"]), "tdb"),
                   _p(_num(res["nao_vieram"] if evento else res["criticos"]), "tdb")])
    out.append(_tabela([v["grupo"], v["pessoas"].capitalize(), "Presença", "Vieram" if evento else "Faltas",
                        "Não vieram" if evento else f"Com {r['faltas_alerta']}+ faltas"], linhas,
                       [0.34, 0.14, 0.16, 0.16, 0.20], total=True))
    if evento:
        faltosos = [x for x in r["pessoas"] if not x["presencas"]]
        titulo = f"2. {v['pessoas'].capitalize()} que não vieram"
        cab, larg = ["Nome", v["grupo"]], [0.6, 0.4]
        linhas = [[x["nome"], x["grupo"]] for x in faltosos]
    else:
        faltosos = [x for x in r["pessoas"] if x["faltas"] >= r["faltas_alerta"]]
        titulo = f"2. {v['pessoas'].capitalize()} com {r['faltas_alerta']} ou mais faltas"
        cab, larg = ["Nome", v["grupo"], "Faltas", "Dias de falta"], [0.34, 0.18, 0.1, 0.38]
        linhas = [[x["nome"], x["grupo"], _num(x["faltas"]), _p(", ".join(d[8:10] + "/" + d[5:7] for d in x["dias_falta"]), "mono")]
                  for x in faltosos]
    out.append(_p(titulo, "h2"))
    out.append(_tabela(cab, linhas, larg) if linhas else _p("Ninguém.", "nota"))
    if r["dias_fora"]:
        out.append(_p("3. Dias que ficaram fora da conta", "h2"))
        out.append(_tabela(["Dia", "Motivo"], [[_br(d["dia"]), d["motivo"]] for d in r["dias_fora"]], [0.18, 0.82]))
    if r.get("fora_leitor"):
        out.append(_p(f"{v['pessoas'].capitalize()} fora da conta: não estão em nenhum leitor", "h2"))
        out.append(_p("Sem cadastro aceito pelo leitor a pessoa não tem como passar; contar falta seria errado. "
                      "Corrija no cadastro (aba Alertas do painel).", "nota"))
        out.append(_tabela(["Nome", v["grupo"]], [[x["nome"], x["grupo"]] for x in r["fora_leitor"]], [0.6, 0.4]))
    util = "" if evento else ("Contam os dias de segunda a sexta, menos os feriados cadastrados para o local. ")
    out.append(KeepTogether([
        _p("Como foi contado", "h2"),
        _p(f"Presença: a pessoa passou em qualquer leitor do local no dia. Falta: dia contado sem nenhuma "
           f"passagem dela. {util}Um dia só conta se pelo menos 1/4 das pessoas passou; com menos, o leitor "
           f"provavelmente estava fora do ar e o dia vai listado acima. O dia de hoje só entra quando o período é só hoje. "
           f"Quem está só no leitor, sem cadastro no SightOps, não entra.", "nota"),
        _assinatura("Responsável")]))
    # aluno por aluno, um grupo por bloco
    por: Dict[str, List[Dict[str, Any]]] = {}
    for x in r["pessoas"]:
        por.setdefault(x["grupo"], []).append(x)
    if por:
        out.append(PageBreak())
        out.append(_p(f"{v['pessoas'].capitalize()} um por um", "titulo"))
        out.append(Spacer(1, 4))
        from app.services.access_control_relatorios import _ordem_grupo
        for g in sorted(por, key=_ordem_grupo):
            lista = sorted(por[g], key=lambda x: x["nome"])
            linhas = [[x["nome"], _num(x["presencas"]), _num(x["faltas"]), _pct(x["pct"]),
                       _p(", ".join(d[8:10] + "/" + d[5:7] for d in x["dias_falta"]) or "—", "mono")] for x in lista]
            out.append(KeepTogether([_p(f"{g} · {len(lista)} {v['pessoas']}", "h2"),
                                     _tabela(["Nome", "Presenças", "Faltas", "Presença", "Dias de falta"], linhas[:12],
                                             [0.34, 0.11, 0.09, 0.1, 0.36])]))
            if len(linhas) > 12:
                out.append(_tabela(["Nome", "Presenças", "Faltas", "Presença", "Dias de falta"], linhas[12:],
                                   [0.34, 0.11, 0.09, 0.1, 0.36]))
    return out


def _cadastro(r: Dict[str, Any]) -> List[Any]:
    v, res = r["vocab"], r["resumo"]
    out: List[Any] = [_kpis([(v["pessoas"].capitalize(), _num(res["pessoas"]), False),
                             ("Sem foto", _num(res["sem_foto"]), bool(res["sem_foto"])),
                             ("Fora do leitor", _num(res["fora_leitor"]), bool(res["fora_leitor"])),
                             ("Sem passar há 30 dias", _num(res["parados"]), False)])]
    out.append(_p(f"1. Por {v['grupo'].lower()}", "h2"))
    out.append(_tabela([v["grupo"], v["pessoas"].capitalize(), "Sem foto", "Fora do leitor", "Sem passar há 30 dias"],
                       [[g["grupo"], _num(g["pessoas"]), _num(g["sem_foto"]), _num(g["fora_leitor"]), _num(g["parados"])]
                        for g in r["grupos"]], [0.3, 0.16, 0.16, 0.18, 0.2]))
    out.append(_p(f"2. {v['pessoas'].capitalize()}", "h2"))
    out.append(_tabela(["Nome", v["grupo"], "Foto", "No leitor", "Última passagem"],
                       [[x["nome"], x["grupo"], "sim" if x["foto"] else _p("não", cor=AMBER),
                         "sim" if x["leitor"] else _p("não", cor=AMBER),
                         (_br(x["ultima"]) + " " + _hm(x["ultima"])) if x["ultima"] else "nunca"] for x in r["pessoas"]],
                       [0.38, 0.14, 0.1, 0.12, 0.26]))
    return out


def _diario(r: Dict[str, Any]) -> List[Any]:
    v, res = r["vocab"], r["resumo"]
    out: List[Any] = [_kpis([("Pessoas do cadastro", _num(res["pessoas"]), False), ("Passagens", _num(res["passagens"]), False),
                             ("Ainda dentro", _num(res["dentro"]) if res["dentro"] is not None else "—", False),
                             ("Só no leitor" if not res["nao_vieram"] else f"{v['pessoas'].capitalize()} que não vieram",
                              _num(res["nao_vieram"] or res["so_leitor"]), bool(res["nao_vieram"]))])]
    out.append(_p("1. Quem passou", "h2"))
    if not r["pessoas"]:
        out.append(_p("Ninguém do cadastro passou neste dia.", "nota"))
    elif r.get("saidas_confiaveis"):
        out.append(_tabela(["Nome", v["grupo"], "Chegou", "Saiu", "Tempo", "Portas"],
                           [[x["nome"], x["grupo"], _hm(x["chegou"]), _hm(x["saiu"]) if x["saiu"] else ("dentro" if x["dentro"] else "—"),
                             _dur(x["minutos"]), _p(", ".join(x["portas"]), "nota")] for x in r["pessoas"]],
                           [0.3, 0.14, 0.09, 0.09, 0.1, 0.28]))
    else:   # sem leitor de saida: "saiu" ficaria vazio para todo mundo
        out.append(_tabela(["Nome", v["grupo"], "Primeira", "Última", "Passagens", "Portas"],
                           [[x["nome"], x["grupo"], _hm(x["primeira"]), _hm(x["ultima"]), _num(x["passagens"]),
                             _p(", ".join(x["portas"]), "nota")] for x in r["pessoas"]],
                           [0.3, 0.12, 0.09, 0.09, 0.1, 0.3]))
    if r["nao_vieram"]:
        out.append(_p(f"2. {v['pessoas'].capitalize()} sem passagem no dia", "h2"))
        out.append(_tabela(["Nome", v["grupo"]], [[x["nome"], x["grupo"]] for x in r["nao_vieram"]], [0.6, 0.4]))
    if r["so_leitor"]:
        out.append(_p("Só no leitor (sem cadastro no SightOps)", "h2"))
        out.append(_tabela(["Nome no leitor", "Passagens", "Primeira", "Última"],
                           [[x["nome"], _num(x["passagens"]), _hm(x["primeira"]), _hm(x["ultima"])] for x in r["so_leitor"]],
                           [0.5, 0.16, 0.17, 0.17]))
    out.append(_p("Como foi contado", "h2"))
    out.append(_p("Chegou: primeira passagem de entrada no dia. Saiu: última passagem de saída. Tempo: entre as duas. "
                  + ("\"dentro\": a última passagem do dia foi de entrada." if r.get("saidas_confiaveis") else
                     "Este local quase não registra saída (falta leitor de saída), então não dá para dizer quem ficou dentro."),
                  "nota"))
    return out


def _uso(r: Dict[str, Any]) -> List[Any]:
    res = r["resumo"]
    hm = res.get("hora_mais")
    out: List[Any] = [_kpis([("Passagens no período", _num(res["passagens"]), False),
                             ("Média por dia com movimento", _num(res["media_dia"]), False),
                             ("Pico de gente dentro", _num(res["pico"]) if res["pico"] is not None else "—", False),
                             ("Horário mais cheio", f"{DIAS_SEMANA[hm['dia_semana']]} {hm['hora']:02d}h" if hm else "—", False)])]
    if res["pico"]:
        out.append(_p(f"Pico de {res['pico']} pessoas dentro ao mesmo tempo em {_br(res['pico_dia'])}, às {res['pico_hora']}.", "nota"))
    out.append(_p("1. Passagens por dia da semana e hora", "h2"))
    mapa = r["mapa"]
    horas = [h for h in range(24) if any(mapa[d][h] for d in range(7))] or list(range(6, 21))
    horas = list(range(min(horas[0], 6), max(horas[-1], 20) + 1))
    maximo = max(1, max(max(l) for l in mapa))
    dados = [[""] + [Paragraph(f"{h}h" if h % 2 == 0 else "", S["th"]) for h in horas]]
    estilo = [("GRID", (1, 1), (-1, -1), 0.4, colors.white), ("FONTSIZE", (0, 0), (-1, -1), 6)]
    for d in range(7):
        dados.append([_p(DIAS_SEMANA[d], "th")] + ["" for _ in horas])
        for i, h in enumerate(horas):
            n = mapa[d][h]
            nivel = 0 if not n else 1 if n / maximo < .15 else 2 if n / maximo < .4 else 3 if n / maximo < .7 else 4
            estilo.append(("BACKGROUND", (i + 1, d + 1), (i + 1, d + 1), colors.HexColor(CALOR[nivel])))
    larg = (LARGURA - 12 * mm) / len(horas)
    t = Table(dados, colWidths=[12 * mm] + [larg] * len(horas), rowHeights=[None] + [7 * mm] * 7)
    estilo.append(("BOX", (1, 1), (-1, -1), 0.4, BORDER))
    t.setStyle(TableStyle(estilo))
    out.append(t)
    out.append(_p("2. Dia a dia", "h2"))
    linhas = [[_br(s["dia"]), DIAS_SEMANA[datetime.strptime(s["dia"], "%Y-%m-%d").weekday()], _num(s["passagens"]),
               _num(s["pessoas"]), _num(s["pico"]) if s["pico"] is not None else "—", s["pico_hora"] or "—"]
              for s in r["serie"] if s["passagens"]]
    out.append(_tabela(["Dia", "", "Passagens", "Pessoas", "Pico dentro", "Hora do pico"], linhas,
                       [0.18, 0.1, 0.18, 0.18, 0.18, 0.18]) if linhas else _p("Sem passagens no período.", "nota"))
    out.append(_p("3. Portas", "h2"))
    out.append(_tabela(["Porta", "Passagens"], [[x["porta"], _num(x["passagens"])] for x in r["portas"]], [0.75, 0.25]))
    out.append(_p("Como foi contado", "h2"))
    out.append(_p("Passagens: todas as marcações dos leitores do local, de pessoas do cadastro ou não. Pico dentro: "
                  "entrada soma, saída tira, começando o dia vazio; quem sai por um leitor de entrada continua contando "
                  "até o fim do dia. " + ("" if r.get("saidas_confiaveis") else
                  "Neste local as saídas quase não são registradas, então o pico dentro não é calculado."), "nota"))
    return out


def _avisos(r: Dict[str, Any]) -> List[Any]:
    v, res = r["vocab"], r["resumo"]
    ok = res["lidos"] + res["entregues"]
    out: List[Any] = [_kpis([("Avisos enviados", _num(res["enviados"]), False),
                             ("Entregues ou lidos", f"{round(100 * ok / res['enviados'])}%" if res["enviados"] else "—", False),
                             ("Não entregues", _num(res["falhas"]), bool(res["falhas"])),
                             (f"{v['pessoas'].capitalize()} sem número", _num(res["sem_numero"]), bool(res["sem_numero"]))])]
    out.append(_p("1. Por dia", "h2"))
    linhas = [[_br(d["dia"]), _num(d["lido"]), _num(d["entregue"]), _num(d["enviado"]), _num(d["falha"])]
              for d in r["serie"] if d["lido"] + d["entregue"] + d["enviado"] + d["falha"]]
    out.append(_tabela(["Dia", "Lidos", "Entregues", "Sem confirmação", "Não entregues"], linhas, [0.2, 0.2, 0.2, 0.2, 0.2])
               if linhas else _p("Nenhum aviso enviado no período.", "nota"))
    out.append(_p(f"2. Por {v['pessoa']}", "h2"))
    out.append(_tabela(["Nome", v["grupo"], "Responsável", "Enviados", "Lidos", "Falhas", "Último"],
                       [[x["nome"], x["grupo"], x["responsavel"], _num(x["enviados"]), _num(x["lidos"]), _num(x["falhas"]),
                         "ok" if x.get("ultimo_ok", True) else _p("falhou", cor=DANGER)] for x in r["pessoas"]],
                       [0.26, 0.12, 0.22, 0.1, 0.09, 0.09, 0.12]) if r["pessoas"] else _p("Ninguém recebeu aviso no período.", "nota"))
    if r["sem_numero"]:
        out.append(_p(f"3. {v['pessoas'].capitalize()} sem número de responsável", "h2"))
        out.append(_tabela(["Nome", v["grupo"]], [[x["nome"], x["grupo"]] for x in r["sem_numero"]], [0.6, 0.4]))
    out.append(_p("Como foi contado", "h2"))
    out.append(_p("Situação informada pelo WhatsApp (Meta) para cada aviso: lido, entregue, enviado sem confirmação ou "
                  "não entregue. \"Último\": situação do aviso mais recente para aquele número."
                  + (f" {res['numeros_compartilhados']} número(s) de responsável também cadastrado(s) em outro local ficaram "
                     "de fora: não dá para saber de qual local foi o aviso." if res.get("numeros_compartilhados") else ""), "nota"))
    return out


# ---------------------------------------------------------------- montagem

class _Paginas(rl_canvas.Canvas):
    """Canvas que sabe o total de paginas ("Pagina 2 de 5")."""

    def __init__(self, *a, rodape: str = "", **k):
        super().__init__(*a, **k)
        self._estados: List[dict] = []
        self._rodape = rodape

    def showPage(self):
        self._estados.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._estados)
        for e in self._estados:
            self.__dict__.update(e)
            self.saveState()
            self.setStrokeColor(BORDER)
            self.line(MARGEM, 12 * mm, A4[0] - MARGEM, 12 * mm)
            self.setFont("Helvetica", 7)
            self.setFillColor(MUTED)
            self.drawString(MARGEM, 8 * mm, self._rodape[:110])
            self.drawRightString(A4[0] - MARGEM, 8 * mm, f"Página {self._pageNumber} de {total}")
            self.restoreState()
            super().showPage()
        super().save()


def _filtros(r: Dict[str, Any]) -> str:
    v = r["vocab"]
    partes = []
    if r.get("grupo"):
        partes.append(f"{v['grupo']}: {r['grupo']}")
    elif r["motor"] == "presenca":
        partes.append(f"Todas as {v['grupos']}")
    if r.get("quem") and r["motor"] == "presenca":
        partes.append(r["quem"])
    if r["motor"] == "diario":
        partes.append(_br(r["dia"]))
    elif r.get("de"):
        partes.append(f"{_br(r['de'])} a {_br(r['ate'])}")
        if r["motor"] == "presenca":
            partes[-1] += f" ({r['resumo']['dias']} dia{'s' if r['resumo']['dias'] != 1 else ''} contado{'s' if r['resumo']['dias'] != 1 else ''})"
    return " · ".join(partes)


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    titulo = f"{r['nome']} · {r['site']}"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=17 * mm, title=titulo, author="SightOps", subject="Relatório do controle de acesso")
    gerado = datetime.strptime(r["gerado_em"][:19], "%Y-%m-%d %H:%M:%S")
    esquerda = [_p(f"RELATÓRIO · {r['nome'].upper()}", "kicker"), _p(r["site"], "titulo"), _p(_filtros(r), "sub")]
    if logo and Path(logo).is_file():
        try:
            img = Image(str(logo))
            prop = img.imageWidth / float(img.imageHeight or 1)
            img.drawHeight, img.drawWidth = 16 * mm, min(40 * mm, 16 * mm * prop)
            cab_esq = Table([[img, esquerda]], colWidths=[img.drawWidth + 4 * mm, None])
            cab_esq.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        except Exception:   # logo invalido nao derruba o relatorio
            cab_esq = esquerda
    else:
        cab_esq = esquerda
    direita = [_p(f"Gerado em {gerado.strftime('%d/%m/%Y às %H:%M')}", "dir")] + (
        [_p(f"por {usuario}", "dir")] if usuario else [])
    cab = Table([[cab_esq, direita]], colWidths=[LARGURA * 0.72, LARGURA * 0.28])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.6, PRIMARY),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    corpo = {"presenca": _presenca, "cadastro": _cadastro, "diario": _diario, "uso": _uso, "avisos": _avisos}[r["motor"]](r)
    historia = [cab, Spacer(1, 10)] + corpo
    rodape = f"SightOps · Controle de Acesso · {titulo}"
    doc.build(historia, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape, **k))
    return buf.getvalue()
