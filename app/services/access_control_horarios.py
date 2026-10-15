"""Aba Acesso do Painel (/v3/acesso/#acesso): grupos, horarios, feriados e a
SIMULACAO do horario contra as passagens reais.

Modelo (o mesmo dos sistemas de mercado e o que o leitor Intelbras guarda,
HTTP API V3.59 12.1.15 AccessTimeSchedule: 7 dias + feriado, ate 6 faixas por
dia): o GRUPO de pessoas abre estas PORTAS neste HORARIO.

Nesta etapa NADA vai para os leitores: o usuario monta grupos e horarios,
simula com as passagens que aconteceram e so depois decide enviar. Por isso
salvar um grupo aqui nao enfileira provisionamento (a tela antiga enfileirava).

Onde fica:
- grupo de pessoas, grupo de portas e regra: tabelas que ja existiam
  (access_groups, access_door_groups, access_rules). Cada grupo ganha um grupo
  de portas so dele, ligado por uma regra; a regra continua "todos os dias,
  00:00-23:59" para o envio de hoje nao mudar.
- horarios, feriados por local, qual horario cada grupo usa e se a saida e
  livre: arquivo do cliente (tenant_scoped_path), como o tipo do local.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from app.services import db_store

ARQUIVO = "acesso-horarios.json"
DIAS = ("dom", "seg", "ter", "qua", "qui", "sex", "sab")   # ordem do leitor: domingo primeiro
LINHAS = [str(i) for i in range(7)] + ["feriado"]
MAX_FAIXAS = 6
FUSO_LOCAL = timezone(timedelta(hours=-3))
HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")


def _t(v: Any) -> str:
    return str(v or "").strip()


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _rows(sql: str, params: Iterable[Any]) -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]


# ---------------------------------------------------------------- arquivo do cliente

def _arquivo():
    from app.core.tenant_context import tenant_scoped_path
    return tenant_scoped_path(ARQUIVO, _tenant())


def _ler() -> Dict[str, Any]:
    try:
        d = json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    for k in ("horarios", "grupo_horario", "feriados", "saida_livre"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def _gravar(d: Dict[str, Any]) -> None:
    arq = _arquivo()
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, arq)


# ---------------------------------------------------------------- horarios

def _minutos(h: str) -> int:
    hh, mm = h.split(":")
    return int(hh) * 60 + int(mm)


def _limpar_faixas(faixas: Any, rotulo: str) -> List[List[str]]:
    saida: List[List[str]] = []
    for f in faixas or []:
        if not isinstance(f, (list, tuple)) or len(f) != 2:
            raise ValueError(f"Faixa invalida em {rotulo}.")
        ini, fim = _t(f[0]), _t(f[1])
        if not HORA.match(ini) or not HORA.match(fim):
            raise ValueError(f"Hora invalida em {rotulo}: use HH:MM.")
        if _minutos(fim) <= _minutos(ini):
            raise ValueError(f"Em {rotulo}, o fim ({fim}) precisa ser depois do inicio ({ini}).")
        saida.append([ini, fim])
    saida.sort(key=lambda x: _minutos(x[0]))
    juntas: List[List[str]] = []
    for f in saida:   # faixas que encostam ou se sobrepoem viram uma so
        if juntas and _minutos(f[0]) <= _minutos(juntas[-1][1]):
            if _minutos(f[1]) > _minutos(juntas[-1][1]):
                juntas[-1][1] = f[1]
        else:
            juntas.append(f)
    if len(juntas) > MAX_FAIXAS:
        raise ValueError(f"Em {rotulo} cabem no maximo {MAX_FAIXAS} faixas (limite do leitor).")
    return juntas


def salvar_horario(payload: Dict[str, Any]) -> Dict[str, Any]:
    nome = _t(payload.get("nome"))[:63]   # o leitor aceita ate 63 caracteres
    if not nome:
        raise ValueError("De um nome ao horario.")
    dias_in = payload.get("dias") or {}
    rotulos = {**{str(i): DIAS[i] for i in range(7)}, "feriado": "feriado"}
    dias = {k: _limpar_faixas(dias_in.get(k), rotulos[k]) for k in LINHAS}
    d = _ler()
    hid = _t(payload.get("id")) or uuid.uuid4().hex[:12]
    if _t(payload.get("id")) and hid not in d["horarios"]:
        raise ValueError("Horario nao encontrado neste cliente.")
    d["horarios"][hid] = {"id": hid, "nome": nome, "site": _t(payload.get("site")), "dias": dias}
    _gravar(d)
    return d["horarios"][hid]


def excluir_horario(hid: str) -> Dict[str, Any]:
    d = _ler()
    if hid not in d["horarios"]:
        raise ValueError("Horario nao encontrado neste cliente.")
    usam = [g for g, h in d["grupo_horario"].items() if h == hid]
    if usam:
        raise ValueError(f"Este horario esta em uso por {len(usam)} grupo(s). Troque o horario deles antes.")
    d["horarios"].pop(hid)
    _gravar(d)
    return {"ok": True}


def salvar_feriados(site: str, feriados: List[Dict[str, Any]]) -> Dict[str, Any]:
    nome_site = _t(site)
    if not nome_site:
        raise ValueError("Informe o local dos feriados.")
    limpos = {}
    for f in feriados or []:
        data = _t(f.get("data"))
        try:
            datetime.strptime(data, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Data invalida: {data!r} (use AAAA-MM-DD).")
        limpos[data] = {"data": data, "nome": _t(f.get("nome"))[:60]}
    d = _ler()
    d["feriados"][nome_site.upper()] = {"site": nome_site, "datas": [limpos[k] for k in sorted(limpos)]}
    _gravar(d)
    return d["feriados"][nome_site.upper()]


# ---------------------------------------------------------------- grupos (cartoes)

def _portas_do_grupo(gid: str, regras: List[Dict[str, Any]]) -> List[str]:
    from app.services.access_control_store import list_door_group_members
    ids: set = set()
    for r in regras:
        if r.get("active") and _t(r.get("people_group_id")) == gid:
            ids.update(_t(x) for x in list_door_group_members(_t(r.get("door_group_id"))))
    return sorted(ids)


def acesso(site: str = "") -> Dict[str, Any]:
    from app.services.access_control_painel import _perfil
    from app.services.access_control_store import list_devices, list_groups, list_people, list_rules
    d = _ler()
    regras = list_rules()
    leitores = [{"id": _t(x.get("id")), "nome": _t(x.get("name")), "site": _t(x.get("site")),
                 "funcao": _t(x.get("access_direction")) or "entrada", "ativo": bool(x.get("active"))}
                for x in list_devices()]
    membros = Counter(_t(r.get("group_id")) for r in _rows(
        "SELECT m.group_id FROM access_group_members m JOIN access_people p "
        "ON p.id=m.person_id AND p.tenant_slug=m.tenant_slug WHERE m.tenant_slug=?", (_tenant(),)))
    grupos = []
    for g in list_groups():
        gid = _t(g.get("id"))
        if site and _t(g.get("site")).upper() != site.upper():
            continue
        grupos.append({
            "id": gid, "nome": _t(g.get("name")), "site": _t(g.get("site")), "ativo": bool(g.get("active", True)),
            "membros": membros.get(gid, 0), "portas": _portas_do_grupo(gid, regras),
            "horario_id": d["grupo_horario"].get(gid, ""), "saida_livre": bool(d["saida_livre"].get(gid, True)),
        })
    grupos.sort(key=lambda x: (x["site"].upper(), x["nome"].upper()))
    horarios = sorted(d["horarios"].values(), key=lambda h: h["nome"].upper())
    usos = Counter(d["grupo_horario"].values())
    for h in horarios:
        h["grupos"] = usos.get(h["id"], 0)
    return {"ok": True, "grupos": grupos, "horarios": horarios, "leitores": leitores,
            "feriados": d["feriados"], "perfil": _perfil(site, list_people())}


def salvar_grupo(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Grava o cartao: nome/local/ativo do grupo, as portas (grupo de portas so
    deste grupo + regra 24h que liga os dois), o horario e a saida livre.
    Membros nao mudam aqui (sao geridos em Pessoas). Nao envia nada ao leitor."""
    from app.services.access_control_store import (list_devices, list_groups, list_rules, save_door_group,
                                                    save_group, save_rule, set_door_group_members)
    gid_in = _t(payload.get("id"))
    if gid_in and gid_in not in {_t(g.get("id")) for g in list_groups()}:
        raise ValueError("Grupo nao encontrado neste cliente.")
    validos = {_t(x.get("id")) for x in list_devices()}
    portas = sorted({_t(p) for p in payload.get("portas") or [] if _t(p)})
    if set(portas) - validos:
        raise ValueError("Porta nao encontrada neste cliente.")
    d = _ler()
    hid = _t(payload.get("horario_id"))
    if hid and hid not in d["horarios"]:
        raise ValueError("Horario nao encontrado neste cliente.")
    grupo = save_group({"id": gid_in, "name": payload.get("nome"), "site": payload.get("site"),
                        "active": payload.get("ativo", True)})
    gid = _t(grupo.get("id"))
    regras = [r for r in list_rules() if _t(r.get("people_group_id")) == gid]
    uso_dg = Counter(_t(r.get("door_group_id")) for r in list_rules())
    propria = next((r for r in regras if uso_dg[_t(r.get("door_group_id"))] == 1), None)
    if propria:
        dg_id = _t(propria.get("door_group_id"))
        save_door_group({"id": dg_id, "name": f"Portas · {grupo['name']}", "site": grupo.get("site")})
    else:
        dg_id = _t(save_door_group({"name": f"Portas · {grupo['name']}", "site": grupo.get("site")}).get("id"))
    set_door_group_members(dg_id, portas)
    regra = save_rule({"id": _t(propria.get("id")) if propria else "", "people_group_id": gid, "door_group_id": dg_id,
                       "name": grupo["name"], "weekdays": "1234567", "time_start": "00:00", "time_end": "23:59",
                       "active": True})
    # As portas das outras regras do grupo ja entraram na lista acima (a tela as
    # mostrou juntas); essas regras saem de cena para nao abrir porta a mais.
    for r in regras:
        if _t(r.get("id")) != _t(regra.get("id")) and r.get("active"):
            save_rule({**r, "active": False})
    if hid:
        d["grupo_horario"][gid] = hid
    else:
        d["grupo_horario"].pop(gid, None)
    d["saida_livre"][gid] = bool(payload.get("saida_livre", True))
    _gravar(d)
    return {"ok": True, "id": gid}


def excluir_grupo(gid: str) -> Dict[str, Any]:
    from app.services.access_control_store import delete_door_group, delete_group, delete_rule, list_groups, list_rules
    gid = _t(gid)
    if gid not in {_t(g.get("id")) for g in list_groups()}:
        raise ValueError("Grupo nao encontrado neste cliente.")
    membros = _rows("SELECT count(*) AS n FROM access_group_members WHERE tenant_slug=? AND group_id=?", (_tenant(), gid))
    if membros and int(membros[0].get("n") or 0):
        raise ValueError("O grupo ainda tem pessoas. Tire as pessoas dele em Pessoas antes de excluir.")
    todas = list_rules()
    uso_dg = Counter(_t(r.get("door_group_id")) for r in todas)
    for r in todas:
        if _t(r.get("people_group_id")) == gid:
            delete_rule(_t(r.get("id")))
            if uso_dg[_t(r.get("door_group_id"))] == 1:
                delete_door_group(_t(r.get("door_group_id")))
    delete_group(gid)
    d = _ler()
    d["grupo_horario"].pop(gid, None)
    d["saida_livre"].pop(gid, None)
    _gravar(d)
    return {"ok": True}


# ---------------------------------------------------------------- simulacao

def _dentro(faixas: List[List[str]], hm: int) -> bool:
    return any(_minutos(a) <= hm < (24 * 60 if b in ("23:59", "24:00") else _minutos(b)) for a, b in faixas)


def simular(site: str = "", dias: int = 14, agora: Optional[datetime] = None) -> Dict[str, Any]:
    """Passa as passagens reais pelo horario configurado e diz o que o leitor
    teria feito. So leitura: nao grava nada e nao fala com leitor nenhum."""
    from app.services.access_control_store import list_devices, list_groups, list_people, list_rules
    agora = agora or datetime.now(timezone.utc)
    dias = max(1, min(int(dias or 14), 60))
    tenant = _tenant()
    d = _ler()
    regras = list_rules()
    grupos = {_t(g.get("id")): g for g in list_groups() if g.get("active", True)}
    portas_de = {gid: set(_portas_do_grupo(gid, regras)) for gid in grupos}
    leitores = {_t(x.get("id")): x for x in list_devices()}
    pessoas = {_t(p.get("id")): p for p in list_people()}
    grupos_da: Dict[str, List[str]] = defaultdict(list)
    for r in _rows("SELECT group_id, person_id FROM access_group_members WHERE tenant_slug=?", (tenant,)):
        if _t(r.get("group_id")) in grupos:
            grupos_da[_t(r.get("person_id"))].append(_t(r.get("group_id")))
    feriados = {k: {x["data"] for x in (v or {}).get("datas", [])} for k, v in d["feriados"].items()}

    inicio = (agora.astimezone(FUSO_LOCAL) - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
    sql = ("SELECT id, person_id, device_id, event_type, occurred_at, site FROM access_events "
           "WHERE tenant_slug=? AND occurred_at >= ? AND person_id IS NOT NULL AND person_id <> ''"
           + (" AND site=?" if site else "") + " ORDER BY occurred_at")
    eventos = _rows(sql, (tenant, inicio, site) if site else (tenant, inicio))

    c = Counter()
    barradas: List[Dict[str, Any]] = []
    fora: List[Dict[str, Any]] = []
    por_grupo: Dict[str, Counter] = defaultdict(Counter)
    por_hora = [0] * 24
    afetadas: set = set()
    for e in eventos:
        pid, did = _t(e.get("person_id")), _t(e.get("device_id"))
        quando = _t(e.get("occurred_at"))[:19]
        try:
            dt = datetime.strptime(quando, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        saida = _t(e.get("event_type")).lower().startswith("saida")
        leitor = leitores.get(did) or {}
        if not pessoas.get(pid):
            continue
        c["analisadas"] += 1
        meus = [g for g in grupos_da.get(pid, []) if did in portas_de.get(g, ())]
        item = {"pessoa_id": pid, "pessoa": _t(pessoas[pid].get("full_name")), "porta": _t(leitor.get("name")) or did,
                "quando": quando, "tipo": "saida" if saida else "entrada"}
        if not meus:
            c["fora_das_portas"] += 1
            if len(fora) < 300:
                fora.append({**item, "grupos": [_t(grupos[g].get("name")) for g in grupos_da.get(pid, [])]})
            continue
        feriado = dt.strftime("%Y-%m-%d") in feriados.get((_t(leitor.get("site")) or _t(e.get("site"))).upper(), set())
        linha = "feriado" if feriado else str((dt.weekday() + 1) % 7)   # python: seg=0; leitor: dom=0
        hm = dt.hour * 60 + dt.minute
        ok_por = None
        for g in meus:
            hid = d["grupo_horario"].get(g)
            if not hid or hid not in d["horarios"]:
                ok_por = g; break                                  # sem horario = 24 horas
            if saida and d["saida_livre"].get(g, True):
                ok_por = g; break
            if _dentro(d["horarios"][hid]["dias"].get(linha, []), hm):
                ok_por = g; break
        if ok_por:
            c["liberadas"] += 1
            por_grupo[ok_por]["liberadas"] += 1
            continue
        c["barradas"] += 1
        c["barradas_" + item["tipo"]] += 1
        por_hora[dt.hour] += 1
        afetadas.add(pid)
        for g in meus:
            por_grupo[g]["barradas"] += 1
        if len(barradas) < 400:
            hid = d["grupo_horario"].get(meus[0])
            barradas.append({**item, "feriado": feriado,
                             "grupos": [_t(grupos[g].get("name")) for g in meus],
                             "horario": (d["horarios"].get(hid) or {}).get("nome", "")})
    resumo_grupos = [{"id": g, "nome": _t(grupos[g].get("name")), "liberadas": v["liberadas"], "barradas": v["barradas"]}
                     for g, v in por_grupo.items()]
    resumo_grupos.sort(key=lambda x: -x["barradas"])
    barradas.sort(key=lambda x: x["quando"], reverse=True)
    return {"ok": True, "dias": dias, "site": site, "desde": inicio,
            "analisadas": c["analisadas"], "liberadas": c["liberadas"], "barradas": c["barradas"],
            "barradas_entrada": c["barradas_entrada"], "barradas_saida": c["barradas_saida"],
            "fora_das_portas": c["fora_das_portas"], "pessoas_afetadas": len(afetadas),
            "por_hora": por_hora, "por_grupo": resumo_grupos,
            "lista_barradas": barradas, "lista_fora": fora[:300]}
