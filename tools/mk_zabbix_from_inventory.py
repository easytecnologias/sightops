#!/usr/bin/env python3
import json, os, re, sys, time, requests
from typing import Any, Optional, Dict, List

INV_PATH = os.getenv("INV_PATH", "data/cam-inventory.json")
# Prefixa o nome tecnico de todo host no Zabbix. Sem isso, dois clientes com
# a mesma camera de IP privado repetido (comum em SaaS -- ver o caso real
# SIERRA/PERUCABA em 192.168.20.0/24) colidiam no MESMO host "CAM-{ip}": um
# sincronismo sobrescrevia titulo/local/foto do outro cliente silenciosamente.
# Bancos ja sao isolados por tenant; o Zabbix precisa da mesma garantia.
ZBX_TENANT = os.getenv("ZBX_TENANT", "default").strip().lower() or "default"
ZBX_PRUNE = os.getenv("ZBX_PRUNE", "0").strip() == "1"
# Acima deste percentual do grupo, a poda para em vez de apagar.
# 100 desliga a trava (limpeza em massa deliberada).
ZBX_PRUNE_MAX_PCT = float(os.getenv("ZBX_PRUNE_MAX_PCT", "20") or 20)
ZBX_PRUNE_MIN_ABS = int(os.getenv("ZBX_PRUNE_MIN_ABS", "5") or 5)
ZBX_LEGACY_DEFAULT_HOSTNAMES = os.getenv("ZBX_LEGACY_DEFAULT_HOSTNAMES", "0").strip() == "1"
ZBX_URL  = os.getenv("ZBX_URL","").strip()
ZBX_USER = os.getenv("ZBX_USER","").strip()
ZBX_PASS = os.getenv("ZBX_PASS","").strip()
ZBX_GROUP = os.getenv("ZBX_GROUP","Cameras").strip() or "Cameras"
ZBX_TEMPLATE = os.getenv("ZBX_TEMPLATE","Template Module ICMP Ping").strip() or "Template Module ICMP Ping"
ZBX_TEMPLATE_DVR = os.getenv("ZBX_TEMPLATE_DVR", "Template Cam-Snapshot DVR Channel").strip() or "Template Cam-Snapshot DVR Channel"
ZBX_DVR_USER = os.getenv("ZBX_DVR_USER", "admin").strip() or "admin"
ZBX_DVR_PASS = os.getenv("ZBX_DVR_PASS", "").strip()

TG_AUTO = os.getenv("ZBX_TG_AUTO","0").strip() == "1"
TG_TOKEN = os.getenv("ZBX_TG_TOKEN","").strip()
TG_CHAT  = os.getenv("ZBX_TG_CHAT","").strip()
# {"INTERBLOCOS": "-100123...", "JARDINS I": "-100456..."}
# Site que nao estiver aqui nao ganha acao: nada dispara sem configuracao.
try:
    TG_CHAT_BY_SITE = json.loads(os.getenv("ZBX_TG_CHAT_BY_SITE", "") or "{}")
    if not isinstance(TG_CHAT_BY_SITE, dict):
        TG_CHAT_BY_SITE = {}
except Exception:
    TG_CHAT_BY_SITE = {}
TG_RELAY_URL = os.getenv("ZBX_TG_RELAY_URL","").strip()
TG_RELAY_KEY = os.getenv("ZBX_TG_RELAY_KEY","").strip()
ZBX_TG_TIMEZONE = os.getenv("ZBX_TG_TIMEZONE", "America/Sao_Paulo").strip() or "America/Sao_Paulo"

WINDOWS_SERVICE_NAME_NOT_MATCHES = (
    r"^(?:RemoteRegistry|MMCSS|gupdate|gupdatem|GoogleUpdate.*|GoogleUpdater.*|"
    r"SysmonLog|clr_optimization_v.+|sppsvc|gpsvc|Pml Driver HPZ12|"
    r"Net Driver HPZ12|MapsBroker|IntelAudioService|Intel\(R\) TPM Provisioning Service|"
    r"dbupdate|DoSvc|CDPUserSvc_.+|WpnUserService_.+|OneSyncSvc_.+|WbioSrvc|BITS|"
    r"tiledatamodelsvc|GISvc|ShellHWDetection|TrustedInstaller|TabletInputService|"
    r"CDPSvc|wuauserv|edgeupdate|edgeupdatem|cbdhsvc_.+|SIMNextLocalRecording)$"
)

MEDIA_NAME = "Telegram (cam-snapshot)"
ACTION_NAME_LEGACY_IP = "Cameras IP -> Telegram (cam-snapshot)"
ACTION_NAME_LEGACY_DVR = "DVR -> Telegram (cam-snapshot)"
ACTION_NAME_LEGACY_WINDOWS = "Computadores Windows -> Telegram (cam-snapshot)"


def _slug_name(v: str) -> str:
    s = str(v or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", ".", s)
    s = re.sub(r"\.+", ".", s).strip(".")
    return s or "default"


def _host_safe(v: str) -> str:
    s = str(v or "").strip().upper()
    s = re.sub(r"[^A-Z0-9_.-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "HOST"


def build_host_name(tenant: str, row: Dict[str, Any]) -> str:
    """Nome tecnico do host no Zabbix -- sempre prefixado pelo tenant.

    Duas cameras de clientes diferentes podem ter o mesmo IP (endereco
    privado, comum em SaaS). Sem o prefixo de tenant, elas colidiam no MESMO
    host "CAM-{ip}" e cada sincronismo sobrescrevia titulo/local/foto do
    cliente anterior. Com o prefixo, cada cliente tem seu proprio host mesmo
    com IP identico -- e sincronizar de novo o MESMO cliente continua
    atualizando o host dele normalmente (upsert por nome, e o nome agora
    inclui o tenant), que e o unico caso em que sobrescrever esta certo.
    """
    tenant_prefix = _host_safe(tenant or "default")
    ip = str(row.get("ip") or "").strip()
    host_key = str(row.get("host_key") or "").strip()
    source = str(row.get("source") or "").strip().lower()
    channel = str(row.get("channel") or "").strip()
    if tenant_prefix == "DEFAULT" and ZBX_LEGACY_DEFAULT_HOSTNAMES:
        if host_key:
            return _host_safe(host_key)
        if source == "dvr" and channel:
            return f"DVR-{ip}-CH{channel}"
        if source == "windows":
            hostname = str(
                row.get("hostname") or row.get("host")
                or row.get("titulo") or row.get("title") or row.get("nome") or ip
            ).strip()
            return f"WIN-{_host_safe(hostname)}"
        return f"CAM-{ip}"
    if host_key:
        return f"{tenant_prefix}-{_host_safe(host_key)}"
    if source == "dvr" and channel:
        return f"{tenant_prefix}-DVR-{ip}-CH{channel}"
    if source == "windows":
        hostname = str(
            row.get("hostname") or row.get("host")
            or row.get("titulo") or row.get("title") or row.get("nome") or ip
        ).strip()
        return f"{tenant_prefix}-WIN-{_host_safe(hostname)}"
    return f"{tenant_prefix}-CAM-{ip}"


def build_visible_name(tenant: str, row: Dict[str, Any], title: str) -> str:
    """Nome exibido no Zabbix tambem precisa ser unico em SaaS.

    O `host` tecnico ja e tenant-aware, mas o Zabbix tambem exige `name`
    unico. Muitos clientes usam os mesmos titulos genericos ("IP CAMERA",
    o proprio IP, "Camera 01"), entao o nome visivel inclui tenant e IP/canal.
    """
    tenant_prefix = _host_safe(tenant or "default")
    ip = str(row.get("ip") or "").strip()
    source = str(row.get("source") or "").strip().lower()
    channel = str(row.get("channel") or "").strip()
    base = str(title or ip or row.get("host_key") or "Camera").strip()
    suffix = f"CH{channel} {ip}" if source == "dvr" and channel else ip
    if tenant_prefix == "DEFAULT" and ZBX_LEGACY_DEFAULT_HOSTNAMES:
        return f"{base} ({suffix})" if suffix and suffix not in base else base
    return f"[{tenant_prefix}] {base} ({suffix})" if suffix and suffix not in base else f"[{tenant_prefix}] {base}"


GROUP_SLUG = _slug_name(ZBX_GROUP)
USER_ALIAS = f"telegram.cam-snapshot.{GROUP_SLUG}"
ACTION_NAME_GROUP = f"{ZBX_GROUP} -> Telegram (cam-snapshot)"
ACTION_NAME_WINDOWS = f"{ZBX_GROUP} -> Telegram Windows (cam-snapshot)"


def _google_maps_url(lat_val: Any, lon_val: Any) -> str:
    try:
        lat = float(str(lat_val).strip().replace(",", "."))
        lon = float(str(lon_val).strip().replace(",", "."))
        return f"https://www.google.com/maps?q={lat},{lon}"
    except Exception:
        return ""

def api(method: str, params: Any, auth: Optional[str]=None, _id=[0]) -> Any:
    _id[0]+=1
    payload={"jsonrpc":"2.0","method":method,"params":params,"id":_id[0]}
    if auth: payload["auth"]=auth
    r=requests.post(ZBX_URL, json=payload, timeout=30)
    r.raise_for_status()
    j=r.json()
    if "error" in j:
        raise RuntimeError(f"{method}: {j['error']}")
    return j["result"]

def login() -> str:
    return api("user.login", {"username": ZBX_USER, "password": ZBX_PASS})

def ensure_hostgroup(auth: str, name: str) -> str:
    res = api("hostgroup.get", {"filter":{"name":[name]}}, auth)
    if res: return res[0]["groupid"]
    return api("hostgroup.create", {"name": name}, auth)["groupids"][0]

def get_template_id(auth: str, name: str) -> str:
    res = api("template.get", {"filter":{"host":[name]}}, auth)
    if not res:
        raise RuntimeError(f"Template não encontrado: {name}")
    return res[0]["templateid"]


def try_get_template_id(auth: str, name: str) -> str:
    nm = str(name or "").strip()
    if not nm:
        return ""
    try:
        res = api("template.get", {"filter": {"host": [nm]}, "output": ["templateid", "host", "name"]}, auth)
        if res:
            return str(res[0]["templateid"])
    except Exception:
        pass
    try:
        res = api("template.get", {"filter": {"name": [nm]}, "output": ["templateid", "host", "name"]}, auth)
        if res:
            return str(res[0]["templateid"])
    except Exception:
        pass
    return ""


def resolve_base_template_id(auth: str, requested_name: str) -> tuple[str, str]:
    rid = try_get_template_id(auth, requested_name)
    if rid:
        return rid, str(requested_name or "").strip()

    candidates = [
        "Template Module ICMP Ping",
        "ICMP Ping",
        "Template ICMP Ping",
        "Template Net Network Generic Device by ICMP",
    ]
    for nm in candidates:
        tid = try_get_template_id(auth, nm)
        if tid:
            return tid, nm

    try:
        res = api(
            "template.get",
            {
                "search": {"host": "ICMP"},
                "output": ["templateid", "host", "name"],
                "searchByAny": True,
                "sortfield": "host",
                "limit": 50,
            },
            auth,
        )
        for t in (res or []):
            host = str(t.get("host") or "").strip()
            tid = str(t.get("templateid") or "").strip()
            if host and tid:
                return tid, host
    except Exception:
        pass

    return "", ""

_SITE_GROUP_CACHE: Dict[str, str] = {}


def ensure_site_group(auth: str, grupo_base: str, site: str) -> str:
    """Devolve o groupid de "<grupo_base>/<SITE>", criando se preciso.

    Procura sem diferenciar maiusculas para reaproveitar um grupo ja existente:
    o Zabbix aceita "SANTANA" e "Santana" como grupos distintos, e foi assim que
    nasceram os duplicados que existem hoje.
    """
    nome_site = " ".join(str(site or "").split()).strip()
    if not nome_site or not grupo_base:
        return ""
    alvo = f"{grupo_base}/{nome_site}"
    chave = alvo.lower()
    if chave in _SITE_GROUP_CACHE:
        return _SITE_GROUP_CACHE[chave]

    existentes = api("hostgroup.get", {"output": ["groupid", "name"],
                                       "search": {"name": grupo_base + "/"},
                                       "startSearch": True}, auth) or []
    for g in existentes:
        if str(g.get("name") or "").strip().lower() == chave:
            _SITE_GROUP_CACHE[chave] = str(g["groupid"])
            return _SITE_GROUP_CACHE[chave]

    novo = api("hostgroup.create", {"name": alvo}, auth)
    gid = str((novo.get("groupids") or [""])[0])
    _SITE_GROUP_CACHE[chave] = gid
    print(f"grupo de site criado: {alvo}")
    return gid


def get_host(auth: str, host: str):
    res = api("host.get", {"filter":{"host":[host]}}, auth)
    return res[0] if res else None

def host_upsert(
    auth: str,
    host: str,
    visible_name: str,
    ip: str,
    groupids: List[str],
    templateids: List[str],
    macros: Dict[str,str],
) -> tuple[str, str]:
    iface=[{"type":1,"main":1,"useip":1,"ip":ip,"dns":"","port":"10050"}]
    macro_list=[{"macro":k,"value":v} for k,v in macros.items()]
    tpl_links=[{"templateid": tid} for tid in dict.fromkeys([str(t).strip() for t in (templateids or []) if str(t).strip()])]
    group_links=[{"groupid": gid} for gid in dict.fromkeys([str(g).strip() for g in (groupids or []) if str(g).strip()])]
    existing=get_host(auth, host)
    if not existing:
        payload = {
            "host": host,
            "name": visible_name,
            "interfaces": iface,
            "groups": group_links,
            "macros": macro_list
        }
        if tpl_links:
            payload["templates"] = tpl_links
        r = api("host.create", payload, auth)
        hostid = str((r.get("hostids") or [""])[0])
        return "created", hostid
    # IMPORTANT:
    # Do not update host interfaces for an existing host.
    # In Zabbix, interfaces can be linked to items (e.g. net.tcp.service items).
    # Updating interfaces on an existing host may fail with:
    # "Interface is linked to item ...".
    # For existing hosts we only update name/groups/templates/macros.
    payload_u = {
        "hostid": existing["hostid"],
        "name": visible_name,
        "groups": group_links,
        "macros": macro_list
    }
    if tpl_links:
        payload_u["templates"] = tpl_links
    api("host.update", payload_u, auth)
    return "updated", str(existing["hostid"])


def ensure_template_group(auth: str, name: str = "Templates") -> str:
    try:
        res = api("templategroup.get", {"filter": {"name": [name]}}, auth)
        if res:
            return str(res[0]["groupid"])
        cr = api("templategroup.create", {"name": name}, auth)
        gids = cr.get("groupids") or []
        if gids:
            return str(gids[0])
    except Exception:
        pass
    return ensure_hostgroup(auth, name)


def ensure_dvr_channel_template(auth: str, name: str) -> str:
    res = api("template.get", {"filter": {"host": [name]}}, auth)
    if res:
        tpl_id = str(res[0]["templateid"])
    else:
        tg_id = ensure_template_group(auth, "Templates")
        cr = api("template.create", {"host": name, "groups": [{"groupid": tg_id}]}, auth)
        tpl_id = str((cr.get("templateids") or [""])[0])

    raw_key = "dvr.videoloss.raw"
    snap_probe_key = "dvr.snapshot.probe"

    def ensure_http_item(key_: str, item_name: str, url: str, retrieve_mode: int, timeout: str = "10s") -> None:
        payload = {
            "name": item_name,
            "key_": key_,
            "type": 19,  # HTTP agent
            "value_type": 4,  # text
            "delay": "30s",
            "url": url,
            "request_method": 0,
            "retrieve_mode": int(retrieve_mode),
            "follow_redirects": 1,
            "timeout": timeout,
            "authtype": 4,  # digest
            "username": "{$DVR_USER}",
            "password": "{$DVR_PASS}",
        }
        found = api("item.get", {"hostids": [tpl_id], "filter": {"key_": [key_]}, "output": ["itemid"]}, auth)
        if not found:
            p = dict(payload)
            p["hostid"] = tpl_id
            api("item.create", p, auth)
        else:
            p = dict(payload)
            p["itemid"] = str(found[0]["itemid"])
            api("item.update", p, auth)

    ensure_http_item(
        raw_key,
        "DVR VideoLoss Raw",
        "{$DVR_HTTP_URL}/cgi-bin/eventManager.cgi?action=getEventIndexes&code=VideoLoss",
        retrieve_mode=0,
        timeout="10s",
    )
    ensure_http_item(
        snap_probe_key,
        "DVR Snapshot Probe",
        "{$DVR_HTTP_URL}/cgi-bin/snapshot.cgi?channel={$DVR_CH}",
        retrieve_mode=0,
        timeout="10s",
    )

    trig_name = "Canal DVR offline ({HOST.NAME})"
    expr = (
        f'find(/{name}/{raw_key},,"regexp","channels\\\\[[0-9]+\\\\]={{$DVR_CH_INDEX}}(\\\\D|$)")=1'
        f' or nodata(/{name}/{snap_probe_key},2m)=1'
    )
    trig = api("trigger.get", {"hostids": [tpl_id], "filter": {"description": [trig_name]}, "output": ["triggerid"]}, auth)
    if not trig:
        api(
            "trigger.create",
            {
                "description": trig_name,
                "expression": expr,
                "priority": 3,
            },
            auth,
        )
    else:
        api(
            "trigger.update",
            {
                "triggerid": str(trig[0]["triggerid"]),
                "expression": expr,
                "priority": 3,
            },
            auth,
        )
    return tpl_id


def push_dvr_channel_state(auth: str, hostid: str, status_text: str) -> None:
    s = str(status_text or "").strip().lower()
    if s == "online":
        state = 1
    elif s in ("sem_camera", "sem camera", "no_camera", "no camera"):
        state = 2
    else:
        state = 0
    now = int(time.time())

    items = api(
        "item.get",
        {
            "hostids": [hostid],
            "filter": {"key_": ["cam.channel.state", "cam.channel.state.text"]},
            "output": ["itemid", "key_"],
        },
        auth,
    )
    if not items:
        return

    values = []
    for it in items:
        key_ = str(it.get("key_") or "")
        iid = str(it.get("itemid") or "")
        if not iid:
            continue
        if key_ == "cam.channel.state":
            values.append({"itemid": iid, "value": str(state), "clock": now})
        elif key_ == "cam.channel.state.text":
            values.append({"itemid": iid, "value": s or "offline", "clock": now})
    if values:
        api("history.push", values, auth)

def ensure_telegram_mediatype(auth: str, token: str, chat_id: str) -> str:
    res = api("mediatype.get", {"filter":{"name":[MEDIA_NAME]}}, auth)
    webhook_script = r'''
    var params = JSON.parse(value);
    
    var Telegram = {
      token: params.api_token,
      parse_mode: params.api_parse_mode || 'HTML',
    
      request: function (method, payload) {
        var url = 'https://api.telegram.org/bot' + Telegram.token + '/' + method;
        var req = new HttpRequest();
        req.addHeader('Content-Type: application/json');
    
        var body = JSON.stringify(payload);
        var resp = req.post(url, body);
        var code = req.getStatus();
    
        if (code < 200 || code >= 300) {
          throw 'Telegram API HTTP ' + code + ': ' + resp;
        }
    
        var obj;
        try { obj = JSON.parse(resp); } catch (e) {
          throw 'Telegram API returned non-JSON: ' + resp;
        }
    
        if (!obj.ok) {
          throw 'Telegram API error: ' + (obj.description || resp);
        }
    
        return obj;
      },
    
      sendMessage: function (chat_id, text) {
        return Telegram.request('sendMessage', {
          chat_id: chat_id,
          text: text,
          parse_mode: Telegram.parse_mode,
          disable_web_page_preview: true
        });
      },
    
      sendPhoto: function (chat_id, photo_url, caption) {
        if (caption && caption.length > 1024) {
          caption = caption.substring(0, 1000) + '...';
        }
        var payload = {
          chat_id: chat_id,
          photo: photo_url,
          caption: caption || '',
          parse_mode: Telegram.parse_mode
        };
        if (params.map_url && String(params.map_url).indexOf('http') === 0) {
          payload.reply_markup = JSON.stringify({
            inline_keyboard: [[{ text: 'Abrir no Google Maps', url: String(params.map_url) }]]
          });
        }
        return Telegram.request('sendPhoto', payload);
      }
    };
    
    try {
      var chat = params.sendto || params.chat_id || params.chatid || params.to;
      if (!chat) {
        throw 'missing chat_id (sendto)';
      }
    
      var subject = (params.subject !== undefined && params.subject !== null) ? String(params.subject) : '';
      var message = (params.message !== undefined && params.message !== null) ? String(params.message) : '';
      var text = (subject ? subject + "\n" : "") + message;
    
      var snap = (params.snapshot_url !== undefined && params.snapshot_url !== null) ? String(params.snapshot_url) : '';
      // fallback: try to find URL in text
      var m = text.match(/https?:\/\/\S+/);
      if (!snap && m) { snap = m[0]; }
    
      var relayUrl = (params.relay_url !== undefined && params.relay_url !== null) ? String(params.relay_url).trim() : '';
      var relayKey = (params.relay_key !== undefined && params.relay_key !== null) ? String(params.relay_key).trim() : '';
      if (relayUrl) {
        try {
          var relayReq = new HttpRequest();
          relayReq.addHeader('Content-Type: application/json');
          var relayPayload = {
            token: Telegram.token,
            chat_id: chat,
            text: text,
            snapshot_url: snap,
            map_url: (params.map_url !== undefined && params.map_url !== null) ? String(params.map_url) : '',
            parse_mode: Telegram.parse_mode,
            relay_key: relayKey
          };
          var relayResp = relayReq.post(relayUrl, JSON.stringify(relayPayload));
          var relayCode = relayReq.getStatus();
          if (relayCode >= 200 && relayCode < 300) {
            return 'OK';
          }
          throw 'relay HTTP ' + relayCode + ': ' + relayResp;
        } catch (eRelay) {
          throw 'relay failed: ' + eRelay;
        }
      }

      if (snap && snap.indexOf('http') === 0) {
        // remove url from caption if it was embedded
        if (m) { text = text.replace(m[0], '').replace(/\n{3,}/g, "\n\n").trim(); }
        Telegram.sendPhoto(chat, snap, text);
      } else {
        // Fallback seguro: envia texto quando nao houver snapshot publico.
        Telegram.sendMessage(chat, text || 'Alerta de camera');
      }
    
      return 'OK';
    } catch (e) {
      throw 'Telegram webhook failed: ' + e;
    }
'''
    if not res:
        created = api("mediatype.create", [{
            "name": MEDIA_NAME,
            "type": 4,
            "parameters": [
                {"name": "api_token", "value": token},
                {"name": "api_parse_mode", "value": "HTML"},
                {"name": "sendto", "value": "{ALERT.SENDTO}"},
                {"name": "subject", "value": "{ALERT.SUBJECT}"},
                {"name": "message", "value": "{ALERT.MESSAGE}"},
                {"name": "snapshot_url", "value": "{$CAM_SNAPSHOT_URL}"},
                {"name": "map_url", "value": "{$CAM_MAP_URL}"},
                {"name": "relay_url", "value": TG_RELAY_URL},
                {"name": "relay_key", "value": TG_RELAY_KEY}
            ],
            "script": webhook_script
        }], auth)
        return created["mediatypeids"][0]
    mtid = res[0]["mediatypeid"]
    api("mediatype.update", {
        "mediatypeid": mtid,
        "parameters": [
            {"name": "api_token", "value": token},
            {"name": "api_parse_mode", "value": "HTML"},
            {"name": "sendto", "value": "{ALERT.SENDTO}"},
            {"name": "subject", "value": "{ALERT.SUBJECT}"},
            {"name": "message", "value": "{ALERT.MESSAGE}"},
            {"name": "snapshot_url", "value": "{$CAM_SNAPSHOT_URL}"},
            {"name": "map_url", "value": "{$CAM_MAP_URL}"},
            {"name": "relay_url", "value": TG_RELAY_URL},
            {"name": "relay_key", "value": TG_RELAY_KEY}
        ],
        "script": webhook_script
    }, auth)
    return mtid

def ensure_user_with_media(auth: str, mediatypeid: str, chatid: str, alias: str = "") -> str:
    """Usuario Zabbix cujo `sendto` e o chat do Telegram.

    O alias e parametro porque agora ha um usuario por site: o chat vive no
    usuario, entao cada destino precisa do seu.
    """
    alias = (alias or USER_ALIAS).strip() or USER_ALIAS
    res = api("user.get", {"filter":{"username":[alias]}}, auth)
    roles = api("role.get", {"output": ["roleid", "name"]}, auth)
    roleid = "3"
    for r in (roles or []):
        if str(r.get("name") or "").strip().lower() == "super admin role":
            roleid = str(r.get("roleid") or roleid)
            break

    groups = api("usergroup.get", {"output":["usrgrpid","name"]}, auth)
    usrgrpid = None
    for g in (groups or []):
        if str(g.get("name") or "").strip().lower() == "zabbix administrators":
            usrgrpid = g.get("usrgrpid")
            break
    if not usrgrpid and groups:
        usrgrpid = groups[0]["usrgrpid"]

    user_medias=[{
        "mediatypeid": mediatypeid,
        "sendto": chatid,
        "active": 0,
        "severity": 63,
        "period": "1-7,00:00-24:00"
    }]
    if not res:
        created = api("user.create", [{
            "username": alias,
            "name": "Telegram",
            "surname": "cam-snapshot",
            "passwd": "ChangeMe_12345!",
            "roleid": roleid,
            "timezone": ZBX_TG_TIMEZONE,
            "usrgrps": [{"usrgrpid": usrgrpid}] if usrgrpid else [],
            "medias": user_medias
        }], auth)
        return created["userids"][0]
    uid = res[0]["userid"]
    payload = {
        "userid": uid,
        "roleid": roleid,
        "timezone": ZBX_TG_TIMEZONE,
        "medias": user_medias,
    }
    if usrgrpid:
        payload["usrgrps"] = [{"usrgrpid": usrgrpid}]
    api("user.update", payload, auth)
    return uid

def _camera_telegram_messages() -> tuple[str, str]:
    problem_msg = "\n".join([
        "📷 <b>CÂMERA:</b> {$CAM_TITLE}",
        "📍 <b>LOCAL:</b> {$CAM_LOCAL}",
        "💻 <b>MAC:</b> {$CAM_MAC}",
        "🌐 <b>IP:</b> {HOST.IP}",
        "🗺 <b>MAPA:</b> {$CAM_MAP_URL}",
        "❌ <b>STATUS:</b> OFFLINE",
        "🔑 <b>ONU SERIAL:</b> {$ONU_SERIAL}",
        "🧩 <b>PON/ONU:</b> {$PON_ONU}",
        "🕒 <b>EVENTO:</b> {EVENT.DATE} {EVENT.TIME}",
    ])
    recovery_msg = "\n".join([
        "📷 <b>CÂMERA:</b> {$CAM_TITLE}",
        "📍 <b>LOCAL:</b> {$CAM_LOCAL}",
        "💻 <b>MAC:</b> {$CAM_MAC}",
        "🌐 <b>IP:</b> {HOST.IP}",
        "🗺 <b>MAPA:</b> {$CAM_MAP_URL}",
        "✅ <b>STATUS:</b> ONLINE",
        "🔑 <b>ONU SERIAL:</b> {$ONU_SERIAL}",
        "🧩 <b>PON/ONU:</b> {$PON_ONU}",
        "🕒 <b>EVENTO:</b> {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}",
    ])
    return problem_msg, recovery_msg


def _windows_telegram_messages() -> tuple[str, str]:
    problem_msg = "\n".join([
        "🚨 <b>ALERTA NO COMPUTADOR</b>",
        "",
        "🖥️ <b>Computador:</b> {$WIN_HOSTNAME}",
        "👤 <b>Usuário:</b> {$WIN_USER}",
        "📍 <b>Local:</b> {$WIN_SITE} / {$WIN_SECTOR}",
        "🌐 <b>IP:</b> {HOST.IP}",
        "🔗 <b>AnyDesk:</b> {$WIN_ANYDESK_ID}",
        "",
        "⚠️ <b>Problema:</b> {EVENT.NAME}",
        "✅ <b>Entenda:</b> se aparecer <b>Space is low</b>, o disco esta ficando cheio. Se aparecer <b>Memory</b>, a memoria esta alta. Se aparecer <b>not running</b>, algum servico parou. Se aparecer <b>Unavailable</b>, o computador ficou sem comunicacao.",
        "🛠️ <b>Ação sugerida:</b> verificar o computador pelo AnyDesk ou presencialmente e corrigir o item acima.",
        "",
        "💻 <b>Equipamento:</b> {$CAM_MODEL}",
        "🪟 <b>Windows:</b> {$WIN_OS}",
        "🧠 <b>RAM:</b> {$WIN_RAM_GB} GB",
        "💾 <b>Disco:</b> {$WIN_DISK_SUMMARY}",
        "🕒 <b>Quando:</b> {EVENT.DATE} {EVENT.TIME}",
    ])
    recovery_msg = "\n".join([
        "✅ <b>COMPUTADOR RECUPERADO</b>",
        "",
        "🖥️ <b>Computador:</b> {$WIN_HOSTNAME}",
        "👤 <b>Usuário:</b> {$WIN_USER}",
        "📍 <b>Local:</b> {$WIN_SITE} / {$WIN_SECTOR}",
        "🌐 <b>IP:</b> {HOST.IP}",
        "",
        "🔔 <b>Problema resolvido:</b> {EVENT.NAME}",
        "🕒 <b>Quando:</b> {EVENT.RECOVERY.DATE} {EVENT.RECOVERY.TIME}",
    ])
    return problem_msg, recovery_msg


def ensure_action(
    auth: str,
    action_name: str,
    groupid: str,
    userid: str,
    mediatypeid: str,
    *,
    message_type: str = "camera",
) -> str:
    res = api("action.get", {"filter":{"name":[action_name]}}, auth)

    if str(message_type or "").strip().lower() == "windows":
        problem_msg, recovery_msg = _windows_telegram_messages()
    else:
        problem_msg, recovery_msg = _camera_telegram_messages()

    operations=[{
        "operationtype": 0,
        "opmessage": {
            "default_msg": 0,
            "mediatypeid": mediatypeid,
            "message": problem_msg
        },
        "opmessage_usr": [{"userid": userid}]
    }]
    recovery_operations=[{
        "operationtype": 0,
        "opmessage": {
            "default_msg": 0,
            "mediatypeid": mediatypeid,
            "message": recovery_msg
        },
        "opmessage_usr": [{"userid": userid}]
    }]
    params={
        "name": action_name,
        "eventsource": 0,
        "status": 0,
        "esc_period": "1m",
        "filter": {"evaltype": 0, "conditions": [{
            "conditiontype": 0, "operator": 0, "value": groupid
        }]},
        "operations": operations,
        "recovery_operations": recovery_operations
    }
    if not res:
        created = api("action.create", params, auth)
        return created["actionids"][0]
    aid = res[0]["actionid"]
    params["actionid"]=aid
    api("action.update", params, auth)
    return aid


def disable_legacy_actions(auth: str, extra_names: list[str] | None = None) -> None:
    legacy_names = [ACTION_NAME_LEGACY_IP, ACTION_NAME_LEGACY_DVR, ACTION_NAME_LEGACY_WINDOWS]
    for name in extra_names or []:
        if name and name not in legacy_names:
            legacy_names.append(name)
    for name in legacy_names:
        try:
            res = api("action.get", {"filter": {"name": [name]}, "output": ["actionid", "status"]}, auth)
            for a in (res or []):
                aid = str(a.get("actionid") or "").strip()
                if not aid:
                    continue
                if str(a.get("status")) == "1":
                    continue
                api("action.update", {"actionid": aid, "status": 1}, auth)
        except Exception:
            pass

def prune_hosts(auth: str, group_name: str, tenant: str, hosts_ativos: set) -> int:
    """Remove do grupo do tenant os hosts que sairam do inventario."""
    if not group_name or not tenant:
        return 0
    grupos = api("hostgroup.get", {"filter": {"name": [group_name]}}, auth)
    if not grupos:
        return 0
    gid = grupos[0]["groupid"]
    atuais = api("host.get", {"groupids": [gid], "output": ["hostid", "host"]}, auth)

    prefixo = f"{_host_safe(tenant).upper()}-"
    alvo = []
    for h in atuais:
        nome = str(h.get("host") or "")
        if not nome.upper().startswith(prefixo):
            continue                      # criado fora do sistema: nao tocar
        if nome in hosts_ativos:
            continue                      # segue no inventario
        alvo.append(h["hostid"])

    if not alvo:
        return 0

    # Remover quase tudo nunca e rotina. Nos dois incidentes de 19 e 20/08 a poda
    # apagou ~88% do grupo porque a Fonte escolhida so enxergava parte do
    # inventario -- e o inventario estava inteiro o tempo todo.
    total_no_grupo = len(atuais)
    limite = max(ZBX_PRUNE_MIN_ABS, int(total_no_grupo * ZBX_PRUNE_MAX_PCT / 100))
    if ZBX_PRUNE_MAX_PCT < 100 and len(alvo) > limite:
        pct = (len(alvo) * 100 // total_no_grupo) if total_no_grupo else 100
        print(
            f"PRUNE BLOQUEADO: removeria {len(alvo)} de {total_no_grupo} hosts ({pct}%) "
            f"de '{group_name}' -- acima do limite de {ZBX_PRUNE_MAX_PCT:.0f}%.",
            file=sys.stderr,
        )
        print(
            "Isso costuma indicar Fonte ou filtro errado, e nao cameras que sairam do "
            "inventario. Nada foi removido. Confira a Fonte selecionada; para limpar "
            "mesmo assim, rode com ZBX_PRUNE_MAX_PCT=100.",
            file=sys.stderr,
        )
        return 0

    for i in range(0, len(alvo), 100):
        api("host.delete", alvo[i:i + 100], auth)
    print(f"PRUNE: {len(alvo)} host(s) removidos de '{group_name}' (fora do inventario)")
    return len(alvo)


def main():
    if not ZBX_URL or not ZBX_USER or not ZBX_PASS:
        print("Preencha ZBX_URL, ZBX_USER e ZBX_PASS.", file=sys.stderr)
        sys.exit(2)
    auth=login()
    groupid=ensure_hostgroup(auth, ZBX_GROUP)
    rows=json.load(open(INV_PATH,"r",encoding="utf-8"))
    has_ip_like = any(str((r or {}).get("source") or "").strip().lower() != "dvr" for r in rows if isinstance(r, dict))

    templateid, template_name_used = resolve_base_template_id(auth, ZBX_TEMPLATE)
    if not templateid and has_ip_like:
        raise RuntimeError(
            f"Template base nao encontrado: '{ZBX_TEMPLATE}'. "
            "Informe um template existente no seu Zabbix (ex.: ICMP Ping)."
        )
    if templateid:
        print(f"Template base: {template_name_used}")
    else:
        print("[WARN] Sem template base de ping. Continuando apenas com template DVR para hosts DVR.", file=sys.stderr)
    dvr_templateid = ""
    try:
        dvr_templateid = ensure_dvr_channel_template(auth, ZBX_TEMPLATE_DVR)
    except Exception as e:
        print(f"[WARN] Template DVR nao criado ({e}). Seguindo sem trigger de canal.", file=sys.stderr)

    if TG_AUTO:
        if not TG_TOKEN or not TG_CHAT:
            print("Telegram auto: ignorado (token/chat vazios).")
        else:
            print("Telegram auto: configurando media type + user + action...")
            mtid=ensure_telegram_mediatype(auth, TG_TOKEN, TG_CHAT)
            uid=ensure_user_with_media(auth, mtid, TG_CHAT)
            has_windows = any(
                str((r or {}).get("source") or "").strip().lower() == "windows"
                for r in rows
                if isinstance(r, dict)
            )
            action_name = ACTION_NAME_WINDOWS if has_windows else ACTION_NAME_GROUP
            aid_ip=ensure_action(
                auth,
                action_name,
                groupid,
                uid,
                mtid,
                message_type="windows" if has_windows else "camera",
            )
            disable_legacy_actions(auth, extra_names=[ACTION_NAME_GROUP] if has_windows else None)
            print(
                f"Telegram auto: OK (mediatypeid={mtid}, userid={uid}, "
                f"action={aid_ip})"
            )

    n=0

    hosts_ativos = set()
    for c in rows:
        ip=(c.get("ip") or "").strip()
        if not ip: 
            continue
        title=(c.get("titulo") or c.get("title") or c.get("nome") or ip).strip()
        local=str(c.get("local") or c.get("location") or c.get("LOCAL") or "").strip()
        mac=str(c.get("mac") or c.get("Mac Address") or c.get("mac_address") or "").strip()
        model=str(c.get("modelo") or c.get("model") or c.get("device_model") or "").strip()
        onu_serial=str(
            c.get("onu_serial") or c.get("onu_sn") or c.get("serial_onu") or c.get("onuSerial") or ""
        ).strip()
        pon=str(c.get("pon") or "").strip()
        map_url = (str(c.get("map_url") or "").strip() or _google_maps_url(c.get("lat"), c.get("lon")))
        # Prefer public URLs so Telegram can render the photo inline.
        cand = [
            str(c.get("imgbb_url") or "").strip(),
            str(c.get("thumb_url") or "").strip(),
            str(c.get("snapshot_url") or "").strip(),
            str(c.get("image_url") or "").strip(),
        ]
        http_first = [u for u in cand if u.lower().startswith(("http://", "https://"))]
        snapshot_url = (http_first[0] if http_first else (cand[0] if cand else ""))
        onu=str(c.get("onu_id") or c.get("onu") or "").strip()
        pon_onu=(f"{pon}/{onu}" if pon and onu else (pon or onu))
        source = str(c.get("source") or "").strip().lower()
        channel = str(c.get("channel") or "").strip()
        http_port = int(c.get("http_port") or 80)
        host = build_host_name(ZBX_TENANT, c)
        status_raw = str(c.get("status") or "").strip().lower()
        templateids = [templateid]
        if source == "dvr" and dvr_templateid:
            templateids.append(dvr_templateid)
        dvr_http_url = f"http://{ip}:{http_port}" if int(http_port) != 80 else f"http://{ip}"
        try:
            ch_idx = str(max(0, int(channel) - 1))
        except Exception:
            ch_idx = "0"
        try:
            ch_num = str(max(1, int(channel)))
        except Exception:
            ch_num = "1"

        # grupo principal + grupo do site (e o que permite filtrar por site
        # no Zabbix; antes os subgrupos existiam vazios)
        host_groups = [groupid]
        try:
            gid_site = ensure_site_group(auth, ZBX_GROUP, local)
            if gid_site:
                host_groups.append(gid_site)
        except Exception as e:
            print(f"AVISO: grupo do site '{local}' nao pode ser usado ({e})", file=sys.stderr)
        macros = {
            "{$CAM_IP}": ip,
            "{$CAM_TITLE}": title,
            "{$CAM_LOCAL}": local,
            "{$CAM_MAC}": mac,
            "{$CAM_MODEL}": model,
            "{$WIN_HOSTNAME}": str(c.get("hostname") or c.get("host") or title).strip(),
            "{$WIN_USER}": str(c.get("logged_user") or "").strip(),
            "{$WIN_OS}": str(c.get("os_name") or "").strip(),
            "{$WIN_SITE}": str(c.get("site") or "").strip(),
            "{$WIN_SECTOR}": str(c.get("sector") or c.get("setor") or "").strip(),
            "{$WIN_SERIAL}": str(c.get("serial") or "").strip(),
            "{$WIN_CPU}": str(c.get("cpu") or "").strip(),
            "{$WIN_RAM_GB}": str(c.get("ram_gb") or "").strip(),
            "{$WIN_DISK_SUMMARY}": str(c.get("disk_summary") or "").strip(),
            "{$WIN_ANYDESK_ID}": str(c.get("anydesk_id") or "").strip(),
            "{$ONU_SERIAL}": onu_serial,
            "{$PON_ONU}": pon_onu,
            "{$PON}": pon,
            "{$CAM_SNAPSHOT_URL}": snapshot_url,
            "{$CAM_MAP_URL}": map_url,
            "{$ONU}": onu,
            "{$CAM_STATUS}": status_raw,
            "{$DVR_HTTP_URL}": dvr_http_url,
            "{$DVR_USER}": ZBX_DVR_USER,
            "{$DVR_PASS}": ZBX_DVR_PASS,
            "{$DVR_CH_INDEX}": ch_idx,
            "{$DVR_CH}": ch_num,
        }
        if source == "windows":
            macros["{$SERVICE.NAME.NOT_MATCHES}"] = WINDOWS_SERVICE_NAME_NOT_MATCHES
        visible_name = build_visible_name(ZBX_TENANT, c, title)
        st, hostid = host_upsert(auth, host, visible_name, ip, host_groups, templateids, macros)
        hosts_ativos.add(host)
        n+=1
        print(f"{st}: {host} ({visible_name})")
    print(f"OK: {n} hosts processados")
    # --- Telegram por site -------------------------------------------------
    # Precisa rodar aqui: os grupos de site sao criados no laco acima, e a acao
    # e filtrada pelo id do grupo.
    if TG_AUTO and TG_TOKEN and TG_CHAT_BY_SITE:
        print(f"Telegram por site: {len(TG_CHAT_BY_SITE)} site(s) configurado(s)")
        try:
            mtid_site = ensure_telegram_mediatype(auth, TG_TOKEN, TG_CHAT or "")
        except Exception as e:
            mtid_site = ""
            print(f"AVISO: media type do Telegram nao configurado ({e})", file=sys.stderr)
        for site_nome, chat in sorted(TG_CHAT_BY_SITE.items()):
            site_nome = " ".join(str(site_nome or "").split()).strip()
            chat = str(chat or "").strip()
            if not site_nome or not chat or not mtid_site:
                continue
            try:
                gid_site = ensure_site_group(auth, ZBX_GROUP, site_nome)
                if not gid_site:
                    print(f"AVISO: sem grupo para o site '{site_nome}'", file=sys.stderr)
                    continue
                alias_site = f"{USER_ALIAS}.{_slug_name(site_nome)}"[:100]
                uid_site = ensure_user_with_media(auth, mtid_site, chat, alias=alias_site)
                nome_acao = f"{ZBX_GROUP}/{site_nome} -> Telegram (cam-snapshot)"
                aid_site = ensure_action(auth, nome_acao, gid_site, uid_site, mtid_site)
                print(f"  {site_nome}: chat {chat} -> acao {aid_site}")
            except Exception as e:
                # um site com chat errado nao pode impedir os outros
                print(f"AVISO: Telegram do site '{site_nome}' falhou ({e})", file=sys.stderr)

    if ZBX_PRUNE and not hosts_ativos:
        # Ninguem chegou aqui querendo esvaziar o grupo: inventario vazio e
        # sintoma de fonte/filtro errado. Podar aqui apagaria todos os hosts.
        print("PRUNE: desligado (inventario vazio -- nada foi removido)")
    elif ZBX_PRUNE:
        try:
            prune_hosts(auth, ZBX_GROUP, ZBX_TENANT, hosts_ativos)
        except Exception as e:
            print(f"AVISO: poda nao concluida: {e}")
    else:
        print("PRUNE: desligado (sync parcial/por site nao remove nada)")

if __name__=="__main__":
    main()
