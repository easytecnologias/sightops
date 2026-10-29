"""Relatorio de disponibilidade do Monitoramento: em que parte do periodo cada
equipamento esteve NO AR, FORA ou SEM LEITURA. As tres somam 100% e sao o unico
conceito do relatorio (o cliente le "81% no ar, 19% sem leitura" sem precisar de
glossario).

O calculo sai de `monitoring_events` (cada mudanca de estado confirmada): a
linha do tempo de cada equipamento e montada a partir do estado no inicio do
periodo (ultimo evento antes dele) e dos eventos dentro dele.

  no ar       = up ou instavel (respondeu)
  fora        = down confirmado
  sem leitura = nao verificado, manutencao, ou atras de conector fora (nesse
                caso nao da para afirmar nada sobre o equipamento)

Horarios no banco em UTC; dias do periodo no horario de Brasilia. A tela e o
PDF leem o mesmo dicionario."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services import db_store
from app.services.monitoring_service import _tenant

try:
    from zoneinfo import ZoneInfo

    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem tzdata: Brasilia nao tem horario de verao desde 2019
    FUSO = timezone(timedelta(hours=-3))

UM = {
    "connector": "Conector", "olt": "OLT", "onu": "ONU/ONT", "camera": "Câmera", "nvr": "NVR", "dvr": "DVR",
    "windows": "Computador", "access_device": "Controladora de acesso", "whatsapp": "WhatsApp",
    "access_point": "Access point", "pdv": "Caixa (PDV)", "switch": "Switch", "link": "Link de provedor",
    "switch_provedor": "Switch de provedores",
}
ROTULOS = {
    "connector": "Conectores", "olt": "OLTs", "onu": "ONUs/ONTs", "camera": "Câmeras", "nvr": "NVRs", "dvr": "DVRs",
    "windows": "Computadores", "access_device": "Controladoras de acesso", "whatsapp": "WhatsApp",
    "access_point": "Access points", "pdv": "Caixas (PDV)", "switch": "Switches", "link": "Links de provedor",
    "switch_provedor": "Switches de provedores",
}
MEDIDOS = ("up", "unstable", "down")
LIMITE_QUEDAS = 600      # anexo do PDF


def _dt(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dia(v: str, padrao: date) -> date:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return padrao


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=FUSO).astimezone(timezone.utc)


def _sql_in(n: int) -> str:
    return ",".join("?" for _ in range(n))


def _entidades(site_f: str, tipo: str, sites: Optional[List[str]]) -> List[Dict[str, Any]]:
    where, params = ["tenant_slug=?", "monitoring_enabled=1"], [_tenant()]
    if tipo:
        where.append("entity_type=?")
        params.append(tipo)
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT entity_key,entity_type,entity_id,connector_id,site,display_name,status,last_changed_at FROM monitoring_entities "
            f"WHERE {' AND '.join(where)}", tuple(params)).fetchall()]
    liberados = None if sites is None else {str(s).strip().upper() for s in sites if str(s).strip()}
    saida = []
    for r in rows:
        s = str(r.get("site") or "").strip()
        if liberados is not None and s.upper() not in liberados:
            continue  # usuario restrito: so os sites dele
        if site_f and s.upper() != site_f:
            continue
        r["site"] = s
        saida.append(r)
    return saida


def _eventos(chaves: List[str], ini: datetime, fim: datetime) -> Dict[str, Dict[str, Any]]:
    """{chave: {"antes": ultimo evento antes de ini, "dentro": [eventos em ini..fim]}}."""
    tenant = _tenant()
    out: Dict[str, Dict[str, Any]] = {k: {"antes": None, "dentro": [], "depois": None} for k in chaves}
    if not chaves:
        return out
    with db_store._conn() as c:
        for i in range(0, len(chaves), 500):
            lote = chaves[i:i + 500]
            dentro = c.execute(
                "SELECT entity_key,from_status,to_status,created_at FROM monitoring_events WHERE tenant_slug=? "
                f"AND created_at >= ? AND created_at < ? AND entity_key IN ({_sql_in(len(lote))}) ORDER BY created_at, id",
                tuple([tenant, ini.isoformat(), fim.isoformat()] + lote)).fetchall()
            for r in dentro:
                r = dict(r)
                out[r["entity_key"]]["dentro"].append(r)
            antes = c.execute(
                "SELECT e.entity_key,e.to_status,e.created_at FROM monitoring_events e JOIN ("
                "SELECT entity_key, MAX(created_at) AS quando FROM monitoring_events WHERE tenant_slug=? AND created_at < ? "
                f"AND entity_key IN ({_sql_in(len(lote))}) GROUP BY entity_key) u "
                "ON u.entity_key=e.entity_key AND u.quando=e.created_at WHERE e.tenant_slug=?",
                tuple([tenant, ini.isoformat()] + lote + [tenant])).fetchall()
            for r in antes:
                r = dict(r)
                out[r["entity_key"]]["antes"] = r
            # Sem evento antes nem dentro: o estado no periodo e o "de" do primeiro evento depois.
            sem = [k for k in lote if not out[k]["antes"] and not out[k]["dentro"]]
            if sem:
                depois = c.execute(
                    "SELECT e.entity_key,e.from_status,e.created_at FROM monitoring_events e JOIN ("
                    "SELECT entity_key, MIN(created_at) AS quando FROM monitoring_events WHERE tenant_slug=? AND created_at >= ? "
                    f"AND entity_key IN ({_sql_in(len(sem))}) GROUP BY entity_key) u "
                    "ON u.entity_key=e.entity_key AND u.quando=e.created_at WHERE e.tenant_slug=?",
                    tuple([tenant, fim.isoformat()] + sem + [tenant])).fetchall()
                for r in depois:
                    r = dict(r)
                    out[r["entity_key"]]["depois"] = r
    return out


def _linha_do_tempo(ent: Dict[str, Any], ev: Dict[str, Any], ini: datetime, fim: datetime) -> List[tuple]:
    """Trechos (inicio, fim, estado) cobrindo ini..fim."""
    dentro = ev["dentro"]
    if ev["antes"]:
        estado = str(ev["antes"]["to_status"])
    elif dentro:
        estado = str(dentro[0]["from_status"])
    elif ev.get("depois"):
        return [(ini, fim, str(ev["depois"]["from_status"]))]
    else:
        # Sem nenhum evento ate o fim: o estado atual vale desde a ultima mudanca.
        desde = _dt(ent.get("last_changed_at"))
        if desde and desde >= fim:
            return [(ini, fim, "unknown")]
        estado = str(ent.get("status") or "unknown")
        inicio = max(ini, desde) if desde else ini
        return ([(ini, inicio, "unknown")] if inicio > ini else []) + [(inicio, fim, estado)]
    trechos, cursor = [], ini
    for e in dentro:
        quando = _dt(e["created_at"]) or cursor
        quando = min(max(quando, cursor), fim)
        if quando > cursor:
            trechos.append((cursor, quando, estado))
        estado, cursor = str(e["to_status"]), quando
    if fim > cursor:
        trechos.append((cursor, fim, estado))
    return trechos


MARGEM_CONECTOR = timedelta(minutes=30)   # antes da queda confirmada do conector
MARGEM_RETORNO = timedelta(minutes=10)    # depois que o conector volta (leituras atrasadas)


def _juntar(trechos: List[tuple]) -> List[tuple]:
    out: List[tuple] = []
    for a, b, est in trechos:
        if b <= a:
            continue
        if out and out[-1][2] == est and out[-1][1] == a:
            out[-1] = (out[-1][0], b, est)
        else:
            out.append((a, b, est))
    return out


def _janelas_do_conector(trechos: List[tuple]) -> List[tuple]:
    """Periodos em que o conector estava fora (down confirmado). "Sem leitura" do
    proprio conector nao entra: antes de o monitoramento existir tambem e assim."""
    return [(a, b) for a, b, est in _juntar([(a, b, "x" if est == "down" else "ok")
                                             for a, b, est in trechos]) if est == "x"] if trechos else []


def _sem_visibilidade(trechos: List[tuple], janelas: List[tuple]) -> List[tuple]:
    """Atras de conector fora, nada se afirma sobre o equipamento: o trecho vira
    "sem visibilidade". Na meia hora antes da queda confirmada do conector, o que
    ja nao respondia tambem (o conector leva algumas leituras para ser dado como
    fora; as cameras caem junto, um pouco antes)."""
    if not janelas:
        return trechos
    cortes = sorted({t for a, b in janelas for t in (a - MARGEM_CONECTOR, a, b, b + MARGEM_RETORNO)})
    out = []
    for a, b, est in trechos:
        pontos = [a] + [t for t in cortes if a < t < b] + [b]
        for p, q in zip(pontos, pontos[1:]):
            meio = p + (q - p) / 2
            if any(ja <= meio < jb for ja, jb in janelas):
                novo = "blind"
            elif est != "up" and any(ja - MARGEM_CONECTOR <= meio < ja or jb <= meio < jb + MARGEM_RETORNO
                                     for ja, jb in janelas):
                novo = "blind"
            else:
                novo = est
            out.append((p, q, novo))
    return _juntar(out)


def _classe(est: str) -> str:
    """Tres classes, e so elas aparecem no relatorio: no ar, fora, sem leitura."""
    if est in ("up", "unstable"):
        return "no_ar"
    if est == "down":
        return "fora"
    return "sem"


def _tres(s: Dict[str, float]) -> Dict[str, Any]:
    """Percentuais do tempo que somam 100 (o arredondamento vai para "no ar")."""
    total = s["no_ar"] + s["fora"] + s["sem"]
    if total <= 0:
        return {"no_ar_pct": None, "fora_pct": None, "sem_pct": None}
    fora = round(100 * s["fora"] / total, 1)
    sem = round(100 * s["sem"] / total, 1)
    return {"no_ar_pct": round(100 - fora - sem, 1), "fora_pct": fora, "sem_pct": sem}


def _soma0() -> Dict[str, float]:
    return {"no_ar": 0.0, "fora": 0.0, "sem": 0.0}


def _calcular(ents: List[Dict[str, Any]], conectores: List[Dict[str, Any]], ini: datetime, fim: datetime,
              dias: List[date]) -> Dict[str, Any]:
    agora = datetime.now(timezone.utc)
    fim_efetivo = min(fim, agora)  # o futuro do "hoje" nao conta
    if fim_efetivo <= ini:
        return {"resumo": _resumo([], []), "equipamentos": [], "ocorrencias": [], "dias": [], "por_site": [],
                "por_tipo": []}
    eventos = _eventos([e["entity_key"] for e in ents], ini, fim_efetivo)

    # Linha do tempo de cada conector (um pouco alem do fim, por causa da margem).
    fim_con = min(fim_efetivo + MARGEM_CONECTOR, agora)
    ev_con = _eventos([c["entity_key"] for c in conectores], ini, fim_con)
    janelas: Dict[str, List[tuple]] = {}
    trechos_con: Dict[str, List[tuple]] = {}
    for c in conectores:
        t = _linha_do_tempo(c, ev_con[c["entity_key"]], ini, fim_con)
        trechos_con[c["entity_key"]] = t
        janelas[str(c.get("entity_id") or "")] = _janelas_do_conector(t)
    con_por_id = {str(c.get("entity_id") or ""): c for c in conectores}

    def inicio_real(ev: Dict[str, Any], a: datetime) -> datetime:
        """Queda que ja vinha de antes do periodo: quando ela comecou de fato."""
        antes = ev.get("antes") or {}
        if a <= ini and str(antes.get("to_status")) == "down":
            return _dt(antes.get("created_at")) or a
        return a

    equipamentos, ocorrencias = [], []
    por_dia = {d: _soma0() for d in dias}
    quedas_dia = {d: 0 for d in dias}
    dependentes: Dict[str, int] = {}
    for ent in ents:
        ev = eventos[ent["entity_key"]]
        trechos = _linha_do_tempo(ent, ev, ini, fim_efetivo)
        cid = str(ent.get("connector_id") or "")
        atras = ent["entity_type"] != "connector" and cid in janelas
        if atras:
            dependentes[cid] = dependentes.get(cid, 0) + 1
            trechos = _sem_visibilidade(trechos, janelas[cid])
        soma, quedas = _soma0(), 0
        for k, (a, b, est) in enumerate(trechos):
            cl = _classe(est)
            soma[cl] += (b - a).total_seconds()
            p = a  # reparte o trecho pelos dias de Brasilia
            while p < b:
                d = p.astimezone(FUSO).date()
                corte = min(b, _utc(d + timedelta(days=1)))
                if d in por_dia:
                    por_dia[d][cl] += (corte - p).total_seconds()
                p = corte
            if est == "down" and ent["entity_type"] != "connector":
                antes = a <= ini and k == 0
                aberta = b >= fim_efetivo
                if not antes:
                    quedas += 1
                    d = a.astimezone(FUSO).date()
                    if d in quedas_dia:
                        quedas_dia[d] += 1
                real = inicio_real(ev, a) if antes else a
                ocorrencias.append({
                    "tipo": "equipamento", "equipamento": ent.get("display_name") or ent["entity_key"],
                    "tipo_item": UM.get(ent["entity_type"], ent["entity_type"]), "site": ent["site"] or "Sem site",
                    "inicio": real.astimezone(FUSO).isoformat(timespec="seconds"), "antes": antes,
                    "fim": "" if aberta else b.astimezone(FUSO).isoformat(timespec="seconds"), "aberta": aberta,
                    "duracao_s": int((b - real).total_seconds()), "no_periodo_s": int((b - a).total_seconds()),
                    "afetados": 0,
                })
        status = ent.get("status") or "unknown"
        desde = _dt(ent.get("last_changed_at"))
        if atras and trechos and trechos[-1][2] == "blind" and fim_efetivo >= agora - timedelta(minutes=1):
            status = "blind"
            desde = _dt((con_por_id.get(cid) or {}).get("last_changed_at")) or desde
        if ent["entity_type"] == "connector":
            quedas = sum(1 for a, b in janelas.get(str(ent.get("entity_id") or ""), []) if a > ini and a < fim_efetivo)
        equipamentos.append({
            "entity_key": ent["entity_key"], "equipamento": ent.get("display_name") or ent["entity_key"],
            "tipo": ent["entity_type"], "tipo_rotulo": ROTULOS.get(ent["entity_type"], ent["entity_type"]),
            "tipo_item": UM.get(ent["entity_type"], ent["entity_type"]), "site": ent["site"] or "Sem site",
            "status": status, "desde": desde.astimezone(FUSO).isoformat(timespec="seconds") if desde else "",
            "quedas": quedas, "no_ar_s": int(soma["no_ar"]), "fora_s": int(soma["fora"]), "sem_s": int(soma["sem"]),
            **_tres(soma),
        })

    # Quedas de conector: a causa de toda a falta de leitura atras dele.
    no_escopo = {e["entity_key"] for e in ents}
    for cid, c in con_por_id.items():
        if c["entity_key"] not in no_escopo and not dependentes.get(cid):
            continue
        for a, b in janelas.get(cid, []):
            a2, b2 = max(a, ini), min(b, fim_efetivo)
            if b2 <= a2:
                continue
            antes = a2 <= ini
            ultimo = (trechos_con[c["entity_key"]] or [(0, 0, "")])[-1]
            aberta = b2 >= fim_efetivo and ultimo[2] == "down"
            real = inicio_real(ev_con[c["entity_key"]], a2) if antes else a2
            ocorrencias.append({
                "tipo": "conector", "equipamento": c.get("display_name") or c["entity_key"], "tipo_item": "Conector",
                "site": c.get("site") or "Sem site", "inicio": real.astimezone(FUSO).isoformat(timespec="seconds"),
                "antes": antes, "fim": "" if aberta else b2.astimezone(FUSO).isoformat(timespec="seconds"),
                "aberta": aberta, "duracao_s": int((b2 - real).total_seconds()),
                "no_periodo_s": int((b2 - a2).total_seconds()), "afetados": dependentes.get(cid, 0),
            })
    ocorrencias.sort(key=lambda o: o["inicio"], reverse=True)

    def agrupa(chave: str) -> List[Dict[str, Any]]:
        g: Dict[str, Dict[str, Any]] = {}
        for e in equipamentos:
            x = g.setdefault(e[chave], {"nome": e[chave], "equipamentos": 0, "quedas": 0, "fora_agora": 0,
                                        "sem_agora": 0, "_s": _soma0()})
            x["equipamentos"] += 1
            x["quedas"] += e["quedas"]
            x["fora_agora"] += 1 if e["status"] == "down" else 0
            x["sem_agora"] += 1 if e["status"] in ("blind", "unknown") else 0
            for k, campo in (("no_ar", "no_ar_s"), ("fora", "fora_s"), ("sem", "sem_s")):
                x["_s"][k] += e[campo]
        out = []
        for x in g.values():
            out.append({**{k: v for k, v in x.items() if k != "_s"}, **_tres(x["_s"])})
        return sorted(out, key=lambda x: (x["no_ar_pct"] if x["no_ar_pct"] is not None else 101, x["nome"]))

    serie = [{"dia": d.isoformat(), "rotulo": d.strftime("%d/%m"), "quedas": quedas_dia[d], **_tres(por_dia[d])}
             for d in dias]
    return {"resumo": _resumo(equipamentos, ocorrencias), "equipamentos": equipamentos, "ocorrencias": ocorrencias,
            "dias": serie, "por_site": agrupa("site"), "por_tipo": agrupa("tipo_rotulo")}


def _resumo(equipamentos: List[Dict[str, Any]], ocorrencias: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = {"no_ar": float(sum(e["no_ar_s"] for e in equipamentos)), "fora": float(sum(e["fora_s"] for e in equipamentos)),
         "sem": float(sum(e["sem_s"] for e in equipamentos))}
    return {
        "equipamentos": len(equipamentos),
        **_tres(s),
        "quedas": sum(1 for o in ocorrencias if o["tipo"] == "equipamento" and not o["antes"]),
        "quedas_conector": sum(1 for o in ocorrencias if o["tipo"] == "conector" and not o["antes"]),
        "com_queda": len({o["equipamento"] + "|" + o["site"] for o in ocorrencias if o["tipo"] == "equipamento"}),
        "fora_agora": sum(1 for e in equipamentos if e["status"] == "down"),
        "sem_agora": sum(1 for e in equipamentos if e["status"] in ("blind", "unknown")),
        "conector_fora_agora": sum(1 for e in equipamentos if e["tipo"] == "connector" and e["status"] == "down"),
    }


SITUACAO = {"up": "No ar", "unstable": "No ar (instável)", "down": "Fora", "blind": "Sem leitura (conector fora)",
            "unknown": "Sem leitura", "maintenance": "Em manutenção"}


def gerar(de: str = "", ate: str = "", site: str = "", tipo: str = "",
          sites: Optional[List[str]] = None) -> Dict[str, Any]:
    """`sites`: so estes (usuario restrito); None = todos."""
    hoje = datetime.now(FUSO).date()
    fim_d = _dia(ate, hoje)
    ini_d = _dia(de, fim_d - timedelta(days=6))
    if fim_d < ini_d:
        ini_d, fim_d = fim_d, ini_d
    if (fim_d - ini_d).days > 92:
        ini_d = fim_d - timedelta(days=92)  # 3 meses por relatorio: o historico e o PDF tem que caber
    tipo = tipo if tipo in ROTULOS else ""
    site_f = str(site or "").strip().upper()
    ents = _entidades(site_f, tipo, sites)
    # Conectores do cliente inteiro: so para saber quando cada equipamento ficou sem leitura.
    conectores = _entidades("", "connector", None)
    dias = [ini_d + timedelta(days=i) for i in range((fim_d - ini_d).days + 1)]
    atual = _calcular(ents, conectores, _utc(ini_d), _utc(fim_d + timedelta(days=1)), dias)
    n = len(dias)
    ant_ini, ant_fim = ini_d - timedelta(days=n), ini_d - timedelta(days=1)
    anterior = _calcular(ents, conectores, _utc(ant_ini), _utc(ini_d), [])["resumo"]

    eq = atual["equipamentos"]
    for e in eq:
        e["situacao"] = SITUACAO.get(e["status"], "Sem leitura")
    # Pendencias: o que NAO esta no ar agora. Conector primeiro (e a causa),
    # depois o que caiu, depois o que esta sem leitura.
    ordem = {"connector": 0}
    pend = [e for e in eq if e["status"] in ("down", "blind", "unknown")]
    pend.sort(key=lambda e: (ordem.get(e["tipo"], 1), {"down": 0, "unknown": 1, "blind": 2}[e["status"]],
                             e["desde"] or "9", e["equipamento"]))
    # Atras de conector fora vira uma linha so ("24 equipamentos"), nao 24 linhas iguais.
    pendencias, cegos = [], {}
    for e in pend:
        if e["status"] == "blind":
            cegos.setdefault(e["site"], []).append(e)
            continue
        pendencias.append({"equipamento": e["equipamento"], "tipo_item": e["tipo_item"], "site": e["site"],
                           "situacao": e["situacao"], "desde": e["desde"]})
    for s_, lista in cegos.items():
        pendencias.append({"equipamento": f"{len(lista)} equipamento(s) atrás do conector", "tipo_item": "",
                           "site": s_, "situacao": "Sem leitura (conector fora)", "desde": lista[0]["desde"]})

    sites_vistos = {e["site"] for e in eq}
    ocorrencias = atual["ocorrencias"]
    return {
        "ok": True,
        "de": ini_d.isoformat(), "ate": fim_d.isoformat(),
        "anterior_de": ant_ini.isoformat(), "anterior_ate": ant_fim.isoformat(),
        "site": str(site or "").strip(), "tipo": tipo, "tipo_rotulo": ROTULOS.get(tipo, ""),
        "um_site": len(sites_vistos) <= 1,
        "margem_conector_min": int(MARGEM_CONECTOR.total_seconds() // 60),
        "margem_retorno_min": int(MARGEM_RETORNO.total_seconds() // 60),
        "gerado_em": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": atual["resumo"], "anterior": anterior, "dias": atual["dias"],
        "por_site": atual["por_site"], "por_tipo": atual["por_tipo"],
        "pendencias": pendencias,
        "ocorrencias": ocorrencias[:LIMITE_QUEDAS], "ocorrencias_total": len(ocorrencias),
        "equipamentos": sorted(eq, key=lambda e: (e["site"], 0 if e["tipo"] == "connector" else 1, e["tipo_item"],
                                                  e["equipamento"])),
    }
