"""Painel novo do controle de acesso (/v3/acesso/): so leitura.

Convive com as telas antigas: nao muda rota nem dado que elas usam. Junta numa
resposta o que a tela antiga espalhava (ou nao mostrava):

- saude dos avisos de WhatsApp pelos envios de VERDADE. O monitoramento olhava
  so se o token da Meta era valido: de 15/09 a 07/10/2026 a conta da RADS ficou
  com pendencia de pagamento ("Business eligibility payment issue"), o token
  continuava valido, o canal aparecia online e 1.208 avisos nao chegaram aos
  pais sem ninguem saber;
- marcacoes sem pessoa por porta (no condominio, 92% numa semana: moradores
  cadastrados so no leitor);
- fotos recusadas pelos leitores (pessoa que nao abre a porta);
- ao vivo: passagens com foto, turma e o recibo do aviso (lido/entregue).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.services import db_store

# Status gravados em access_whatsapp_messages (envio + webhook da Meta).
FALHA = {"failed", "whatsapp_failed"}
LIDO = {"read"}
ENTREGUE = {"delivered"}
ENVIADO = {"sent", "whatsapp_sent"}

# O leitor grava occurred_at no horario local, sem fuso; o log do WhatsApp
# grava em UTC. Brasil sem horario de verao desde 2019.
FUSO_LOCAL = timezone(timedelta(hours=-3))

# Alerta de avisos: com pelo menos MINIMO envios na janela, mais que LIMITE
# falhando = o canal nao esta entregando, mesmo "conectado".
ALERTA_JANELA_MIN = 30
ALERTA_MINIMO = 10
ALERTA_LIMITE = 0.10


def _t(v: Any) -> str:
    return str(v or "").strip()


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _utc_txt(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _local_txt(d: datetime) -> str:
    return d.astimezone(FUSO_LOCAL).strftime("%Y-%m-%d %H:%M:%S")


def _ler_utc(v: Any) -> Optional[datetime]:
    s = _t(v)
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        try:
            d = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _ler_local(v: Any) -> Optional[datetime]:
    s = _t(v)[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=FUSO_LOCAL)
    except ValueError:
        return None


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _rows(sql: str, params: Iterable[Any]) -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]


def _numero(v: Any) -> str:
    """Mesma regra do log (_digits_br): so digitos, com 55 na frente."""
    d = "".join(ch for ch in _t(v) if ch.isdigit())
    if not d:
        return ""
    return d if d.startswith("55") and len(d) >= 12 else "55" + d


def _classe(status: Any) -> str:
    s = _t(status).lower()
    if s in FALHA:
        return "falha"
    if s in LIDO:
        return "lido"
    if s in ENTREGUE:
        return "entregue"
    if s in ENVIADO:
        return "enviado"
    return "outro"


def _mensagens(desde: datetime) -> List[Dict[str, Any]]:
    return _rows(
        "SELECT contact_number, status, error, created_at, updated_at FROM access_whatsapp_messages "
        "WHERE tenant_slug=? AND direction='out' AND created_at >= ? ORDER BY created_at",
        (_tenant(), _utc_txt(desde)),
    )


# ---------------------------------------------------------------- avisos

def saude_avisos(minutos: int = ALERTA_JANELA_MIN, agora: Optional[datetime] = None) -> Dict[str, Any]:
    """Envios reais da janela. `alerta` so com volume minimo, para 1 falha em
    2 envios de madrugada nao virar alarme.

    Janela com pouco envio (noite, fim de semana) nao "recupera" o canal: o
    julgamento passa a ser pelos ultimos 20 avisos das ultimas 24 h. Sem isso,
    num bloqueio de pagamento o canal voltava a online toda noite e caia de
    novo de manha.
    """
    agora = agora or _agora()
    msgs = _mensagens(agora - timedelta(minutes=minutos))
    if sum(1 for m in msgs if _classe(m.get("status")) != "outro") < ALERTA_MINIMO:
        recentes = [m for m in _mensagens(agora - timedelta(hours=24)) if _classe(m.get("status")) != "outro"]
        if len(recentes) > len(msgs):
            msgs = recentes[-20:]
            minutos = int((agora - (_ler_utc(msgs[0].get("created_at")) or agora)).total_seconds() // 60) or minutos
    c = Counter(_classe(m.get("status")) for m in msgs)
    total = sum(c[k] for k in ("falha", "lido", "entregue", "enviado"))
    falhas = c["falha"]
    taxa = falhas / total if total else 0.0
    erros = Counter(_t(m.get("error")) for m in msgs if _classe(m.get("status")) == "falha" and _t(m.get("error")))
    return {
        "janela_min": minutos, "enviados": total, "falhas": falhas, "taxa_falha": round(taxa, 3),
        "alerta": total >= ALERTA_MINIMO and taxa > ALERTA_LIMITE,
        "erro_principal": erros.most_common(1)[0][0] if erros else "",
    }


def _incidentes(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dias com 10+ avisos e metade ou mais falhando, juntando dias vizinhos
    (fim de semana sem aula nao quebra o mesmo incidente)."""
    por_dia: Dict[str, Counter] = defaultdict(Counter)
    erros_dia: Dict[str, Counter] = defaultdict(Counter)
    for m in msgs:
        dia = _t(m.get("created_at"))[:10]
        cl = _classe(m.get("status"))
        por_dia[dia][cl] += 1
        if cl == "falha" and _t(m.get("error")):
            erros_dia[dia][_t(m.get("error"))] += 1
    ruins = []
    for dia in sorted(por_dia):
        c = por_dia[dia]
        tot = sum(c.values())
        if tot >= 10 and c["falha"] / tot >= 0.5:
            ruins.append(dia)
    periodos: List[Dict[str, Any]] = []
    for dia in ruins:
        d = datetime.strptime(dia, "%Y-%m-%d")
        if periodos and (d - datetime.strptime(periodos[-1]["fim"], "%Y-%m-%d")).days <= 3:
            periodos[-1]["fim"] = dia
            periodos[-1]["dias"].append(dia)
        else:
            periodos.append({"inicio": dia, "fim": dia, "dias": [dia]})
    saida = []
    for p in periodos:
        falhas = sum(por_dia[d]["falha"] for d in p["dias"])
        erros = Counter()
        for d in p["dias"]:
            erros.update(erros_dia[d])
        saida.append({"inicio": p["inicio"], "fim": p["fim"], "falhas": falhas,
                      "erro": erros.most_common(1)[0][0] if erros else ""})
    return saida


def _responsaveis(pessoas: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    mapa: Dict[str, Dict[str, Any]] = {}
    for p in pessoas:
        n = _numero(p.get("guardian_phone"))
        if n:
            mapa.setdefault(n, p)
    return mapa


def _avisos(agora: datetime, pessoas: List[Dict[str, Any]]) -> Dict[str, Any]:
    msgs60 = _mensagens(agora - timedelta(days=60))
    corte7 = _utc_txt(agora - timedelta(days=7))
    corte30 = _utc_txt(agora - timedelta(days=30))
    sete = [m for m in msgs60 if _t(m.get("created_at")) >= corte7]
    c7 = Counter(_classe(m.get("status")) for m in sete)
    total7 = sum(c7[k] for k in ("falha", "lido", "entregue", "enviado"))

    por_dia: Dict[str, Counter] = defaultdict(Counter)
    for m in msgs60:
        if _t(m.get("created_at")) >= corte30:
            por_dia[_t(m.get("created_at"))[:10]][_classe(m.get("status"))] += 1
    serie = []
    for i in range(29, -1, -1):
        dia = (agora - timedelta(days=i)).strftime("%Y-%m-%d")
        c = por_dia.get(dia, Counter())
        serie.append({"dia": dia, "lido": c["lido"], "entregue": c["entregue"],
                      "enviado": c["enviado"], "falha": c["falha"]})

    motivos = Counter(_t(m.get("error")) or "sem motivo informado" for m in sete if _classe(m.get("status")) == "falha")

    # Quem esta sem receber AGORA: o ultimo aviso de cada numero (14 dias) falhou.
    corte14 = _utc_txt(agora - timedelta(days=14))
    ultimo: Dict[str, Dict[str, Any]] = {}
    for m in msgs60:
        if _t(m.get("created_at")) >= corte14:
            ultimo[_t(m.get("contact_number"))] = m
    resp = _responsaveis(pessoas)
    falhando = []
    for numero, m in ultimo.items():
        if _classe(m.get("status")) != "falha":
            continue
        p = resp.get(numero) or {}
        falhando.append({"numero": numero, "erro": _t(m.get("error")), "quando": _t(m.get("updated_at") or m.get("created_at")),
                         "responsavel": _t(p.get("guardian_name")), "pessoa": _t(p.get("full_name")),
                         "turma": _t(p.get("class_name")), "pessoa_id": _t(p.get("id"))})
    falhando.sort(key=lambda x: x["quando"], reverse=True)
    sem_numero = [{"pessoa": _t(p.get("full_name")), "turma": _t(p.get("class_name")), "pessoa_id": _t(p.get("id"))}
                  for p in pessoas if _t(p.get("person_type")) == "student" and p.get("active")
                  and not _numero(p.get("guardian_phone"))]
    return {
        "sete_dias": {"enviados": total7, "lidos": c7["lido"], "entregues": c7["entregue"],
                      "sem_confirmacao": c7["enviado"], "falhas": c7["falha"]},
        "serie_30d": serie,
        "motivos_7d": [{"motivo": k, "qtd": v} for k, v in motivos.most_common(6)],
        "incidentes": _incidentes(msgs60),
        "falhando": falhando[:50],
        "sem_numero": sem_numero[:50],
        "sem_numero_total": len(sem_numero),
        "agora": saude_avisos(agora=agora),
    }


# ---------------------------------------------------------------- visao geral

def _pessoas() -> List[Dict[str, Any]]:
    from app.services.access_control_store import list_people
    return list_people()


def _leitores(site: str = "") -> List[Dict[str, Any]]:
    from app.services.access_control_store import list_devices
    return [d for d in list_devices(site) if d.get("active")]


def visao_geral(site: str = "", agora: Optional[datetime] = None) -> Dict[str, Any]:
    agora = agora or _agora()
    tenant = _tenant()
    pessoas = _pessoas()
    if site:
        pessoas = [p for p in pessoas if _t(p.get("site")).upper() == site.upper()]

    # Marcacoes sem pessoa por porta, 7 dias. occurred_at e hora local.
    corte = _local_txt(agora - timedelta(days=7))
    sql = ("SELECT device_name, person_id, person_name_raw FROM access_events "
           "WHERE tenant_slug=? AND occurred_at >= ?" + (" AND site=?" if site else ""))
    eventos = _rows(sql, (tenant, corte, site) if site else (tenant, corte))
    por_porta: Dict[str, Dict[str, Any]] = {}
    for e in eventos:
        porta = _t(e.get("device_name")) or "sem porta"
        info = por_porta.setdefault(porta, {"porta": porta, "total": 0, "sem_pessoa": 0, "nomes": Counter()})
        info["total"] += 1
        if not _t(e.get("person_id")):
            info["sem_pessoa"] += 1
            nome = _t(e.get("person_name_raw"))
            if nome:
                info["nomes"][nome] += 1
    portas = []
    for info in por_porta.values():
        if not info["sem_pessoa"]:
            continue
        portas.append({"porta": info["porta"], "total": info["total"], "sem_pessoa": info["sem_pessoa"],
                       "exemplos": [n for n, _ in info["nomes"].most_common(3)],
                       "nomes_distintos": len(info["nomes"])})
    portas.sort(key=lambda x: x["sem_pessoa"], reverse=True)
    total_ev = len(eventos)
    sem_ev = sum(1 for e in eventos if not _t(e.get("person_id")))

    # Fotos nos leitores (provisionamento).
    prov = _rows("SELECT person_id, device_id, status, last_error, updated_at FROM access_provision_status WHERE tenant_slug=?",
                 (tenant,))
    nomes_p = {_t(p.get("id")): p for p in _pessoas()}
    leitores = _leitores(site)
    nomes_d = {_t(d.get("id")): _t(d.get("name")) for d in _leitores()}
    if site:
        ids_site = {_t(d.get("id")) for d in leitores}
        prov = [r for r in prov if _t(r.get("device_id")) in ids_site]
    cont = Counter(_t(r.get("status")).lower() or "pendente" for r in prov)
    recusadas = [{"pessoa": _t((nomes_p.get(_t(r.get("person_id"))) or {}).get("full_name")) or "pessoa removida",
                  "turma": _t((nomes_p.get(_t(r.get("person_id"))) or {}).get("class_name")),
                  "pessoa_id": _t(r.get("person_id")), "leitor": nomes_d.get(_t(r.get("device_id")), ""),
                  "erro": _t(r.get("last_error")), "quando": _t(r.get("updated_at"))}
                 for r in prov if _t(r.get("status")).lower() == "failed"]

    online = sum(1 for d in leitores if _t(d.get("status")).lower() == "online")
    return {
        "ok": True,
        "gerado_em": _utc_txt(agora),
        "site": site,
        "avisos": _avisos(agora, pessoas),
        "marcacoes_7d": {"total": total_ev, "sem_pessoa": sem_ev, "por_porta": portas},
        "fotos": {"ok": cont.get("ok", 0), "falhou": cont.get("failed", 0),
                  "pendente": sum(v for k, v in cont.items() if k not in ("ok", "failed")),
                  "recusadas": recusadas[:50]},
        "leitores": {"total": len(leitores), "online": online,
                     "lista": [{"id": _t(d.get("id")), "nome": _t(d.get("name")), "site": _t(d.get("site")),
                                "status": _t(d.get("status")), "visto": _t(d.get("last_seen_at"))} for d in leitores]},
        "pessoas": {"total": len(pessoas), "ativas": sum(1 for p in pessoas if p.get("active")),
                    "por_tipo": dict(Counter(_t(p.get("person_type")) or "outro" for p in pessoas))},
    }


# ---------------------------------------------------------------- ao vivo

def ao_vivo(site: str = "", limite: int = 40, agora: Optional[datetime] = None) -> Dict[str, Any]:
    from app.services.access_control_store import (access_present_people, access_report_summary,
                                                    list_access_report_events)
    agora = agora or _agora()
    filtros = {"period": "today", "site": site}
    resumo = access_report_summary(filtros)
    eventos = list_access_report_events({**filtros, "limit": max(1, min(int(limite or 40), 200))})
    pessoas = {_t(p.get("id")): p for p in _pessoas()}

    # Recibo do aviso: mensagem para o responsavel nos minutos seguintes a
    # passagem. Uma leitura so das mensagens de hoje, indexada por numero.
    inicio_dia = datetime.now(FUSO_LOCAL).replace(hour=0, minute=0, second=0, microsecond=0)
    msgs = _mensagens(inicio_dia)
    por_numero: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for m in msgs:
        por_numero[_t(m.get("contact_number"))].append(m)

    def _recibo(ev: Dict[str, Any], pessoa: Dict[str, Any]) -> Dict[str, Any]:
        quando = _ler_local(ev.get("occurred_at"))
        numero = _numero(pessoa.get("guardian_phone"))
        if not quando or not numero:
            return {"status": "sem_aviso" if not numero else "", "para": _t(pessoa.get("guardian_name"))}
        for m in por_numero.get(numero, []):
            criado = _ler_utc(m.get("created_at"))
            if criado and timedelta(seconds=-60) <= criado - quando <= timedelta(minutes=10):
                return {"status": _classe(m.get("status")), "para": _t(pessoa.get("guardian_name")),
                        "enviado": _utc_txt(criado), "atualizado": _t(m.get("updated_at"))[:19],
                        "erro": _t(m.get("error"))}
        return {"status": "", "para": _t(pessoa.get("guardian_name"))}

    passagens = []
    por_leitor: Dict[str, Dict[str, Any]] = {}
    for ev in eventos:
        p = pessoas.get(_t(ev.get("person_id"))) or {}
        tipo = _t(ev.get("event_type")).lower()
        passagens.append({
            "id": _t(ev.get("id")), "hora": _t(ev.get("occurred_at")), "tipo": tipo,
            "porta": _t(ev.get("resolved_device_name") or ev.get("device_name")),
            "pessoa_id": _t(ev.get("person_id")),
            "nome": _t(ev.get("person_name") or ev.get("person_name_raw")),
            "turma": _t(ev.get("class_name")), "tipo_pessoa": _t(ev.get("person_type")),
            "tem_foto": bool(_t(p.get("face_photo_path"))),
            "aviso": _recibo(ev, p) if p else {"status": "sem_pessoa"},
        })
    # Movimento do dia por hora (geral e por porta): o ritmo da portaria e a
    # porta que parou aparecem sem precisar ler numero.
    horas = [{"h": h, "entradas": 0, "saidas": 0} for h in range(24)]
    for ev in list_access_report_events({**filtros, "limit": 2000}):
        did = _t(ev.get("device_id"))
        info = por_leitor.setdefault(did, {"hoje": 0, "ultima": "", "horas": [0] * 24})
        info["hoje"] += 1
        info["ultima"] = max(info["ultima"], _t(ev.get("occurred_at")))
        quando = _ler_local(ev.get("occurred_at"))
        if quando:
            info["horas"][quando.hour] += 1
            chave = "saidas" if _t(ev.get("event_type")).lower().startswith("saida") else "entradas"
            horas[quando.hour][chave] += 1
    portas = [{"id": _t(d.get("id")), "nome": _t(d.get("name")), "status": _t(d.get("status")),
               "visto": _t(d.get("last_seen_at")),
               **por_leitor.get(_t(d.get("id")), {"hoje": 0, "ultima": "", "horas": [0] * 24})}
              for d in _leitores(site)]

    # Presenca por turma: alunos ativos de cada turma x presentes agora.
    lista_presentes = access_present_people(site=site)
    presentes = {_t(x.get("person_id")) for x in lista_presentes}
    # Quem esta dentro agora, mais recente primeiro (o mosaico de fotos).
    dentro = []
    for x in sorted(lista_presentes, key=lambda x: _t(x.get("since")), reverse=True)[:60]:
        p = pessoas.get(_t(x.get("person_id"))) or {}
        dentro.append({"pessoa_id": _t(x.get("person_id")), "nome": _t(x.get("name") or p.get("full_name")),
                       "turma": _t(p.get("class_name")), "tipo_pessoa": _t(p.get("person_type")),
                       "tem_foto": bool(_t(p.get("face_photo_path"))), "desde": _t(x.get("since"))})
    turmas: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "presentes": 0})
    for pid, p in pessoas.items():
        if not p.get("active") or _t(p.get("person_type")) != "student":
            continue
        if site and _t(p.get("site")).upper() != site.upper():
            continue
        t = _t(p.get("class_name")) or "Sem turma"
        turmas[t]["total"] += 1
        if pid in presentes:
            turmas[t]["presentes"] += 1
    return {
        "ok": True, "gerado_em": _utc_txt(agora), "site": site,
        "resumo": resumo,
        "avisos_hoje": dict(Counter(_classe(m.get("status")) for m in msgs)),
        "avisos_agora": saude_avisos(agora=agora),
        "passagens": passagens,
        "portas": portas,
        "turmas": [{"turma": k, **v} for k, v in sorted(turmas.items())],
        "horas": horas,
        "dentro": dentro,
        "dentro_total": len(lista_presentes),
    }
