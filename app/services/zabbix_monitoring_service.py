from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List
import os
from urllib.parse import urlsplit, urlunsplit

import requests

from app.core.tenant_context import get_current_tenant_slug
from app.services.db_store import _conn, load_app_settings
from app.services.monitoring_service import list_entities


def _text(value: Any) -> str:
    return str(value or "").strip()


def _api_url(raw: Any) -> str:
    value = _text(raw)
    if not value:
        return ""
    parts = urlsplit(value)
    if (parts.hostname or "").lower() in {"10.10.12.51", "zabbix-web", "zabbix-prod-web"}:
        host = os.getenv("SIGHTOPS_ZABBIX_WEB_HOST", "zabbix-prod-web").strip() or "zabbix-prod-web"
        port = os.getenv("SIGHTOPS_ZABBIX_WEB_PORT", "8080").strip() or "8080"
        return urlunsplit((parts.scheme or "http", f"{host}:{port}", "/api_jsonrpc.php", "", ""))
    return value


def _default_zabbix_cfg(cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    base = dict(cfg or {})
    url = _api_url(base.get("url"))
    if not url:
        url = (
            _text(os.getenv("SIGHTOPS_ZABBIX_URL"))
            or _text(os.getenv("ZBX_URL"))
            or _text(os.getenv("ZABBIX_URL"))
            or "http://zabbix-prod-web:8080/api_jsonrpc.php"
        )
    user = (
        _text(base.get("user"))
        or _text(os.getenv("SIGHTOPS_ZABBIX_USER"))
        or _text(os.getenv("ZBX_USER"))
        or _text(os.getenv("ZABBIX_USER"))
        or "Admin"
    )
    password = (
        _text(base.get("pass") or base.get("password"))
        or _text(os.getenv("SIGHTOPS_ZABBIX_PASS"))
        or _text(os.getenv("ZBX_PASS"))
        or _text(os.getenv("ZABBIX_PASS"))
        or "zabbix"
    )
    return {**base, "url": _api_url(url), "user": user, "pass": password}


def _call(url: str, method: str, params: Any, auth: str | None = None, req_id: int = 1) -> Any:
    body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
    if auth:
        body["auth"] = auth
    response = requests.post(url, json=body, timeout=45)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise RuntimeError(f"{method}: {data['error']}")
    return data.get("result")


def _chunks(rows: List[Dict[str, Any]], size: int = 50) -> Iterable[List[Dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index:index + size]


def _host_key(tenant: str, row: Dict[str, Any]) -> str:
    digest = hashlib.sha1(_text(row.get("entity_key")).encode("utf-8")).hexdigest()[:16]
    return f"SIGHTOPS.{tenant}.{_text(row.get('entity_type')).upper()}.{digest}"


def _number(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", _text(value))
    try:
        return float(match.group(0).replace(",", ".")) if match else None
    except ValueError:
        return None


def find_orphan_hostids(
    current_hosts: List[Dict[str, Any]],
    technical_names: Dict[str, Any],
    tenant: str,
    entity_types: Iterable[str],
) -> List[str]:
    """Hosts SIGHTOPS.<tenant>.<TIPO>.* que existem no Zabbix mas cuja entidade
    (ONU/OLT) nao esta mais ativa em `technical_names` -- ficaram orfaos porque
    o sync so criava hosts, nunca removia os que sumiram do inventario."""
    prefixes = tuple(f"SIGHTOPS.{tenant}.{entity_type.upper()}." for entity_type in entity_types)
    return [
        _text(row.get("hostid"))
        for row in current_hosts
        if _text(row.get("host")).startswith(prefixes) and _text(row.get("host")) not in technical_names
    ]


def _ensure_group(url: str, auth: str, name: str, req_id: int) -> str:
    rows = _call(url, "hostgroup.get", {"output": ["groupid"], "filter": {"name": [name]}}, auth, req_id) or []
    if rows:
        return _text(rows[0].get("groupid"))
    created = _call(url, "hostgroup.create", {"name": name}, auth, req_id + 1) or {}
    return _text((created.get("groupids") or [""])[0])


def _detalhe(row: Dict[str, Any]) -> Dict[str, Any]:
    """O detalhe vem do banco como texto JSON."""
    bruto = row.get("detail") if isinstance(row.get("detail"), dict) else row.get("detail_json")
    if isinstance(bruto, dict):
        return bruto
    try:
        valor = json.loads(bruto or "{}")
        return valor if isinstance(valor, dict) else {}
    except Exception:
        return {}


_RE_MAC = re.compile(r"^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.I)
_RE_SERIAL_GPON = re.compile(r"^[0-9A-Fa-f]{8}$|^[A-Z]{4}[0-9A-Fa-f]{8}$")


def _identificacao_onu(detalhe: Dict[str, Any], row: Dict[str, Any]) -> tuple[str, str, str]:
    """Devolve (serial_gpon, mac, texto_rotulado).

    O campo `onu_serial` guarda coisas diferentes conforme o fabricante: serial
    GPON na Intelbras, MAC na FiberHome. Classificar pelo formato do valor evita
    chamar MAC de serial no alerta.
    """
    bruto_serial = _text(detalhe.get("serial"))
    mac = _text(detalhe.get("mac") or row.get("onu_mac") or row.get("cpe_mac"))
    serial = ""
    if _RE_MAC.match(bruto_serial):
        mac = mac or bruto_serial
    elif bruto_serial:
        serial = bruto_serial

    if serial and mac:
        texto = f"Serial {serial}  |  MAC {mac}"
    elif serial:
        texto = f"Serial {serial}"
    elif mac:
        texto = f"MAC {mac}"
    else:
        texto = "sem identificacao registrada"
    return serial, mac, texto


def _linha_sinal(detalhe: Dict[str, Any]) -> str:
    """Texto pronto do sinal optico -- ou o motivo de nao haver.

    A FiberHome desta base nao entrega potencia. Repetir "-- dBm" em todo alerta
    daquele cliente treina o leitor a ignorar a linha.
    """
    onu_rx = _text(detalhe.get("onu_rx"))
    olt_rx = _text(detalhe.get("olt_rx"))
    if onu_rx and olt_rx:
        return f"ONU RX {onu_rx} dBm  |  OLT RX {olt_rx} dBm"
    if onu_rx or olt_rx:
        return f"ONU RX {onu_rx or '--'} dBm  |  OLT RX {olt_rx or '--'} dBm"
    return "esta OLT nao informa potencia optica"


def _dica_onu(detalhe: Dict[str, Any]) -> str:
    """O que verificar primeiro, conforme o ultimo sinal conhecido.

    Texto fixo dizendo "se o sinal ja estava fraco" numa OLT que nao mede sinal
    manda o tecnico procurar um dado que nao existe.
    """
    try:
        onu_rx = float(str(detalhe.get("onu_rx") or "").replace(",", "."))
    except (TypeError, ValueError):
        onu_rx = None
    if onu_rx is None:
        return ("esta OLT nao mede potencia, entao comece pela energia no ponto do "
                "assinante; persistindo, verifique fibra e conector.")
    if onu_rx <= -27:
        return (f"o sinal ja estava fraco ({onu_rx:.1f} dBm): suspeite de fibra, "
                "conector sujo ou curva no cabo.")
    return (f"o sinal estava bom ({onu_rx:.1f} dBm): provavelmente queda de energia "
            "no ponto do assinante.")


def _macros_da_entidade(row: Dict[str, Any]) -> List[Dict[str, str]]:
    """Dados de identificacao que a mensagem do Telegram vai usar.

    Sinal e distancia tambem entram, mas como retrato do ultimo sincronismo: no
    alerta, o valor fresco vem do item (`{ITEM.LASTVALUE}`). Ter os dois ajuda --
    a macro diz como estava quando cadastramos, o item diz como esta agora.
    """
    d = _detalhe(row)
    tipo = _text(row.get("entity_type")).lower()
    chave = _text(row.get("entity_key"))
    comuns = {
        "{$SITE}": _text(row.get("site")),
        "{$SIGHTOPS_NOME}": _text(row.get("display_name")),
        "{$SIGHTOPS_TIPO}": tipo.upper(),
    }
    if tipo == "olt":
        comuns.update({
            "{$OLT_IP}": _text(d.get("host")),
            "{$OLT_FABRICANTE}": _text(d.get("vendor")),
            "{$OLT_MODELO}": _text(d.get("model")),
            "{$OLT_ULTIMO_TESTE}": _text(d.get("last_test_status")),
        })
    elif tipo == "onu":
        ident_serial, ident_mac, ident_texto = _identificacao_onu(d, row)
        # a chave carrega conector|olt_ip|pon|onu no formato "onu:a|b|c|d"
        partes = chave.split(":", 1)[-1].split("|") if "|" in chave else []
        olt_ip = partes[1] if len(partes) > 1 else ""
        pon = partes[2] if len(partes) > 2 else _text(d.get("pon"))
        onu = partes[3] if len(partes) > 3 else ""
        comuns.update({
            # Em um cliente esse campo traz o assinante (Escola_Medea, CAIXA-07);
            # no outro, so o rotulo "gpon X onu Y". Vale nos dois casos.
            "{$ONU_NOME}": _text(row.get("display_name")),
            "{$ONU_IDENT}": ident_texto,
            "{$ONU_SINAL}": _linha_sinal(d),
            "{$ONU_DICA}": _dica_onu(d),
            "{$ONU_SERIAL}": ident_serial,
            "{$ONU_MAC}": ident_mac,
            "{$ONU_PON}": _text(pon),
            "{$ONU_ID}": _text(onu),
            "{$ONU_OLT_IP}": _text(olt_ip),
            "{$ONU_RX}": _text(d.get("onu_rx")),
            "{$OLT_RX}": _text(d.get("olt_rx")),
            "{$ONU_DISTANCIA}": _text(d.get("distance_km")),
            "{$ONU_OMCI}": _text(d.get("omci_status")),
        })
    return [{"macro": k, "value": v} for k, v in comuns.items()]


def _mensagens_telegram(entity_type: str) -> tuple[str, str]:
    """Texto de problema e de recuperacao, por tipo de equipamento."""
    if entity_type == "olt":
        problema = "\n".join([
            "\U0001F534 <b>OLT FORA DO AR</b>",
            "",
            "\U0001F5A5 <b>OLT:</b> {$SIGHTOPS_NOME}",
            "\U0001F4CD <b>Local:</b> {$SITE}",
            "\U0001F310 <b>IP:</b> {$OLT_IP}",
            "\U0001F527 <b>Equipamento:</b> {$OLT_FABRICANTE} {$OLT_MODELO}",
            "",
            "\u26A0\uFE0F <b>Problema:</b> {EVENT.NAME}",
            "\U0001F6E0 <b>O que fazer:</b> a OLT parou de responder. Verifique energia,",
            "link e acesso ao equipamento -- enquanto ela estiver fora, TODAS as ONUs",
            "e cameras atendidas por ela ficam sem monitoramento.",
            "",
            "\U0001F552 <b>Quando:</b> {EVENT.DATE} {EVENT.TIME}",
        ])
        recuperacao = "\n".join([
            "\u2705 <b>OLT NORMALIZADA</b>",
            "",
            "\U0001F5A5 <b>OLT:</b> {$SIGHTOPS_NOME}",
            "\U0001F4CD <b>Local:</b> {$SITE}  |  \U0001F310 {$OLT_IP}",
            "",
            "\U0001F514 <b>Resolvido:</b> {EVENT.NAME}",
            "\U0001F552 <b>Quando:</b> {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}",
        ])
        return problema, recuperacao

    problema = "\n".join([
        "\U0001F4E1 <b>ONU SEM COMUNICACAO</b>",
        "",
        "\U0001F3E0 <b>ONU:</b> {$ONU_NOME}",
        "\U0001F522 <b>Identificacao:</b> {$ONU_IDENT}",
        "\U0001F4CD <b>Local:</b> {$SITE}  |  PON {$ONU_PON} / ONU {$ONU_ID}",
        "\U0001F50C <b>OLT:</b> {$ONU_OLT_IP}",
        "",
        "\U0001F4F6 <b>Sinal:</b> {$ONU_SINAL}",
        "\U0001F4CF <b>Distancia:</b> {$ONU_DISTANCIA} km",
        "",
        "\u26A0\uFE0F <b>Problema:</b> {EVENT.NAME}",
        "🛠 <b>O que verificar:</b> {$ONU_DICA}",
        "",
        "\U0001F552 <b>Quando:</b> {EVENT.DATE} {EVENT.TIME}",
    ])
    recuperacao = "\n".join([
        "\u2705 <b>ONU NORMALIZADA</b>",
        "",
        "\U0001F3E0 <b>ONU:</b> {$ONU_NOME}  |  \U0001F522 {$ONU_IDENT}",
        "\U0001F4CD <b>Local:</b> {$SITE}  |  PON {$ONU_PON} / ONU {$ONU_ID}",
        "",
        "\U0001F514 <b>Resolvido:</b> {EVENT.NAME}",
        "\U0001F552 <b>Quando:</b> {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}",
    ])
    return problema, recuperacao


MEDIA_NAME_TELEGRAM = "Telegram (cam-snapshot)"


def _slug_site(valor: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _text(valor).lower()).strip("-") or "site"


def _usuario_do_site(url: str, auth: str, tenant: str, site: str, chat: str, mediatypeid: str) -> str:
    """Usuario Zabbix cujo destino e o chat daquele site."""
    alias = f"sightops.telegram.{tenant}.{_slug_site(site)}"[:100]
    achado = _call(url, "user.get", {"filter": {"username": [alias]}, "output": ["userid"]}, auth, 400) or []
    medias = [{
        "mediatypeid": mediatypeid, "sendto": chat, "active": 0,
        "severity": 63, "period": "1-7,00:00-24:00",
    }]
    if achado:
        uid = _text(achado[0].get("userid"))
        _call(url, "user.update", {"userid": uid, "medias": medias}, auth, 401)
        return uid

    papeis = _call(url, "role.get", {"output": ["roleid", "name"]}, auth, 402) or []
    roleid = next((_text(r.get("roleid")) for r in papeis
                   if _text(r.get("name")).lower() == "super admin role"), "3")
    grupos = _call(url, "usergroup.get", {"output": ["usrgrpid", "name"]}, auth, 403) or []
    usrgrpid = next((_text(g.get("usrgrpid")) for g in grupos
                     if _text(g.get("name")).lower() == "zabbix administrators"),
                    _text((grupos or [{}])[0].get("usrgrpid")))
    criado = _call(url, "user.create", [{
        "username": alias, "name": "SightOps", "surname": site[:60] or "Telegram",
        "passwd": "ChangeMe_12345!", "roleid": roleid,
        "usrgrps": [{"usrgrpid": usrgrpid}] if usrgrpid else [],
        "medias": medias,
    }], auth, 404) or {}
    return _text((criado.get("userids") or [""])[0])


def _configurar_telegram_por_site(
    url: str, auth: str, tenant: str, cfg: Dict[str, Any],
    grupos_site: Dict[str, str], entity_types: Iterable[str],
) -> Dict[str, Any]:
    """Cria/atualiza uma acao por (tipo, site) com chat configurado."""
    chats = cfg.get("tg_chat_by_site") if isinstance(cfg.get("tg_chat_by_site"), dict) else {}
    if not chats:
        return {"acoes": 0, "motivo": "nenhum site com chat configurado"}

    midias = _call(url, "mediatype.get",
                   {"filter": {"name": [MEDIA_NAME_TELEGRAM]}, "output": ["mediatypeid"]}, auth, 405) or []
    if not midias:
        return {"acoes": 0,
                "motivo": f"tipo de midia '{MEDIA_NAME_TELEGRAM}' nao existe; "
                          "sincronize as cameras uma vez para cria-lo"}
    mediatypeid = _text(midias[0].get("mediatypeid"))

    feitas = 0
    for entity_type in entity_types:
        problema, recuperacao = _mensagens_telegram(_text(entity_type).lower())
        for site, chat in sorted(chats.items()):
            site = " ".join(_text(site).split()).strip()
            chat = _text(chat).strip()
            nome_grupo = f"SIGHTOPS - {tenant.upper()} - {_text(entity_type).upper()}/{site}"
            gid = grupos_site.get(nome_grupo.lower())
            if not site or not chat or not gid:
                continue          # site sem chat, ou sem equipamento deste tipo
            try:
                uid = _usuario_do_site(url, auth, tenant, site, chat, mediatypeid)
                if not uid:
                    continue
                nome_acao = f"{nome_grupo} -> Telegram (SightOps)"
                existente = _call(url, "action.get",
                                  {"filter": {"name": [nome_acao]}, "output": ["actionid"]}, auth, 406) or []
                params = {
                    "name": nome_acao, "eventsource": 0, "status": 0, "esc_period": "1m",
                    "filter": {"evaltype": 0, "conditions": [
                        {"conditiontype": 0, "operator": 0, "value": gid}]},
                    "operations": [{"operationtype": 0, "opmessage": {
                        "default_msg": 0, "mediatypeid": mediatypeid, "message": problema},
                        "opmessage_usr": [{"userid": uid}]}],
                    "recovery_operations": [{"operationtype": 0, "opmessage": {
                        "default_msg": 0, "mediatypeid": mediatypeid, "message": recuperacao},
                        "opmessage_usr": [{"userid": uid}]}],
                }
                if existente:
                    params["actionid"] = _text(existente[0].get("actionid"))
                    _call(url, "action.update", params, auth, 407)
                else:
                    _call(url, "action.create", params, auth, 408)
                feitas += 1
            except Exception:
                # um site com chat invalido nao pode impedir os outros
                continue
    return {"acoes": feitas, "motivo": ""}


def sync_monitoring_to_zabbix(entity_types: tuple[str, ...] = ("olt", "onu", "camera", "nvr", "dvr", "connector", "access_device", "whatsapp")) -> Dict[str, Any]:
    settings = load_app_settings()
    raw_cfg = settings.get("zabbix_ip_sync") if isinstance(settings.get("zabbix_ip_sync"), dict) else {}
    cfg = _default_zabbix_cfg(raw_cfg)
    url = _api_url(cfg.get("url"))
    user = _text(cfg.get("user"))
    password = _text(cfg.get("pass") or cfg.get("password"))
    if not (url and user and password):
        return {"ok": False, "error": "Zabbix nao configurado automaticamente."}

    tenant = _text(get_current_tenant_slug() or "default").lower()
    entities: List[Dict[str, Any]] = []
    for entity_type in entity_types:
        entities.extend(list_entities(entity_type=entity_type, limit=2000))

    auth = _text(_call(url, "user.login", {"username": user, "password": password}, req_id=1))
    technical_names = {_host_key(tenant, row): row for row in entities}
    current_hosts = _call(
        url, "host.get",
        {"output": ["hostid", "host", "name"], "search": {"host": f"SIGHTOPS.{tenant}."}, "startSearch": True},
        auth, 30,
    ) or []

    # Remove hosts orfaos mesmo quando `entities` fica vazio (ex: todas as ONUs
    # de um tenant foram excluidas).
    orphan_hostids = find_orphan_hostids(current_hosts, technical_names, tenant, entity_types)
    if orphan_hostids:
        _call(url, "host.delete", orphan_hostids, auth, 20)

    if not entities:
        return {
            "ok": True, "tenant": tenant, "total": 0, "created_hosts": 0, "created_items": 0,
            "pushed": 0, "removed_hosts": len(orphan_hostids),
        }

    group_ids = {
        entity_type: _ensure_group(url, auth, f"SIGHTOPS - {tenant.upper()} - {entity_type.upper()}", 10 + idx * 4)
        for idx, entity_type in enumerate(entity_types)
    }

    # Grupo por site: e o que permite filtrar e mandar Telegram por site. Os
    # subgrupos ja existiam de uma versao antiga, com hosts congelados dentro --
    # aqui eles voltam a ser preenchidos.
    _grupo_site_cache: Dict[str, str] = {}

    def _grupo_do_site(entity_type: str, site: str) -> str:
        site = " ".join(_text(site).split()).strip()
        if not site:
            return ""
        nome = f"SIGHTOPS - {tenant.upper()} - {entity_type.upper()}/{site}"
        if nome.lower() not in _grupo_site_cache:
            try:
                _grupo_site_cache[nome.lower()] = _ensure_group(url, auth, nome, 200 + len(_grupo_site_cache))
            except Exception:
                _grupo_site_cache[nome.lower()] = ""
        return _grupo_site_cache[nome.lower()]

    def _grupos_do_host(entity_type: str, site: str) -> List[Dict[str, str]]:
        ids = [group_ids[entity_type]]
        gid_site = _grupo_do_site(entity_type, site)
        if gid_site:
            ids.append(gid_site)
        return [{"groupid": g} for g in dict.fromkeys(ids) if g]
    host_ids = {_text(row.get("host")): _text(row.get("hostid")) for row in current_hosts if _text(row.get("host")) in technical_names}

    create_hosts: List[Dict[str, Any]] = []
    missing_names: List[str] = []
    for technical_name, row in technical_names.items():
        if technical_name in host_ids:
            continue
        entity_type = _text(row.get("entity_type"))
        display_name = _text(row.get("display_name")) or technical_name
        site = _text(row.get("site"))
        visible_name = f"{display_name} - {site} - {technical_name.rsplit('.', 1)[-1][:6]}"
        missing_names.append(technical_name)
        create_hosts.append({
            "host": technical_name,
            "name": visible_name,
            "groups": _grupos_do_host(entity_type, site),
            "macros": _macros_da_entidade(row),
            "tags": [
                {"tag": "sightops_tenant", "value": tenant},
                {"tag": "sightops_type", "value": entity_type},
                {"tag": "sightops_key", "value": _text(row.get("entity_key"))},
                {"tag": "site", "value": site},
            ],
        })
    cursor = 0
    for batch in _chunks(create_hosts):
        created = _call(url, "host.create", batch, auth, 40 + cursor) or {}
        ids = created.get("hostids") or []
        for technical_name, hostid in zip(missing_names[cursor:cursor + len(batch)], ids):
            host_ids[technical_name] = _text(hostid)
        cursor += len(batch)

    # Host que ja existia nunca era tocado de novo -- por isso os 476 estavam sem
    # macro nenhuma. Atualiza grupos e macros de quem ja esta la.
    atualizados = 0
    for technical_name, row in technical_names.items():
        hostid = host_ids.get(technical_name)
        if not hostid or technical_name in missing_names:
            continue
        try:
            _call(url, "host.update", {
                "hostid": hostid,
                "groups": _grupos_do_host(_text(row.get("entity_type")), _text(row.get("site"))),
                "macros": _macros_da_entidade(row),
            }, auth, 300)
            atualizados += 1
        except Exception:
            # um host com problema nao pode parar os outros
            continue

    telegram = _configurar_telegram_por_site(
        url, auth, tenant, cfg, _grupo_site_cache, entity_types)

    all_hostids = [host_ids[name] for name in technical_names if host_ids.get(name)]
    wanted_keys = ["sightops.status", "sightops.onu_rx", "sightops.olt_rx", "sightops.distance"]
    items = _call(
        url, "item.get",
        {"output": ["itemid", "hostid", "key_"], "hostids": all_hostids, "filter": {"key_": wanted_keys}},
        auth, 100,
    ) or []
    item_by_host_key = {(_text(row.get("hostid")), _text(row.get("key_"))): _text(row.get("itemid")) for row in items}
    item_specs = {
        "sightops.status": ("SightOps - Estado operacional", 3, "1=up, 0=down, 2=instavel, 3=desconhecido, 4=manutencao"),
        "sightops.onu_rx": ("SightOps - ONU RX", 0, "Potencia recebida pela ONU em dBm"),
        "sightops.olt_rx": ("SightOps - OLT RX", 0, "Potencia recebida pela OLT em dBm"),
        "sightops.distance": ("SightOps - Distancia", 0, "Distancia da ONU em km"),
    }
    create_items = []
    for technical_name, row in technical_names.items():
        hostid = host_ids.get(technical_name, "")
        keys = ["sightops.status"] + (["sightops.onu_rx", "sightops.olt_rx", "sightops.distance"] if row.get("entity_type") == "onu" else [])
        for key in keys:
            if (hostid, key) in item_by_host_key:
                continue
            name, value_type, description = item_specs[key]
            create_items.append({"hostid": hostid, "name": name, "key_": key, "type": 2, "value_type": value_type, "delay": "0", "history": "30d", "trends": "365d", "description": description})
    cursor = 0
    missing_item_keys = [(row["hostid"], row["key_"]) for row in create_items]
    for batch in _chunks(create_items):
        created = _call(url, "item.create", batch, auth, 110 + cursor) or {}
        ids = created.get("itemids") or []
        for host_key, itemid in zip(missing_item_keys[cursor:cursor + len(batch)], ids):
            item_by_host_key[host_key] = _text(itemid)
        cursor += len(batch)

    status_value = {"up": "1", "down": "0", "unstable": "2", "unknown": "3", "maintenance": "4"}
    push_rows = []
    links = []
    for technical_name, row in technical_names.items():
        hostid = host_ids.get(technical_name, "")
        itemid = item_by_host_key.get((hostid, "sightops.status"), "")
        if hostid:
            links.append((hostid, _text(row.get("entity_key"))))
        if itemid:
            push_rows.append({"itemid": itemid, "value": status_value.get(_text(row.get("status")), "3")})
        try:
            detail = json.loads(_text(row.get("detail_json")) or "{}")
        except Exception:
            detail = {}
        for key, value in (
            ("sightops.onu_rx", _number(detail.get("onu_rx"))),
            ("sightops.olt_rx", _number(detail.get("olt_rx"))),
            ("sightops.distance", _number(detail.get("distance_km"))),
        ):
            metric_itemid = item_by_host_key.get((hostid, key), "")
            if metric_itemid and value is not None:
                push_rows.append({"itemid": metric_itemid, "value": str(value)})
    pushed = 0
    for batch in _chunks(push_rows, 200):
        result = _call(url, "history.push", batch, auth, 200 + pushed) or {}
        pushed += int(result.get("response") == "success") * len(batch) if isinstance(result, dict) else len(batch)

    with _conn() as connection:
        for hostid, entity_key in links:
            connection.execute(
                "UPDATE monitoring_entities SET zabbix_hostid=? WHERE tenant_slug=? AND entity_key=?",
                (hostid, tenant, entity_key),
            )
    return {
        "ok": True, "tenant": tenant, "total": len(entities),
        "groups": len(group_ids) + len(_grupo_site_cache), "hosts_atualizados": atualizados,
        "acoes_telegram": telegram["acoes"], "telegram_motivo": telegram["motivo"],
        "created_hosts": len(create_hosts), "linked_hosts": len(host_ids),
        "created_items": len(create_items), "pushed": pushed, "removed_hosts": len(orphan_hostids),
    }
