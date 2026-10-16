"""Canais do gravador aberto (mini DVR, parte 5): o que o SightOps mudou num
canal fica registrado, com quem e quando, e da para desfazer.

Os registros moram no MESMO lugar e formato das correcoes de configuracao
(recorder_avisos: gravador_backups/registros/<id>.json), para a tela mostrar
um historico so. A diferenca: correcao de configuracao se desfaz reaplicando
chaves (g.aplicar); edicao de canal se desfaz reeditando o canal pelo
recorder_write. Por isso o registro de canal leva `tipo: "canal"`,
`desfazivel: False` (o desfazer das correcoes nao sabe voltar canal) e
`desfazivel_canal`, que so este modulo usa.

Senha da camera: editar/adicionar canal exige usuario e senha da camera. Quando
a tela nao manda (o caso de "a camera mudou de IP, apontar o canal"), vale a
senha salva da camera pelo MAC, ou a do site (camera_credentials).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.tenant_context import tenant_scoped_path


def _t(v: Any) -> str:
    return str(v or "").strip()


def base_registros() -> Path:
    # Mesma base de recorder_driver._base_registros (por cliente).
    return tenant_scoped_path("gravador_backups")


def _dir(base: Path) -> Path:
    d = base / "registros"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mac(v: Any) -> str:
    return re.sub(r"[^0-9a-f]", "", _t(v).lower())


def canal_no_inventario(host: str, canal: int) -> Dict[str, str]:
    """MAC e site que o inventario do SightOps (deste cliente) tem para o canal
    deste gravador. E o que autoriza usar a senha salva: o MAC e o site vem
    daqui, nao da tela (senao um operador faria o gravador entregar a senha de
    uma camera a um IP qualquer da rede)."""
    try:
        from app.api.endpoints.nvr import _read_rows
        linhas = _read_rows()
    except Exception:
        linhas = []
    for r in linhas:
        try:
            ch = int(r.get("channel") or 0)
        except (TypeError, ValueError):
            continue
        if _t(r.get("host")) == _t(host) and ch == int(canal):
            return {"mac": _t(r.get("camera_mac") or r.get("mac")), "site": _t(r.get("site") or r.get("local"))}
    return {"mac": "", "site": ""}


def senha_autorizada(host: str, canal: int, mac_tela: str, user: str, senha: str) -> tuple[str, str]:
    """Senha da camera para editar/adicionar o canal: a digitada, ou a salva --
    so se o MAC da tela for o MAC que o inventario tem para este canal deste
    gravador (o caso "a camera mudou de IP"); a senha do site entra so com o
    site do inventario."""
    if _t(senha):
        return (_t(user) or "admin", _t(senha))
    inv = canal_no_inventario(host, canal)
    mac_ok = bool(inv["mac"]) and _mac(inv["mac"]) == _mac(mac_tela)
    return senha_da_camera(inv["mac"] if mac_ok else "", inv["site"] if mac_ok else "", user, "")


def senha_da_camera(mac: str, site: str, user: str, senha: str) -> tuple[str, str]:
    """(usuario, senha) da camera: o que veio da tela, ou o salvo por MAC/site."""
    if _t(senha):
        return (_t(user) or "admin", _t(senha))
    try:
        from app.services.camera_credentials import resolve_camera_credential
        salva = resolve_camera_credential(mac, site)
    except Exception:
        salva = None
    if salva and salva.get("password"):
        return (salva.get("username") or "admin", salva["password"])
    return (_t(user) or "admin", "")


_TITULOS = {
    "editar": "Canal {c}: camera apontada para {ip}",
    "adicionar": "Canal {c}: camera {ip} adicionada",
    "excluir": "Canal {c}: camera removida",
    "renomear": "Canal {c}: renomeado para \"{nome}\"",
}


def registrar(acao: str, *, host: str, conector: str, canal: int, por: str,
              antes: Optional[Dict[str, Any]] = None, depois: Optional[Dict[str, Any]] = None,
              ok: bool = True, base: Optional[Path] = None) -> Dict[str, Any]:
    """Grava o registro de uma edicao de canal. `antes` (ip, nome, mac, user)
    vem da tela, lido do gravador antes de mudar; sem ele nao ha como desfazer."""
    base = base or base_registros()
    antes = {k: _t(v) for k, v in (antes or {}).items() if k in ("ip", "nome", "mac", "user", "protocolo")}
    depois = {k: _t(v) for k, v in (depois or {}).items() if k in ("ip", "nome", "mac", "user", "protocolo")}
    if acao in ("editar", "renomear"):
        pode = bool(antes.get("ip") if acao == "editar" else antes.get("nome"))
    elif acao == "excluir":
        pode = bool(antes.get("ip"))
    else:   # adicionar se desfaz excluindo
        pode = True
    reg = {
        "id": uuid.uuid4().hex[:12], "tipo": "canal", "acao": acao,
        "host": _t(host), "conector": _t(conector), "canal": int(canal),
        "titulo": _TITULOS.get(acao, "Canal {c}").format(c=f"{int(canal):02d}", ip=depois.get("ip") or antes.get("ip") or "",
                                                         nome=depois.get("nome") or ""),
        "quando": datetime.now().isoformat(timespec="seconds"), "por": _t(por),
        "antes": antes, "depois": depois, "ok": bool(ok),
        "desfazivel": False, "desfazivel_canal": pode and bool(ok),
    }
    (_dir(base) / f"{reg['id']}.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    return reg


def ler(reg_id: str, base: Optional[Path] = None) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{12}", _t(reg_id)):
        raise ValueError("registro invalido")
    arq = _dir(base or base_registros()) / f"{reg_id}.json"
    if not arq.exists():
        raise ValueError("registro nao encontrado")
    return json.loads(arq.read_text(encoding="utf-8"))


def marcar_desfeito(reg: Dict[str, Any], por: str, base: Optional[Path] = None) -> None:
    reg["desfeito_em"] = datetime.now().isoformat(timespec="seconds")
    reg["desfeito_por"] = _t(por)
    (_dir(base or base_registros()) / f"{reg['id']}.json").write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def plano_desfazer(reg: Dict[str, Any], host: str, conector: str) -> Dict[str, Any]:
    """A acao que volta o canal ao que era. Recusa registro de outro gravador
    (mesmo IP existe em sites diferentes, atras de conectores diferentes)."""
    if reg.get("tipo") != "canal":
        raise ValueError("esse registro nao e de canal")
    if reg.get("host") != _t(host) or _t(reg.get("conector")) != _t(conector):
        raise ValueError("esse registro e de outro gravador")
    if reg.get("desfeito_em"):
        raise ValueError("ja foi desfeito")
    if not reg.get("desfazivel_canal"):
        raise ValueError("essa mudanca nao guardou o estado anterior; nao tem como desfazer")
    a, antes = reg.get("acao"), reg.get("antes") or {}
    canal = int(reg.get("canal") or 0)
    if a == "editar":
        return {"acao": "editar", "canal": canal, "ip": antes["ip"], "mac": antes.get("mac", ""),
                "user": antes.get("user", ""), "protocolo": antes.get("protocolo", ""), "nome": antes.get("nome", "")}
    if a == "renomear":
        return {"acao": "renomear", "canal": canal, "nome": antes["nome"]}
    if a == "excluir":
        return {"acao": "adicionar", "canal": canal, "ip": antes["ip"], "mac": antes.get("mac", ""),
                "user": antes.get("user", ""), "protocolo": antes.get("protocolo", ""), "nome": antes.get("nome", "")}
    if a == "adicionar":
        return {"acao": "excluir", "canal": canal}
    raise ValueError("acao desconhecida")


def eventos_das_cameras(ips: List[str], dias: int = 7, limite: int = 60) -> List[Dict[str, Any]]:
    """Quedas e voltas das cameras destes IPs (monitoramento do SightOps), do
    cliente atual. A chave da entidade camera termina em ':<ip>'."""
    from app.services import db_store
    ips = [i for i in {_t(x) for x in ips or []} if re.fullmatch(r"[0-9.]{7,15}", i)][:128]
    if not ips:
        return []
    tenant = db_store._current_tenant_slug()
    desde = (datetime.utcnow() - timedelta(days=max(1, min(int(dias), 30)))).isoformat(timespec="seconds")
    alvo = {f":{ip}" for ip in ips}
    with db_store._conn() as c:
        rows = c.execute(
            "SELECT entity_key, from_status, to_status, message, created_at FROM monitoring_events "
            "WHERE tenant_slug=? AND entity_type='camera' AND created_at >= ? ORDER BY created_at DESC LIMIT 2000",
            (tenant, desde),
        ).fetchall()
    saida = []
    for r in rows:
        r = dict(r)
        chave = _t(r.get("entity_key"))
        ip = chave.rsplit(":", 1)[-1]
        if f":{ip}" not in alvo:
            continue
        saida.append({"ip": ip, "de": _t(r.get("from_status")), "para": _t(r.get("to_status")),
                      "mensagem": _t(r.get("message")), "quando": _t(r.get("created_at"))[:19]})
        if len(saida) >= limite:
            break
    return saida
