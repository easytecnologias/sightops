"""Relatorios do Painel de Acesso (aba Relatorios), um catalogo por modo do local.

Desenho aprovado em 22/10/2026 (mockup "Relatorios do Controle de Acesso"):
cada relatorio responde uma pergunta, tem periodo e filtros, e sai em PDF
(access_control_relatorios_pdf). O modo vem do tipo do local (escola,
condominio, empresa, evento); muda o catalogo e o vocabulario, o motor por
baixo e o mesmo:

- presenca: quem veio e quem faltou, por grupo (turma/setor/categoria);
- cadastro: situacao do cadastro por grupo (unidade, no condominio);
- diario:   todas as pessoas que passaram num dia, chegada e saida;
- uso:      passagens por dia e hora, pico de gente dentro, portas;
- avisos:   avisos ao responsavel no periodo, por pessoa.

Dia que conta na presenca: em escola e empresa, segunda a sexta menos os
feriados do local; em qualquer modo, o dia so conta se pelo menos 1/4 das
pessoas passou. Na Escola P. Dutra (outubro/2026) houve dia util com 11
passagens de 5 pessoas e dias sem nenhuma (leitor fora do ar): contar esses
dias poria a escola inteira em falta. Os dias que ficam de fora vao listados
com o motivo, na tela e no PDF.

So leitura. Tudo filtrado por cliente (tenant_slug) e por local.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException

from app.services import access_control_painel as P

MODOS = ("escola", "condominio", "empresa", "evento")
DIA_MINIMO = 0.25          # fracao das pessoas que precisa passar para o dia contar
FALTAS_ALERTA = 3          # "alunos com 3+ faltas"
PERIODO_MAXIMO = 190       # dias
RELOGIO_MINIMO = "2020-01-01"

VOCAB = {
    "escola": {"grupo": "Turma", "grupos": "turmas", "pessoa": "aluno", "pessoas": "alunos", "local": "escola"},
    "condominio": {"grupo": "Unidade", "grupos": "unidades", "pessoa": "morador", "pessoas": "moradores", "local": "condomínio"},
    "empresa": {"grupo": "Setor", "grupos": "setores", "pessoa": "colaborador", "pessoas": "colaboradores", "local": "empresa"},
    "evento": {"grupo": "Categoria", "grupos": "categorias", "pessoa": "participante", "pessoas": "participantes", "local": "evento"},
}

# (id, nome, pergunta, motor). A ordem e a do catalogo; o primeiro abre sozinho.
CATALOGO = {
    "escola": [
        ("frequencia", "Frequência", "Quem veio, quem faltou e em que dias, por turma.", "presenca"),
        ("diario", "Diário da portaria", "Todos que passaram num dia: chegada, saída e tempo na escola.", "diario"),
        ("uso", "Uso da escola", "Dias e horários de pico, quantos estavam dentro e portas mais usadas.", "uso"),
        ("avisos", "Avisos enviados", "Comprovante dos avisos aos responsáveis: entregue, lido ou falhou.", "avisos"),
    ],
    "condominio": [
        ("movimento", "Movimento da portaria", "Todos que passaram num dia: primeira entrada, última saída e tempo.", "diario"),
        ("cadastro", "Cadastro de moradores", "Por unidade: quem está no cadastro, com foto, no leitor e quando passou.", "cadastro"),
        ("uso", "Portarias e áreas comuns", "Dias e horários de pico, quantos estavam dentro e portas mais usadas.", "uso"),
    ],
    "empresa": [
        ("presenca", "Presença por setor", "Quem veio e quem não veio, por setor e por dia.", "presenca"),
        ("diario", "Diário da portaria", "Todos que passaram num dia: primeira entrada, última saída e tempo.", "diario"),
        ("uso", "Uso do prédio", "Dias e horários de pico, quantos estavam dentro e portas mais usadas.", "uso"),
    ],
    "evento": [
        ("comparecimento", "Comparecimento", "Credenciados que vieram e que não vieram, por categoria.", "presenca"),
        ("publico", "Público", "Entradas por dia e hora, pico de gente dentro e portões mais usados.", "uso"),
        ("diario", "Diário por portão", "Todos que passaram num dia: primeira entrada, última saída e tempo.", "diario"),
    ],
}

# Quem entra na presenca por padrao, por modo (person_type do cadastro).
QUEM = {
    "escola": [("alunos", "Alunos", {"student"}), ("funcionarios", "Funcionários", {"employee"}),
               ("todos", "Todos", None)],
    "empresa": [("colaboradores", "Colaboradores", {"employee", "student", "resident"}),
                ("prestadores", "Prestadores", {"contractor"}), ("todos", "Todos", None)],
    "evento": [("todos", "Todos", None)],
    "condominio": [("todos", "Todos", None)],
}

UNIDADE = re.compile(r"\s([A-Z]{1,2}\d{1,3})$", re.I)


def _t(v: Any) -> str:
    return str(v or "").strip()


def _dia(v: Any) -> Optional[date]:
    try:
        return datetime.strptime(_t(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ---------------------------------------------------------------- local e modo

def _locais_liberados() -> Optional[set]:
    from app.core import permissions
    sites = permissions.sites_da_sessao()
    return None if sites is None else {s.strip().upper() for s in sites}


def contexto(site: str) -> Dict[str, Any]:
    """Modo e vocabulario do local. Relatorio e sempre de UM local: o modo
    depende dele e misturar locais misturaria turmas de escolas diferentes."""
    site = _t(site)
    pessoas = P._pessoas()
    perfil = P._perfil(site, pessoas)
    liberados = _locais_liberados()
    locais = [x for x in perfil["locais"] if liberados is None or x["site"].upper() in liberados]
    perfil = {**perfil, "locais": locais}   # usuario restrito nao ve tipo/contagem de outro local
    if not site:
        if len(locais) != 1:
            return {"ok": True, "precisa_local": True, "locais": [x["site"] for x in locais], "perfil": perfil}
        site = locais[0]["site"]
        perfil = P._perfil(site, pessoas)
        perfil = {**perfil, "locais": [x for x in perfil["locais"] if liberados is None or x["site"].upper() in liberados]}
    if liberados is not None and site.upper() not in liberados:
        raise HTTPException(status_code=403, detail="local fora dos seus sites")
    modo = perfil["tipo"] if perfil["tipo"] in MODOS else "escola"
    return {"ok": True, "site": site, "modo": modo, "vocab": VOCAB[modo], "perfil": perfil,
            "pessoas": [p for p in pessoas if _t(p.get("site")).upper() == site.upper()]}


def catalogo(site: str = "") -> Dict[str, Any]:
    ctx = contexto(site)
    if ctx.get("precisa_local"):
        return {k: v for k, v in ctx.items() if k != "pessoas"}
    modo = ctx["modo"]

    def grupos(tipos: Optional[set]) -> List[str]:
        return sorted({_grupo(p, modo) for p in ctx["pessoas"] if p.get("active") and _grupo(p, modo)
                       and (tipos is None or _t(p.get("person_type")) in tipos)}, key=_ordem_grupo)
    return {"ok": True, "site": ctx["site"], "modo": modo, "vocab": ctx["vocab"], "perfil": ctx["perfil"],
            "relatorios": [{"id": i, "nome": n, "pergunta": q, "motor": m} for i, n, q, m in CATALOGO[modo]],
            "grupos": grupos(None), "quem": [{"id": i, "nome": n, "grupos": grupos(t)} for i, n, t in QUEM[modo]]}


def _ordem_grupo(g: str) -> Tuple[int, str, str]:
    """1º Ano, 2º Ano... antes de EJA e de nomes; dentro, pelo numero."""
    n = re.search(r"\d+", g)
    return (0 if re.match(r"^\d", g) else 1, (n.group(0).zfill(3) if n else "999"), g.upper())


def _grupo(p: Dict[str, Any], modo: str) -> str:
    g = _t(p.get("class_name"))
    if not g and modo == "condominio":   # no condominio a unidade vem no fim do nome ("THAMIS A01")
        m = UNIDADE.search(_t(p.get("full_name")))
        g = m.group(1).upper() if m else ""
    return g


def _relatorio(modo: str, rid: str) -> Tuple[str, str, str, str]:
    for r in CATALOGO[modo]:
        if r[0] == rid:
            return r
    raise HTTPException(status_code=404, detail="Relatorio nao existe para este tipo de local.")


def _periodo(de: str, ate: str, hoje: date, padrao_dias: int = 30) -> Tuple[date, date]:
    fim = _dia(ate) or hoje
    ini = _dia(de) or (fim - timedelta(days=padrao_dias - 1))
    fim = min(fim, hoje)
    if ini > fim:
        raise HTTPException(status_code=400, detail="O início do período é depois do fim.")
    if (fim - ini).days + 1 > PERIODO_MAXIMO:
        raise HTTPException(status_code=400, detail=f"Período de no máximo {PERIODO_MAXIMO} dias.")
    return ini, fim


def _eventos(site: str, ini: date, fim: date, portas: Iterable[str] = (), campos: str = "") -> List[Dict[str, Any]]:
    portas = [p for p in portas if p][:50]
    sql = (f"SELECT person_id, person_name_raw, event_type, device_id, device_name, occurred_at{campos} "
           "FROM access_events WHERE tenant_slug=? AND site=? AND occurred_at >= ? AND occurred_at <= ?"
           + (f" AND device_id IN ({','.join('?' for _ in portas)})" if portas else "") + " ORDER BY occurred_at")
    return P._rows(sql, (P._tenant(), site, max(ini.isoformat(), RELOGIO_MINIMO) + " 00:00:00",
                         fim.isoformat() + " 23:59:59", *portas))


def _feriados(site: str) -> Dict[str, str]:
    from app.services.access_control_horarios import _ler
    f = (_ler().get("feriados") or {}).get(site.upper()) or {}
    return {x["data"]: _t(x.get("nome")) or "feriado" for x in f.get("datas") or [] if x.get("data")}


def _quem(modo: str, quem: str) -> Tuple[str, Optional[set]]:
    opcoes = QUEM[modo]
    for i, n, tipos in opcoes:
        if i == quem:
            return n, tipos
    return opcoes[0][1], opcoes[0][2]


# ---------------------------------------------------------------- motores

def _no_leitor() -> set:
    """Pessoas que algum leitor aceitou (envio ok)."""
    return {_t(r.get("person_id")) for r in P._rows(
        "SELECT person_id FROM access_provision_status WHERE tenant_slug=? AND status='ok'", (P._tenant(),))}


def _saidas_confiaveis(eventos: List[Dict[str, Any]]) -> bool:
    """Da para saber quem esta dentro? So se as saidas sao registradas. No
    RESERVA (outubro/2026) so uma portaria tem leitor de saida: o "pico
    dentro" dava 82 as 23:48, todo mundo que entrou no dia."""
    tipos = Counter("saida" if _t(e.get("event_type")).lower().startswith("saida") else "entrada" for e in eventos)
    return bool(tipos["entrada"]) and tipos["saida"] / tipos["entrada"] >= 0.6


def _presenca(ctx: Dict[str, Any], de: str, ate: str, grupo: str, quem: str, hoje: date) -> Dict[str, Any]:
    modo, site = ctx["modo"], ctx["site"]
    quem_nome, tipos = _quem(modo, quem)
    candidatos = [p for p in ctx["pessoas"] if p.get("active") and (tipos is None or _t(p.get("person_type")) in tipos)
                  and (not grupo or _grupo(p, modo) == grupo)]
    # Quem nao esta em nenhum leitor nao tem como passar: falta seria mentira.
    # Na Escola P. Dutra (22/10/2026) eram 3 alunos sem ID no leitor.
    no_leitor = _no_leitor()
    pop = [p for p in candidatos if _t(p.get("id")) in no_leitor]
    fora_leitor = sorted(({"id": _t(p.get("id")), "nome": _t(p.get("full_name")), "grupo": _grupo(p, modo)}
                          for p in candidatos if _t(p.get("id")) not in no_leitor), key=lambda x: (x["grupo"], x["nome"]))
    # Hoje so entra se o periodo e so hoje: de manha o turno da tarde ainda
    # nao chegou e viraria falta.
    ini, fim = _periodo(de, ate, hoje)
    if fim == hoje and ini < hoje:
        fim = hoje - timedelta(days=1)
    ids = {_t(p.get("id")) for p in pop}
    veio: Dict[str, set] = defaultdict(set)              # pessoa -> dias
    for e in _eventos(site, ini, fim):
        pid = _t(e.get("person_id"))
        if pid in ids:
            veio[pid].add(_t(e.get("occurred_at"))[:10])
    por_dia = Counter(d for dias in veio.values() for d in dias)
    feriados = _feriados(site)
    util = modo in ("escola", "empresa")
    minimo = max(1, int(len(pop) * DIA_MINIMO + 0.999))
    contados: List[str] = []
    fora: List[Dict[str, Any]] = []
    d = ini
    while d <= fim:
        k = d.isoformat()
        if util and d.weekday() >= 5:
            pass                                          # fim de semana nem aparece
        elif util and k in feriados:
            fora.append({"dia": k, "motivo": f"feriado: {feriados[k]}"})
        elif not por_dia.get(k):
            if util:
                fora.append({"dia": k, "motivo": "ninguém passou (sem aula ou leitor fora do ar)"})
        elif por_dia[k] < minimo and modo != "evento":
            fora.append({"dia": k, "motivo": f"só {por_dia[k]} de {len(pop)} passaram (leitor fora do ar ou dia sem aula?)"})
        else:
            contados.append(k)
        d += timedelta(days=1)
    n = len(contados)
    pessoas = []
    for p in pop:
        pid = _t(p.get("id"))
        vieram = sorted(veio.get(pid, set()) & set(contados))
        faltas = [x for x in contados if x not in vieram]
        pessoas.append({"id": pid, "nome": _t(p.get("full_name")), "grupo": _grupo(p, modo) or "sem " + ctx["vocab"]["grupo"].lower(),
                        "presencas": len(vieram), "faltas": len(faltas), "dias_falta": faltas,
                        "pct": round(100 * len(vieram) / n) if n else None})
    por_grupo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for x in pessoas:
        por_grupo[x["grupo"]].append(x)
    grupos = []
    for g, lista in por_grupo.items():
        pres = sum(x["presencas"] for x in lista)
        grupos.append({"grupo": g, "pessoas": len(lista), "presencas": pres, "faltas": sum(x["faltas"] for x in lista),
                       "pct": round(100 * pres / (len(lista) * n)) if n and lista else None,
                       "vieram": sum(1 for x in lista if x["presencas"]),
                       "criticos": sum(1 for x in lista if x["faltas"] >= FALTAS_ALERTA)})
    grupos.sort(key=lambda g: _ordem_grupo(g["grupo"]))
    serie = [{"dia": k, "presentes": por_dia.get(k, 0), "pct": round(100 * por_dia.get(k, 0) / len(pop)) if pop else 0}
             for k in contados]
    total_pres = sum(x["presencas"] for x in pessoas)
    pessoas.sort(key=lambda x: (-x["faltas"], x["grupo"], x["nome"]))
    return {
        "motor": "presenca", "de": ini.isoformat(), "ate": fim.isoformat(), "quem": quem_nome,
        "dias_contados": contados, "dias_fora": fora,
        "resumo": {"pessoas": len(pop), "dias": n,
                   "pct": round(100 * total_pres / (len(pop) * n)) if n and pop else None,
                   "faltas": sum(x["faltas"] for x in pessoas),
                   "criticos": sum(1 for x in pessoas if x["faltas"] >= FALTAS_ALERTA),
                   "vieram": sum(1 for x in pessoas if x["presencas"]),
                   "nao_vieram": sum(1 for x in pessoas if not x["presencas"])},
        "grupos": grupos, "pessoas": pessoas, "serie": serie, "faltas_alerta": FALTAS_ALERTA,
        "fora_leitor": fora_leitor,
    }


def _cadastro(ctx: Dict[str, Any]) -> Dict[str, Any]:
    modo, site = ctx["modo"], ctx["site"]
    pop = [p for p in ctx["pessoas"] if p.get("active")]
    ids = {_t(p.get("id")) for p in pop}
    tenant = P._tenant()
    ultima = {_t(r.get("person_id")): _t(r.get("ultima")) for r in P._rows(
        "SELECT person_id, max(occurred_at) AS ultima FROM access_events WHERE tenant_slug=? AND site=? "
        "AND occurred_at >= ? AND person_id IS NOT NULL AND person_id <> '' GROUP BY person_id",
        (tenant, site, RELOGIO_MINIMO + " 00:00:00")) if _t(r.get("person_id")) in ids}
    no_leitor = _no_leitor()
    corte = (P._agora().astimezone(P.FUSO_LOCAL) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    pessoas = []
    for p in pop:
        pid = _t(p.get("id"))
        pessoas.append({"id": pid, "nome": _t(p.get("full_name")), "grupo": _grupo(p, modo) or "sem unidade",
                        "foto": bool(_t(p.get("face_photo_path"))),
                        "leitor": pid in no_leitor,
                        "ultima": ultima.get(pid, ""), "parado": not ultima.get(pid) or ultima[pid] < corte})
    por_grupo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for x in pessoas:
        por_grupo[x["grupo"]].append(x)
    grupos = [{"grupo": g, "pessoas": len(l), "sem_foto": sum(1 for x in l if not x["foto"]),
               "fora_leitor": sum(1 for x in l if not x["leitor"]), "parados": sum(1 for x in l if x["parado"])}
              for g, l in por_grupo.items()]
    grupos.sort(key=lambda g: g["grupo"])
    pessoas.sort(key=lambda x: (x["grupo"], x["nome"]))
    return {"motor": "cadastro", "resumo": {"pessoas": len(pessoas), "grupos": len(grupos),
                                            "sem_foto": sum(1 for x in pessoas if not x["foto"]),
                                            "fora_leitor": sum(1 for x in pessoas if not x["leitor"]),
                                            "parados": sum(1 for x in pessoas if x["parado"])},
            "grupos": grupos, "pessoas": pessoas}


def _diario(ctx: Dict[str, Any], dia: str, portas: List[str], hoje: date) -> Dict[str, Any]:
    modo, site = ctx["modo"], ctx["site"]
    d = min(_dia(dia) or hoje, hoje)
    pessoas = {_t(p.get("id")): p for p in ctx["pessoas"]}
    por: Dict[str, Dict[str, Any]] = {}
    so_leitor: Dict[str, Dict[str, Any]] = {}
    horas = [0] * 24
    eventos = _eventos(site, d, d, portas)
    for e in eventos:
        quando = _t(e.get("occurred_at"))
        h = P._ler_local(quando)
        if h:
            horas[h.hour] += 1
        saida = _t(e.get("event_type")).lower().startswith("saida")
        pid = _t(e.get("person_id"))
        if not pid:
            nome = _t(e.get("person_name_raw")) or "sem nome no leitor"
            x = so_leitor.setdefault(nome, {"nome": nome, "passagens": 0, "primeira": quando, "ultima": quando})
            x["passagens"] += 1
            x["ultima"] = quando
            continue
        p = pessoas.get(pid) or {}
        r = por.setdefault(pid, {"id": pid, "nome": _t(p.get("full_name") or e.get("person_name_raw")),
                                 "grupo": _grupo(p, modo), "chegou": "", "saiu": "", "passagens": 0,
                                 "primeira": quando, "ultima": quando,
                                 "ultimo_tipo": "", "portas": []})
        r["passagens"] += 1
        r["ultima"] = quando
        porta = P._t(e.get("device_name"))
        if porta and porta not in r["portas"]:
            r["portas"].append(porta)
        if not saida and not r["chegou"]:
            r["chegou"] = quando
        if saida:
            r["saiu"] = quando
        r["ultimo_tipo"] = "saida" if saida else "entrada"
    lista = sorted(por.values(), key=lambda x: x["chegou"] or x["saiu"])
    for r in lista:
        ini, fim_ = P._ler_local(r["chegou"]), P._ler_local(r["saiu"])
        r["minutos"] = int((fim_ - ini).total_seconds() // 60) if ini and fim_ and fim_ > ini else None
        r["dentro"] = r["ultimo_tipo"] == "entrada"
    nao_vieram = []
    if modo == "escola" and lista and d.weekday() < 5:
        vieram = set(por)
        nao_vieram = sorted(({"id": _t(p.get("id")), "nome": _t(p.get("full_name")), "grupo": _grupo(p, modo)}
                             for p in ctx["pessoas"] if p.get("active") and _t(p.get("person_type")) == "student"
                             and _t(p.get("id")) not in vieram), key=lambda x: (x["grupo"], x["nome"]))
    saidas = _saidas_confiaveis(eventos)
    if not saidas:
        for r in lista:
            r["dentro"] = False
    return {"motor": "diario", "dia": d.isoformat(), "pessoas": lista, "saidas_confiaveis": saidas, "so_leitor": sorted(so_leitor.values(), key=lambda x: x["primeira"]),
            "nao_vieram": nao_vieram, "horas": horas,
            "resumo": {"passagens": len(eventos), "pessoas": len(lista), "so_leitor": len(so_leitor),
                       "dentro": sum(1 for x in lista if x["dentro"]) if saidas else None, "nao_vieram": len(nao_vieram)}}


def _uso(ctx: Dict[str, Any], de: str, ate: str, portas: List[str], hoje: date) -> Dict[str, Any]:
    ini, fim = _periodo(de, ate, hoje, 28)
    mapa = [[0] * 24 for _ in range(7)]
    por_dia: Dict[str, Dict[str, Any]] = {}
    por_porta: Counter = Counter()
    dentro: Dict[str, set] = defaultdict(set)
    pico_dia: Dict[str, Tuple[int, str]] = {}
    eventos = _eventos(ctx["site"], ini, fim, portas)
    saidas = _saidas_confiaveis(eventos)
    for e in eventos:
        quando = P._ler_local(e.get("occurred_at"))
        if not quando:
            continue
        k = quando.strftime("%Y-%m-%d")
        mapa[quando.weekday()][quando.hour] += 1
        info = por_dia.setdefault(k, {"passagens": 0, "pessoas": set()})
        info["passagens"] += 1
        quem = _t(e.get("person_id")) or "leitor:" + _t(e.get("person_name_raw"))
        info["pessoas"].add(quem)
        por_porta[_t(e.get("device_name")) or "sem porta"] += 1
        # gente dentro ao mesmo tempo: entrada soma, saida tira (o dia comeca vazio)
        if _t(e.get("event_type")).lower().startswith("saida"):
            dentro[k].discard(quem)
        else:
            dentro[k].add(quem)
        if len(dentro[k]) > pico_dia.get(k, (0, ""))[0]:
            pico_dia[k] = (len(dentro[k]), quando.strftime("%H:%M"))
    serie = []
    d = ini
    while d <= fim:
        k = d.isoformat()
        info = por_dia.get(k) or {"passagens": 0, "pessoas": set()}
        serie.append({"dia": k, "passagens": info["passagens"], "pessoas": len(info["pessoas"]),
                      "pico": pico_dia.get(k, (0, ""))[0], "pico_hora": pico_dia.get(k, (0, ""))[1]})
        d += timedelta(days=1)
    com = [s for s in serie if s["passagens"]]
    if not saidas:
        for s_ in serie:
            s_["pico"], s_["pico_hora"] = None, ""
    maior = max(com, key=lambda s: s["pico"]) if com and saidas else None
    hora_pico = max(((di, h) for di in range(7) for h in range(24)), key=lambda x: mapa[x[0]][x[1]])
    return {"motor": "uso", "de": ini.isoformat(), "ate": fim.isoformat(), "mapa": mapa, "serie": serie,
            "saidas_confiaveis": saidas,
            "portas": [{"porta": k, "passagens": v} for k, v in por_porta.most_common(12)],
            "resumo": {"passagens": sum(s["passagens"] for s in serie), "dias_com_movimento": len(com),
                       "media_dia": round(sum(s["passagens"] for s in com) / len(com)) if com else 0,
                       "pico": maior["pico"] if maior else None, "pico_dia": maior["dia"] if maior else "",
                       "pico_hora": maior["pico_hora"] if maior else "",
                       "hora_mais": {"dia_semana": hora_pico[0], "hora": hora_pico[1]} if com else None}}


def _avisos(ctx: Dict[str, Any], de: str, ate: str, hoje: date) -> Dict[str, Any]:
    ini, fim = _periodo(de, ate, hoje)
    pessoas = [p for p in ctx["pessoas"] if p.get("active")]
    resp = P._responsaveis(pessoas)
    # A mensagem gravada so tem o numero, nao o local. Numero que tambem e de
    # pessoa de outro local do cliente (irmaos em duas escolas) traria aviso de
    # la para ca: fica de fora e e contado. (revisor-isolamento, 22/10/2026)
    outros = {P._numero(p.get("guardian_phone")) for p in P._pessoas()
              if _t(p.get("site")).upper() != ctx["site"].upper() and P._numero(p.get("guardian_phone"))}
    compartilhados = set(resp) & outros
    for n in compartilhados:
        resp.pop(n, None)
    desde = datetime.combine(ini, datetime.min.time(), P.FUSO_LOCAL) - timedelta(hours=3)
    serie: Dict[str, Counter] = defaultdict(Counter)
    por_pessoa: Dict[str, Dict[str, Any]] = {}
    ultimo: Dict[str, Dict[str, Any]] = {}
    for m in P._mensagens(desde):
        numero = _t(m.get("contact_number"))
        p = resp.get(numero)
        if not p:
            continue                                   # aviso de outro local do cliente
        quando = P._ler_utc(m.get("created_at"))
        if not quando:
            continue
        local = quando.astimezone(P.FUSO_LOCAL).date()
        if not (ini <= local <= fim):
            continue
        classe = P._classe(m.get("status"))
        serie[local.isoformat()][classe] += 1
        pid = _t(p.get("id"))
        x = por_pessoa.setdefault(pid, {"id": pid, "nome": _t(p.get("full_name")), "grupo": _grupo(p, ctx["modo"]),
                                        "responsavel": _t(p.get("guardian_name")), "numero": numero,
                                        "enviados": 0, "lidos": 0, "entregues": 0, "falhas": 0, "erro": ""})
        x["enviados"] += 1
        if classe in ("lido", "entregue", "falha"):
            x[{"lido": "lidos", "entregue": "entregues", "falha": "falhas"}[classe]] += 1
        if classe == "falha":
            x["erro"] = _t(m.get("error"))
        ultimo[pid] = m
    for pid, m in ultimo.items():
        por_pessoa[pid]["ultimo_ok"] = P._classe(m.get("status")) != "falha"
    sem_numero = sorted(({"id": _t(p.get("id")), "nome": _t(p.get("full_name")), "grupo": _grupo(p, ctx["modo"])}
                         for p in pessoas if _t(p.get("person_type")) == "student" and not P._numero(p.get("guardian_phone"))),
                        key=lambda x: (x["grupo"], x["nome"]))
    dias = []
    d = ini
    while d <= fim:
        c = serie.get(d.isoformat(), Counter())
        dias.append({"dia": d.isoformat(), "lido": c["lido"], "entregue": c["entregue"], "enviado": c["enviado"], "falha": c["falha"]})
        d += timedelta(days=1)
    tot = Counter()
    for c in serie.values():
        tot.update(c)
    enviados = sum(tot[k] for k in ("lido", "entregue", "enviado", "falha"))
    lista = sorted(por_pessoa.values(), key=lambda x: (x.get("ultimo_ok", True), x["grupo"], x["nome"]))
    return {"motor": "avisos", "de": ini.isoformat(), "ate": fim.isoformat(), "serie": dias, "pessoas": lista,
            "sem_numero": sem_numero,
            "resumo": {"enviados": enviados, "lidos": tot["lido"], "entregues": tot["entregue"],
                       "sem_confirmacao": tot["enviado"], "falhas": tot["falha"],
                       "pessoas_avisadas": len(lista), "sem_numero": len(sem_numero),
                       "falhando": sum(1 for x in lista if not x.get("ultimo_ok", True)),
                       "numeros_compartilhados": len(compartilhados)}}


def gerar(rid: str, site: str = "", de: str = "", ate: str = "", dia: str = "", grupo: str = "",
          quem: str = "", portas: Optional[List[str]] = None, agora: Optional[datetime] = None) -> Dict[str, Any]:
    ctx = contexto(site)
    if ctx.get("precisa_local"):
        raise HTTPException(status_code=400, detail="Escolha um local no topo: cada relatório é de um local.")
    rid_, nome, pergunta, motor = _relatorio(ctx["modo"], _t(rid))
    hoje = (agora or P._agora()).astimezone(P.FUSO_LOCAL).date()
    portas = [p for p in (portas or []) if p]
    if motor == "presenca":
        dados = _presenca(ctx, de, ate, _t(grupo), _t(quem), hoje)
    elif motor == "cadastro":
        dados = _cadastro(ctx)
    elif motor == "diario":
        dados = _diario(ctx, dia, portas, hoje)
    elif motor == "uso":
        dados = _uso(ctx, de, ate, portas, hoje)
    else:
        dados = _avisos(ctx, de, ate, hoje)
    return {"ok": True, "id": rid_, "nome": nome, "pergunta": pergunta, "site": ctx["site"], "modo": ctx["modo"],
            "vocab": ctx["vocab"], "grupo": _t(grupo), "gerado_em": P._local_txt(agora or P._agora()), **dados}
