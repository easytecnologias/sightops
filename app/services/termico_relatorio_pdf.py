"""PDF do relatorio das Cameras termicas (A4 retrato), mesmo padrao do relatorio
do Alerta. Recebe o dicionario de termico_relatorio.gerar e devolve os bytes."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.access_control_relatorios_pdf import BORDER, LARGURA, MARGEM, _assinatura, _Paginas
from app.services.alert_relatorio_pdf import E, _barras, _cabecalho, _cel, _quadro, _secao, _t, _tabela, _tempo

SITUACAO = {"novo": "Sem resposta", "visto": "Ciente", "falso": "Falso alarme"}


def _temp(v: Any) -> str:
    return "—" if v is None else f"{float(v):.1f} °C".replace(".", ",")


def _conclusao(r: Dict[str, Any]) -> Paragraph:
    s = r["resumo"]
    if not s["alarmes"]:
        txt = "Nenhum alarme no período."
    else:
        txt = (f"{s['alarmes']} alarme(s) no período: {s['cientes']} com Ciente, {s['falsos']} falso(s) alarme(s) "
               f"e {s['pendentes']} sem resposta.")
        if s["resposta_s"] is not None:
            txt += f" Metade foi respondida em até {_tempo(s['resposta_s'])}."
    return Paragraph(_t(txt), E["frase"])


def _indicadores(r: Dict[str, Any]) -> Table:
    s = r["resumo"]
    itens = [("ALARMES", s["alarmes"]), ("CIENTE", s["cientes"]), ("FALSOS", s["falsos"]),
             ("TEMPO DE RESPOSTA", _tempo(s["resposta_s"]) if s["resposta_s"] is not None else "—")]
    t = Table([[[_cel(_t(a), "rot"), _cel(_t(b), "val")] for a, b in itens]], colWidths=[LARGURA / 4] * 4)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, BORDER), ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def _por_usina(r: Dict[str, Any]) -> List[Any]:
    if not r["usinas"]:
        return []
    linhas = [[_cel(_t(u["site"])), _cel(_t(u["alarmes"])), _cel(_t(u["cientes"])), _cel(_t(u["falsos"])), _cel(_t(u["pendentes"])),
               _cel(_t(_tempo(u["resposta_s"]) if u["resposta_s"] is not None else "—"))] for u in r["usinas"]]
    return _secao("Por usina") + [_tabela(["Usina", "Alarmes", "Ciente", "Falsos", "Sem resposta", "Resposta"], linhas,
                                          [0.34, 0.12, 0.12, 0.12, 0.15, 0.15])]


def _motivos(r: Dict[str, Any]) -> List[Any]:
    if not r["motivos"]:
        return []
    linhas = [[_cel(_t(m["rotulo"])), _cel(_t(m["n"]))] for m in r["motivos"]]
    return _secao("Falsos alarmes por motivo") + [_tabela(["Motivo", "Quantidade"], linhas, [0.7, 0.3])]


def _lista(r: Dict[str, Any]) -> List[Any]:
    if not r["lista"]:
        return []
    linhas = [[_cel(_t(x["quando"])), _cel(_t(x["site"])), _cel(_t(x["camera"])), _cel(_t(_temp(x["temp_c"]))), _cel(_t(_temp(x["fundo_c"]))),
               _cel(_t(SITUACAO.get(x["situacao"], x["situacao"]) + (f": {x['motivo']}" if x["motivo"] else "")))] for x in r["lista"]]
    sub = f"Os {len(r['lista'])} mais recentes." if r["cortada"] else ""
    return _secao("Alarmes do período", sub) + [_tabela(["Quando", "Usina", "Câmera", "Mancha", "Fundo", "Situação"], linhas,
                                                        [0.17, 0.2, 0.19, 0.1, 0.1, 0.24])]


def gerar_pdf(r: Dict[str, Any], usuario: str = "", logo: Optional[Path] = None) -> bytes:
    buf = io.BytesIO()
    local = r["site"] or "Todas as usinas"
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"Câmeras térmicas · {local}", author="SightOps",
                            subject="Relatório das câmeras térmicas")
    cab = dict(r, site=local)
    h: List[Any] = [_cabecalho(cab, usuario, logo, "RELATÓRIO · CÂMERAS TÉRMICAS"), Spacer(1, 12), _conclusao(r), Spacer(1, 12), _indicadores(r)]
    if r["resumo"]["alarmes"]:
        h += [Spacer(1, 12), _quadro("Alarmes por hora", "Horário de Brasília",
                                     _barras(r["por_hora"], [f"{i:02d}" for i in range(24)], LARGURA - 20, 90, rotulo_cada=2))]
    h += _por_usina(r) + _motivos(r) + _lista(r)
    como = ("Cada alarme é uma detecção de pessoa pelo calor no período. Tempo de resposta é a mediana entre o alarme e o "
            f"Ciente ou Falso alarme: metade foi mais rápida. Alarmes de teste não entram na conta ({r['testes']} no período).")
    h.append(KeepTogether([Spacer(1, 8), Paragraph("Como foi contado", E["sec"]), Paragraph(_t(como), E["nota"]),
                           Spacer(1, 16), _assinatura("Responsável pelo monitoramento")]))
    doc.build(h, canvasmaker=lambda *a, **k: _Paginas(*a, rodape=f"SightOps · Câmeras térmicas · {local}", **k))
    return buf.getvalue()
