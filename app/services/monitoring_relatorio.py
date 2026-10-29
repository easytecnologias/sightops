"""Relatorio de disponibilidade do Monitoramento: quanto tempo cada equipamento
ficou no ar no periodo, quantas quedas teve e quanto tempo ficou fora.

O calculo sai de `monitoring_events` (cada mudanca de estado confirmada): a
linha do tempo de cada equipamento e montada a partir do estado no inicio do
periodo (ultimo evento antes dele) e dos eventos dentro dele.

  disponibilidade = 1 - tempo down / tempo medido
  tempo medido    = up + instavel + down  (nao verificado e manutencao ficam
                    de fora: sem leitura nao ha como dizer que estava no ar)

Instavel conta como no ar (respondeu, mas oscilando) e aparece a parte.
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

ROTULOS = {
    "connector": "Conectores", "olt": "OLTs", "onu": "ONUs/ONTs", "camera": "Câmeras", "nvr": "NVRs", "dvr": "DVRs",
    "windows": "Computadores", "access_device": "Controladoras de acesso", "whatsapp": "WhatsApp",
    "access_point": "Access points", "pdv": "Caixas (PDV)", "switch": "Switches", "link": "Links de provedor",
    "switch_provedor": "Switches de provedores",
}
MEDIDOS = ("up", "unstable", "down")
META_PCT = 99.0          # abaixo disso o equipamento entra em "o que conferir"
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


def _pct(fora: float, medido: float) -> Optional[float]:
    if medido <= 0:
        return None
    return round(max(0.0, 100.0 * (1 - fora / medido)), 2)


def _sql_in(n: int) -> str:
    return ",".join("?" for _ in range(n))


def _entidades(site_f: str, tipo: str, sites: Optional[List[str]]) -> List[Dict[str, Any]]:
    where, params = ["tenant_slug=?", "monitoring_enabled=1"], [_tenant()]
    if tipo:
        where.append("entity_type=?")
        params.append(tipo)
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT entity_key,entity_type,site,display_name,status,last_changed_at,detail_json FROM monitoring_entities "
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


def _calcular(ents: List[Dict[str, Any]], ini: datetime, fim: datetime, dias: List[date]) -> Dict[str, Any]:
    eventos = _eventos([e["entity_key"] for e in ents], ini, fim)
    agora = datetime.now(timezone.utc)
    fim_efetivo = min(fim, agora)  # o futuro do "hoje" nao conta como medido
    equipamentos, quedas = [], []
    fora_dia = {d: 0.0 for d in dias}
    medido_dia = {d: 0.0 for d in dias}
    quedas_dia = {d: 0 for d in dias}
    for ent in ents:
        if fim_efetivo <= ini:
            break
        trechos = _linha_do_tempo(ent, eventos[ent["entity_key"]], ini, fim_efetivo)
        soma = {"up": 0.0, "unstable": 0.0, "down": 0.0, "unknown": 0.0, "maintenance": 0.0}
        n_quedas, n_instab, maior = 0, 0, 0.0
        for k, (a, b, est) in enumerate(trechos):
            seg = (b - a).total_seconds()
            soma[est if est in soma else "unknown"] += seg
            if est == "unstable" and (k == 0 or trechos[k - 1][2] != "unstable") and a > ini:
                n_instab += 1
            if est in MEDIDOS:
                # Reparte o trecho pelos dias de Brasilia (grafico por dia).
                p = a
                while p < b:
                    d = p.astimezone(FUSO).date()
                    corte = min(b, _utc(d + timedelta(days=1)))
                    if d in medido_dia:
                        medido_dia[d] += (corte - p).total_seconds()
                        if est == "down":
                            fora_dia[d] += (corte - p).total_seconds()
                    p = corte
            if est == "down":
                comecou_antes = a <= ini and k == 0
                aberta = b >= fim_efetivo
                maior = max(maior, seg)
                if not comecou_antes:
                    n_quedas += 1
                    d = a.astimezone(FUSO).date()
                    if d in quedas_dia:
                        quedas_dia[d] += 1
                quedas.append({
                    "equipamento": ent.get("display_name") or ent["entity_key"], "entity_key": ent["entity_key"],
                    "tipo": ent["entity_type"], "site": ent["site"] or "Sem site",
                    "inicio": a.astimezone(FUSO).isoformat(timespec="seconds"),
                    "fim": "" if aberta else b.astimezone(FUSO).isoformat(timespec="seconds"),
                    "duracao_s": int(seg), "comecou_antes": comecou_antes, "aberta": aberta,
                })
        medido = soma["up"] + soma["unstable"] + soma["down"]
        equipamentos.append({
            "entity_key": ent["entity_key"], "equipamento": ent.get("display_name") or ent["entity_key"],
            "tipo": ent["entity_type"], "tipo_rotulo": ROTULOS.get(ent["entity_type"], ent["entity_type"]),
            "site": ent["site"] or "Sem site", "status_atual": ent.get("status") or "unknown",
            "disponibilidade": _pct(soma["down"], medido), "fora_s": int(soma["down"]),
            "instavel_s": int(soma["unstable"]), "sem_leitura_s": int(soma["unknown"] + soma["maintenance"]),
            "medido_s": int(medido), "quedas": n_quedas, "instabilidades": n_instab, "maior_queda_s": int(maior),
        })

    def agrupa(chave: str) -> List[Dict[str, Any]]:
        g: Dict[str, Dict[str, Any]] = {}
        for e in equipamentos:
            nome = e[chave]
            x = g.setdefault(nome, {"nome": nome, "equipamentos": 0, "com_queda": 0, "quedas": 0, "fora_s": 0,
                                    "medido_s": 0, "fora_agora": 0})
            x["equipamentos"] += 1
            x["quedas"] += e["quedas"]
            x["com_queda"] += 1 if e["fora_s"] else 0
            x["fora_s"] += e["fora_s"]
            x["medido_s"] += e["medido_s"]
            x["fora_agora"] += 1 if e["status_atual"] == "down" else 0
        for x in g.values():
            x["disponibilidade"] = _pct(x["fora_s"], x["medido_s"])
        return sorted(g.values(), key=lambda x: (x["disponibilidade"] if x["disponibilidade"] is not None else 101,
                                                 x["nome"]))

    fora = sum(e["fora_s"] for e in equipamentos)
    medido = sum(e["medido_s"] for e in equipamentos)
    resumo = {
        "equipamentos": len(equipamentos),
        "disponibilidade": _pct(fora, medido),
        "quedas": sum(e["quedas"] for e in equipamentos),
        "com_queda": sum(1 for e in equipamentos if e["fora_s"]),
        "fora_s": int(fora),
        "medido_s": int(medido),
        "instabilidades": sum(e["instabilidades"] for e in equipamentos),
        "sem_dados": sum(1 for e in equipamentos if not e["medido_s"]),
        "fora_agora": sum(1 for e in equipamentos if e["status_atual"] == "down"),
        "abaixo_meta": sum(1 for e in equipamentos if e["disponibilidade"] is not None and e["disponibilidade"] < META_PCT),
    }
    serie = [{"dia": d.isoformat(), "rotulo": d.strftime("%d/%m"), "disponibilidade": _pct(fora_dia[d], medido_dia[d]),
              "quedas": quedas_dia[d], "fora_s": int(fora_dia[d])} for d in dias]
    return {"resumo": resumo, "equipamentos": equipamentos, "quedas": quedas, "serie": serie,
            "por_site": agrupa("site"), "por_tipo": agrupa("tipo_rotulo")}


def _dur(seg: int) -> str:
    seg = int(seg or 0)
    d, r = divmod(seg, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}min"
    return f"{m} min" if m else f"{seg}s"


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
    dias = [ini_d + timedelta(days=i) for i in range((fim_d - ini_d).days + 1)]
    atual = _calcular(ents, _utc(ini_d), _utc(fim_d + timedelta(days=1)), dias)
    n = len(dias)
    ant_ini, ant_fim = ini_d - timedelta(days=n), ini_d - timedelta(days=1)
    anterior = _calcular(ents, _utc(ant_ini), _utc(ini_d), [])["resumo"]

    eq = atual["equipamentos"]
    piores = sorted([e for e in eq if e["fora_s"] or e["quedas"]],
                    key=lambda e: (-e["fora_s"], -e["quedas"], e["equipamento"]))
    instaveis = sorted([e for e in eq if e["instabilidades"] >= 3],
                       key=lambda e: (-e["instabilidades"], e["equipamento"]))[:15]
    atencao = []
    for e in piores:
        if e["status_atual"] == "down":
            atencao.append({"nivel": "alto", "equipamento": e["equipamento"], "site": e["site"],
                            "texto": f"Continua fora agora; {_dur(e['fora_s'])} fora no período"})
        elif e["disponibilidade"] is not None and e["disponibilidade"] < META_PCT:
            atencao.append({"nivel": "medio", "equipamento": e["equipamento"], "site": e["site"],
                            "texto": f"{e['disponibilidade']:.2f}% no ar, {e['quedas']} queda(s), "
                                     f"{_dur(e['fora_s'])} fora".replace(".", ",", 1)})
    ja = {a["equipamento"] + "|" + a["site"] for a in atencao}
    for e in instaveis:
        if e["equipamento"] + "|" + e["site"] in ja:
            continue
        atencao.append({"nivel": "medio", "equipamento": e["equipamento"], "site": e["site"],
                        "texto": f"Oscilou {e['instabilidades']} vezes (rede ou alimentação instável?)"})

    destaques = []
    rs = atual["resumo"]
    if atual["por_site"] and len(atual["por_site"]) > 1 and atual["por_site"][0]["disponibilidade"] is not None:
        pior = atual["por_site"][0]
        destaques.append(f"Site com menor disponibilidade: {pior['nome']} ({pior['disponibilidade']:.2f}%)."
                         .replace(".", ",", 1))
    if piores:
        destaques.append(f"Equipamento que mais ficou fora: {piores[0]['equipamento']} "
                         f"({piores[0]['site']}), {_dur(piores[0]['fora_s'])}.")
    pior_dia = max(atual["serie"], key=lambda s: s["fora_s"], default=None)
    if pior_dia and pior_dia["fora_s"]:
        destaques.append(f"Pior dia: {pior_dia['rotulo']}, {pior_dia['quedas']} queda(s) e "
                         f"{_dur(pior_dia['fora_s'])} de equipamento fora somados.")
    if rs["sem_dados"]:
        destaques.append(f"{rs['sem_dados']} equipamento(s) sem nenhuma leitura no período (não entram na conta).")

    quedas = sorted(atual["quedas"], key=lambda q: q["inicio"], reverse=True)
    return {
        "ok": True,
        "de": ini_d.isoformat(), "ate": fim_d.isoformat(),
        "anterior_de": ant_ini.isoformat(), "anterior_ate": ant_fim.isoformat(),
        "site": str(site or "").strip(), "tipo": tipo, "tipo_rotulo": ROTULOS.get(tipo, ""),
        "meta_pct": META_PCT,
        "gerado_em": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": rs, "anterior": anterior, "serie": atual["serie"],
        "por_site": atual["por_site"], "por_tipo": atual["por_tipo"],
        "piores": piores[:20], "atencao": sorted(atencao, key=lambda a: a["nivel"] != "alto")[:40], "destaques": destaques,
        "equipamentos": sorted(eq, key=lambda e: (e["site"], e["tipo_rotulo"], e["equipamento"])),
        "quedas": quedas[:LIMITE_QUEDAS], "quedas_total": len(quedas),
        "tipos": [{"valor": k, "rotulo": v} for k, v in ROTULOS.items()],
    }
