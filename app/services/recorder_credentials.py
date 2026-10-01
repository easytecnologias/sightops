"""Credencial de acesso a gravador (DVR/NVR), lembrada pelo servidor.

Mesmo problema que app/services/camera_credentials.py resolveu para camera: o
inventario de gravador guarda `recorder_user` mas NUNCA a senha (ver
`editable_fields` em app/api/endpoints/nvr.py), entao todo acesso a um gravador
ja cadastrado caia no formulario completo pedindo conector, OLT, usuario e
senha -- dados que o sistema ja conhece, menos a senha, que ninguem guardava.

As duas regras do modulo de camera valem aqui igual:

1. **A senha nunca sai daqui pra cima.** So `resolve_recorder_credential`
   decifra, e ela existe pra ser chamada pelo endpoint que fala com o
   equipamento. `tem_credencial`/`hosts_com_credencial` respondem ao navegador
   e nao tocam no texto cifrado.
2. **Todo acesso e filtrado por tenant.** Nao ha consulta sem `tenant_slug`
   no WHERE.

A chave e (host, porta http): e assim que o gravador e identificado no resto
do sistema (o inventario, o snapshot e o raio-x sao todos por IP), e o mesmo
IP em porta diferente e outro equipamento. Quando nao ha linha na porta exata,
cai para qualquer linha do mesmo host -- o caso de um cadastro antigo salvo
antes de a porta ser conhecida.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.crypto import decrypt, encrypt
from app.services.db_store import _conn, _current_tenant_slug


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm_host(host: Any) -> str:
    return _text(host).lower()


def _norm_port(port: Any) -> int:
    try:
        n = int(str(port or "").strip() or 0)
    except Exception:
        return 0
    return n if 0 < n < 65536 else 0


def save_recorder_credential(host: str, port: Any, username: str, password: str) -> None:
    """Guarda a senha deste gravador. Chamada depois do login dar certo, nunca
    antes: senha errada nao vira senha salva."""
    pw = str(password or "")
    host_n = _norm_host(host)
    if not pw or not host_n:
        return
    user = _text(username) or "admin"
    port_n = _norm_port(port)
    tenant = _current_tenant_slug()
    enc = encrypt(pw)

    with _conn() as c:
        existente = c.execute(
            "SELECT id FROM recorder_credentials WHERE tenant_slug = ? AND host = ? AND port = ?",
            (tenant, host_n, port_n),
        ).fetchone()
        if existente:
            c.execute(
                "UPDATE recorder_credentials SET username = ?, password_enc = ?, "
                "updated_at = (datetime('now')) WHERE tenant_slug = ? AND host = ? AND port = ?",
                (user, enc, tenant, host_n, port_n),
            )
        else:
            c.execute(
                "INSERT INTO recorder_credentials(tenant_slug, host, port, username, password_enc) "
                "VALUES(?, ?, ?, ?, ?)",
                (tenant, host_n, port_n, user, enc),
            )


def resolve_recorder_credential(host: str, port: Any = 0) -> Optional[Dict[str, str]]:
    """Devolve {"username", "password"} decifrado, ou None se nao ha nada salvo.

    Unico ponto que decifra -- chamado pelo endpoint na hora de falar com o
    gravador, nunca por rota que so responde ao navegador.
    """
    host_n = _norm_host(host)
    if not host_n:
        return None
    tenant = _current_tenant_slug()
    port_n = _norm_port(port)

    with _conn() as c:
        row = None
        if port_n:
            row = c.execute(
                "SELECT username, password_enc FROM recorder_credentials "
                "WHERE tenant_slug = ? AND host = ? AND port = ?",
                (tenant, host_n, port_n),
            ).fetchone()
        if not row:
            row = c.execute(
                "SELECT username, password_enc FROM recorder_credentials "
                "WHERE tenant_slug = ? AND host = ? ORDER BY port DESC",
                (tenant, host_n),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        return {
            "username": _text(item.get("username")) or "admin",
            "password": decrypt(_text(item.get("password_enc"))),
        }


def tem_credencial(host: str, port: Any = 0) -> bool:
    """Existe senha salva? Nao decifra nada."""
    host_n = _norm_host(host)
    if not host_n:
        return False
    tenant = _current_tenant_slug()
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM recorder_credentials WHERE tenant_slug = ? AND host = ?",
            (tenant, host_n),
        ).fetchone()
    return bool(row)


def hosts_com_credencial() -> List[Dict[str, Any]]:
    """Lista `[{host, port, username}]` dos gravadores com senha salva, para a
    tela saber quais entram direto e quais ainda precisam perguntar. Nunca
    inclui a senha, nem cifrada."""
    tenant = _current_tenant_slug()
    with _conn() as c:
        linhas = c.execute(
            "SELECT host, port, username FROM recorder_credentials WHERE tenant_slug = ?",
            (tenant,),
        ).fetchall()
    saida: List[Dict[str, Any]] = []
    for linha in linhas or []:
        item = dict(linha)
        saida.append({
            "host": _text(item.get("host")),
            "port": _norm_port(item.get("port")),
            "username": _text(item.get("username")) or "admin",
        })
    return saida


def esquecer_recorder_credential(host: str, port: Any = 0) -> int:
    """Apaga a senha salva deste gravador. Usado quando o gravador sai do
    inventario -- senha orfa nao fica guardada."""
    host_n = _norm_host(host)
    if not host_n:
        return 0
    tenant = _current_tenant_slug()
    port_n = _norm_port(port)
    with _conn() as c:
        if port_n:
            cur = c.execute(
                "DELETE FROM recorder_credentials WHERE tenant_slug = ? AND host = ? AND port = ?",
                (tenant, host_n, port_n),
            )
        else:
            cur = c.execute(
                "DELETE FROM recorder_credentials WHERE tenant_slug = ? AND host = ?",
                (tenant, host_n),
            )
    try:
        return int(getattr(cur, "rowcount", 0) or 0)
    except Exception:
        return 0
