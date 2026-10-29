"""PDF do relatorio de disponibilidade do Monitoramento (A4 retrato).

  pagina 1  conclusao numa frase, 4 indicadores com comparacao ao periodo
            anterior, disponibilidade por dia, quedas por dia e destaques;
  depois    o que conferir, por site, por tipo, equipamentos que mais ficaram
            fora e, como anexo, a lista de quedas e a de todos os equipamentos.

Recebe o dicionario de monitoring_relatorio.gerar e devolve os bytes."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from app.services.access_control_relatorios_pdf import (AMBER, BORDER, DANGER, LARGURA, MARGEM, MUTED, PRIMARY,
                                                        SOFT, TEXT, _assinatura, _br, _num, _p, _Paginas)
from app.services.alert_relatorio_pdf import (AMBER_SOFT, DANGER_SOFT, E, VERDE, ZEBRA, _barras, _cel, _cinza,
                                              _quadro, _secao, _t, _tabela)

ESTADOS = {"up": ("No ar", "#087f5b"), "down": ("Fora", "#c92a2a"), "unstable": ("Instável", "#b86b00"),
           "unknown": ("Não verificado", "#66747e"), "maintenance": ("Manutenção", "#66747e")}


def _dur(seg: Any) -> str:
    seg = int(seg or 0)
    if not seg:
        return "—"
    d, r = divmod(seg, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m" if m else f"{seg}s"


def _pct(v: Any) -> str:
    return "—" if v is None else f"{v:.2f}%".replace(".", ",")


def _cor_pct(v: Any, meta: float) -> str:
    if v is None:
        return "#66747e"
    return "#2f9e44" if v >= meta else ("#b86b00" if v >= 95 else "#c92a2a")


def _quando(iso: str) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


def _cabecalho(r: Dict[str, Any], usuario: str, logo: Optional[Path]) -> Table:
    local = r["site"] or "Todos os sites"
    gerado = datetime.strptime(r["gerado_em"][:19], "%Y-%m-%d %H:%M:%S")
    periodo = f"{_br(r['de'])} a {_br(r['ate'])}" if r["de"] != r["ate"] else _br(r["de"])
    filtros = [f"Período {periodo}"] + ([f"Tipo: {r['tipo_rotulo']}"] if r.get("tipo") else [])
    esquerda = [_p("RELATÓRIO DE DISPONIBILIDADE · MONITORAMENTO", "kicker"), Spacer(1, 3), _p(local, "titulo"),
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
    rs = r["resumo"]
    if not rs["equipamentos"]:
        return Paragraph("Nenhum equipamento monitorado com estes filtros.", E["frase"])
    if rs["disponibilidade"] is None:
        return Paragraph(f"{_num(rs['equipamentos'])} equipamento(s), mas nenhum teve leitura no período.", E["frase"])
    partes = [f"No período, os <b>{_num(rs['equipamentos'])} equipamentos</b> ficaram "
              f"<b>{_pct(rs['disponibilidade'])} do tempo no ar</b>."]
    if rs["quedas"]:
        partes.append(f"Houve <b>{_num(rs['quedas'])} queda(s)</b> em {_num(rs['com_queda'])} equipamento(s), "
                      f"somando <b>{_dur(rs['fora_s'])}</b> de equipamento fora.")
    else:
        partes.append("Nenhuma queda registrada.")
    if rs["fora_agora"]:
        partes.append(f'<font color="#c92a2a"><b>{rs["fora_agora"]} continua(m) fora agora.</b></font>')
    return Paragraph(" ".join(partes), E["frase"])


def _variacao(atual: Any, antes: Any, menor_melhor: bool, fmt) -> str:
    if atual is None or antes is None:
        return _cinza("sem período anterior para comparar")
    dif = atual - antes
    if abs(dif) < 0.005:
        return _cinza("igual ao período anterior")
    melhor = dif < 0 if menor_melhor else dif > 0
    cor = "#2f9e44" if melhor else "#c92a2a"
    return f'<font color="{cor}"><b>{"▲" if dif > 0 else "▼"} {fmt(abs(dif))}</b></font> ' + _cinza("vs anterior")


def _indicadores(r: Dict[str, Any]) -> Table:
    rs, an, meta = r["resumo"], r["anterior"], r["meta_pct"]
    pp = lambda v: f"{v:.2f} pp".replace(".", ",")
    itens = [
        ("DISPONIBILIDADE", _pct(rs["disponibilidade"]), _cor_pct(rs["disponibilidade"], meta),
         _cinza(f"meta {_pct(meta)}") + "<br/>" + _variacao(rs["disponibilidade"], an["disponibilidade"], False, pp)),
        ("QUEDAS", _num(rs["quedas"]), TEXT,
         _cinza(f"em {_num(rs['com_queda'])} equipamento(s)") + "<br/>" +
         _variacao(rs["quedas"], an["quedas"], True, _num)),
        ("TEMPO FORA (SOMADO)", _dur(rs["fora_s"]), TEXT,
         _cinza("soma de todos os equipamentos") + "<br/>" + _variacao(rs["fora_s"], an["fora_s"], True, _dur)),
        ("FORA AGORA", _num(rs["fora_agora"]), DANGER if rs["fora_agora"] else TEXT,
         _cinza(f"{_num(rs['abaixo_meta'])} abaixo da meta no período")),
    ]
    cel = [[_cel(_t(rot), "rot"), Spacer(1, 4),
            Paragraph(_t(val), ParagraphStyle("v", parent=E["val"], textColor=cor)), Spacer(1, 3), _cel(ctx, "ctx")]
           for rot, val, cor, ctx in itens]
    t = Table([cel], colWidths=[LARGURA / 4] * 4)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11), ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("LINEABOVE", (0, 0), (-1, 0), 2.4, PRIMARY),
    ]))
    return t


def _graficos(r: Dict[str, Any]) -> List[Any]:
    serie = r["serie"]
    if not serie:
        return []
    from reportlab.lib import colors
    cada = max(1, -(-len(serie) // 16))
    meta = r["meta_pct"]
    # Barra = % de tempo FORA no dia (zero e o normal); assim um dia ruim salta aos olhos.
    fora = [0 if s["disponibilidade"] is None else round(100 - s["disponibilidade"], 1) for s in serie]
    cores = [colors.HexColor(_cor_pct(s["disponibilidade"], meta)) for s in serie]
    meio = (LARGURA - 8) / 2 - 20
    d1 = _barras([int(round(v)) for v in fora], [s["rotulo"] for s in serie], meio, 42 * mm, cores=cores,
                 rotulo_cada=max(cada, -(-len(serie) // 8)), mostrar_valor=len(serie) <= 16)
    q1 = _quadro("% do tempo fora, por dia", "Soma de todos os equipamentos. Zero é o normal.", d1)
    d2 = _barras([s["quedas"] for s in serie], [s["rotulo"] for s in serie], meio, 42 * mm,
                 rotulo_cada=max(cada, -(-len(serie) // 8)), mostrar_valor=len(serie) <= 16)
    q2 = _quadro("Quedas por dia", "Quantas vezes algum equipamento caiu.", d2)
    lado = Table([[q1, q2]], colWidths=[LARGURA / 2, LARGURA / 2])
    lado.setStyle(TableStyle([("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 4),
                              ("LEFTPADDING", (1, 0), (1, 0), 4), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                              ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [Spacer(1, 12), lado]


def _destaques(r: Dict[str, Any]) -> List[Any]:
    if not r["destaques"]:
        return []
    itens = [Paragraph(_t(x), E["item"], bulletText="•") for x in r["destaques"]]
    t = Table([[[_cel("<b>Destaques do período</b>", "chip"), Spacer(1, 4)] + itens]], colWidths=[LARGURA])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("TOPPADDING", (0, 0), (-1, -1), 10),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 12)]))
    return [Spacer(1, 10), t]


def _atencao(r: Dict[str, Any]) -> List[Any]:
    if not r["atencao"]:
        return _secao("O que conferir", f"Nada fora do esperado: nenhum equipamento fora agora, abaixo de "
                                        f"{_pct(r['meta_pct'])} ou oscilando.")
    linhas, extra = [], []
    for i, a in enumerate(r["atencao"], start=1):
        alto = a["nivel"] == "alto"
        cor = "#c92a2a" if alto else "#b86b00"
        linhas.append([_cel(f"<b>{_t(a['equipamento'])}</b>"), _cel(_t(a["site"])),
                       _cel(f'<font color="{cor}"><b>{_t(a["texto"])}</b></font>')])
        extra.append(("BACKGROUND", (0, i), (-1, i), DANGER_SOFT if alto else AMBER_SOFT))
    return _secao(f"O que conferir ({len(r['atencao'])})", "Do mais grave ao mais leve.") + [
        _tabela(["Equipamento", "Site", "Motivo"], linhas, [0.34, 0.22, 0.44], extra)]


def _grupo(titulo: str, sub: str, cab0: str, grupos: List[Dict[str, Any]], meta: float) -> List[Any]:
    if len(grupos) <= 1:
        return []
    linhas = []
    for g in grupos:
        cor = _cor_pct(g["disponibilidade"], meta)
        linhas.append([_cel(f"<b>{_t(g['nome'])}</b>"), _cel(_num(g["equipamentos"])),
                       _cel(f'<font color="{cor}"><b>{_pct(g["disponibilidade"])}</b></font>'),
                       _cel(_num(g["quedas"]) if g["quedas"] else "—"), _cel(_t(_dur(g["fora_s"]))),
                       _cel(f'<font color="#c92a2a"><b>{g["fora_agora"]}</b></font>' if g["fora_agora"] else "—")])
    return _secao(titulo, sub) + [_tabela([cab0, "Equip.", "Disponível", "Quedas", "Tempo fora", "Fora agora"],
                                          linhas, [0.34, 0.1, 0.15, 0.11, 0.16, 0.14])]


def _piores(r: Dict[str, Any]) -> List[Any]:
    if not r["piores"]:
        return []
    linhas = []
    for e in r["piores"]:
        cor = _cor_pct(e["disponibilidade"], r["meta_pct"])
        linhas.append([_cel(f"<b>{_t(e['equipamento'])}</b><br/>" + _cinza(_t(f"{e['tipo_rotulo']} · {e['site']}"))),
                       _cel(f'<font color="{cor}"><b>{_pct(e["disponibilidade"])}</b></font>'),
                       _cel(_num(e["quedas"])), _cel(_t(_dur(e["fora_s"]))), _cel(_t(_dur(e["maior_queda_s"])))])
    return _secao("Equipamentos que mais ficaram fora", "Ordenados pelo tempo fora no período.") + [
        _tabela(["Equipamento", "Disponível", "Quedas", "Tempo fora", "Maior queda"], linhas,
                [0.44, 0.15, 0.11, 0.15, 0.15])]


def _anexo_quedas(r: Dict[str, Any]) -> List[Any]:
    total = r["quedas_total"]
    sub = "Da mais recente à mais antiga." + (f" Mostrando {len(r['quedas'])} de {total}." if total > len(r["quedas"]) else "")
    h = _secao(f"Anexo · Quedas ({total})", sub)
    if not r["quedas"]:
        return h
    linhas, extra = [], []
    for i, q in enumerate(r["quedas"], start=1):
        fim = '<font color="#c92a2a"><b>ainda fora</b></font>' if q["aberta"] else _t(_quando(q["fim"]))
        ini = _t(_quando(q["inicio"])) + ("<br/>" + _cinza("antes do período") if q["comecou_antes"] else "")
        linhas.append([_cel(f"<b>{_t(q['equipamento'])}</b><br/>" + _cinza(_t(q["site"]))), _cel(ini), _cel(fim),
                       _cel(_t(_dur(q["duracao_s"])))])
        if i % 2 == 0:
            extra.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    return h + [_tabela(["Equipamento", "Caiu", "Voltou", "Duração"], linhas, [0.46, 0.2, 0.2, 0.14], extra)]


def _anexo_equipamentos(r: Dict[str, Any]) -> List[Any]:
    eqs = r["equipamentos"]
    h = _secao(f"Anexo · Todos os equipamentos ({len(eqs)})", "Por site e tipo. Estado = situação na hora do relatório.")
    if not eqs:
        return h
    linhas, extra = [], []
    for i, e in enumerate(eqs, start=1):
        rot, cor_e = ESTADOS.get(e["status_atual"], ESTADOS["unknown"])
        cor = _cor_pct(e["disponibilidade"], r["meta_pct"])
        linhas.append([_cel(f"<b>{_t(e['equipamento'])}</b>"), _cel(_t(e["site"])), _cel(_t(e["tipo_rotulo"])),
                       _cel(f'<font color="{cor}"><b>{_pct(e["disponibilidade"])}</b></font>'),
                       _cel(_num(e["quedas"]) if e["quedas"] else "—"), _cel(_t(_dur(e["fora_s"]))),
                       _cel(f'<font color="{cor_e}"><b>{rot}</b></font>')])
        if i % 2 == 0:
            extra.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    return h + [_tabela(["Equipamento", "Site", "Tipo", "Disponível", "Quedas", "Fora", "Estado"], linhas,
                        [0.27, 0.17, 0.14, 0.12, 0.08, 0.1, 0.12], extra)]


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    local = r["site"] or "Todos os sites"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"Disponibilidade · {local}", author="SightOps",
                            subject="Relatório de disponibilidade do monitoramento")
    meta = r["meta_pct"]
    h: List[Any] = [_cabecalho(r, usuario, logo), Spacer(1, 12), _conclusao(r), Spacer(1, 12), _indicadores(r)]
    h += _graficos(r) + _destaques(r)
    h += [PageBreak()] + _atencao(r)
    h += _grupo("Por site", "Do site com menor disponibilidade ao maior.", "Site", r["por_site"], meta)
    h += _grupo("Por tipo de equipamento", "Do tipo com menor disponibilidade ao maior.", "Tipo", r["por_tipo"], meta)
    h += [CondPageBreak(50 * mm)] + _piores(r)
    h += [CondPageBreak(60 * mm)] + _anexo_quedas(r)
    h += [CondPageBreak(60 * mm)] + _anexo_equipamentos(r)
    como = ("Disponibilidade é o tempo em que o equipamento respondeu, dividido pelo tempo em que ele foi verificado "
            "no período (horário de Brasília). Instável conta como no ar (respondeu, oscilando); \"não verificado\" e "
            "manutenção ficam fora da conta, porque sem leitura não há como afirmar que estava no ar. Uma queda é cada "
            "vez que o equipamento passou a fora; o estado só muda depois de leituras seguidas confirmarem, então "
            "falhas de um único minuto não contam. Tempo fora somado é a soma de todos os equipamentos (2 câmeras "
            "fora por 1 h = 2 h). A comparação usa o período anterior de mesmo tamanho "
            f"({_br(r['anterior_de'])} a {_br(r['anterior_ate'])}), com os mesmos filtros. Meta: {_pct(meta)}.")
    h.append(KeepTogether([Spacer(1, 8), Paragraph("Como foi contado", E["sec"]), Paragraph(_t(como), E["nota"]),
                           Spacer(1, 16), _assinatura("Responsável técnico")]))
    rodape = f"SightOps · Disponibilidade do monitoramento · {local}"
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape, **k))
    return buf.getvalue()
