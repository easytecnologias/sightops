"""PDF do relatorio de disponibilidade do Monitoramento (A4 retrato), no formato
de relatorio tecnico: secoes numeradas, indicadores em tabela com o periodo
anterior, linguagem formal e cor so onde ha desvio (abaixo da meta, fora).

  1 Sumario executivo          5 Indisponibilidade de conectores
  2 Indicadores do periodo     6 Pontos de atencao
  3 Indisponibilidade diaria   7 Equipamentos com maior indisponibilidade
  4 Por site e por tipo        Anexos A (ocorrencias) e B (inventario), metodologia

Recebe o dicionario de monitoring_relatorio.gerar e devolve os bytes."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app.services.access_control_relatorios_pdf import (BORDER, LARGURA, MARGEM, MUTED, SOFT, TEXT, _assinatura, _br,
                                                        _num, _p, _Paginas)
from app.services.alert_relatorio_pdf import _barras

ESCURO = colors.HexColor("#2b3a42")
LINHA = colors.HexColor("#c9d1d6")
VERMELHO = "#a61e1e"

E = {
    "kicker": ParagraphStyle("k", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED),
    "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=TEXT),
    "sub": ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED),
    "dir": ParagraphStyle("d", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, alignment=2),
    "sec": ParagraphStyle("sec", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=TEXT,
                          spaceBefore=14, spaceAfter=2),
    "secsub": ParagraphStyle("secsub", fontName="Helvetica", fontSize=7.8, leading=10, textColor=MUTED, spaceAfter=6),
    "texto": ParagraphStyle("tx", fontName="Helvetica", fontSize=9.2, leading=13.5, textColor=TEXT),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=8.2, leading=10.6, textColor=TEXT),
    "num": ParagraphStyle("num", fontName="Helvetica", fontSize=8.2, leading=10.6, textColor=TEXT, alignment=2),
    "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED),
    "thn": ParagraphStyle("thn", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=MUTED, alignment=2),
    "nota": ParagraphStyle("nota", fontName="Helvetica", fontSize=7.4, leading=10.2, textColor=MUTED),
}

ESTADOS = {"up": "Disponível", "down": "Indisponível", "unstable": "Instável", "unknown": "Sem leitura",
           "maintenance": "Manutenção", "blind": "Sem visibilidade"}


def _t(txt: Any) -> str:
    return escape(str(txt if txt not in (None, "") else "—"))


def _dur(seg: Any) -> str:
    seg = int(seg or 0)
    if not seg:
        return "—"
    d, r = divmod(seg, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h:02d}h"
    if h:
        return f"{h}h {m:02d}min"
    return f"{m} min" if m else f"{seg} s"


def _pct(v: Any) -> str:
    return "—" if v is None else f"{v:.2f}%".replace(".", ",")


def _pct_meta(v: Any, meta: float) -> str:
    """Abaixo da meta em vermelho e negrito; o resto, texto comum."""
    if v is None:
        return '<font color="#66747e">n/d</font>'
    return f'<font color="{VERMELHO}"><b>{_pct(v)}</b></font>' if v < meta else _pct(v)


def _quando(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _c(html: str, estilo: str = "cel") -> Paragraph:
    return Paragraph(html, E[estilo])


def _secao(numero: str, titulo: str, sub: str = "") -> List[Any]:
    rot = f"{numero}  {titulo}" if numero else titulo
    return [Paragraph(_t(rot), E["sec"])] + ([Paragraph(_t(sub), E["secsub"])] if sub else [Spacer(1, 4)])


def _tabela(cab: List[str], linhas: List[List[Any]], larguras: List[float], numericas: tuple = ()) -> Table:
    dados = [[_c(_t(c.upper()), "thn" if i in numericas else "th") for i, c in enumerate(cab)]] + linhas
    t = Table(dados, colWidths=[LARGURA * f for f in larguras], repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, ESCURO), ("LINEBELOW", (0, 0), (-1, 0), 0.6, ESCURO),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINHA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _n(txt: Any) -> Paragraph:
    return _c(_t(txt), "num")


# ---------------------------------------------------------------- blocos

def _cabecalho(r: Dict[str, Any], usuario: str, logo: Optional[Path]) -> Table:
    local = r["site"] or "Todos os sites"
    gerado = datetime.strptime(r["gerado_em"][:19], "%Y-%m-%d %H:%M:%S")
    periodo = f"{_br(r['de'])} a {_br(r['ate'])}" if r["de"] != r["ate"] else _br(r["de"])
    filtros = [f"Período de apuração: {periodo}"] + ([f"Tipo: {r['tipo_rotulo']}"] if r.get("tipo") else [])
    esquerda = [Paragraph("RELATÓRIO TÉCNICO DE DISPONIBILIDADE", E["kicker"]), Spacer(1, 3),
                Paragraph(_t(local), E["titulo"]), Spacer(1, 2), Paragraph(_t(" · ".join(filtros)), E["sub"])]
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
        direita.append(Paragraph(_t(f"Responsável pela emissão: {usuario}"), E["dir"]))
    cab = Table([[cab_esq, direita]], colWidths=[LARGURA * 0.68, LARGURA * 0.32])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, ESCURO),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return cab


def _sumario(r: Dict[str, Any]) -> List[Any]:
    rs, meta = r["resumo"], r["meta_pct"]
    h = _secao("1", "Sumário executivo")
    if not rs["equipamentos"]:
        return h + [Paragraph("Não há equipamentos monitorados com os filtros informados.", E["texto"])]
    frases = [f"No período de apuração foram monitorados {_num(rs['equipamentos'])} equipamentos."]
    if rs["disponibilidade"] is None:
        frases.append("Não houve leituras suficientes para apurar a disponibilidade.")
    else:
        situacao = "acima" if rs["disponibilidade"] >= meta else "abaixo"
        frases.append(f"A disponibilidade apurada foi de {_pct(rs['disponibilidade'])}, {situacao} da meta de "
                      f"{_pct(meta)}, com cobertura de monitoramento de {_pct(rs['cobertura'])} do tempo.")
    if rs["quedas"]:
        frases.append(f"Foram registradas {_num(rs['quedas'])} ocorrências de indisponibilidade em "
                      f"{_num(rs['com_queda'])} equipamentos, totalizando {_dur(rs['fora_s'])} de indisponibilidade "
                      f"acumulada.")
    else:
        frases.append("Não foram registradas ocorrências de indisponibilidade.")
    if r["conectores"]:
        frases.append(f"Houve {_num(len(r['conectores']))} período(s) de indisponibilidade de conector, nos quais os "
                      f"equipamentos dependentes ficaram sem visibilidade por {_dur(rs['sem_visibilidade_s'])} "
                      f"acumulados; esse tempo não é contado como disponível nem como indisponível.")
    if rs["fora_agora"] or rs["sem_vis_agora"]:
        partes = []
        if rs["fora_agora"]:
            partes.append(f"{_num(rs['fora_agora'])} equipamento(s) indisponível(is)")
        if rs["sem_vis_agora"]:
            partes.append(f"{_num(rs['sem_vis_agora'])} sem visibilidade")
        frases.append(f"Na emissão deste relatório havia {' e '.join(partes)}.")
    return h + [Paragraph(_t(" ".join(frases)), E["texto"])]


def _indicadores(r: Dict[str, Any]) -> List[Any]:
    rs, an = r["resumo"], r["anterior"]

    def var(a: Any, b: Any, fmt, unidade: str = "") -> str:
        if a is None or b is None:
            return "—"
        d = a - b
        if abs(d) < 0.005:
            return "sem variação"
        return f"{'+' if d > 0 else '−'}{fmt(abs(d))}{unidade}"

    pp = lambda v: f"{v:.2f}".replace(".", ",")
    linhas = [
        ("Disponibilidade (média ponderada pelo tempo)", _pct(rs["disponibilidade"]), _pct(an["disponibilidade"]),
         var(rs["disponibilidade"], an["disponibilidade"], pp, " p.p.")),
        ("Cobertura de monitoramento", _pct(rs["cobertura"]), _pct(an["cobertura"]),
         var(rs["cobertura"], an["cobertura"], pp, " p.p.")),
        ("Ocorrências de indisponibilidade", _num(rs["quedas"]), _num(an["quedas"]),
         var(rs["quedas"], an["quedas"], _num)),
        ("Tempo indisponível acumulado", _dur(rs["fora_s"]), _dur(an["fora_s"]), var(rs["fora_s"], an["fora_s"], _dur)),
        ("Indisponibilidades de conector", _num(rs["quedas_conector"]), _num(an["quedas_conector"]),
         var(rs["quedas_conector"], an["quedas_conector"], _num)),
        ("Tempo sem visibilidade (conector indisponível)", _dur(rs["sem_visibilidade_s"]),
         _dur(an["sem_visibilidade_s"]), var(rs["sem_visibilidade_s"], an["sem_visibilidade_s"], _dur)),
        (f"Equipamentos abaixo da meta ({_pct(r['meta_pct'])})", _num(rs["abaixo_meta"]), _num(an["abaixo_meta"]),
         var(rs["abaixo_meta"], an["abaixo_meta"], _num)),
    ]
    ant = f"{_br(r['anterior_de'])} a {_br(r['anterior_ate'])}"
    return _secao("2", "Indicadores do período", f"Comparação com o período anterior de mesma duração ({ant}).") + [
        _tabela(["Indicador", "Período", "Período anterior", "Variação"],
                [[_c(_t(a)), _n(b), _n(c), _n(d)] for a, b, c, d in linhas], [0.49, 0.17, 0.17, 0.17],
                numericas=(1, 2, 3))]


def _diario(r: Dict[str, Any]) -> List[Any]:
    serie = r["serie"]
    if not serie or not any(s["fora_s"] for s in serie):
        return _secao("3", "Indisponibilidade diária", "Sem indisponibilidade registrada no período.")
    horas = [round(s["fora_s"] / 3600) for s in serie]
    cada = max(1, -(-len(serie) // 15))
    d = _barras(horas, [s["rotulo"] for s in serie], LARGURA, 42 * mm, cores=[ESCURO] * len(serie),
                rotulo_cada=cada, mostrar_valor=len(serie) <= 31)
    return _secao("3", "Indisponibilidade diária",
                  "Horas de indisponibilidade somadas de todos os equipamentos, por dia (horário de Brasília). "
                  "Não inclui o tempo sem visibilidade.") + [d]


def _grupo(numero: str, titulo: str, cab0: str, grupos: List[Dict[str, Any]], r: Dict[str, Any]) -> List[Any]:
    meta = r["meta_pct"]
    if not grupos:
        return []
    linhas = [[_c(f"<b>{_t(g['nome'])}</b>"), _n(_num(g["equipamentos"])), _c(_pct_meta(g["disponibilidade"], meta), "num"),
               _n(_pct(g["cobertura"])), _n(_num(g["quedas"]) if g["quedas"] else "—"), _n(_dur(g["fora_s"])),
               _n(_dur(g["sem_visibilidade_s"]))] for g in grupos]
    return _secao(numero, titulo, "Ordenado da menor para a maior disponibilidade. n/d: cobertura insuficiente "
                                  f"(abaixo de {r['cobertura_minima_pct']}%).") + [
        _tabela([cab0, "Equip.", "Disponib.", "Cobertura", "Ocorr.", "Indisponível", "Sem visib."], linhas,
                [0.31, 0.08, 0.12, 0.12, 0.09, 0.14, 0.14], numericas=(1, 2, 3, 4, 5, 6))]


def _conectores(r: Dict[str, Any]) -> List[Any]:
    h = _secao("5", "Indisponibilidade de conectores",
               "Períodos em que o conector do site não respondeu. Durante esses períodos os equipamentos "
               "dependentes ficam sem visibilidade.")
    if not r["conectores"]:
        return h + [Paragraph("Nenhuma indisponibilidade de conector no período.", E["texto"])]
    linhas = []
    for c in r["conectores"]:
        fim = f'<font color="{VERMELHO}"><b>em aberto</b></font>' if c["aberta"] else _t(_quando(c["fim"]))
        ini = _t(_quando(c["inicio"])) + (" *" if c["comecou_antes"] else "")
        linhas.append([_c(f"<b>{_t(c['conector'])}</b>"), _c(_t(c["site"])), _c(ini), _c(fim), _n(_dur(c["duracao_s"])),
                       _n(_num(c["afetados"]))])
    h.append(_tabela(["Conector", "Site", "Início", "Fim", "Duração", "Equip. afetados"], linhas,
                     [0.23, 0.25, 0.15, 0.15, 0.11, 0.11], numericas=(4, 5)))
    if any(c["comecou_antes"] for c in r["conectores"]):
        h.append(Paragraph("* iniciado antes do período de apuração.", E["nota"]))
    return h


def _atencao(r: Dict[str, Any]) -> List[Any]:
    h = _secao("6", "Pontos de atenção", "Ordenados por severidade.")
    if not r["atencao"]:
        return h + [Paragraph(f"Nenhum equipamento indisponível na emissão, abaixo da meta de {_pct(r['meta_pct'])} "
                              f"ou com instabilidade recorrente.", E["texto"])]
    linhas = []
    for a in r["atencao"]:
        sev = f'<font color="{VERMELHO}"><b>Alta</b></font>' if a["nivel"] == "alto" else "Média"
        linhas.append([_c(sev), _c(f"<b>{_t(a['equipamento'])}</b>"), _c(_t(a["site"])), _c(_t(a["texto"]))])
    return h + [_tabela(["Severidade", "Equipamento", "Site", "Descrição"], linhas, [0.11, 0.22, 0.24, 0.43])]


def _piores(r: Dict[str, Any]) -> List[Any]:
    if not r["piores"]:
        return []
    meta = r["meta_pct"]
    linhas = [[_c(f"<b>{_t(e['equipamento'])}</b>"), _c(_t(e["tipo_item"])), _c(_t(e["site"])),
               _c(_pct_meta(e["disponibilidade"], meta), "num"), _n(_num(e["quedas"])), _n(_dur(e["fora_s"])),
               _n(_dur(e["maior_queda_s"]))] for e in r["piores"]]
    return _secao("7", "Equipamentos com maior indisponibilidade", "Ordenados pelo tempo indisponível no período.") + [
        _tabela(["Equipamento", "Tipo", "Site", "Disponib.", "Ocorr.", "Indisponível", "Maior evento"], linhas,
                [0.23, 0.12, 0.23, 0.1, 0.07, 0.12, 0.13], numericas=(3, 4, 5, 6))]


def _anexo_quedas(r: Dict[str, Any]) -> List[Any]:
    total = r["quedas_total"]
    sub = "Da mais recente para a mais antiga. Não inclui o tempo sem visibilidade."
    if total > len(r["quedas"]):
        sub += f" Exibidas {len(r['quedas'])} de {total}."
    h = _secao("Anexo A", f"Registro de ocorrências de indisponibilidade ({_num(total)})", sub)
    if not r["quedas"]:
        return h + [Paragraph("Nenhuma ocorrência no período.", E["texto"])]
    linhas = []
    for q in r["quedas"]:
        fim = f'<font color="{VERMELHO}"><b>em aberto</b></font>' if q["aberta"] else _t(_quando(q["fim"]))
        linhas.append([_c(f"<b>{_t(q['equipamento'])}</b>"), _c(_t(q.get("tipo_rotulo") or q["tipo"])),
                       _c(_t(q["site"])), _c(_t(_quando(q["inicio"])) + (" *" if q["comecou_antes"] else "")),
                       _c(fim), _n(_dur(q["duracao_s"]))])
    out = h + [_tabela(["Equipamento", "Tipo", "Site", "Início", "Fim", "Duração"], linhas,
                       [0.23, 0.12, 0.23, 0.15, 0.15, 0.12], numericas=(5,))]
    if any(q["comecou_antes"] for q in r["quedas"]):
        out.append(Paragraph("* iniciada antes do período de apuração.", E["nota"]))
    return out


def _anexo_inventario(r: Dict[str, Any]) -> List[Any]:
    eqs = r["equipamentos"]
    h = _secao("Anexo B", f"Inventário monitorado ({_num(len(eqs))})",
               "Por site e tipo. Situação: estado na emissão do relatório.")
    if not eqs:
        return h
    meta = r["meta_pct"]
    linhas = [[_c(_t(e["equipamento"])), _c(_t(e["site"])), _c(_t(e["tipo_item"])),
               _c(_pct_meta(e["disponibilidade"], meta), "num"), _n(_pct(e["cobertura"])),
               _n(_num(e["quedas"]) if e["quedas"] else "—"), _n(_dur(e["fora_s"])),
               _c(_t(ESTADOS.get(e["status_atual"], "Sem leitura")))] for e in eqs]
    return h + [_tabela(["Equipamento", "Site", "Tipo", "Disponib.", "Cobertura", "Ocorr.", "Indisponível", "Situação"],
                        linhas, [0.2, 0.21, 0.11, 0.1, 0.1, 0.06, 0.1, 0.12], numericas=(3, 4, 5, 6))]


def _metodologia(r: Dict[str, Any]) -> List[Any]:
    itens = [
        "Fonte: registros de mudança de estado do monitoramento do SightOps. O estado de cada equipamento só muda "
        "após leituras consecutivas o confirmarem; falhas isoladas de uma única leitura não geram ocorrência.",
        "Disponibilidade = 1 − (tempo indisponível ÷ tempo com leitura). O estado instável conta como disponível "
        "(o equipamento respondeu de forma intermitente) e é relatado à parte como ponto de atenção.",
        "Sem visibilidade: enquanto o conector do site está indisponível, não é possível afirmar o estado dos "
        "equipamentos que dependem dele. Esse tempo é excluído do cálculo e não gera ocorrência. Também é tratado "
        f"assim o equipamento que deixou de responder até {r['margem_conector_min']} min antes da indisponibilidade "
        f"do conector ser confirmada ou até {r['margem_retorno_min']} min depois do seu retorno, pois a falha é a mesma.",
        "Cobertura = tempo com leitura ÷ tempo do período. Equipamentos ou grupos com cobertura inferior a "
        f"{r['cobertura_minima_pct']}% não têm disponibilidade apurada (n/d).",
        "Tempo indisponível acumulado é a soma de todos os equipamentos (dois equipamentos indisponíveis por 1 h "
        "somam 2 h). Horários no fuso de Brasília.",
        f"Meta de disponibilidade: {_pct(r['meta_pct'])}. Comparação com o período anterior de mesma duração, "
        "com os mesmos filtros.",
    ]
    corpo = [Paragraph(_t(x), E["nota"], bulletText="•") for x in itens]
    return [KeepTogether([Spacer(1, 6)] + _secao("", "Metodologia") + corpo +
                         [Spacer(1, 18), _assinatura("Responsável técnico")])]


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    local = r["site"] or "Todos os sites"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"Relatório técnico de disponibilidade · {local}",
                            author="SightOps", subject="Relatório técnico de disponibilidade")
    h: List[Any] = [_cabecalho(r, usuario, logo), Spacer(1, 4)]
    h += _sumario(r) + _indicadores(r) + _diario(r)
    if len(r["por_site"]) > 1:
        h += [CondPageBreak(45 * mm)] + _grupo("4.1", "Disponibilidade por site", "Site", r["por_site"], r)
    h += [CondPageBreak(45 * mm)] + _grupo("4.2" if len(r["por_site"]) > 1 else "4", "Disponibilidade por tipo de "
                                           "equipamento", "Tipo", r["por_tipo"], r)
    h += [CondPageBreak(40 * mm)] + _conectores(r)
    h += [CondPageBreak(40 * mm)] + _atencao(r)
    h += [CondPageBreak(40 * mm)] + _piores(r)
    h += [CondPageBreak(50 * mm)] + _anexo_quedas(r)
    h += [CondPageBreak(50 * mm)] + _anexo_inventario(r)
    h += _metodologia(r)
    rodape = f"SightOps · Relatório técnico de disponibilidade · {local} · {_br(r['de'])} a {_br(r['ate'])}"
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape, **k))
    return buf.getvalue()
