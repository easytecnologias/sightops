"""Aba Pessoas do Painel de Acesso (/v3/acesso/#pessoas).

O cadastro em si continua na rota que ja existe (POST /people -> save_person,
com as regras de CPF obrigatorio, matricula do aluno e o casamento por CPF e
matricula). Aqui fica o que faltava para a tela nova:

- a lista completa para a tela: grupos da pessoa, situacao em cada leitor
  (foto enviada, recusada com o motivo, pendente) e ultima passagem;
- trocar os grupos de UMA pessoa sem regravar o grupo inteiro (a tela antiga
  reenviava a lista de membros do grupo: duas edicoes ao mesmo tempo apagavam
  uma a outra);
- excluir de verdade. DELETE /people so apagava do banco: a pessoa continuava
  cadastrada nos leitores e seguia abrindo a porta. Agora ela sai dos leitores
  primeiro (AccessFace/AccessUser removeMulti pelo ID da controladora, HTTP API
  Intelbras V3.59 12.4.4 e 12.4.25); se algum leitor nao responder, ela fica
  DESATIVADA (UserStatus 1 = congelada quando o leitor voltar) e nao some.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from app.services import db_store


def _t(v: Any) -> str:
    return str(v or "").strip()


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _rows(sql: str, params: Iterable[Any]) -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]


# ---------------------------------------------------------------- grupos -> leitores

def _mapa_grupos() -> Dict[str, Any]:
    """Grupos do cliente, os leitores que cada um abre (regra ativa -> grupo de
    portas -> leitores) e os membros."""
    from app.services.access_control_store import (list_devices, list_door_group_members, list_groups,
                                                    list_rules)
    leitores = {_t(d.get("id")): d for d in list_devices()}
    portas_por_grupo: Dict[str, set] = defaultdict(set)
    for regra in list_rules():
        if regra.get("active"):
            portas_por_grupo[_t(regra.get("people_group_id"))].add(_t(regra.get("door_group_id")))
    membros: Dict[str, set] = defaultdict(set)
    for r in _rows("SELECT group_id, person_id FROM access_group_members WHERE tenant_slug=?", (_tenant(),)):
        membros[_t(r.get("group_id"))].add(_t(r.get("person_id")))
    grupos = []
    for g in list_groups():
        gid = _t(g.get("id"))
        ids: set = set()
        for dg in portas_por_grupo.get(gid, ()):
            ids.update(_t(x) for x in list_door_group_members(dg))
        grupos.append({
            "id": gid, "nome": _t(g.get("name")), "site": _t(g.get("site")), "ativo": bool(g.get("active", True)),
            "membros": len(membros.get(gid, ())),
            "leitores": sorted(({"id": i, "nome": _t(leitores[i].get("name"))} for i in ids if i in leitores),
                               key=lambda x: x["nome"].upper()),
        })
    grupos.sort(key=lambda x: (x["site"].upper(), x["nome"].upper()))
    return {"grupos": grupos, "membros": membros, "leitores": leitores}


# ---------------------------------------------------------------- lista

def pessoas(site: str = "") -> Dict[str, Any]:
    from app.services.access_control_painel import _perfil
    from app.services.access_control_store import list_people
    tenant = _tenant()
    todas = list_people()
    lista = [p for p in todas if not site or _t(p.get("site")).upper() == site.upper()]
    mapa = _mapa_grupos()
    grupos_da: Dict[str, List[str]] = defaultdict(list)
    for gid, ids in mapa["membros"].items():
        for pid in ids:
            grupos_da[pid].append(gid)
    situacao: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in _rows("SELECT person_id, device_id, status, last_error, updated_at FROM access_provision_status "
                   "WHERE tenant_slug=?", (tenant,)):
        d = mapa["leitores"].get(_t(r.get("device_id")))
        situacao[_t(r.get("person_id"))].append({
            "leitor_id": _t(r.get("device_id")), "leitor": _t(d.get("name")) if d else "leitor removido",
            "status": _t(r.get("status")).lower() or "pendente", "erro": _t(r.get("last_error")),
            "quando": _t(r.get("updated_at"))[:19]})
    ultima = {_t(r.get("person_id")): _t(r.get("ultima")) for r in _rows(
        "SELECT person_id, max(occurred_at) AS ultima FROM access_events WHERE tenant_slug=? "
        "AND person_id IS NOT NULL AND person_id <> '' AND occurred_at >= '2020-01-01' GROUP BY person_id", (tenant,))}
    saida = []
    for p in lista:
        pid = _t(p.get("id"))
        saida.append({
            "id": pid, "nome": _t(p.get("full_name")), "tipo": _t(p.get("person_type")) or "student",
            "cpf": _t(p.get("document_id")), "matricula": _t(p.get("enrollment_code")),
            "turma": _t(p.get("class_name")), "site": _t(p.get("site")),
            "id_controladora": _t(p.get("controller_user_id")),
            "responsavel": _t(p.get("guardian_name")), "telefone": _t(p.get("guardian_phone")),
            "whatsapp": bool(p.get("whatsapp_enabled", True)), "ativo": bool(p.get("active")),
            "notas": _t(p.get("notes")),
            "tem_foto": bool(_t(p.get("face_photo_path"))), "foto_em": _t(p.get("face_photo_updated_at"))[:19],
            "grupos": sorted(grupos_da.get(pid, [])),
            "leitores": sorted(situacao.get(pid, []), key=lambda x: x["leitor"]),
            "ultima": ultima.get(pid, ""),
        })
    saida.sort(key=lambda x: x["nome"].upper())
    return {"ok": True, "pessoas": saida, "grupos": mapa["grupos"], "perfil": _perfil(site, todas),
            "sites": sorted({_t(p.get("site")) for p in todas if _t(p.get("site"))} |
                            {_t(d.get("site")) for d in mapa["leitores"].values() if _t(d.get("site"))}, key=str.upper)}


# ---------------------------------------------------------------- grupos da pessoa

def _pessoa(person_id: str) -> Dict[str, Any]:
    from app.services.access_control_store import list_people
    pid = _t(person_id)
    p = next((x for x in list_people() if _t(x.get("id")) == pid), None)
    if not p:
        raise HTTPException(status_code=404, detail="Pessoa nao encontrada neste cliente.")
    return p


def definir_grupos(person_id: str, group_ids: List[str], remover=None) -> Dict[str, Any]:
    """Coloca a pessoa exatamente nestes grupos, mexendo so nas linhas dela.
    Enfileira o envio para os leitores dos grupos novos (o loop de fundo envia)
    e tira a pessoa dos leitores que deixaram de valer para ela: sem isso ela
    continuava abrindo a porta do grupo antigo, e o reenvio automatico (que
    reprocessa toda linha pendente/falha) a cadastrava de novo la."""
    from app.services.access_control_store import get_device_with_password, list_groups, list_provision_status_for_person
    from app.services.access_control_sync import enqueue_person_provisioning, resolve_target_devices_for_person
    remover = remover or _remover_do_leitor
    p = _pessoa(person_id)
    pid = _t(p.get("id"))
    validos = {_t(g.get("id")) for g in list_groups()}
    pedidos = {_t(g) for g in group_ids or [] if _t(g)}
    estranhos = pedidos - validos
    if estranhos:
        raise HTTPException(status_code=400, detail="Grupo nao encontrado neste cliente.")
    tenant = _tenant()
    with db_store._conn() as c:
        atuais = {_t(r["group_id"]) for r in c.execute(
            "SELECT group_id FROM access_group_members WHERE tenant_slug=? AND person_id=?", (tenant, pid)).fetchall()}
        for gid in atuais - pedidos:
            c.execute("DELETE FROM access_group_members WHERE tenant_slug=? AND group_id=? AND person_id=?",
                      (tenant, gid, pid))
        for gid in pedidos - atuais:
            c.execute("INSERT INTO access_group_members(tenant_slug, group_id, person_id) VALUES(?, ?, ?) "
                      "ON CONFLICT(tenant_slug, group_id, person_id) DO NOTHING", (tenant, gid, pid))
    enfileirados = enqueue_person_provisioning([pid], force=bool(pedidos - atuais))
    alvo = {_t(d.get("id")) for d in resolve_target_devices_for_person(pid)}
    sobrando = {_t(r.get("device_id")) for r in list_provision_status_for_person(pid)} - alvo
    removidos, falhas = [], []
    for did in sorted(x for x in sobrando if x):
        device = get_device_with_password(did)
        uid = _id_no_leitor(device, p) if device else ""
        if device and uid:
            nome = _t(device.get("name")) or did
            try:
                remover(device, uid)
                removidos.append(nome)
            except Exception as exc:
                falhas.append({"leitor": nome, "erro": _t(getattr(exc, "detail", "")) or _t(exc) or exc.__class__.__name__})
        with db_store._conn() as c:   # a linha sai de qualquer jeito: senao o reenvio cadastra de novo
            c.execute("DELETE FROM access_provision_status WHERE tenant_slug=? AND person_id=? AND device_id=?",
                      (tenant, pid, did))
    return {"ok": True, "grupos": sorted(pedidos), "entrou": sorted(pedidos - atuais),
            "saiu": sorted(atuais - pedidos), "enfileirados": enfileirados,
            "removidos": removidos, "falhas_remocao": falhas}


# ---------------------------------------------------------------- excluir

def _id_no_leitor(device: Dict[str, Any], pessoa: Dict[str, Any]) -> str:
    """Intelbras guarda a pessoa pelo ID da controladora (o mesmo que o envio
    usa); Dahua generico, pelo id do SightOps."""
    from app.services.access_control_device import _is_intelbras_device
    if _is_intelbras_device(device):
        return "".join(ch for ch in _t(pessoa.get("controller_user_id")) if ch.isdigit())
    return _t(pessoa.get("id"))


def _remover_do_leitor(device: Dict[str, Any], uid: str) -> None:
    from app.services.access_control_device import _get, _is_intelbras_device, remove_person
    if _is_intelbras_device(device):
        # Rosto primeiro (12.4.25); se o leitor nao tiver rosto dessa pessoa, segue.
        try:
            _get(device, "/cgi-bin/AccessFace.cgi", {"action": "removeMulti", "UserIDList[0]": uid})
        except HTTPException:
            pass
    remove_person(device, uid)


def _desativar(pid: str) -> None:
    with db_store._conn() as c:
        c.execute("UPDATE access_people SET active=0, updated_at=datetime('now') WHERE tenant_slug=? AND id=?",
                  (_tenant(), pid))


def excluir(person_id: str, remover=None) -> Dict[str, Any]:
    """Tira a pessoa de todos os leitores onde ela foi (ou ia ser) cadastrada e
    so entao apaga. Leitor que nao responde: a pessoa fica desativada e nada e
    apagado, para nao sobrar alguem abrindo a porta sem constar no SightOps."""
    from app.services.access_control_store import delete_person, get_device_with_password, list_provision_status_for_person
    from app.services.access_control_sync import enqueue_person_provisioning, resolve_target_devices_for_person
    remover = remover or _remover_do_leitor
    p = _pessoa(person_id)
    pid = _t(p.get("id"))
    alvo = {_t(r.get("device_id")) for r in list_provision_status_for_person(pid)}
    alvo |= {_t(d.get("id")) for d in resolve_target_devices_for_person(pid)}
    removidos, falhas = [], []
    for did in sorted(x for x in alvo if x):
        device = get_device_with_password(did)
        if not device:
            continue   # leitor ja removido do SightOps: nao ha onde apagar
        nome = _t(device.get("name")) or did
        uid = _id_no_leitor(device, p)
        if not uid:
            continue   # nunca chegou a ser enviada (sem ID na controladora)
        try:
            remover(device, uid)
            removidos.append(nome)
        except HTTPException as exc:
            falhas.append({"leitor": nome, "erro": _t(exc.detail)})
        except Exception as exc:  # um leitor nao derruba os outros
            falhas.append({"leitor": nome, "erro": _t(exc) or exc.__class__.__name__})
    if falhas:
        _desativar(pid)
        enqueue_person_provisioning([pid], force=True)   # congela no leitor quando ele voltar
        return {"ok": False, "excluida": False, "desativada": True, "removidos": removidos, "falhas": falhas}
    tenant = _tenant()
    with db_store._conn() as c:
        c.execute("DELETE FROM access_group_members WHERE tenant_slug=? AND person_id=?", (tenant, pid))
        c.execute("DELETE FROM access_provision_status WHERE tenant_slug=? AND person_id=?", (tenant, pid))
    delete_person(pid)
    return {"ok": True, "excluida": True, "desativada": False, "removidos": removidos, "falhas": []}
