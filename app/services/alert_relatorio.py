"""Relatorio do Alerta: pedidos de ajuda e como foram atendidos no periodo.

Formato de relatorio analitico de central (como os de SOC e de despacho de
emergencia): resumo com meta e cumprimento (assumir em ate 2 min), mediana e
90o percentil em vez de so media, comparacao com o periodo anterior, volume
por dia e por hora, distribuicao do tempo de resposta, destaques, atencao e a
lista detalhada no fim. A tela e o PDF leem o mesmo dicionario.

Os horarios ficam em UTC no banco; o periodo e as horas do relatorio sao no
horario de Brasilia (o cliente le "14:32", nao "17:32Z").
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services import alert_store as A
from app.services import db_store

try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem tzdata: Brasilia nao tem horario de verao desde 2019
    FUSO = timezone(timedelta(hours=-3))

# Meta da central: assumir o pedido em ate 2 min. Quem passa disso entra em
# "Atencao" e conta como fora do prazo.
META_ASSUMIR_S = 120
ESPERA_ATENCAO_S = META_ASSUMIR_S
TIPOS = {"": "Todos", "panico": "Pânico", "coacao": "Coação", "cancelado": "Cancelados pela pessoa", "aberto": "Ainda abertos"}
FAIXAS_ESPERA = [("até 30s", 0, 30), ("30s a 1min", 30, 60), ("1 a 2min", 60, 120), ("2 a 5min", 120, 300), ("mais de 5min", 300, None)]
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _dt(v: Any) -> Optional[datetime]:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _local(v: Any) -> Optional[datetime]:
    d = _dt(v)
    return d.astimezone(FUSO) if d else None


def _seg(ini: Any, fim: Any) -> Optional[int]:
    a, b = _dt(ini), _dt(fim)
    if not a or not b or b < a:
        return None
    return int((b - a).total_seconds())


def _dia(v: str, padrao: date) -> date:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return padrao


def _media(xs: List[int]) -> Optional[int]:
    return int(sum(xs) / len(xs)) if xs else None


def _percentil(xs: List[int], p: float) -> Optional[int]:
    """Rank mais proximo: o 90o percentil e o tempo em que 9 de 10 ficaram."""
    if not xs:
        return None
    ordem = sorted(xs)
    i = max(0, min(len(ordem) - 1, int(-(-p * len(ordem) // 1)) - 1))
    return ordem[i]


def _carregar(desde: datetime, antes: datetime, site_f: str, tipo: str, termo: str) -> Tuple[List[Dict[str, Any]], set]:
    tenant = A._tenant()
    liberados = A._sites_liberados()
    with db_store._conn() as c:
        rows = A._rows(
            c,
            "SELECT * FROM alert_incidents WHERE tenant_slug=? AND opened_at >= ? AND opened_at < ? ORDER BY opened_at",
            (tenant, A._iso(desde), A._iso(antes)),
        )
        membros = A._members_by_id(c, tenant, [r["member_id"] for r in rows])
    linhas: List[Dict[str, Any]] = []
    sites_vistos: set = set()
    for r in rows:
        m = membros.get(r["member_id"]) or {}
        # Mesma regra da central: quem so ve alguns sites so ve os pedidos deles.
        if not A._membro_liberado(m or None, liberados):
            continue
        s = A.site_do_membro(m) or "Sem site"
        sites_vistos.add(s)
        if site_f and s.upper() != site_f:
            continue
        coacao = (r.get("kind") or "") == "duress"
        status = r.get("status") or "new"
        aberto = status in A.OPEN_STATUSES
        if tipo == "panico" and coacao or tipo == "coacao" and not coacao:
            continue
        if tipo == "cancelado" and status != "cancelled" or tipo == "aberto" and not aberto:
            continue
        if termo and termo not in " ".join(str(x or "") for x in (
                m.get("full_name"), m.get("document_id"), m.get("role_title"), s, r.get("acknowledged_by"),
                r.get("closed_by"), r.get("close_note"))).lower():
            continue
        quando = _local(r.get("opened_at"))
        linhas.append({
            "id": r["id"],
            "data": quando.strftime("%d/%m/%Y") if quando else "",
            "hora": quando.strftime("%H:%M") if quando else "",
            "quando": quando.isoformat(timespec="seconds") if quando else "",
            "pessoa": m.get("full_name") or "(pessoa removida)",
            "cargo": m.get("role_title") or "",
            "site": s,
            "tipo": "coacao" if coacao else "panico",
            "status": status,
            "aberto": aberto,
            "assumido_por": r.get("acknowledged_by") or "",
            "encerrado_por": r.get("closed_by") or "",
            "espera_s": _seg(r.get("opened_at"), r.get("acknowledged_at")),
            "chegada_s": _seg(r.get("opened_at"), r.get("arrived_at")),
            "duracao_s": _seg(r.get("opened_at"), r.get("closed_at")),
            "escalado": bool(r.get("escalated_at")),
            "relato": (r.get("close_note") or "").strip(),
        })
    return linhas, sites_vistos


def _indicadores(linhas: List[Dict[str, Any]]) -> Dict[str, Any]:
    esperas = [x["espera_s"] for x in linhas if x["espera_s"] is not None]
    chegadas = [x["chegada_s"] for x in linhas if x["chegada_s"] is not None]
    no_prazo = sum(1 for e in esperas if e <= META_ASSUMIR_S)
    return {
        "pedidos": len(linhas),
        "pessoas": len({x["pessoa"] for x in linhas}),
        "coacao": sum(1 for x in linhas if x["tipo"] == "coacao"),
        "cancelados": sum(1 for x in linhas if x["status"] == "cancelled"),
        "encerrados": sum(1 for x in linhas if x["status"] == "closed"),
        "abertos": sum(1 for x in linhas if x["aberto"]),
        "escalados": sum(1 for x in linhas if x["escalado"]),
        "assumidos": len(esperas),
        "no_prazo": no_prazo,
        "no_prazo_pct": round(100 * no_prazo / len(esperas)) if esperas else None,
        "media_assumir_s": _media(esperas),
        "mediana_assumir_s": _percentil(esperas, 0.5),
        "p90_assumir_s": _percentil(esperas, 0.9),
        "max_assumir_s": max(esperas) if esperas else None,
        "media_chegada_s": _media(chegadas),
        "mediana_chegada_s": _percentil(chegadas, 0.5),
        "com_chegada": len(chegadas),
    }


def _fmt(seg: Optional[int]) -> str:
    if seg is None:
        return "—"
    m, s = divmod(int(seg), 60)
    return f"{m}m {s:02d}s" if m else f"{s}s"


def gerar(de: str = "", ate: str = "", site: str = "", tipo: str = "", busca: str = "") -> Dict[str, Any]:
    hoje = datetime.now(FUSO).date()
    ini = _dia(de, hoje)
    fim = _dia(ate, hoje)
    if fim < ini:
        ini, fim = fim, ini
    if (fim - ini).days > 366:
        ini = fim - timedelta(days=366)  # um ano por relatorio: o PDF tem que caber
    tipo = tipo if tipo in TIPOS else ""
    site_f = str(site or "").strip().upper()
    termo = str(busca or "").strip().lower()

    def utc(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=FUSO).astimezone(timezone.utc)

    linhas, sites_vistos = _carregar(utc(ini), utc(fim) + timedelta(days=1), site_f, tipo, termo)
    # Periodo anterior do mesmo tamanho, com os mesmos filtros: "subiu ou caiu?"
    dias = (fim - ini).days + 1
    ant_ini, ant_fim = ini - timedelta(days=dias), ini - timedelta(days=1)
    anteriores, _ = _carregar(utc(ant_ini), utc(ini), site_f, tipo, termo)
    resumo = _indicadores(linhas)
    anterior = _indicadores(anteriores)

    # Volume por dia (ate 62 dias) ou por semana (periodo maior), com coacao.
    serie: List[Dict[str, Any]] = []
    passo = 1 if dias <= 62 else 7
    d = ini
    while d <= fim:
        ate_d = min(fim, d + timedelta(days=passo - 1))
        no = [x for x in linhas if d.isoformat() <= x["quando"][:10] <= ate_d.isoformat()]
        serie.append({"rotulo": d.strftime("%d/%m"), "pedidos": len(no), "coacao": sum(1 for x in no if x["tipo"] == "coacao")})
        d = ate_d + timedelta(days=1)
    por_hora = [0] * 24
    por_semana = [0] * 7
    for x in linhas:
        if x["quando"]:
            q = datetime.fromisoformat(x["quando"])
            por_hora[q.hour] += 1
            por_semana[q.weekday()] += 1
    esperas = [x["espera_s"] for x in linhas if x["espera_s"] is not None]
    faixas = [{"rotulo": rot, "pedidos": sum(1 for e in esperas if e >= lo and (hi is None or e < hi)), "no_prazo": hi is not None and hi <= META_ASSUMIR_S}
              for rot, lo, hi in FAIXAS_ESPERA]

    por_site: Dict[str, List[Dict[str, Any]]] = {}
    for x in linhas:
        por_site.setdefault(x["site"], []).append(x)
    sites = sorted(({"site": s, **{k: v for k, v in _indicadores(ls).items()
                                   if k in ("pedidos", "coacao", "media_assumir_s", "mediana_assumir_s", "p90_assumir_s",
                                            "media_chegada_s", "no_prazo_pct")}}
                    for s, ls in por_site.items()), key=lambda g: (-g["pedidos"], g["site"]))

    # Atencao: o que um gestor precisa conferir, do mais grave ao mais leve.
    atencao: List[Dict[str, Any]] = []
    for x in linhas:
        quando = f"{x['data']} {x['hora']}"
        if x["aberto"]:
            atencao.append({"nivel": "alto", "pessoa": x["pessoa"], "quando": quando, "texto": "Ainda aberto: não foi encerrado"})
        if x["tipo"] == "coacao":
            atencao.append({"nivel": "alto", "pessoa": x["pessoa"], "quando": quando, "texto": "Coação: a pessoa digitou a senha de coação"})
        if x["escalado"]:
            atencao.append({"nivel": "medio", "pessoa": x["pessoa"], "quando": quando,
                            "texto": "Ninguém assumiu a tempo: o Telegram do site foi avisado"})
        elif x["espera_s"] is not None and x["espera_s"] > META_ASSUMIR_S:
            atencao.append({"nivel": "medio", "pessoa": x["pessoa"], "quando": quando,
                            "texto": f"Assumido em {_fmt(x['espera_s'])}, acima da meta de {META_ASSUMIR_S // 60} min"})
    ordem = {"alto": 0, "medio": 1}
    atencao.sort(key=lambda a: (ordem.get(a["nivel"], 2), a["quando"]))

    # Destaques em linguagem simples (o que um gestor contaria numa reuniao).
    destaques: List[str] = []
    if linhas:
        pico_h = max(range(24), key=lambda h: por_hora[h])
        destaques.append(f"Horário com mais pedidos: {pico_h:02d}h às {(pico_h + 1) % 24:02d}h ({por_hora[pico_h]} de {len(linhas)}).")
        pico_d = max(range(7), key=lambda i: por_semana[i])
        destaques.append(f"Dia da semana com mais pedidos: {DIAS_SEMANA[pico_d]} ({por_semana[pico_d]}).")
        if resumo["max_assumir_s"] is not None:
            lento = max((x for x in linhas if x["espera_s"] is not None), key=lambda x: x["espera_s"])
            destaques.append(f"Maior espera para assumir: {_fmt(lento['espera_s'])}, em {lento['data']} às {lento['hora']} ({lento['pessoa']}).")
        if len(sites) > 1:
            destaques.append(f"Site com mais pedidos: {sites[0]['site']} ({sites[0]['pedidos']} de {len(linhas)}).")
        if resumo["cancelados"]:
            destaques.append(f"{resumo['cancelados']} pedido(s) cancelado(s) pela própria pessoa no app (senha normal).")
        repetem = sorted(((p, n) for p, n in {x["pessoa"]: sum(1 for y in linhas if y["pessoa"] == x["pessoa"]) for x in linhas}.items() if n >= 3),
                         key=lambda t: -t[1])
        if repetem:
            destaques.append(f"Quem mais acionou: {repetem[0][0]} ({repetem[0][1]} vezes) — vale conferir se são testes ou falso disparo.")

    return {
        "ok": True,
        "nome": "Atendimentos do Alerta",
        "de": ini.isoformat(),
        "ate": fim.isoformat(),
        "anterior_de": ant_ini.isoformat(),
        "anterior_ate": ant_fim.isoformat(),
        "site": site or "",
        "tipo": tipo,
        "tipo_rotulo": TIPOS[tipo],
        "busca": busca or "",
        "gerado_em": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S"),
        "meta_assumir_s": META_ASSUMIR_S,
        "resumo": resumo,
        "anterior": anterior,
        "serie": serie,
        "serie_semanal": passo == 7,
        "por_hora": por_hora,
        "por_semana": por_semana,
        "faixas_espera": faixas,
        "por_site": sites,
        "atencao": atencao,
        "destaques": destaques,
        "linhas": linhas,
        "sites": sorted(sites_vistos),
        "espera_atencao_s": ESPERA_ATENCAO_S,
    }
