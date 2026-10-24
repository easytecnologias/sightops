"""Relatorio do Alerta: pedidos de ajuda e como foram atendidos no periodo.

Mesmo formato do relatorio de entrada e saida do controle de acesso: resumo,
"atencao", por site e a lista de atendimentos. A tela e o PDF leem o mesmo
dicionario (alert_relatorio_pdf.gerar_pdf).

Os horarios ficam em UTC no banco; o periodo e as horas do relatorio sao no
horario de Brasilia (o cliente le "14:32", nao "17:32Z").
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services import alert_store as A
from app.services import db_store

try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem tzdata: Brasilia nao tem horario de verao desde 2019
    FUSO = timezone(timedelta(hours=-3))

# Acima disso para alguem assumir, o atendimento entra em "Atencao".
ESPERA_ATENCAO_S = 120
TIPOS = {"": "Todos", "panico": "Pânico", "coacao": "Coação", "cancelado": "Cancelados pela pessoa", "aberto": "Ainda abertos"}


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


def gerar(de: str = "", ate: str = "", site: str = "", tipo: str = "", busca: str = "") -> Dict[str, Any]:
    hoje = datetime.now(FUSO).date()
    ini = _dia(de, hoje)
    fim = _dia(ate, hoje)
    if fim < ini:
        ini, fim = fim, ini
    if (fim - ini).days > 366:
        ini = fim - timedelta(days=366)  # um ano por relatorio: o PDF tem que caber
    desde = datetime(ini.year, ini.month, ini.day, tzinfo=FUSO).astimezone(timezone.utc)
    antes = datetime(fim.year, fim.month, fim.day, tzinfo=FUSO).astimezone(timezone.utc) + timedelta(days=1)
    tipo = tipo if tipo in TIPOS else ""
    site_f = str(site or "").strip().upper()
    termo = str(busca or "").strip().lower()

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
        aberto_em = _local(r.get("opened_at"))
        linhas.append({
            "id": r["id"],
            "data": aberto_em.strftime("%d/%m/%Y") if aberto_em else "",
            "hora": aberto_em.strftime("%H:%M") if aberto_em else "",
            "quando": aberto_em.isoformat(timespec="seconds") if aberto_em else "",
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

    esperas = [x["espera_s"] for x in linhas if x["espera_s"] is not None]
    chegadas = [x["chegada_s"] for x in linhas if x["chegada_s"] is not None]
    resumo = {
        "pedidos": len(linhas),
        "pessoas": len({x["pessoa"] for x in linhas}),
        "coacao": sum(1 for x in linhas if x["tipo"] == "coacao"),
        "cancelados": sum(1 for x in linhas if x["status"] == "cancelled"),
        "encerrados": sum(1 for x in linhas if x["status"] == "closed"),
        "abertos": sum(1 for x in linhas if x["aberto"]),
        "escalados": sum(1 for x in linhas if x["escalado"]),
        "media_assumir_s": _media(esperas),
        "max_assumir_s": max(esperas) if esperas else None,
        "media_chegada_s": _media(chegadas),
    }

    por_site: Dict[str, Dict[str, Any]] = {}
    for x in linhas:
        g = por_site.setdefault(x["site"], {"site": x["site"], "pedidos": 0, "coacao": 0, "esperas": [], "chegadas": []})
        g["pedidos"] += 1
        g["coacao"] += x["tipo"] == "coacao"
        if x["espera_s"] is not None:
            g["esperas"].append(x["espera_s"])
        if x["chegada_s"] is not None:
            g["chegadas"].append(x["chegada_s"])
    sites = sorted(({"site": g["site"], "pedidos": g["pedidos"], "coacao": g["coacao"],
                     "media_assumir_s": _media(g["esperas"]), "media_chegada_s": _media(g["chegadas"])}
                    for g in por_site.values()), key=lambda g: (-g["pedidos"], g["site"]))

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
        elif x["espera_s"] is not None and x["espera_s"] > ESPERA_ATENCAO_S:
            atencao.append({"nivel": "medio", "pessoa": x["pessoa"], "quando": quando,
                            "texto": f"Demorou {x['espera_s'] // 60} min {x['espera_s'] % 60:02d} s para alguém assumir"})
    ordem = {"alto": 0, "medio": 1}
    atencao.sort(key=lambda a: (ordem.get(a["nivel"], 2), a["quando"]))

    return {
        "ok": True,
        "nome": "Atendimentos do Alerta",
        "de": ini.isoformat(),
        "ate": fim.isoformat(),
        "site": site or "",
        "tipo": tipo,
        "tipo_rotulo": TIPOS[tipo],
        "busca": busca or "",
        "gerado_em": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": resumo,
        "por_site": sites,
        "atencao": atencao,
        "linhas": linhas,
        "sites": sorted(sites_vistos),
        "espera_atencao_s": ESPERA_ATENCAO_S,
    }
