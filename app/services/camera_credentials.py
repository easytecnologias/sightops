"""Credencial de acesso a camera, lembrada pelo servidor (cifrada, por tenant).

Antes disto, "ver ao vivo"/reboot/renomear/PTZ exigiam usuario+senha em TODA
chamada -- o operador digitava a senha da camera de novo a cada aba nova, e
essa senha trafegava do navegador ate o backend em toda acao. Aqui a senha e
digitada uma vez e o servidor passa a resolve-la sozinho dali pra frente.

Duas regras que valem pra tudo neste modulo (mesmas do app/services/olt_registry.py):

1. **A senha nunca sai daqui pra cima.** So `resolve_camera_credential` decifra,
   e ela existe pra ser chamada pelos endpoints que falam com o equipamento --
   nunca por rota que so informa "essa camera tem senha salva?".
2. **Todo acesso e filtrado por tenant.** Nao ha funcao que busque credencial
   sem `tenant_slug` no WHERE.

Duas tabelas (ver migrations/main/*/010_camera_credentials.sql):
- `camera_site_credentials`: senha padrao de um site inteiro.
- `camera_mac_credentials`: senha de UMA camera especifica (por MAC, estavel
  mesmo se o IP mudar) -- tem prioridade sobre a do site quando existe.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.core.crypto import decrypt, encrypt
from app.services.db_store import _conn, _current_tenant_slug


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm_site(site: Any) -> str:
    return _text(site).lower()


def _norm_mac(mac: Any) -> str:
    s = _text(mac).lower().replace("-", ":").replace(".", ":")
    return re.sub(r":+", ":", s)


def save_camera_credential(mac: str, site: str, username: str, password: str) -> None:
    """Salva a senha desta camera especifica (por MAC) e, se o site ainda nao
    tiver uma senha padrao, salva a mesma senha como padrao do site tambem --
    assim a proxima camera nova do mesmo site ja nasce sabendo.

    Sem MAC (camera sem essa info no inventario) so o site e atualizado, se
    houver site. Sem MAC e sem site, nao ha o que lembrar -- a chamada e um
    no-op silencioso (o comando na hora ainda funciona com a senha digitada,
    so nao fica salva pra proxima vez).
    """
    user = _text(username) or "admin"
    pw = str(password or "")
    if not pw:
        return
    mac_n = _norm_mac(mac)
    site_n = _norm_site(site)
    tenant = _current_tenant_slug()
    enc = encrypt(pw)

    with _conn() as c:
        if mac_n:
            existente = c.execute(
                "SELECT id FROM camera_mac_credentials WHERE tenant_slug = ? AND mac = ?",
                (tenant, mac_n),
            ).fetchone()
            if existente:
                c.execute(
                    "UPDATE camera_mac_credentials SET username = ?, password_enc = ?, "
                    "updated_at = (datetime('now')) WHERE tenant_slug = ? AND mac = ?",
                    (user, enc, tenant, mac_n),
                )
            else:
                c.execute(
                    "INSERT INTO camera_mac_credentials(tenant_slug, mac, username, password_enc) "
                    "VALUES(?, ?, ?, ?)",
                    (tenant, mac_n, user, enc),
                )

        if site_n:
            tem_padrao = c.execute(
                "SELECT id FROM camera_site_credentials WHERE tenant_slug = ? AND site = ?",
                (tenant, site_n),
            ).fetchone()
            if not tem_padrao:
                c.execute(
                    "INSERT INTO camera_site_credentials(tenant_slug, site, username, password_enc) "
                    "VALUES(?, ?, ?, ?)",
                    (tenant, site_n, user, enc),
                )


def resolve_camera_credential(mac: str, site: str) -> Optional[Dict[str, str]]:
    """Devolve {"username", "password"} com a senha decifrada, ou None se nao
    ha nada salvo pra essa camera/site. Prioridade: senha da camera (MAC)
    primeiro, senha do site como fallback.

    Unico ponto do sistema que decifra -- chamado pelos endpoints na hora de
    falar com o equipamento, nunca por rota que so responde ao navegador.
    """
    tenant = _current_tenant_slug()
    mac_n = _norm_mac(mac)
    site_n = _norm_site(site)

    with _conn() as c:
        if mac_n:
            row = c.execute(
                "SELECT username, password_enc FROM camera_mac_credentials "
                "WHERE tenant_slug = ? AND mac = ?",
                (tenant, mac_n),
            ).fetchone()
            if row:
                item = dict(row)
                return {"username": _text(item.get("username")) or "admin", "password": decrypt(_text(item.get("password_enc")))}

        if site_n:
            row = c.execute(
                "SELECT username, password_enc FROM camera_site_credentials "
                "WHERE tenant_slug = ? AND site = ?",
                (tenant, site_n),
            ).fetchone()
            if row:
                item = dict(row)
                return {"username": _text(item.get("username")) or "admin", "password": decrypt(_text(item.get("password_enc")))}

    return None
