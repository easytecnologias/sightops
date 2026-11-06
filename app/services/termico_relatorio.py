"""Numeros do relatorio das Cameras termicas. So le, sempre do cliente da sessao
e dos sites que o usuario acessa. Alarme de teste fica fora dos indicadores."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from app.services import db_store
from app.services.termico_store import FUSO, MOTIVOS_FALSO, _segundos_entre, _site_ok, _tenant

ROTULO_MOTIVO = {"animal": "Animal", "sol": "Reflexo do sol", "equipe": "Equipe da usina", "mato": "Vento ou mato",
                 "veiculo": "Veículo", "outro": "Outro"}
MAX_LISTA = 300


def _dia(txt: str, padrao: date) -> date:
    try:
        return date.fromisoformat(str(txt)[:10]) if txt else padrao
    except ValueError:
        raise ValueError("Data inválida.")


def _local(iso: str) -> Optional[datetime]:
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(FUSO)
    except (TypeError, ValueError):
        return None


def gerar(de: str = "", ate: str = "", site: str = "") -> Dict[str, Any]:
    tenant = _tenant()
    hoje = datetime.now(FUSO).date()
    fim = _dia(ate, hoje)
    ini = _dia(de, fim - timedelta(days=29))
    if ini > fim:
        raise ValueError("A data inicial é depois da final.")
    if (fim - ini).days > 366:
        raise ValueError("Escolha até 1 ano.")
    if site and not _site_ok(site):
        raise LookupError("Usina não encontrada.")
    # Margem de 1 dia nos dois lados: o filtro exato e no horario de Brasilia.
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, site, camera_nome, criado_at, situacao, temp_c, fundo_c, visto_por, visto_at, motivo_falso, mancha "
            "FROM termico_alertas WHERE tenant_slug=? AND criado_at>=? AND criado_at<=? ORDER BY criado_at DESC",
            (tenant, (ini - timedelta(days=1)).isoformat(), (fim + timedelta(days=2)).isoformat())).fetchall()]
    lista: List[Dict[str, Any]] = []
    testes = 0
    usinas: Dict[str, Dict[str, Any]] = {}
    motivos = {m: 0 for m in MOTIVOS_FALSO}
    por_hora = [0] * 24
    tempos: List[float] = []
    for r in rows:
        quando = _local(r.get("criado_at"))
        if not quando or not ini <= quando.date() <= fim or not _site_ok(r.get("site")) or (site and r.get("site") != site):
            continue
        try:
            mancha = json.loads(r.get("mancha") or "{}")
        except ValueError:
            mancha = {}
        if mancha.get("teste"):
            testes += 1
            continue
        u = usinas.setdefault(r.get("site") or "", {"site": r.get("site") or "", "alarmes": 0, "cientes": 0, "falsos": 0, "pendentes": 0, "_t": []})
        u["alarmes"] += 1
        por_hora[quando.hour] += 1
        sit = r.get("situacao")
        if sit == "novo":
            u["pendentes"] += 1
        else:
            u["falsos" if sit == "falso" else "cientes"] += 1
            t = _segundos_entre(r.get("criado_at"), r.get("visto_at"))
            if t is not None and t >= 0:
                u["_t"].append(t)
                tempos.append(t)
        if sit == "falso" and r.get("motivo_falso") in motivos:
            motivos[r["motivo_falso"]] += 1
        if len(lista) < MAX_LISTA:
            lista.append({"quando": quando.strftime("%d/%m/%Y %H:%M"), "site": r.get("site") or "", "camera": r.get("camera_nome") or "",
                          "situacao": sit, "motivo": ROTULO_MOTIVO.get(r.get("motivo_falso") or "", ""),
                          "temp_c": r.get("temp_c"), "fundo_c": r.get("fundo_c"), "por": r.get("visto_por") or ""})
    for u in usinas.values():
        t = u.pop("_t")
        u["resposta_s"] = median(t) if t else None
    total = sum(u["alarmes"] for u in usinas.values())
    return {
        "de": ini.isoformat(), "ate": fim.isoformat(), "site": site, "testes": testes,
        "gerado_em": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": {"alarmes": total, "cientes": sum(u["cientes"] for u in usinas.values()),
                   "falsos": sum(u["falsos"] for u in usinas.values()),
                   "pendentes": sum(u["pendentes"] for u in usinas.values()),
                   "resposta_s": median(tempos) if tempos else None},
        "usinas": sorted(usinas.values(), key=lambda u: u["site"]),
        "motivos": [{"rotulo": ROTULO_MOTIVO[k], "n": v} for k, v in motivos.items() if v],
        "por_hora": por_hora, "lista": lista, "cortada": total > len(lista),
    }
