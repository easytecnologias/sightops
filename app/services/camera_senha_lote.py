"""Ensinar UMA senha a todas as cameras de um site que recusam a guardada.

Quando o instalador troca a senha de um site inteiro, as cameras passam a
recusar a senha guardada (a da camera e a do site) e o ao vivo, a foto e a
troca de IP param -- e o operador teria de digitar a senha camera por camera
(15/10/2026, RESERVA da Easy). Aqui ele digita uma vez.

Cuidado que manda no desenho: camera Intelbras BLOQUEIA o usuario depois de
algumas senhas erradas seguidas. Por isso:
- no maximo DUAS tentativas por camera: confere a guardada; so se ela for
  recusada, testa a nova;
- a conferencia para no primeiro 401 (nao testa a outra prova com a mesma
  senha errada);
- so grava com resposta 2xx. Timeout ou 404 = "sem resposta", nada muda --
  diferente de maintenance._senha_aceita, que aprova o inconclusivo para nao
  APAGAR senha certa; aqui o risco e o oposto, GRAVAR senha errada.
Camera atras de conector isolado so e consultada pelo IP virtual.
"""
from __future__ import annotations

import contextvars
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import requests
from requests.auth import HTTPDigestAuth

from app.core.tenant_context import get_current_tenant_slug
from app.services import connector_routing_vnat as vnat
from app.services.camera_credentials import (
    definir_senha_do_site,
    resolve_camera_credential,
    save_camera_credential,
)
from app.services.inventory_json import load_inventory_json

_PROVA_INTELBRAS = "/cgi-bin/magicBox.cgi?action=getSystemInfo"
_PROVA_HIKVISION = "/ISAPI/System/deviceInfo"
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _txt(v: Any) -> str:
    return str(v or "").strip()


def conferir_senha(alvo: str, user: str, senha: str, marca: str = "") -> str:
    """'aceita' | 'recusa' | 'sem_resposta'. Para no primeiro 401/403."""
    provas = [_PROVA_HIKVISION, _PROVA_INTELBRAS] if "hik" in marca.lower() else [_PROVA_INTELBRAS, _PROVA_HIKVISION]
    for caminho in provas:
        try:
            r = requests.get(f"http://{alvo}{caminho}", auth=HTTPDigestAuth(user, senha), timeout=6, verify=False)
        except Exception:
            continue
        if 200 <= r.status_code < 300:
            return "aceita"
        if r.status_code in (401, 403):
            return "recusa"
    return "sem_resposta"


def _alcance(ip: str, conector: str) -> str:
    """IP para falar com a camera; '' quando so daria pelo IP real."""
    if not conector:
        return ip
    virtual = vnat.virtual_ip_for(conector, ip)
    if not virtual or virtual == vnat.IP_BLOQUEADO:
        return ""
    if virtual == ip and vnat.has_mapping(conector):
        return ""
    return virtual


def cameras_do_site(site: str) -> List[Dict[str, Any]]:
    alvo = site.strip().lower()
    vistos, out = set(), []
    for modo in ("olt", "switch", "basic"):
        for r in load_inventory_json(mode=modo) or []:
            if not isinstance(r, dict) or not _txt(r.get("ip")):
                continue
            s = _txt(r.get("site") or r.get("site_name") or r.get("local")).lower()
            if s != alvo:
                continue
            conector = _txt(r.get("remote_connector_id") or r.get("connector_id"))
            chave = (conector, _txt(r.get("ip")))
            if chave in vistos:
                continue
            vistos.add(chave)
            out.append(r)
    return out


def _uma(r: Dict[str, Any], site: str, user: str, senha: str) -> str:
    ip = _txt(r.get("ip"))
    mac = _txt(r.get("mac"))
    conector = _txt(r.get("remote_connector_id") or r.get("connector_id"))
    marca = _txt(r.get("fabricante") or r.get("manufacturer") or r.get("model"))
    alvo = _alcance(ip, conector)
    if not alvo:
        return "fora_do_conector"
    guardada = resolve_camera_credential(mac, site) or {}
    senha_guardada = guardada.get("password") or ""
    if senha_guardada:
        if senha_guardada == senha and _txt(guardada.get("username") or "admin") == user:
            return "ja_era_essa"
        atual = conferir_senha(alvo, _txt(guardada.get("username")) or "admin", senha_guardada, marca)
        if atual == "aceita":
            return "guardada_funciona"
        if atual == "sem_resposta":
            return "sem_resposta"
    nova = conferir_senha(alvo, user, senha, marca)
    if nova == "aceita":
        if mac:
            save_camera_credential(mac, site, user, senha)
            return "aprendeu"
        return "aprendeu_sem_mac"
    return "nova_recusada" if nova == "recusa" else "sem_resposta"


def _rodar(job_id: str, site: str, user: str, senha: str) -> None:
    job = _JOBS[job_id]
    try:
        cameras = cameras_do_site(site)
        job["total"] = len(cameras)
        contagem: Dict[str, int] = {}

        def tarefa(r):
            res = _uma(r, site, user, senha)
            with _JOBS_LOCK:
                contagem[res] = contagem.get(res, 0) + 1
                job["feitas"] += 1
                job["resultado"] = dict(contagem)
                if res in ("nova_recusada", "sem_resposta", "fora_do_conector"):
                    job["pendentes"].append({"ip": _txt(r.get("ip")), "nome": _txt(r.get("titulo")), "motivo": res})
            return res

        # 4 por vez: rapido o bastante e sem rajada em cima do tunel/cameras.
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda r: contextvars.copy_context().run(tarefa, r), cameras))

        aprendeu = contagem.get("aprendeu", 0) + contagem.get("aprendeu_sem_mac", 0)
        recusou_as_duas = contagem.get("nova_recusada", 0)
        # O site inteiro mudou de senha? Passa a nova a ser o padrao -- camera
        # nova do site (e as sem MAC) ja nasce com a senha certa.
        if aprendeu and aprendeu >= recusou_as_duas:
            definir_senha_do_site(site, user, senha)
            job["senha_do_site_trocada"] = True
        job["estado"] = "concluido"
    except Exception as exc:  # noqa: BLE001
        job["estado"] = "erro"
        job["erro"] = str(exc)[:200]
    job["fim"] = time.time()


def iniciar(site: str, user: str, senha: str) -> Dict[str, Any]:
    tenant = get_current_tenant_slug() or ""
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        # guarda so os ultimos 50, sem senha nenhuma dentro
        for velho in sorted(_JOBS, key=lambda k: _JOBS[k]["inicio"])[:-50]:
            _JOBS.pop(velho, None)
        _JOBS[job_id] = {"id": job_id, "tenant": tenant, "site": site, "estado": "rodando", "inicio": time.time(),
                         "total": 0, "feitas": 0, "resultado": {}, "pendentes": [], "senha_do_site_trocada": False}
    ctx = contextvars.copy_context()  # a thread precisa do cliente da requisicao
    threading.Thread(target=ctx.run, args=(_rodar, job_id, site, user, senha), daemon=True).start()
    return {"job_id": job_id}


def estado(job_id: str) -> Dict[str, Any] | None:
    job = _JOBS.get(job_id)
    if not job or job.get("tenant") != (get_current_tenant_slug() or ""):
        return None  # job de outro cliente nao existe para este
    return {k: v for k, v in job.items() if k != "tenant"}
