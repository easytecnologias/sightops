"""Relatorio de computadores (PDF em texto, ReportLab).

Substitui o de 2026-09, que desenhava cada pagina como IMAGEM com PIL: sem
texto selecionavel nem busca, e gravado em output/reports -- pasta comum a
todos os clientes, onde os arquivos se acumulavam. Este monta o PDF em memoria
e devolve os bytes.

Paginas (mockup aprovado em 14/10/2026):
  1. capa e resumo do parque (numeros, saude, por site, "em resumo");
  2. precisa de atencao, agrupado, com o porque e o que fazer;
  3. uma ficha por computador;
  4. plano de troca e atualizacao + inventario completo.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Mesmo limite da tela e do monitoramento (LIMITE_WINDOWS_MIN).
LIMITE_CONTATO_MIN = 45

ESCURO = colors.HexColor("#13252d")
VERDE = colors.HexColor("#087f5b")
VERMELHO = colors.HexColor("#c92a2a")
AMBAR = colors.HexColor("#a35a00")
AZUL = colors.HexColor("#1864ab")
CINZA = colors.HexColor("#4f5d66")
LINHA = colors.HexColor("#dfe4e8")
FUNDO = colors.HexColor("#f6f8f9")
TEXTO = colors.HexColor("#172026")


def _t(v: Any) -> str:
    return str(v or "").strip()


def _e(v: Any) -> str:
    return escape(_t(v))


# ---------------------------------------------------------------- leitura

def _data(v: Any) -> Optional[datetime]:
    """ISO do servidor ou "/Date(ms)/" do PowerShell 5."""
    s = _t(v)
    if not s:
        return None
    m = re.search(r"/Date\((-?\d+)", s)
    try:
        if m:
            return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _idade_min(row: Dict[str, Any], agora: datetime) -> float:
    d = _data(row.get("last_seen") or row.get("updated_at"))
    return (agora - d).total_seconds() / 60 if d else float("inf")


def _quando(d: Optional[datetime], agora: datetime) -> str:
    if not d:
        return "nunca"
    m = (agora - d).total_seconds() / 60
    if m < 60:
        return f"ha {max(1, int(m))} min"
    if m < 48 * 60:
        return f"ha {int(m / 60)} h"
    return d.astimezone().strftime("%d/%m/%Y")


def _online(row: Dict[str, Any], agora: datetime) -> bool:
    return _t(row.get("status")).lower() in ("online", "agent_reported") and _idade_min(row, agora) <= LIMITE_CONTATO_MIN


def _os_nome(row: Dict[str, Any]) -> str:
    return re.sub(r"^Microsoft\s+", "", _t((row.get("os") or {}).get("name")), flags=re.I)


def _sem_suporte(row: Dict[str, Any]) -> bool:
    return bool(re.search(r"windows (10|8|7)\b", _os_nome(row), re.I))


def _seg(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("security") if isinstance(row.get("security"), dict) else {}


def _bitlocker_c(row: Dict[str, Any]) -> Optional[bool]:
    for v in row.get("bitlocker") or []:
        if isinstance(v, dict) and _t(v.get("mount_point")).upper().startswith("C"):
            return _t(v.get("protection_status")).lower() in ("1", "on", "true")
    return None


def _vol_c(row: Dict[str, Any]) -> Dict[str, Any]:
    for v in row.get("volumes") or []:
        if isinstance(v, dict) and _t(v.get("drive")).upper().startswith("C"):
            return v
    return {}


def _ram(row: Dict[str, Any]) -> float:
    try:
        return float(row.get("ram_gb") or 0)
    except (TypeError, ValueError):
        return 0.0


def _usuario(row: Dict[str, Any]) -> str:
    """"DOMINIO\\maria" -> "maria"."""
    return _t(row.get("logged_user")).rsplit("\\", 1)[-1]


def _cpu(row: Dict[str, Any]) -> str:
    c = row.get("cpu") if isinstance(row.get("cpu"), dict) else {}
    return _t(c.get("name") or row.get("cpu"))


def _cpu_curto(row: Dict[str, Any]) -> str:
    s = re.sub(r"\d+th Gen |Intel\(R\)|Core\(TM\)|\(R\)|\(TM\)|CPU|Processor|@.*$", "", _cpu(row), flags=re.I)
    return " ".join(s.split()) or "-"


def _disco(row: Dict[str, Any]) -> str:
    kind = _t(row.get("disk_kind")).lower()
    tipo = "SSD" if kind in ("ssd", "mixed") else "HD" if kind == "hdd" else ""
    try:
        gb = float(row.get("disk_total_gb") or 0)
    except (TypeError, ValueError):
        gb = 0
    tam = (f"{gb / 1024:.1f} TB".replace(".0 TB", " TB") if gb >= 1000 else f"{gb:.0f} GB") if gb else ""
    return " ".join(x for x in (tipo, tam) if x) or _t(row.get("disk_summary")) or "-"


def aceita_windows_11(row: Dict[str, Any]) -> Tuple[str, str]:
    """("sim"|"nao"|"verificar", motivo) pelo processador e pelo TPM.

    Regra da Microsoft resumida: Intel Core de 8a geracao em diante (ou Core
    Ultra), AMD Ryzen 2000 em diante, e TPM 2.0. Celeron/Pentium/Xeon/Atom tem
    lista propria modelo a modelo: fica "verificar". TPM sem dado (agente sem
    Administrador) tambem.
    """
    cpu = _cpu(row)
    tpm = _seg(row).get("tpm_present")
    cpu_ok: Optional[bool] = None
    m = re.search(r"\bi[3579]-(\d{4,5})", cpu, re.I)
    g = re.search(r"(\d{1,2})th Gen", cpu)
    r = re.search(r"Ryzen\s+\d\s+(?:PRO\s+)?(\d)\d{3}", cpu, re.I)
    if re.search(r"core\(tm\) ultra|core ultra", cpu, re.I):
        cpu_ok = True
    elif g:
        cpu_ok = int(g.group(1)) >= 8
    elif m:
        num = m.group(1)
        # 5 digitos (i5-12400) ou 4 comecando em 10-14 (i3-1115G4, i5-1235U,
        # notebooks da 10a em diante) = dois primeiros; senao (i5-7400) o primeiro.
        geracao = int(num[:2]) if len(num) == 5 or (num[0] == "1" and num[1] in "01234") else int(num[0])
        cpu_ok = geracao >= 8
    elif r:
        cpu_ok = int(r.group(1)) >= 2
    if cpu_ok is False:
        return "nao", "processador fora da lista"
    if tpm is False:
        return "nao", "sem TPM 2.0"
    if cpu_ok and tpm is True:
        return "sim", ""
    return "verificar", "processador ou TPM sem confirmacao"


def problemas(row: Dict[str, Any], agora: datetime) -> List[Dict[str, Any]]:
    """Mesma leitura da tela (windows.js: winProblemas), do mais grave ao menos."""
    p: List[Dict[str, Any]] = []
    seg = _seg(row)
    if seg.get("defender_realtime") is False or seg.get("defender_enabled") is False:
        p.append({"grupo": "seguranca", "det": "Defender " + ("desativado" if seg.get("defender_enabled") is False
                                                             else "em tempo real desligado")})
    c = _vol_c(row)
    try:
        livre = float(c.get("free_percent")) if c.get("free_percent") is not None else None
    except (TypeError, ValueError):
        livre = None
    if livre is not None and livre < 10:
        extra = f" ({c.get('free_gb'):.0f} GB de {c.get('size_gb'):.0f} GB)" if c.get("free_gb") is not None and c.get("size_gb") else ""
        p.append({"grupo": "disco", "det": f"C: com {livre:.0f}% livre{extra}"})
    if not _online(row, agora):
        p.append({"grupo": "contato", "det": f"ultimo contato {_quando(_data(row.get('last_seen') or row.get('updated_at')), agora)}"})
    if _bitlocker_c(row) is False:
        p.append({"grupo": "seguranca", "det": "BitLocker desligado no C:"})
    if seg.get("tpm_ready") is False:
        p.append({"grupo": "seguranca", "det": "TPM nao esta pronto"})
    if _sem_suporte(row):
        aceita, motivo = aceita_windows_11(row)
        txt = {"sim": "aceita Windows 11", "nao": f"nao aceita Windows 11 ({motivo})",
               "verificar": "conferir se aceita Windows 11"}[aceita]
        p.append({"grupo": "windows", "det": f"{_os_nome(row)} · {txt}"})
    ram = _ram(row)
    if row.get("has_ssd") is False or (ram and ram < 7.5):
        o = [x for x in ("HD mecanico" if row.get("has_ssd") is False else "",
                         f"{ram:.0f} GB de RAM" if ram and ram < 7.5 else "") if x]
        p.append({"grupo": "hardware", "det": " e ".join(o)})
    return p


GRUPOS = [
    ("seguranca", "SEGURANCA", "Protecao desligada", VERMELHO, colors.HexColor("#fdecec"),
     "Sem Defender em tempo real ou sem BitLocker, o computador fica exposto a virus e, se for furtado, os dados ficam legiveis.",
     "religar o Defender (ou conferir se outro antivirus o substitui) e ativar o BitLocker onde houver TPM."),
    ("disco", "DISCO", "Disco quase cheio", VERMELHO, colors.HexColor("#fdecec"),
     "Abaixo de 10% livre o Windows deixa de atualizar e o computador fica lento.",
     "limpar arquivos temporarios e downloads; se voltar a encher, trocar por SSD maior."),
    ("contato", "SEM CONTATO", "Nao reporta", CINZA, colors.HexColor("#eef1f3"),
     "Desligado, fora da rede ou com o agente parado. Sem contato, os outros dados deste computador ficam velhos.",
     "confirmar se o computador ainda existe; se sim, rodar o instalador do agente de novo."),
    ("windows", "WINDOWS", "Windows sem suporte", AMBAR, colors.HexColor("#fff3e0"),
     "A Microsoft parou de corrigir falhas de seguranca do Windows 10 em 14/10/2025.",
     "atualizar os compativeis para Windows 11; os outros entram no plano de troca (ultima pagina)."),
    ("hardware", "HARDWARE", "Hardware fraco", AMBAR, colors.HexColor("#fff3e0"),
     "HD mecanico e pouca memoria deixam o computador lento e travando.",
     "trocar o HD por SSD e completar a memoria para 8 GB."),
]


# ---------------------------------------------------------------- estilo

def _estilos() -> Dict[str, ParagraphStyle]:
    b = dict(fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=TEXTO)
    return {
        "corpo": ParagraphStyle("corpo", **b),
        "peq": ParagraphStyle("peq", **{**b, "fontSize": 8.5, "leading": 11, "textColor": CINZA}),
        "tab": ParagraphStyle("tab", **{**b, "fontSize": 8.5, "leading": 10.5}),
        "tabb": ParagraphStyle("tabb", **{**b, "fontSize": 8.5, "leading": 10.5, "fontName": "Helvetica-Bold"}),
        "h1": ParagraphStyle("h1", **{**b, "fontName": "Helvetica-Bold", "fontSize": 17, "leading": 21}),
        "h2": ParagraphStyle("h2", **{**b, "fontName": "Helvetica-Bold", "fontSize": 11.5, "leading": 15, "spaceBefore": 4}),
        "sobre": ParagraphStyle("sobre", **{**b, "fontName": "Helvetica-Bold", "fontSize": 8, "textColor": VERDE}),
        "num": ParagraphStyle("num", **{**b, "fontName": "Helvetica-Bold", "fontSize": 20, "leading": 23}),
        "dir": ParagraphStyle("dir", **{**b, "fontSize": 8.5, "leading": 10.5, "alignment": TA_RIGHT}),
    }


def _cartao(rot: str, val: Any, sub: str, cor: Any, st: Dict[str, ParagraphStyle]) -> Table:
    t = Table([[Paragraph(_e(rot), st["peq"])],
               [Paragraph(f'<font color="{cor.hexval()}">{_e(val)}</font>', st["num"])],
               [Paragraph(_e(sub), st["peq"])]], colWidths=[None])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINHA), ("LEFTPADDING", (0, 0), (-1, -1), 7),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _barra(pct: float, largura: float, cor: Any) -> Table:
    pct = max(0.0, min(100.0, pct))
    cheio = largura * pct / 100
    cols = [w for w in (cheio, largura - cheio) if w > 0.5] or [largura]
    t = Table([[""] * len(cols)], colWidths=cols, rowHeights=[5])
    estilo = [("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e6ebee"))]
    if cheio > 0.5:
        estilo.append(("BACKGROUND", (0, 0), (0, 0), cor))
    t.setStyle(TableStyle(estilo + [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return t


def _tabela(linhas: List[List[Any]], larguras: List[float], cabecalho: bool = True) -> Table:
    t = Table(linhas, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    estilo = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINHA),
              ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if cabecalho:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), FUNDO)]
    t.setStyle(TableStyle(estilo))
    return t


# ---------------------------------------------------------------- paginas

LARG = A4[0] - 36 * mm


def _capa(rows, cliente, logo, agora, st) -> List[Any]:
    total = len(rows)
    on = sum(1 for r in rows if _online(r, agora))
    probs = {id(r): problemas(r, agora) for r in rows}
    conta = lambda g: sum(1 for r in rows if any(x["grupo"] == g for x in probs[id(r)]))  # noqa: E731
    sites = sorted({_t(r.get("site")) or "Sem site" for r in rows})
    longe = sum(1 for r in rows if not _online(r, agora) and _idade_min(r, agora) > 7 * 1440)
    sem_sup = [r for r in rows if _sem_suporte(r)]
    aceitam = sum(1 for r in sem_sup if aceita_windows_11(r)[0] == "sim")
    seg_n = conta("seguranca")
    hw_n = sum(1 for r in rows if any(x["grupo"] in ("hardware", "disco") for x in probs[id(r)]))

    topo_txt = [Paragraph('<font color="#8fd3b8"><b>RELATORIO DE COMPUTADORES</b></font>', st["corpo"]),
                Paragraph(f'<font color="#ffffff" size="22"><b>{_e(cliente) or "Parque de computadores"}</b></font>',
                          ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=22, leading=28)),
                Paragraph(f'<font color="#c3d3d9">Parque Windows · {total} computador{"es" if total != 1 else ""} em '
                          f'{len(sites)} site{"s" if len(sites) != 1 else ""} · gerado em '
                          f'{agora.astimezone().strftime("%d/%m/%Y %H:%M")}</font>', st["corpo"])]
    img = ""
    if logo and Path(logo).exists():
        try:
            img = Image(str(logo), width=34 * mm, height=16 * mm, kind="proportional")
        except Exception:
            img = ""
    topo = Table([[topo_txt, img]], colWidths=[LARG - 40 * mm, 40 * mm])
    topo.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ESCURO), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 14),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 14), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
    out: List[Any] = [topo, Spacer(1, 10)]

    w3 = (LARG - 12) / 3
    cards = [
        _cartao("Computadores", total, f"{len(sites)} site(s)", TEXTO, st),
        _cartao("Online agora", on, f"{(on * 100 // total) if total else 0}% do parque", VERDE, st),
        _cartao("Sem contato", total - on, f"{longe} ha mais de 7 dias" if longe else "desligados ou sem agente",
                VERMELHO if total - on else TEXTO, st),
        _cartao("Seguranca em risco", seg_n, "Defender, BitLocker ou TPM", VERMELHO if seg_n else TEXTO, st),
        _cartao("Windows sem suporte", len(sem_sup), f"{aceitam} aceitam Windows 11", AMBAR if sem_sup else TEXTO, st),
        _cartao("Hardware fraco", hw_n, "disco cheio, HD ou pouca RAM", AMBAR if hw_n else TEXTO, st),
    ]
    g = Table([cards[:3], cards[3:]], colWidths=[w3] * 3)
    g.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    out += [g, Spacer(1, 10)]

    sim = lambda fn: sum(1 for r in rows if fn(r))  # noqa: E731
    saude = [
        ("Agente respondendo", on),
        ("Defender ativo", sim(lambda r: _seg(r).get("defender_realtime") is True)),
        ("BitLocker no C:", sim(lambda r: _bitlocker_c(r) is True)),
        ("Windows com suporte", sim(lambda r: _os_nome(r) and not _sem_suporte(r))),
        ("Com SSD", sim(lambda r: r.get("has_ssd") is True)),
        ("Memoria >= 8 GB", sim(lambda r: _ram(r) >= 7.5)),
        ("AnyDesk instalado", sim(lambda r: bool(_t(r.get("anydesk_id"))))),
    ]
    larg_meia = (LARG - 14) / 2
    col_saude: List[Any] = [Paragraph("Saude do parque", st["h2"])]
    for rot, n in saude:
        pct = n * 100 / total if total else 0
        cor = VERDE if pct >= 90 else AMBAR if pct >= 70 else VERMELHO
        linha = Table([[Paragraph(_e(rot), st["tab"]), Paragraph(f"{n} / {total}", st["dir"])]],
                      colWidths=[larg_meia * 0.7, larg_meia * 0.3])
        linha.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
        col_saude += [linha, _barra(pct, larg_meia, cor)]
    por_site = [[Paragraph("<b>Site</b>", st["tab"]), Paragraph("<b>PCs</b>", st["dir"]),
                 Paragraph("<b>Online</b>", st["dir"]), Paragraph("<b>Alertas</b>", st["dir"])]]
    for s in sites:
        rs = [r for r in rows if (_t(r.get("site")) or "Sem site") == s]
        al = sum(len(probs[id(r)]) for r in rs)
        por_site.append([Paragraph(_e(s), st["tab"]), Paragraph(str(len(rs)), st["dir"]),
                         Paragraph(str(sum(1 for r in rs if _online(r, agora))), st["dir"]),
                         Paragraph(f'<font color="{(VERMELHO if al else CINZA).hexval()}"><b>{al}</b></font>', st["dir"])])
    col_site = [Paragraph("Por site", st["h2"]),
                _tabela(por_site, [larg_meia * 0.52, larg_meia * 0.16, larg_meia * 0.16, larg_meia * 0.16])]
    duas = Table([[col_saude, col_site]], colWidths=[larg_meia + 7, larg_meia + 7])
    duas.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (0, 0), 14)]))
    out += [duas, Spacer(1, 12)]

    # "Em resumo": frase montada dos numeros, para quem nao vai ler o resto.
    partes = []
    if seg_n:
        partes.append(f"{seg_n} computador{'es estao' if seg_n != 1 else ' esta'} com a seguranca em risco "
                      "(Defender desligado, BitLocker inativo ou TPM com problema)")
    if sem_sup:
        partes.append(f"{len(sem_sup)} roda{'m' if len(sem_sup) != 1 else ''} Windows sem suporte da Microsoft"
                      + (f", dos quais {aceitam} aceita{'m' if aceitam != 1 else ''} Windows 11 sem troca de hardware" if aceitam else ""))
    if total - on:
        partes.append(f"{total - on} nao reporta{'m' if total - on != 1 else ''} ha mais de {LIMITE_CONTATO_MIN} min")
    if hw_n:
        partes.append(f"{hw_n} tem disco quase cheio, HD mecanico ou pouca memoria")
    resumo = ("; ".join(partes) + ". Detalhes na pagina 2; plano de troca e atualizacao na ultima pagina.") if partes \
        else "Nenhum problema encontrado nos computadores com agente: seguranca, disco e Windows em dia."
    caixa = Table([[[Paragraph("Em resumo", st["h2"]), Paragraph(_e(resumo[0].upper() + resumo[1:]), st["corpo"])]]],
                  colWidths=[LARG])
    caixa.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FUNDO), ("BOX", (0, 0), (-1, -1), 0.6, LINHA),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    out.append(caixa)
    return out


def _atencao(rows, agora, st) -> List[Any]:
    out: List[Any] = [Paragraph("COMPUTADORES", st["sobre"]), Paragraph("Precisa de atencao", st["h1"]), Spacer(1, 6)]
    algum = False
    for chave, tag, titulo, cor, fundo, porque, acao in GRUPOS:
        itens = [(r, x) for r in rows for x in problemas(r, agora) if x["grupo"] == chave]
        if not itens:
            continue
        algum = True
        n_pc = len({id(r) for r, _ in itens})
        cab = Table([[Paragraph(f'<font color="{cor.hexval()}"><b>{tag}</b></font>', st["tab"]),
                      Paragraph(f"<b>{_e(titulo)}</b>", st["corpo"]),
                      Paragraph(f"{n_pc} computador{'es' if n_pc != 1 else ''}", st["dir"])]],
                    colWidths=[26 * mm, LARG - 26 * mm - 34 * mm, 34 * mm])
        cab.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), fundo), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        linhas = [[Paragraph(f"<b>{_e(r.get('hostname') or r.get('ip'))}</b>", st["tab"]),
                   Paragraph(_e(" · ".join(x for x in (_t(r.get("site")), _t(r.get("sector"))) if x) or "-"), st["tab"]),
                   Paragraph(_e(x["det"]), st["tab"]),
                   Paragraph(_e(r.get("anydesk_id") or "-"), st["dir"])] for r, x in itens]
        t = _tabela(linhas, [30 * mm, 38 * mm, LARG - 30 * mm - 38 * mm - 26 * mm, 26 * mm], cabecalho=False)
        bloco = [cab, Paragraph(_e(porque), st["peq"]), t,
                 Paragraph(f"<b>O que fazer:</b> {_e(acao)}", st["tab"]), Spacer(1, 10)]
        out.append(CondPageBreak(40 * mm))
        out += bloco
    if not algum:
        out.append(Paragraph("Nenhum computador com problema de seguranca, disco, contato, Windows ou hardware.", st["corpo"]))
    return out


def _ficha(row, agora, st) -> List[Any]:
    seg = _seg(row)
    os_ = row.get("os") if isinstance(row.get("os"), dict) else {}
    cpu = row.get("cpu") if isinstance(row.get("cpu"), dict) else {}
    mb = row.get("motherboard") if isinstance(row.get("motherboard"), dict) else {}
    on = _online(row, agora)
    onde = " › ".join(x for x in (_t(row.get("site")), _t(row.get("sector"))) if x).upper()
    out: List[Any] = [
        Paragraph(f"FICHA DO COMPUTADOR{(' · ' + _e(onde)) if onde else ''}", st["sobre"]),
        Paragraph(_e(row.get("hostname") or row.get("ip")), st["h1"]),
        Paragraph(_e(" · ".join(x for x in (
            " ".join(x for x in (_t(row.get("manufacturer")), _t(row.get("model"))) if x),
            f"serial {_t(row.get('serial'))}" if _t(row.get("serial")) else "",
            f"usuario {_usuario(row)}" if _usuario(row) else "",
            ("Online" if on else "Sem contato") + f" · reportou {_quando(_data(row.get('last_seen')), agora)}",
            f"AnyDesk {_t(row.get('anydesk_id'))}" if _t(row.get("anydesk_id")) else "",
        ) if x)), st["peq"]),
        Spacer(1, 6),
    ]
    flags = row.get("health_flags") if isinstance(row.get("health_flags"), list) else []
    if flags:
        a = Table([[Paragraph(f"<b>{len(flags)} alerta{'s' if len(flags) != 1 else ''}:</b> {_e(' · '.join(flags))}",
                              ParagraphStyle("al", parent=st["tab"], textColor=colors.HexColor("#7a1f1f")))]],
                  colWidths=[LARG])
        a.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdecec")),
                               ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#f2c4c4"))]))
        out += [a, Spacer(1, 6)]

    def _ok(v, sim="Sim", nao="Nao", nd="sem dado"):
        if v is None:
            return f'<font color="{CINZA.hexval()}">{nd}</font>'
        return f'<font color="{(VERDE if v else VERMELHO).hexval()}"><b>{sim if v else nao}</b></font>'

    aceita, motivo = aceita_windows_11(row) if _sem_suporte(row) else ("", "")
    seg_l = [("Defender em tempo real", _ok(seg.get("defender_realtime"), "Ligado", "Desligado")),
             ("BitLocker no C:", _ok(_bitlocker_c(row), "Protegido", "Desligado")),
             ("TPM", _ok(seg.get("tpm_ready"), "Pronto", "Nao pronto")),
             ("Secure Boot", _ok(seg.get("secure_boot"), "Ativo", "Desligado")),
             ("Windows com suporte", _ok(None if not _os_nome(row) else not _sem_suporte(row)))]
    if aceita:
        seg_l.append(("Aceita Windows 11", _ok(None if aceita == "verificar" else aceita == "sim", nd="verificar")))
    hot = next((h for h in (row.get("hotfixes") or []) if isinstance(h, dict) and _t(h.get("id"))), {})
    boot = _data(os_.get("last_boot"))
    mods = [m for m in (row.get("memory_modules") or []) if isinstance(m, dict) and m.get("capacity_gb")]
    sis_l = [("Windows", " · ".join(x for x in (_os_nome(row), f"build {_t(os_.get('build'))}" if _t(os_.get("build")) else "") if x)),
             ("Ultima atualizacao", " · ".join(x for x in (_t(hot.get("id")), _t(hot.get("installed_on"))) if x)),
             ("Ligado desde", boot.astimezone().strftime("%d/%m/%Y %H:%M") if boot else ""),
             ("Dominio", _t(row.get("domain"))),
             ("Agente SightOps", " · ".join(x for x in (_t(row.get("agent_version")),
                                                         "tarefa agendada" if row.get("agent_scheduled") else
                                                         ("sem tarefa agendada" if row.get("agent_scheduled") is False else "")) if x))]
    hw_l = [("Processador", " · ".join(x for x in (_cpu_curto(row), f"{cpu.get('cores')} nucleos" if cpu.get("cores") else "") if x)),
            ("Memoria", " · ".join(x for x in (f"{_ram(row):.0f} GB" if _ram(row) else "",
                                               next((_t(m.get("ddr")) for m in mods if _t(m.get("ddr"))), ""),
                                               f"{len(mods)} pente(s)" if mods else "") if x)),
            ("Placa-mae", " ".join(x for x in (_t(mb.get("manufacturer")), _t(mb.get("model"))) if x)),
            ("Video", ", ".join(_t(g.get("name")) for g in (row.get("gpus") or []) if isinstance(g, dict) and _t(g.get("name")))),
            ("Disco", _disco(row))]

    def _bloco(titulo, pares, largura, html=False):
        lin = [[Paragraph(_e(k), st["peq"]), Paragraph(v if html else (_e(v) or "-"), st["tab"])] for k, v in pares]
        t = Table(lin, colWidths=[largura * 0.42, largura * 0.58])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return [Paragraph(titulo, st["h2"]), t]

    meia = (LARG - 16) / 2
    vols = []
    for v in row.get("volumes") or []:
        if not isinstance(v, dict) or not _t(v.get("drive")):
            continue
        try:
            livre = float(v.get("free_percent"))
        except (TypeError, ValueError):
            livre = None
        cor = VERDE if livre is None or livre >= 20 else AMBAR if livre >= 10 else VERMELHO
        txt = f"{v.get('free_gb'):.0f} GB livres de {v.get('size_gb'):.0f} GB" if v.get("free_gb") is not None and v.get("size_gb") else ""
        vols += [Paragraph(f"<b>{_e(v.get('drive'))}</b> {_e(txt)}" + (f" · {livre:.0f}% livre" if livre is not None else ""), st["tab"]),
                 _barra(100 - (livre or 0), meia, cor), Spacer(1, 3)]
    grade = Table([[_bloco("Seguranca", seg_l, meia, html=True), _bloco("Sistema", sis_l, meia)],
                   [_bloco("Hardware", hw_l, meia), [Paragraph("Discos", st["h2"])] + (vols or [Paragraph("-", st["tab"])])]],
                  colWidths=[meia + 8, meia + 8])
    grade.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (0, -1), 16)]))
    out += [grade, Spacer(1, 4)]

    p = row.get("physical") if isinstance(row.get("physical"), dict) else {}
    net = next((n for n in (row.get("network") or []) if isinstance(n, dict) and n.get("mac")), {})
    rede = f"IP {_e(row.get('ip'))} · MAC {_e(row.get('mac') or net.get('mac'))}"
    caminho = [x for x in (
        f"Switch {_t(p.get('switch_name'))}" + (f" porta {_t(p.get('switch_port'))}" if _t(p.get("switch_port")) else "") if _t(p.get("switch_name")) else "",
        f"Patch panel {_t(p.get('patch_panel'))}" + (f" porta {_t(p.get('patch_port'))}" if _t(p.get("patch_port")) else "") if _t(p.get("patch_panel")) else "",
        f"Tomada {_t(p.get('outlet'))}" if _t(p.get("outlet")) else "",
        f"Rack {_t(p.get('rack'))}" if _t(p.get("rack")) else "") if x]
    out += [Paragraph("Rede e caminho fisico", st["h2"]), Paragraph(rede, st["tab"]),
            Paragraph(_e(" → ".join([_t(row.get("hostname"))] + caminho)) if caminho else
                      "Caminho fisico nao informado.", st["peq"])]

    eventos = [e for e in (row.get("eventos") or []) if isinstance(e, dict)]
    limite = agora.timestamp() - 30 * 86400
    recentes = [e for e in eventos if (_data(e.get("em")) or agora).timestamp() >= limite][-10:][::-1]
    out.append(Paragraph("O que mudou nos ultimos 30 dias", st["h2"]))
    if recentes:
        lin = [[Paragraph(_e((_data(e.get("em")) or agora).astimezone().strftime("%d/%m %H:%M")), st["peq"]),
                Paragraph(_e(e.get("txt")), st["tab"])] for e in recentes]
        out.append(_tabela(lin, [28 * mm, LARG - 28 * mm], cabecalho=False))
    else:
        out.append(Paragraph("Sem mudancas registradas.", st["peq"]))
    obs = Table([[""]], colWidths=[LARG], rowHeights=[16 * mm])
    obs.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINHA)]))
    out += [Paragraph("Observacoes do tecnico", st["h2"]), obs]
    return out


def _plano(rows, agora, st) -> List[Any]:
    out: List[Any] = [Paragraph("COMPUTADORES", st["sobre"]), Paragraph("Plano de troca e atualizacao", st["h1"]), Spacer(1, 6)]
    trocar, atualizar, verificar, melhorar = [], [], [], []
    for r in rows:
        if _sem_suporte(r):
            a, motivo = aceita_windows_11(r)
            (trocar if a == "nao" else atualizar if a == "sim" else verificar).append((r, motivo))
        acoes = []
        if r.get("has_ssd") is False:
            acoes.append("trocar HD por SSD")
        if 0 < _ram(r) < 7.5:
            acoes.append(f"memoria de {_ram(r):.0f} GB para 8 GB")
        c = _vol_c(r)
        try:
            if c.get("free_percent") is not None and float(c["free_percent"]) < 10:
                acoes.append(f"liberar espaco no C: ({float(c['free_percent']):.0f}% livre) ou SSD maior")
        except (TypeError, ValueError):
            pass
        if acoes and not any(x is r for x, _ in trocar):
            melhorar.append((r, "; ".join(acoes)))
    w3 = (LARG - 12) / 3
    g = Table([[_cartao("Trocar o computador", len(trocar), "nao aceita Windows 11", VERMELHO if trocar else TEXTO, st),
                _cartao("Atualizar para Windows 11", len(atualizar), "hardware ja compativel", AZUL if atualizar else TEXTO, st),
                _cartao("Trocar peca", len(melhorar), "SSD, memoria ou disco", AMBAR if melhorar else TEXTO, st)]],
              colWidths=[w3] * 3)
    g.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    out += [g, Spacer(1, 8)]

    def _onde(r):
        return " · ".join(x for x in (_t(r.get("site")), _t(r.get("sector"))) if x) or "-"

    def _hoje(r):
        return " · ".join(x for x in (_cpu_curto(r), f"{_ram(r):.0f} GB" if _ram(r) else "", _disco(r), _os_nome(r)) if x and x != "-")

    cab = lambda *c: [Paragraph(f"<b>{_e(x)}</b>", st["tab"]) for x in c]  # noqa: E731
    secoes = [
        ("Trocar o computador", "Nao aceitam Windows 11 (processador fora da lista ou sem TPM 2.0).", trocar,
         lambda r, m: [r.get("hostname"), _onde(r), _hoje(r), m], ("Computador", "Local", "Hoje", "Motivo"), [30, 36, 70, 38]),
        ("Atualizar para Windows 11", "Hardware compativel: so a atualizacao do sistema.", atualizar,
         lambda r, m: [r.get("hostname"), _onde(r), _hoje(r), ""], ("Computador", "Local", "Hoje", ""), [30, 36, 90, 18]),
        ("Conferir se aceita Windows 11", "Processador com lista propria da Microsoft ou TPM sem dado (agente sem Administrador).",
         verificar, lambda r, m: [r.get("hostname"), _onde(r), _hoje(r), m], ("Computador", "Local", "Hoje", "Por que"), [30, 36, 70, 38]),
        ("Melhorar sem trocar", "Peca ou limpeza resolve.", melhorar,
         lambda r, m: [r.get("hostname"), _onde(r), m], ("Computador", "Local", "O que fazer"), [30, 40, 104]),
    ]
    for titulo, sub, itens, fn, cols, larg in secoes:
        if not itens:
            continue
        lin = [cab(*cols)] + [[Paragraph(_e(v), st["tab"]) for v in fn(r, m)] for r, m in itens]
        out += [CondPageBreak(30 * mm), Paragraph(titulo, st["h2"]), Paragraph(_e(sub), st["peq"]),
                _tabela(lin, [w * mm for w in larg]), Spacer(1, 8)]
    if not (trocar or atualizar or verificar or melhorar):
        out.append(Paragraph("Nenhum computador precisa de troca ou de peca no momento.", st["corpo"]))

    lin = [cab("Computador", "Site · setor", "Windows", "CPU / RAM / disco", "Serial", "AnyDesk")]
    for r in sorted(rows, key=lambda x: (_t(x.get("site")), _t(x.get("hostname")))):
        lin.append([Paragraph(f"<b>{_e(r.get('hostname') or r.get('ip'))}</b>", st["tab"]), Paragraph(_e(_onde(r)), st["tab"]),
                    Paragraph(_e(_os_nome(r).replace("Windows ", "") or "-"), st["tab"]),
                    Paragraph(_e(" / ".join(x for x in (_cpu_curto(r), f"{_ram(r):.0f} GB" if _ram(r) else "", _disco(r)) if x)), st["tab"]),
                    Paragraph(_e(r.get("serial") or "-"), st["tab"]), Paragraph(_e(r.get("anydesk_id") or "-"), st["tab"])])
    out += [CondPageBreak(40 * mm), Paragraph("Inventario completo", st["h2"]),
            _tabela(lin, [w * mm for w in (26, 34, 20, 50, 24, 20)])]
    return out


# ---------------------------------------------------------------- montagem

def build_windows_inventory_pdf(rows: List[Dict[str, Any]], company_name: str = "",
                                logo_path: Optional[Path] = None, agora: Optional[datetime] = None) -> bytes:
    agora = agora or datetime.now(timezone.utc)
    rows = [r for r in rows if isinstance(r, dict)]
    st = _estilos()
    cliente = _t(company_name)
    rotulo = f"{cliente} · Relatorio de computadores · {agora.astimezone().strftime('%d/%m/%Y')}" if cliente \
        else f"Relatorio de computadores · {agora.astimezone().strftime('%d/%m/%Y')}"

    def _rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(CINZA)
        canvas.drawString(18 * mm, 10 * mm, rotulo)
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Pagina {doc.page}")
        canvas.setStrokeColor(LINHA)
        canvas.line(18 * mm, 13.5 * mm, A4[0] - 18 * mm, 13.5 * mm)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=f"Relatorio de computadores - {cliente}" if cliente else "Relatorio de computadores",
                            author="SightOps")
    historia: List[Any] = _capa(rows, cliente, logo_path, agora, st)
    if rows:
        historia += [PageBreak()] + _atencao(rows, agora, st)
        peso = {g[0]: i for i, g in enumerate(GRUPOS)}
        ordem = sorted(rows, key=lambda r: (min([peso[x["grupo"]] for x in problemas(r, agora)] or [99]),
                                            _t(r.get("hostname"))))
        for r in ordem:
            historia += [PageBreak()] + [KeepTogether(_ficha(r, agora, st))]
        historia += [PageBreak()] + _plano(rows, agora, st)
    doc.build(historia, onFirstPage=_rodape, onLaterPages=_rodape)
    return buf.getvalue()
