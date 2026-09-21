import re
import requests
from requests.auth import HTTPDigestAuth

UA = {"User-Agent": "cam-snapshot/1.16 model-fallback"}

REALM_MODEL_PATTERNS = [
    r"\((?P<model>VIP[-_ ]?\d{3,5}[A-Za-z0-9\-]*)\)",
    r"(?P<model>VIP[-_ ]?\d{3,5}[A-Za-z0-9\-]*)",
    r"(?P<model>Intelbras[-_ ]?VIP[^\s,\)]+)",
    r'(?P<model>IPC(?:-|\s)?[A-Za-z0-9\-_]+)',
]

def _req(url, user=None, pwd=None, timeout=4, digest=False, stream=False, allow_401=False):
    try:
        if user is None:
            r = requests.get(url, timeout=timeout, headers=UA, stream=stream, allow_redirects=False)
        else:
            auth = HTTPDigestAuth(user, pwd) if digest else (user, pwd)
            r = requests.get(url, timeout=timeout, headers=UA, stream=stream, auth=auth, allow_redirects=False)
        if allow_401 and r is not None and r.status_code == 401:
            return r
        if r is not None and r.status_code == 200:
            return r
    except Exception:
        pass
    return None

def _extract_model_from_headers(resp):
    if resp is None:
        return None
    cand = []
    wa = resp.headers.get("WWW-Authenticate", "") if resp is not None else ""
    srv = resp.headers.get("Server", "") if resp is not None else ""
    if wa:
        cand.append(wa)
    if srv:
        cand.append(srv)
    text = " ".join(cand)
    if not text:
        return None
    for pat in REALM_MODEL_PATTERNS:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group("model").strip().replace("  "," ")
    return None

def probe_headers_model(ip):
    r = _req(f"http://{ip}/", timeout=3, allow_401=True)
    model = _extract_model_from_headers(r)
    if model:
        return model
    for u in [
        f"http://{ip}/cgi-bin/snapshot.cgi?channel=1",
        f"http://{ip}/onvif/snapshot",
        f"http://{ip}/snapshot.jpg",
        f"http://{ip}/ISAPI/Streaming/channels/101/picture",
    ]:
        r = _req(u, timeout=3, allow_401=True)
        model = _extract_model_from_headers(r)
        if model:
            return model
    return None

def probe_dahua_magicbox(ip, user, pwd):
    urls = [
        f"http://{ip}/cgi-bin/magicBox.cgi?action=getSystemInfo",
        f"http://{ip}/cgi-bin/configManager.cgi?action=getConfig&name=SystemInfo",
        f"http://{ip}/cgi-bin/magicBox.cgi?action=getMachineName",
    ]
    for u in urls:
        r = _req(u, user, pwd, timeout=4, digest=False)
        if r and getattr(r, 'text', None):
            t = r.text
            for key in ["deviceType", "deviceName", "model", "MachineName"]:
                m = re.search(rf"{key}\s*[\=:]\s*\"?([^\r\n\"<]+)", t, flags=re.IGNORECASE)
                if m:
                    return m.group(1).strip()
        r = _req(u, user, pwd, timeout=4, digest=True)
        if r and getattr(r, 'text', None):
            t = r.text
            for key in ["deviceType", "deviceName", "model", "MachineName"]:
                m = re.search(rf"{key}\s*[\=:]\s*\"?([^\r\n\"<]+)", t, flags=re.IGNORECASE)
                if m:
                    return m.group(1).strip()
    return None

def probe_isapi(ip, user, pwd):
    u = f"http://{ip}/ISAPI/System/deviceInfo"
    for dg in (False, True):
        r = _req(u, user, pwd, timeout=4, digest=dg)
        if r and getattr(r, 'text', None):
            m = re.search(r"<model>\s*([^<]+)\s*</model>", r.text, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
            m = re.search(r"<deviceName>\s*([^<]+)\s*</deviceName>", r.text, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return None

def probe_onvif(ip, user, pwd):
    import textwrap
    body = textwrap.dedent("""\
        <s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
          <s:Body>
            <GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>
          </s:Body>
        </s:Envelope>""").strip()
    headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
    u = f"http://{ip}/onvif/device_service"
    for dg in (False, True):
        try:
            if dg:
                auth = HTTPDigestAuth(user, pwd)
            else:
                auth = (user, pwd)
            r = requests.post(u, data=body.encode("utf-8"), headers=headers, auth=auth, timeout=4)
            if r is not None and r.status_code == 200:
                m = re.search(r"<(?:\w+:)?Model>\s*([^<]+)\s*</(?:\w+:)?Model>", r.text, flags=re.IGNORECASE)
                if m:
                    return m.group(1).strip()
        except Exception:
            pass
    return None

def best_guess_model(ip, user, pwd):
    for fn in (probe_headers_model, lambda ip: probe_dahua_magicbox(ip, user, pwd),
               lambda ip: probe_isapi(ip, user, pwd), lambda ip: probe_onvif(ip, user, pwd)):
        try:
            model = fn(ip)
        except Exception:
            model = None
        if model:
            model = re.sub(r"\bintelbras\b", "Intelbras", model, flags=re.IGNORECASE)
            model = model.replace("VIP_", "VIP ").replace("VIP-", "VIP ").replace("  ", " ").strip()
            return model
    return None
