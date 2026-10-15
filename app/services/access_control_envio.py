"""Enviar um grupo aos leitores: SO O QUE FALTA.

O envio antigo (access_control_sync.provision_person_everywhere) faz
AccessUser insertMulti para cada pessoa: quem ja esta no leitor e recusado
(ID repetido), e trocar para updateMulti regravaria todo mundo com senha
123456, validade fixa e a foto de novo -- mexendo no que funciona.

Aqui: le cada leitor das portas do grupo (recordFinder AccessControlCard),
cadastra SO quem esta no grupo e nao esta no leitor (usuario sem senha,
validade de 10 anos a partir de hoje, e a foto) e nao toca em mais ninguem.
Nada e apagado. Quem ja estava fica marcado "ok" no SightOps, para a tela
mostrar a situacao real.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)
FUSO_LOCAL = timezone(timedelta(hours=-3))


def _t(v: Any) -> str:
    return str(v or "").strip()


def leitores_do_grupo(group_id: str) -> List[str]:
    from app.services import access_control_store as S
    ids: set = set()
    for r in S.list_rules():
        if r.get("active") and r.get("people_group_id") == group_id:
            ids |= set(S.list_door_group_members(r["door_group_id"]))
    return sorted(ids)


def enviar_faltantes(group_id: str, usuario: str = "", agora: Optional[datetime] = None,
                     listar=None, cadastrar=None, so_planejar: bool = False) -> Dict[str, Any]:
    from app.services import access_control_store as S
    from app.services.access_control_device import _provision_intelbras_person, list_controller_people
    from app.services.access_control_photos import load_person_face_photo

    listar = listar or list_controller_people
    cadastrar = cadastrar or _provision_intelbras_person
    grupo = next((g for g in S.list_groups() if g["id"] == group_id), None)
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo nao encontrado neste cliente.")
    agora = (agora or datetime.now(timezone.utc)).astimezone(FUSO_LOCAL)
    de = agora.strftime("%Y-%m-%d 00:00:00")
    ate = agora.replace(year=agora.year + 10).strftime("%Y-%m-%d 23:59:59")
    pessoas = {p["id"]: p for p in S.list_people()}
    membros = [pessoas[i] for i in S.list_group_members(group_id) if i in pessoas and pessoas[i].get("active")]
    sem_id = [p["full_name"] for p in membros if not _t(p.get("controller_user_id"))]
    por_uid = {_t(p["controller_user_id"]): p for p in membros if _t(p.get("controller_user_id"))}

    saida: Dict[str, Any] = {"ok": True, "grupo": grupo["name"], "leitores": [], "sem_id_no_leitor": sem_id}
    for did in leitores_do_grupo(group_id):
        device = S.get_device_with_password(did)
        if not device:
            continue
        r: Dict[str, Any] = {"leitor": device["name"], "ja_estavam": 0, "cadastradas": [], "falhas": []}
        saida["leitores"].append(r)
        try:
            no_leitor = {_t(p.get("controller_user_id")) for p in listar(device)}
        except HTTPException as exc:
            r["erro"] = _t(exc.detail)
            saida["ok"] = False
            continue
        faltam = [p for u, p in por_uid.items() if u not in no_leitor]
        r["ja_estavam"] = len(por_uid) - len(faltam)
        r["faltam"] = [p["full_name"] for p in faltam]
        if so_planejar:
            continue
        for u, p in por_uid.items():
            if u in no_leitor:
                S.upsert_provision_status(p["id"], did, "ok")
        for p in faltam:
            try:
                cadastrar(device, p, load_person_face_photo(p), senha=None, valido_de=de, valido_ate=ate)
                S.upsert_provision_status(p["id"], did, "ok")
                r["cadastradas"].append(p["full_name"])
            except Exception as exc:   # um nao para os outros
                erro = _t(getattr(exc, "detail", exc)) or exc.__class__.__name__
                S.upsert_provision_status(p["id"], did, "failed", erro)
                r["falhas"].append({"nome": p["full_name"], "erro": erro})
                saida["ok"] = False
        logger.info("envio do grupo %s ao leitor %s por %s: %s ja estavam, %s cadastradas, %s falhas",
                    grupo["name"], device["name"], usuario, r["ja_estavam"], len(r["cadastradas"]), len(r["falhas"]))
    return saida
