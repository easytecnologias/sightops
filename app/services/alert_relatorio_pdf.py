"""PDF do relatorio do Alerta (A4 retrato), no mesmo visual dos relatorios do
controle de acesso: logo do cliente, filtros, quem gerou, resumo, atencao,
por site, atendimentos, "como foi contado", assinatura e "Pagina x de y".

Recebe o dicionario de alert_relatorio.gerar e devolve os bytes (nada vai
para disco)."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.access_control_relatorios_pdf import (AMBER, DANGER, LARGURA, MARGEM, PRIMARY, S, _assinatura,
                                                        _br, _kpis, _num, _p, _Paginas, _tabela)


def _tempo(seg: Any) -> str:
    if seg is None:
        return "—"
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    if h:
        return f"{h}h{m:02d}"
    return f"{m} min {s:02d} s" if m else f"{s} s"


def _status(x: Dict[str, Any]) -> str:
    if x["aberto"]:
        return "aberto"
    return {"closed": "encerrado", "cancelled": "cancelado pela pessoa"}.get(x["status"], x["status"])


def _filtros(r: Dict[str, Any]) -> str:
    partes = [f"Período {_br(r['de'])} a {_br(r['ate'])}" if r["de"] != r["ate"] else f"Dia {_br(r['de'])}"]
    partes.append(f"Site: {r['site'] or 'todos'}")
    if r.get("tipo"):
        partes.append(f"Tipo: {r['tipo_rotulo']}")
    if r.get("busca"):
        partes.append(f"Busca: {r['busca']}")
    return " · ".join(partes)


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    local = r["site"] or "Todos os sites"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=17 * mm, title=f"{r['nome']} · {local}", author="SightOps",
                            subject="Relatório do Alerta")
    gerado = datetime.strptime(r["gerado_em"][:19], "%Y-%m-%d %H:%M:%S")
    esquerda = [_p("RELATÓRIO · ATENDIMENTOS DO ALERTA", "kicker"), _p(local, "titulo"), _p(_filtros(r), "sub")]
    cab_esq: Any = esquerda
    if logo and Path(logo).is_file():
        try:
            img = Image(str(logo))
            prop = img.imageWidth / float(img.imageHeight or 1)
            img.drawHeight, img.drawWidth = 16 * mm, min(40 * mm, 16 * mm * prop)
            cab_esq = Table([[img, esquerda]], colWidths=[img.drawWidth + 4 * mm, None])
            cab_esq.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        except Exception:  # logo invalido nao derruba o relatorio
            cab_esq = esquerda
    direita = [_p(f"Gerado em {gerado.strftime('%d/%m/%Y às %H:%M')}", "dir")] + ([_p(f"por {usuario}", "dir")] if usuario else [])
    cab = Table([[cab_esq, direita]], colWidths=[LARGURA * 0.72, LARGURA * 0.28])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 1.6, PRIMARY),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    rs = r["resumo"]
    h: List[Any] = [cab, Spacer(1, 10), _kpis([
        ("Pedidos de ajuda", _num(rs["pedidos"]), False),
        ("Coação", _num(rs["coacao"]), bool(rs["coacao"])),
        ("Tempo médio para assumir", _tempo(rs["media_assumir_s"]), False),
        ("Tempo médio até a equipe chegar", _tempo(rs["media_chegada_s"]), False),
        ("Telegram acionado", _num(rs["escalados"]), bool(rs["escalados"])),
    ])]
    h.append(_p(f"{_num(rs['pessoas'])} pessoa(s) pediram ajuda · {_num(rs['encerrados'])} encerrados · "
                f"{_num(rs['cancelados'])} cancelados pela pessoa · {_num(rs['abertos'])} ainda abertos · "
                f"maior espera para assumir: {_tempo(rs['max_assumir_s'])}", "nota"))

    if r["atencao"]:
        h.append(_p(f"Atenção ({len(r['atencao'])})", "h2"))
        h.append(_tabela(["Quando", "Pessoa", "O que conferir"],
                         [[a["quando"], a["pessoa"], _p(a["texto"], "td", DANGER if a["nivel"] == "alto" else AMBER)]
                          for a in r["atencao"]], [0.18, 0.27, 0.55]))

    if len(r["por_site"]) > 1:
        h.append(_p("Por site", "h2"))
        h.append(_tabela(["Site", "Pedidos", "Coação", "Média para assumir", "Média até a equipe chegar"],
                         [[g["site"], _num(g["pedidos"]), _num(g["coacao"]), _tempo(g["media_assumir_s"]),
                           _tempo(g["media_chegada_s"])] for g in r["por_site"]],
                         [0.32, 0.12, 0.12, 0.2, 0.24]))

    h.append(_p(f"Atendimentos ({len(r['linhas'])})", "h2"))
    if r["linhas"]:
        def _linha(x: Dict[str, Any]) -> List[Any]:
            coacao = x["tipo"] == "coacao"
            assumiu = _tempo(x["espera_s"]) + (f" · {x['assumido_por']}" if x["assumido_por"] else "")
            situacao = _status(x) + (f" — {x['relato']}" if x["relato"] else "")
            return [f"{x['data']} {x['hora']}", _p(f"{x['pessoa']} · {x['site']}", "tdb"),
                    _p("Coação" if coacao else "Pânico", "td", DANGER if coacao else None),
                    assumiu, _tempo(x["chegada_s"]), _tempo(x["duracao_s"]), situacao]

        h.append(_tabela(["Data", "Pessoa / site", "Tipo", "Assumiu", "Equipe", "Duração", "Situação / relato"],
                         [_linha(x) for x in r["linhas"]], [0.11, 0.22, 0.08, 0.17, 0.09, 0.11, 0.22]))
    else:
        h.append(_p("Nenhum pedido de ajuda no período com esses filtros.", "nota"))

    h.append(KeepTogether([
        _p("Como foi contado", "h2"),
        _p("Cada linha é um pedido de ajuda feito pelo app no período (horário de Brasília). \"Assumiu\" é o tempo "
           "do disparo até um operador assumir; \"Equipe\" é do disparo até marcarem a chegada ao local; "
           "\"Duração\" é do disparo ao encerramento. Coação é quando a pessoa cancelou o alerta com a senha de "
           f"coação. Entra em Atenção quem esperou mais de {r['espera_atencao_s'] // 60} min para ser assumido, "
           "teve o Telegram acionado, foi coação ou ainda está aberto.", "nota"),
        Spacer(1, 10),
        _assinatura("Responsável pela central"),
    ]))
    rodape = f"SightOps · Alerta · {r['nome']} · {local}"
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=rodape, **k))
    return buf.getvalue()
