"""Dados do controle de acesso de UM cliente: backup e excluir um local inteiro
(/v3/acesso, botao "Dados", so admin -- regra em app/core/security.py).

Backup: um .zip com as linhas do cliente (ou de um local) de todas as tabelas
access_*, as fotos das pessoas e os arquivos do cliente (horarios, tipo do
local). Fica guardado no armazenamento do cliente (access-control/backups) e
sai para download. NAO e o backup do servidor (deploy/backup, banco inteiro
de todos os clientes): este nunca leva dado de outro cliente.

Excluir local: faz o backup ANTES e so entao apaga. Pessoas saem pela mesma
regra da aba Pessoas (access_control_pessoas.excluir): primeiro dos leitores,
depois do SightOps. Se algum leitor nao responder, a pessoa fica desativada e
o resto (leitores, grupos) NAO e apagado, para ninguem continuar abrindo a
porta sem constar no SightOps. O historico de passagens so sai se pedirem.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from app.services import db_store

logger = logging.getLogger(__name__)

PASTA = "access-control/backups"
MANTER = 30                      # backups guardados por cliente; o mais velho sai
FUSO_LOCAL = timezone(timedelta(hours=-3))
NOME_OK = re.compile(r"^acesso-[a-z0-9-]{1,60}-\d{8}-\d{6}\.zip$")
ARQUIVOS_CLIENTE = ("acesso-horarios.json", "acesso-tipos-de-local.json")
TABELAS = ("access_people", "access_devices", "access_groups", "access_group_members",
           "access_door_groups", "access_door_group_members", "access_rules",
           "access_provision_status", "access_events", "access_whatsapp_messages")


def _t(v: Any) -> str:
    return str(v or "").strip()


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _rows(sql: str, params: Iterable[Any]) -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        return [dict(r) for r in c.execute(sql, tuple(params)).fetchall()]


def _pasta_cliente() -> Path:
    from app.core.tenant_context import tenant_data_dir
    return tenant_data_dir(_tenant())


def _pasta_backups() -> Path:
    p = _pasta_cliente() / PASTA
    p.mkdir(parents=True, exist_ok=True)
    return p


def _foto_do_cliente(pasta: Path, rel: str) -> Optional[Path]:
    """Arquivo da foto, so se estiver em access-control/faces DESTA pasta de
    cliente. Comparar texto (startswith) deixaria /tenants/acme "conter"
    /tenants/acme2; is_relative_to compara pasta por pasta."""
    rel = _t(rel)
    if not rel.startswith("access-control/faces/") or ".." in rel:
        return None
    base = (pasta / "access-control" / "faces").resolve()
    arq = (pasta / rel).resolve()
    return arq if arq.is_relative_to(base) and arq.is_file() else None


def _slug(texto: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", _t(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "local"


# ---------------------------------------------------------------- o que existe

def _do_site(sql_tabela: str, site: str) -> str:
    return f"SELECT * FROM {sql_tabela} WHERE tenant_slug=?" + (" AND UPPER(site)=?" if site else "")


def coletar(site: str = "") -> Dict[str, List[Dict[str, Any]]]:
    """Linhas do cliente atual; com `site`, so o que pertence a esse local.
    Tabelas de ligacao entram quando tocam algo do local (membro de grupo do
    local ou pessoa do local, regra de grupo do local, ...)."""
    from app.services.access_control_store import ensure_access_control_schema
    ensure_access_control_schema()
    tenant, s = _tenant(), _t(site).upper()
    p = (tenant, s) if s else (tenant,)
    d: Dict[str, List[Dict[str, Any]]] = {}
    for tab in ("access_people", "access_devices", "access_groups", "access_door_groups", "access_events"):
        d[tab] = _rows(_do_site(tab, s), p)
    pessoas = {r["id"] for r in d["access_people"]}
    leitores = {r["id"] for r in d["access_devices"]}
    grupos = {r["id"] for r in d["access_groups"]}
    portas = {r["id"] for r in d["access_door_groups"]}

    def todos(tab: str) -> List[Dict[str, Any]]:
        try:
            return _rows(f"SELECT * FROM {tab} WHERE tenant_slug=?", (tenant,))
        except Exception:
            # access_whatsapp_messages nasce com o primeiro canal; cliente sem
            # WhatsApp nao tem a tabela. Conexao propria: no Postgres o erro
            # nao contamina as outras consultas.
            if tab != "access_whatsapp_messages":
                raise
            return []

    d["access_group_members"] = [r for r in todos("access_group_members")
                                 if not s or r["group_id"] in grupos or r["person_id"] in pessoas]
    d["access_door_group_members"] = [r for r in todos("access_door_group_members")
                                      if not s or r["door_group_id"] in portas or r["device_id"] in leitores]
    d["access_rules"] = [r for r in todos("access_rules")
                         if not s or r["people_group_id"] in grupos or r["door_group_id"] in portas]
    d["access_provision_status"] = [r for r in todos("access_provision_status")
                                    if not s or r["person_id"] in pessoas or r["device_id"] in leitores]
    # Conversa de WhatsApp nao tem local: so vai no backup do cliente inteiro.
    d["access_whatsapp_messages"] = [] if s else todos("access_whatsapp_messages")
    return d


def resumo() -> Dict[str, Any]:
    """Para a janela "Dados": o que cada local tem e os backups guardados."""
    tenant = _tenant()
    locais: Dict[str, Dict[str, Any]] = {}

    def conta(sql: str, campo: str) -> None:
        for r in _rows(sql, (tenant,)):
            nome = _t(r.get("site"))
            if not nome:
                continue
            l = locais.setdefault(nome.upper(), {"site": nome, "pessoas": 0, "fotos": 0, "leitores": 0,
                                                 "grupos": 0, "grupos_portas": 0, "passagens": 0})
            l[campo] += int(r.get("n") or 0)

    from app.services.access_control_store import ensure_access_control_schema
    ensure_access_control_schema()
    conta("SELECT site, COUNT(*) AS n FROM access_people WHERE tenant_slug=? GROUP BY site", "pessoas")
    conta("SELECT site, COUNT(*) AS n FROM access_people WHERE tenant_slug=? AND face_photo_path<>'' GROUP BY site", "fotos")
    conta("SELECT site, COUNT(*) AS n FROM access_devices WHERE tenant_slug=? GROUP BY site", "leitores")
    conta("SELECT site, COUNT(*) AS n FROM access_groups WHERE tenant_slug=? GROUP BY site", "grupos")
    conta("SELECT site, COUNT(*) AS n FROM access_door_groups WHERE tenant_slug=? GROUP BY site", "grupos_portas")
    conta("SELECT site, COUNT(*) AS n FROM access_events WHERE tenant_slug=? GROUP BY site", "passagens")
    return {"ok": True, "locais": sorted(locais.values(), key=lambda l: l["site"].upper()), "backups": backups()}


# ---------------------------------------------------------------- backup

def _manifesto(arq: Path) -> Dict[str, Any]:
    try:
        with zipfile.ZipFile(arq) as z:
            return json.loads(z.read("manifesto.json"))
    except Exception:
        return {}


def backups() -> List[Dict[str, Any]]:
    saida = []
    for arq in sorted(_pasta_backups().glob("acesso-*.zip"), key=lambda a: a.name[-19:], reverse=True):
        if not NOME_OK.match(arq.name):
            continue
        m = _manifesto(arq)
        saida.append({"nome": arq.name, "bytes": arq.stat().st_size, "site": m.get("site", ""),
                      "feito_em": m.get("feito_em", ""), "por": m.get("por", ""), "motivo": m.get("motivo", ""),
                      "contagem": m.get("contagem", {})})
    return saida


def fazer_backup(site: str = "", usuario: str = "", motivo: str = "", agora: Optional[datetime] = None) -> Dict[str, Any]:
    agora = (agora or datetime.now(timezone.utc)).astimezone(FUSO_LOCAL)
    site = _t(site)
    dados = coletar(site)
    pasta = _pasta_cliente()
    contagem = {tab: len(v) for tab, v in dados.items()}
    fotos = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for tab, linhas in dados.items():
            z.writestr(f"tabelas/{tab}.json", json.dumps(linhas, ensure_ascii=False, default=str, indent=1))
        for p in dados["access_people"]:
            rel = _t(p.get("face_photo_path"))
            arq = _foto_do_cliente(pasta, rel)
            if arq:
                z.write(arq, f"fotos/{rel}", compress_type=zipfile.ZIP_STORED)   # JPEG ja e comprimido
                fotos += 1
        for nome in ARQUIVOS_CLIENTE:
            arq = pasta / nome
            if arq.is_file():
                z.write(arq, f"arquivos/{nome}")
        contagem["fotos"] = fotos
        manifesto = {"versao": 1, "cliente": _tenant(), "site": site, "feito_em": agora.isoformat(timespec="seconds"),
                     "por": _t(usuario), "motivo": _t(motivo), "contagem": contagem,
                     "observacao": "Senhas dos leitores vao cifradas (password_enc): so este servidor le."}
        z.writestr("manifesto.json", json.dumps(manifesto, ensure_ascii=False, indent=1))
    nome = f"acesso-{_slug(site) if site else 'cliente'}-{agora:%Y%m%d-%H%M%S}.zip"
    destino = _pasta_backups() / nome
    tmp = destino.with_suffix(".tmp")
    tmp.write_bytes(buf.getvalue())
    os.replace(tmp, destino)
    for velho in backups()[MANTER:]:
        try:
            (_pasta_backups() / velho["nome"]).unlink()
        except OSError:
            pass
    logger.info("backup do controle de acesso: cliente=%s site=%s por=%s arquivo=%s bytes=%s",
                _tenant(), site or "(todos)", usuario, nome, destino.stat().st_size)
    return {"ok": True, "nome": nome, "bytes": destino.stat().st_size, "site": site,
            "feito_em": manifesto["feito_em"], "contagem": contagem}


def arquivo_backup(nome: str) -> Path:
    nome = _t(nome)
    if not NOME_OK.match(nome):
        raise HTTPException(status_code=400, detail="Nome de backup invalido.")
    arq = _pasta_backups() / nome
    if not arq.is_file():
        raise HTTPException(status_code=404, detail="Backup nao encontrado neste cliente.")
    return arq


# ---------------------------------------------------------------- excluir local

def excluir_local(site: str, confirmacao: str, apagar_historico: bool = False, usuario: str = "",
                  remover=None) -> Dict[str, Any]:
    from app.services import access_control_pessoas as pessoas_svc
    from app.services.access_control_store import delete_device

    site = _t(site)
    if not site:
        raise HTTPException(status_code=400, detail="Escolha o local.")
    if " ".join(_t(confirmacao).upper().split()) != " ".join(site.upper().split()):
        raise HTTPException(status_code=400, detail=f"Para confirmar, digite o nome do local: {site}")
    dados = coletar(site)
    if not any(dados[t] for t in ("access_people", "access_devices", "access_groups", "access_door_groups", "access_events")):
        raise HTTPException(status_code=404, detail="Nada encontrado neste local.")

    backup = fazer_backup(site, usuario, motivo="antes de excluir o local")   # falhou: nada e apagado
    tenant = _tenant()
    pasta = _pasta_cliente()

    excluidas, mantidas = 0, []
    for p in dados["access_people"]:
        r = pessoas_svc.excluir(p["id"], remover)
        if r.get("excluida"):
            excluidas += 1
            arq = _foto_do_cliente(pasta, p.get("face_photo_path"))
            if arq:
                arq.unlink()
        else:
            mantidas.append({"nome": p.get("full_name"), "falhas": r.get("falhas", [])})

    resultado: Dict[str, Any] = {"ok": not mantidas, "site": site, "backup": backup["nome"],
                                 "pessoas_excluidas": excluidas, "pessoas_mantidas": mantidas,
                                 "leitores": 0, "grupos": 0, "grupos_portas": 0, "passagens": 0}
    if mantidas:
        # Leitor fora: quem ficou nele continua cadastrado. Apagar o leitor e os
        # grupos agora tiraria do SightOps a unica forma de tirar a pessoa de la.
        logger.warning("excluir local %s/%s parou: %s pessoa(s) ficaram desativadas (leitor sem resposta)",
                       tenant, site, len(mantidas))
        return resultado

    for d in dados["access_devices"]:
        resultado["leitores"] += int(delete_device(d["id"]))
    grupos = [g["id"] for g in dados["access_groups"]]
    portas = [g["id"] for g in dados["access_door_groups"]]
    with db_store._conn() as c:
        for gid in grupos:
            c.execute("DELETE FROM access_rules WHERE tenant_slug=? AND people_group_id=?", (tenant, gid))
            c.execute("DELETE FROM access_group_members WHERE tenant_slug=? AND group_id=?", (tenant, gid))
            resultado["grupos"] += int(c.execute("DELETE FROM access_groups WHERE tenant_slug=? AND id=?", (tenant, gid)).rowcount or 0)
        for did in portas:
            c.execute("DELETE FROM access_rules WHERE tenant_slug=? AND door_group_id=?", (tenant, did))
            c.execute("DELETE FROM access_door_group_members WHERE tenant_slug=? AND door_group_id=?", (tenant, did))
            resultado["grupos_portas"] += int(c.execute("DELETE FROM access_door_groups WHERE tenant_slug=? AND id=?", (tenant, did)).rowcount or 0)
        if apagar_historico:
            resultado["passagens"] = int(c.execute("DELETE FROM access_events WHERE tenant_slug=? AND UPPER(site)=?",
                                                   (tenant, site.upper())).rowcount or 0)
    _limpar_arquivos(site, set(grupos))
    logger.info("local excluido: cliente=%s site=%s por=%s backup=%s resultado=%s", tenant, site, usuario,
                backup["nome"], {k: v for k, v in resultado.items() if k != "pessoas_mantidas"})
    return resultado


def _limpar_arquivos(site: str, grupos: set) -> None:
    """Horarios/feriados do local e o tipo escolhido para ele."""
    from app.services import access_control_horarios as H
    from app.services import access_control_painel as P
    S = site.upper()
    d = H._ler()
    for gid in grupos:
        d["grupo_horario"].pop(gid, None)
        d["saida_livre"].pop(gid, None)
    d["feriados"].pop(S, None)
    em_uso = set(d["grupo_horario"].values())
    for hid, h in list(d["horarios"].items()):
        if _t(h.get("site")).upper() == S and hid not in em_uso:
            d["horarios"].pop(hid)
    H._gravar(d)
    arq = P._arquivo_tipos()
    try:
        tipos = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(tipos, dict) and tipos.pop(S, None) is not None:
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(tipos, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, arq)
