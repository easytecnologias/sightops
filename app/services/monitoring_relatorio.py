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
COBERTURA_MINIMA = 0.5   # abaixo disso a disponibilidade do equipamento nao e afirmada


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


def _calcular(ents: List[Dict[str, Any]], conectores: List[Dict[str, Any]], ini: datetime, fim: datetime,
              dias: List[date]) -> Dict[str, Any]:
    agora = datetime.now(timezone.utc)
    fim_efetivo = min(fim, agora)  # o futuro do "hoje" nao conta como medido
    vazio = {"resumo": _resumo([], []), "equipamentos": [], "quedas": [], "serie": [], "por_site": [],
             "por_tipo": [], "conectores": []}
    if fim_efetivo <= ini:
        return vazio
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

    equipamentos, quedas = [], []
    fora_dia = {d: 0.0 for d in dias}
    medido_dia = {d: 0.0 for d in dias}
    quedas_dia = {d: 0 for d in dias}
    dependentes: Dict[str, int] = {}
    for ent in ents:
        trechos = _linha_do_tempo(ent, eventos[ent["entity_key"]], ini, fim_efetivo)
        cid = str(ent.get("connector_id") or "")
        if ent["entity_type"] != "connector" and cid in janelas:
            dependentes[cid] = dependentes.get(cid, 0) + 1
            trechos = _sem_visibilidade(trechos, janelas[cid])
        soma = {"up": 0.0, "unstable": 0.0, "down": 0.0, "unknown": 0.0, "maintenance": 0.0, "blind": 0.0}
        n_quedas, n_instab, maior = 0, 0, 0.0
        for k, (a, b, est) in enumerate(trechos):
            seg = (b - a).total_seconds()
            soma[est if est in soma else "unknown"] += seg
            if est == "unstable" and (k == 0 or trechos[k - 1][2] != "unstable") and a > ini:
                n_instab += 1
            if est in MEDIDOS:
                p = a  # reparte o trecho pelos dias de Brasilia (serie diaria)
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
                    "tipo": ent["entity_type"], "tipo_rotulo": UM.get(ent["entity_type"], ent["entity_type"]),
                    "site": ent["site"] or "Sem site",
                    "inicio": a.astimezone(FUSO).isoformat(timespec="seconds"),
                    "fim": "" if aberta else b.astimezone(FUSO).isoformat(timespec="seconds"),
                    "duracao_s": int(seg), "comecou_antes": comecou_antes, "aberta": aberta,
                })
        total = sum(soma.values())
        medido = soma["up"] + soma["unstable"] + soma["down"]
        cobertura = medido / total if total else 0.0
        status_atual = ent.get("status") or "unknown"
        if ent["entity_type"] != "connector" and cid in janelas and trechos and trechos[-1][2] == "blind" \
                and trechos[-1][1] >= fim_efetivo and fim_efetivo >= agora - timedelta(minutes=1):
            status_atual = "blind"
        equipamentos.append({
            "entity_key": ent["entity_key"], "equipamento": ent.get("display_name") or ent["entity_key"],
            "tipo": ent["entity_type"], "tipo_rotulo": ROTULOS.get(ent["entity_type"], ent["entity_type"]),
            "tipo_item": UM.get(ent["entity_type"], ent["entity_type"]),
            "site": ent["site"] or "Sem site", "status_atual": status_atual,
            "disponibilidade": _pct(soma["down"], medido) if cobertura >= COBERTURA_MINIMA else None,
            "cobertura": round(100 * cobertura, 1),
            "fora_s": int(soma["down"]), "instavel_s": int(soma["unstable"]),
            "sem_visibilidade_s": int(soma["blind"]), "sem_leitura_s": int(soma["unknown"] + soma["maintenance"]),
            "medido_s": int(medido), "periodo_s": int(total), "quedas": n_quedas, "instabilidades": n_instab,
            "maior_queda_s": int(maior),
        })

    # Indisponibilidade dos conectores: a causa de toda a perda de visibilidade.
    nomes_con = {str(c.get("entity_id") or ""): c for c in conectores}
    no_escopo = {e["entity_key"] for e in ents}
    eventos_con = []
    for cid, c in nomes_con.items():
        if c["entity_key"] not in no_escopo and not dependentes.get(cid):
            continue
        for a, b in janelas.get(cid, []):
            a, b = max(a, ini), min(b, fim_efetivo)
            if b <= a:
                continue
            aberta = b >= fim_efetivo and (trechos_con[c["entity_key"]] or [(0, 0, "")])[-1][2] == "down"
            eventos_con.append({
                "conector": c.get("display_name") or c["entity_key"], "site": c.get("site") or "Sem site",
                "inicio": a.astimezone(FUSO).isoformat(timespec="seconds"),
                "fim": "" if aberta else b.astimezone(FUSO).isoformat(timespec="seconds"),
                "duracao_s": int((b - a).total_seconds()), "aberta": aberta, "comecou_antes": a <= ini,
                "afetados": dependentes.get(cid, 0),
            })
    eventos_con.sort(key=lambda x: x["inicio"], reverse=True)

    def agrupa(chave: str) -> List[Dict[str, Any]]:
        g: Dict[str, Dict[str, Any]] = {}
        for e in equipamentos:
            x = g.setdefault(e[chave], {"nome": e[chave], "equipamentos": 0, "quedas": 0, "fora_s": 0, "medido_s": 0,
                                        "periodo_s": 0, "sem_visibilidade_s": 0, "fora_agora": 0, "sem_vis_agora": 0})
            x["equipamentos"] += 1
            x["quedas"] += e["quedas"]
            x["fora_s"] += e["fora_s"]
            x["medido_s"] += e["medido_s"]
            x["periodo_s"] += e["periodo_s"]
            x["sem_visibilidade_s"] += e["sem_visibilidade_s"]
            x["fora_agora"] += 1 if e["status_atual"] == "down" else 0
            x["sem_vis_agora"] += 1 if e["status_atual"] == "blind" else 0
        for x in g.values():
            cob = x["medido_s"] / x["periodo_s"] if x["periodo_s"] else 0.0
            x["cobertura"] = round(100 * cob, 1)
            x["disponibilidade"] = _pct(x["fora_s"], x["medido_s"]) if cob >= COBERTURA_MINIMA else None
        return sorted(g.values(), key=lambda x: (x["disponibilidade"] if x["disponibilidade"] is not None else -1,
                                                 x["nome"]))

    serie = [{"dia": d.isoformat(), "rotulo": d.strftime("%d/%m"), "disponibilidade": _pct(fora_dia[d], medido_dia[d]),
              "quedas": quedas_dia[d], "fora_s": int(fora_dia[d])} for d in dias]
    return {"resumo": _resumo(equipamentos, eventos_con), "equipamentos": equipamentos, "quedas": quedas,
            "serie": serie, "por_site": agrupa("site"), "por_tipo": agrupa("tipo_rotulo"), "conectores": eventos_con}


def _resumo(equipamentos: List[Dict[str, Any]], eventos_con: List[Dict[str, Any]]) -> Dict[str, Any]:
    fora = sum(e["fora_s"] for e in equipamentos)
    medido = sum(e["medido_s"] for e in equipamentos)
    periodo = sum(e["periodo_s"] for e in equipamentos)
    return {
        "equipamentos": len(equipamentos),
        "disponibilidade": _pct(fora, medido),
        "cobertura": round(100 * medido / periodo, 1) if periodo else None,
        "quedas": sum(e["quedas"] for e in equipamentos),
        "com_queda": sum(1 for e in equipamentos if e["fora_s"]),
        "fora_s": int(fora),
        "medido_s": int(medido),
        "sem_visibilidade_s": sum(e["sem_visibilidade_s"] for e in equipamentos),
        "quedas_conector": sum(1 for c in eventos_con if not c["comecou_antes"]),
        "instabilidades": sum(e["instabilidades"] for e in equipamentos),
        "sem_dados": sum(1 for e in equipamentos if e["disponibilidade"] is None),
        "fora_agora": sum(1 for e in equipamentos if e["status_atual"] == "down"),
        "sem_vis_agora": sum(1 for e in equipamentos if e["status_atual"] == "blind"),
        "abaixo_meta": sum(1 for e in equipamentos if e["disponibilidade"] is not None and e["disponibilidade"] < META_PCT),
    }


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


def _br_pct(v: float) -> str:
    return f"{v:.2f}%".replace(".", ",")


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
    # Conectores do cliente inteiro: so para saber quando cada equipamento ficou sem visibilidade.
    conectores = _entidades("", "connector", None)
    dias = [ini_d + timedelta(days=i) for i in range((fim_d - ini_d).days + 1)]
    atual = _calcular(ents, conectores, _utc(ini_d), _utc(fim_d + timedelta(days=1)), dias)
    n = len(dias)
    ant_ini, ant_fim = ini_d - timedelta(days=n), ini_d - timedelta(days=1)
    anterior = _calcular(ents, conectores, _utc(ant_ini), _utc(ini_d), [])["resumo"]

    eq = atual["equipamentos"]
    piores = sorted([e for e in eq if e["fora_s"] or e["quedas"]],
                    key=lambda e: (-e["fora_s"], -e["quedas"], e["equipamento"]))
    atencao = []
    for c in atual["conectores"]:
        if c["aberta"]:
            atencao.append({"nivel": "alto", "equipamento": c["conector"], "site": c["site"],
                            "texto": f"Conector indisponível desde {_quando_br(c['inicio'])}. "
                                     f"{c['afetados']} equipamento(s) sem visibilidade."})
    ja_conector = {a["equipamento"] + "|" + a["site"] for a in atencao}
    for e in piores:
        if e["equipamento"] + "|" + e["site"] in ja_conector:
            continue
        if e["status_atual"] == "down":
            atencao.append({"nivel": "alto", "equipamento": e["equipamento"], "site": e["site"],
                            "texto": f"Indisponível na emissão do relatório. Tempo indisponível no período: "
                                     f"{_dur(e['fora_s'])}."})
        elif e["disponibilidade"] is not None and e["disponibilidade"] < META_PCT:
            atencao.append({"nivel": "medio", "equipamento": e["equipamento"], "site": e["site"],
                            "texto": f"Disponibilidade de {_br_pct(e['disponibilidade'])}, abaixo da meta de "
                                     f"{_br_pct(META_PCT)}; {e['quedas']} ocorrência(s), {_dur(e['fora_s'])} indisponível."})
    ja = {a["equipamento"] + "|" + a["site"] for a in atencao}
    for e in sorted([e for e in eq if e["instabilidades"] >= 3], key=lambda e: (-e["instabilidades"], e["equipamento"]))[:15]:
        if e["equipamento"] + "|" + e["site"] not in ja:
            atencao.append({"nivel": "medio", "equipamento": e["equipamento"], "site": e["site"],
                            "texto": f"{e['instabilidades']} ocorrências de instabilidade no período "
                                     f"(respostas intermitentes)."})
    sem_leitura = [e for e in eq if e["disponibilidade"] is None and e["status_atual"] != "blind"]

    quedas = sorted(atual["quedas"], key=lambda q: q["inicio"], reverse=True)
    return {
        "ok": True,
        "de": ini_d.isoformat(), "ate": fim_d.isoformat(),
        "anterior_de": ant_ini.isoformat(), "anterior_ate": ant_fim.isoformat(),
        "site": str(site or "").strip(), "tipo": tipo, "tipo_rotulo": ROTULOS.get(tipo, ""),
        "meta_pct": META_PCT, "cobertura_minima_pct": int(COBERTURA_MINIMA * 100),
        "margem_conector_min": int(MARGEM_CONECTOR.total_seconds() // 60),
        "margem_retorno_min": int(MARGEM_RETORNO.total_seconds() // 60),
        "gerado_em": datetime.now(FUSO).strftime("%Y-%m-%d %H:%M:%S"),
        "resumo": atual["resumo"], "anterior": anterior, "serie": atual["serie"],
        "por_site": atual["por_site"], "por_tipo": atual["por_tipo"], "conectores": atual["conectores"],
        "piores": piores[:20], "atencao": sorted(atencao, key=lambda a: a["nivel"] != "alto")[:40],
        "sem_leitura": [{"equipamento": e["equipamento"], "site": e["site"], "cobertura": e["cobertura"]}
                        for e in sem_leitura][:40],
        "equipamentos": sorted(eq, key=lambda e: (e["site"], e["tipo_rotulo"], e["equipamento"])),
        "quedas": quedas[:LIMITE_QUEDAS], "quedas_total": len(quedas),
    }


def _quando_br(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso
