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

import re
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


def _avisos(agora: datetime, pessoas: List[Dict[str, Any]], escolas: Optional[set] = None) -> Dict[str, Any]:
    """`escolas`: locais (site em maiusculas) do tipo escola. "Aluno sem numero
    de responsavel" so existe neles: no condominio o morador foi cadastrado
    como aluno e nao tem responsavel nenhum."""
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
                  and not _numero(p.get("guardian_phone"))
                  and (escolas is None or _t(p.get("site")).upper() in escolas)]
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


# ---------------------------------------------------------------- tipo de local
# O mesmo painel serve escola e condominio (e cliente com os dois). O tipo de
# cada local sai do proprio cadastro: escola tem aluno com turma e numero de
# responsavel. O cadastro so oferece Aluno/Funcionario/Visitante, entao no
# condominio os moradores ficaram como "aluno" sem turma nem telefone; o tipo
# de pessoa sozinho enganaria.
ESCOLA_MINIMO = 0.3


# Nome que denuncia escola, para local sem ninguem no cadastro ainda.
NOME_ESCOLA = re.compile(r"\b(ESCOLA|COL[EÉ]GIO|CRECHE|CMEI|EMEF|EMEI|ESC\.?|INSTITUTO|UNIVERSIDADE|FACULDADE)\b", re.I)


def _tipo_do_grupo(pessoas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tipo pelo cadastro. Sem aluno nenhum no local, o cadastro nao decide
    (tipo vazio): quem decide e o nome do local ou o resto do cliente."""
    ativas = [p for p in pessoas if p.get("active")]
    alunos = [p for p in ativas if _t(p.get("person_type")) == "student"]
    com_turma = sum(1 for p in alunos if _t(p.get("class_name")))
    com_resp = sum(1 for p in alunos if _numero(p.get("guardian_phone")))
    base = len(alunos)
    tipo = ""
    if base:
        tipo = "escola" if max(com_turma, com_resp) / base >= ESCOLA_MINIMO else "condominio"
    return {"tipo": tipo, "origem": "cadastro" if tipo else "", "pessoas": len(ativas),
            "com_turma": com_turma, "com_responsavel": com_resp, "alunos": base}


def perfil_locais(pessoas: List[Dict[str, Any]], sites: Iterable[str], site: str = "") -> Dict[str, Any]:
    """Tipo de cada local (escola/condominio) e o do filtro atual. Com
    "todos os sites" e locais de tipos diferentes, o tipo e "misto".

    Local sem aluno no cadastro (leitor recem-instalado, moradores so no
    leitor): o nome decide ("ESCOLA MEDEA" e escola); sem pista no nome, vale
    o tipo que predomina no cliente; cliente sem cadastro nenhum = condominio.
    """
    por_site: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in pessoas:
        por_site[_t(p.get("site")).upper()].append(p)
    nomes = sorted({_t(s) for s in sites if _t(s)} | {_t(p.get("site")) for p in pessoas if _t(p.get("site"))},
                   key=lambda s: s.upper())
    vistos: Dict[str, Dict[str, Any]] = {}
    locais = []
    for nome in nomes:
        if nome.upper() in vistos:
            continue
        info = {"site": nome, **_tipo_do_grupo(por_site.get(nome.upper(), []))}
        vistos[nome.upper()] = info
        locais.append(info)
    decididos = Counter(x["tipo"] for x in locais if x["tipo"])
    predominante = decididos.most_common(1)[0][0] if decididos else "condominio"
    for x in locais:
        if x["tipo"]:
            continue
        if NOME_ESCOLA.search(x["site"]):
            x["tipo"], x["origem"] = "escola", "nome"
        else:
            x["tipo"], x["origem"] = predominante, "cliente"
    if site:
        atual = vistos.get(site.upper())
        if atual is None:
            atual = {"site": site, **_tipo_do_grupo([])}
            atual["tipo"] = "escola" if NOME_ESCOLA.search(site) else predominante
        tipo = atual["tipo"]
    else:
        tipos = {x["tipo"] for x in locais}
        tipo = tipos.pop() if len(tipos) == 1 else ("misto" if tipos else "condominio")
    return {"tipo": tipo, "locais": locais}


def _perfil(site: str, pessoas: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    todas = pessoas if pessoas is not None else _pessoas()
    return perfil_locais(todas, [_t(d.get("site")) for d in _leitores()], site)


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
    todas = _pessoas()
    perfil = _perfil(site, todas)
    escolas = {x["site"].upper() for x in perfil["locais"] if x["tipo"] == "escola"}
    pessoas = [p for p in todas if _t(p.get("site")).upper() == site.upper()] if site else todas

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
        "perfil": perfil,
        "avisos": _avisos(agora, pessoas, escolas),
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


# Leitor com relogio zerado grava a passagem em 1999/2000: ela some dos
# graficos e relatorios "de hoje" sem ninguem saber. Conta por leitor.
RELOGIO_MINIMO = "2020-01-01"


def _relogio_errado() -> Dict[str, Dict[str, Any]]:
    linhas = _rows(
        "SELECT device_id, count(*) AS qtd, max(synced_at) AS quando FROM access_events "
        "WHERE tenant_slug=? AND occurred_at < ? GROUP BY device_id",
        (_tenant(), RELOGIO_MINIMO),
    )
    return {_t(r.get("device_id")): {"qtd": int(r.get("qtd") or 0), "quando": _t(r.get("quando"))[:19]} for r in linhas}


# ---------------------------------------------------------------- relatorios

def relatorios(site: str = "", dias: int = 28, agora: Optional[datetime] = None) -> Dict[str, Any]:
    """Uso do predio (dia da semana x hora), dia a dia e chegada/saida de hoje
    por pessoa. Separado do ao vivo: e para analisar, nao para operar."""
    agora = agora or _agora()
    dias = max(7, min(int(dias or 28), 90))
    tenant = _tenant()
    local_agora = agora.astimezone(FUSO_LOCAL)
    hoje = local_agora.strftime("%Y-%m-%d")
    inicio = (local_agora - timedelta(days=dias - 1)).strftime("%Y-%m-%d") + " 00:00:00"
    sql = ("SELECT person_id, person_name_raw, event_type, device_name, occurred_at FROM access_events "
           "WHERE tenant_slug=? AND occurred_at >= ? AND occurred_at <= ?" + (" AND site=?" if site else ""))
    fim = _local_txt(agora)
    eventos = _rows(sql, (tenant, inicio, fim, site) if site else (tenant, inicio, fim))

    mapa = [[0] * 24 for _ in range(7)]  # 0 = segunda
    por_dia: Dict[str, Dict[str, Any]] = {}
    por_porta: Counter = Counter()
    for e in eventos:
        quando = _ler_local(e.get("occurred_at"))
        if not quando:
            continue
        mapa[quando.weekday()][quando.hour] += 1
        dia = quando.strftime("%Y-%m-%d")
        info = por_dia.setdefault(dia, {"passagens": 0, "pessoas": set()})
        info["passagens"] += 1
        if _t(e.get("person_id")):
            info["pessoas"].add(_t(e.get("person_id")))
        por_porta[_t(e.get("device_name")) or "sem porta"] += 1
    serie = []
    for i in range(dias - 1, -1, -1):
        dia = (local_agora - timedelta(days=i)).strftime("%Y-%m-%d")
        info = por_dia.get(dia) or {"passagens": 0, "pessoas": set()}
        serie.append({"dia": dia, "passagens": info["passagens"], "pessoas": len(info["pessoas"])})

    # Hoje por pessoa: primeira entrada, ultima saida, se ainda esta dentro.
    todas = _pessoas()
    perfil = _perfil(site, todas)
    escolas = {x["site"].upper() for x in perfil["locais"] if x["tipo"] == "escola"}
    pessoas = {_t(p.get("id")): p for p in todas}
    # Quem o leitor reconhece mas o SightOps nao tem (no condominio, a maioria
    # dos moradores): fica fora da presenca e dos relatorios.
    so_leitor: Dict[str, Dict[str, Any]] = {}
    hoje_p: Dict[str, Dict[str, Any]] = {}
    for e in eventos:
        pid = _t(e.get("person_id"))
        quando = _t(e.get("occurred_at"))
        if not quando.startswith(hoje):
            continue
        if not pid:
            nome = _t(e.get("person_name_raw")) or "sem nome no leitor"
            x = so_leitor.setdefault(nome, {"nome": nome, "passagens": 0, "ultima": "", "porta": ""})
            x["passagens"] += 1
            if quando > x["ultima"]:
                x["ultima"], x["porta"] = quando, _t(e.get("device_name"))
            continue
        p = pessoas.get(pid) or {}
        r = hoje_p.setdefault(pid, {"pessoa_id": pid, "nome": _t(p.get("full_name") or e.get("person_name_raw")),
                                    "turma": _t(p.get("class_name")), "tipo_pessoa": _t(p.get("person_type")),
                                    "site": _t(p.get("site")), "chegou": "", "saiu": "", "ultima": "", "ultimo_tipo": "", "passagens": 0})
        r["passagens"] += 1
        saida = _t(e.get("event_type")).lower().startswith("saida")
        if not saida and (not r["chegou"] or quando < r["chegou"]):
            r["chegou"] = quando
        if saida and quando > r["saiu"]:
            r["saiu"] = quando
        if quando > r["ultima"]:
            r["ultima"], r["ultimo_tipo"] = quando, "saida" if saida else "entrada"
    lista_hoje = sorted(hoje_p.values(), key=lambda x: x["chegou"] or x["ultima"])
    # "Nao veio" so faz sentido em escola e em dia com movimento (fim de semana
    # e feriado deixariam a escola inteira como falta). Morador de condominio
    # nao "falta".
    nao_vieram: List[Dict[str, Any]] = []
    if lista_hoje:
        for pid, p in pessoas.items():
            if (p.get("active") and _t(p.get("person_type")) == "student" and pid not in hoje_p
                    and _t(p.get("site")).upper() in escolas
                    and (not site or _t(p.get("site")).upper() == site.upper())):
                nao_vieram.append({"pessoa_id": pid, "nome": _t(p.get("full_name")), "turma": _t(p.get("class_name"))})
        nao_vieram.sort(key=lambda x: (x["turma"], x["nome"]))
    return {
        "ok": True, "gerado_em": _utc_txt(agora), "site": site, "dias": dias, "perfil": perfil,
        "so_leitor_hoje": sorted(so_leitor.values(), key=lambda x: -x["passagens"])[:100],
        "so_leitor_total": len(so_leitor),
        "mapa": mapa, "serie": serie,
        "portas": [{"porta": k, "passagens": v} for k, v in por_porta.most_common(8)],
        "hoje": lista_hoje[:400], "hoje_total": len(lista_hoje),
        "nao_vieram": nao_vieram[:200], "nao_vieram_total": len(nao_vieram),
    }


# ---------------------------------------------------------------- ao vivo

def ao_vivo(site: str = "", limite: int = 40, agora: Optional[datetime] = None) -> Dict[str, Any]:
    from app.services.access_control_store import (access_present_people, access_report_summary,
                                                    list_access_report_events)
    agora = agora or _agora()
    filtros = {"period": "today", "site": site}
    resumo = access_report_summary(filtros)
    eventos = list_access_report_events({**filtros, "limit": max(1, min(int(limite or 40), 500))})
    todas = _pessoas()
    perfil = _perfil(site, todas)
    pessoas = {_t(p.get("id")): p for p in todas}

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
            "site": _t(ev.get("resolved_site") or ev.get("site")),
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
    relogio = _relogio_errado()
    portas = [{"id": _t(d.get("id")), "nome": _t(d.get("name")), "status": _t(d.get("status")),
               "visto": _t(d.get("last_seen_at")),
               "relogio_errado": relogio.get(_t(d.get("id")), {}).get("qtd", 0),
               "relogio_errado_em": relogio.get(_t(d.get("id")), {}).get("quando", ""),
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
        "ok": True, "gerado_em": _utc_txt(agora), "site": site, "perfil": perfil,
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


# ---------------------------------------------------------------- dispositivos
# Pagina /v3/acesso/dispositivos/: lista os leitores com o que o cadastro
# antigo nao mostrava (IP virtual pelo qual o SightOps fala com ele, conector e
# se esta online, movimento do dia, fotos recusadas, relogio zerado) e os
# locais do cliente com o conector de cada um, para o cadastro sugerir.
# So leitura: salvar, testar e remover usam as rotas /devices que ja existem.

def ip_virtual(connector_id: str, host: str) -> Dict[str, Any]:
    """IP que o SightOps vai usar para alcancar `host` pelo conector. Igual ao
    host = conector sem faixa virtual (ou IP fora das redes mapeadas)."""
    from app.services import connector_routing_vnat as vnat
    cid, real = _t(connector_id), _t(host)
    # Conector que nao e deste cliente responde sempre igual (bloqueado), tenha
    # ele faixa virtual ou nao: a previa nao confirma id de conector alheio.
    if cid and cid not in {c["id"] for c in _conectores()}:
        return {"host": real, "connector_id": cid, "virtual": "", "traduzido": False, "bloqueado": True}
    virtual = _t(vnat.virtual_ip_for(cid, real)) if cid and real else real
    bloqueado = bool(virtual) and virtual == _t(getattr(vnat, "IP_BLOQUEADO", ""))
    return {"host": real, "connector_id": cid, "virtual": "" if bloqueado else virtual,
            "traduzido": bool(virtual) and virtual != real and not bloqueado, "bloqueado": bloqueado}


def _conectores() -> List[Dict[str, Any]]:
    from app.services.connector_service import list_connectors
    r = list_connectors()
    lista = r.get("connectors") if isinstance(r, dict) else r
    return [{"id": _t(c.get("id")), "nome": _t(c.get("name") or c.get("site") or c.get("id")),
             "site": _t(c.get("site")), "status": _t(c.get("status")).lower(),
             "visto": _t(c.get("last_seen")), "isolado": bool(c.get("iso_vnat"))}
            for c in (lista or []) if _t(c.get("id"))]


def _locais_do_cliente() -> List[Dict[str, str]]:
    try:
        from app.services.windows_inventory_service import sites_do_cliente
        return sites_do_cliente(_tenant())
    except Exception:  # sem a lista oficial, a tela ainda lista os sites dos leitores
        return []


def dispositivos(agora: Optional[datetime] = None) -> Dict[str, Any]:
    from app.services.access_control_store import list_devices
    agora = agora or _agora()
    tenant = _tenant()
    hoje = agora.astimezone(FUSO_LOCAL).strftime("%Y-%m-%d")
    leitores = list_devices()
    conectores = _conectores()
    por_conector = {c["id"]: c for c in conectores}

    mov = {_t(r.get("device_id")): r for r in _rows(
        "SELECT device_id, count(*) AS hoje, max(occurred_at) AS ultima FROM access_events "
        "WHERE tenant_slug=? AND occurred_at >= ? GROUP BY device_id", (tenant, hoje + " 00:00:00"))}
    ultima_geral = {_t(r.get("device_id")): _t(r.get("ultima")) for r in _rows(
        "SELECT device_id, max(occurred_at) AS ultima FROM access_events "
        "WHERE tenant_slug=? AND occurred_at >= ? GROUP BY device_id", (tenant, RELOGIO_MINIMO))}
    fotos: Dict[str, Counter] = defaultdict(Counter)
    for r in _rows("SELECT device_id, status FROM access_provision_status WHERE tenant_slug=?", (tenant,)):
        fotos[_t(r.get("device_id"))][_t(r.get("status")).lower() or "pendente"] += 1
    relogio = _relogio_errado()

    saida = []
    for d in leitores:
        did = _t(d.get("id"))
        cid = _t(d.get("connector_id"))
        con = por_conector.get(cid) or {}
        f = fotos.get(did, Counter())
        saida.append({
            "id": did, "nome": _t(d.get("name")), "site": _t(d.get("site")),
            "fabricante": _t(d.get("vendor")), "modelo": _t(d.get("model")),
            "host": _t(d.get("host")), "usuario": _t(d.get("username")),
            "connector_id": cid, "conector": con.get("nome", cid), "conector_status": con.get("status", ""),
            "ip": ip_virtual(cid, _t(d.get("host"))) if cid else {"host": _t(d.get("host")), "virtual": _t(d.get("host")), "traduzido": False, "bloqueado": False},
            "funcao": _t(d.get("access_direction")) or "entrada", "ativo": bool(d.get("active")),
            "status": _t(d.get("status")).lower(), "visto": _t(d.get("last_seen_at")),
            "hoje": int((mov.get(did) or {}).get("hoje") or 0),
            "ultima": _t((mov.get(did) or {}).get("ultima")) or ultima_geral.get(did, ""),
            "fotos_ok": f.get("ok", 0), "fotos_falha": f.get("failed", 0),
            "fotos_pendentes": sum(v for k, v in f.items() if k not in ("ok", "failed")),
            "relogio_errado": relogio.get(did, {}).get("qtd", 0),
            "criado": _t(d.get("created_at")),
        })

    todas = _pessoas()
    nomes = [x["site"] for x in _locais_do_cliente()] + [x["site"] for x in saida]
    perfil = perfil_locais(todas, nomes, "")
    sugestao = {_t(x.get("site")).upper(): _t(x.get("connector_id")) for x in _locais_do_cliente()}
    locais = [{**l, "connector_id": sugestao.get(l["site"].upper(), ""),
               "leitores": sum(1 for x in saida if x["site"].upper() == l["site"].upper())}
              for l in perfil["locais"]]
    return {"ok": True, "gerado_em": _utc_txt(agora), "dispositivos": saida,
            "locais": locais, "conectores": conectores, "perfil": perfil}
