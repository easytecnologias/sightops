#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mk_netwatch_from_inventory.py

Gera output/netwatch_setup.rsc a partir do inventário atual, em formato 100% compatível com RouterOS /import.

Pontos-chave (baseado no que funcionou no seu Mikrotik):
- NÃO usa querystring com "?" (o terminal pode tratar "?" como help).
- Usa POST via /tool fetch: http-method=post + http-data=...
- NÃO usa aspas internas no url= nem no http-data= (evita "expected end of command" no /import).
- Cria /system script (up/down) e no Netwatch apenas chama "/system script run ...".
- Se houver snapshot_url (ImgBB), usa sendPhoto com caption (card completo). Caso contrário, sendMessage.

Entrada (tentativa na ordem):
- data/cam-inventory.json   (padrão do backend)
- output/inventory.json     (compat)
- output/cam-inventory.json (compat)

Uso:
python tools/mk_netwatch_from_inventory.py --token XXX --chat -4597... [--interval 1m] [--timeout 2s]
"""
import argparse
import html
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _load_inventory(base: Path, tenant: str = ""):
    candidates = []
    tenant_slug = _slug(tenant) if str(tenant or "").strip() else ""
    if tenant_slug:
        candidates.extend([
            base / "data" / "tenants" / tenant_slug / "cam-inventory.json",
            base / "data" / "tenants" / tenant_slug / "cam-inventory-switch.json",
        ])
    candidates.extend([
        base / "data" / "cam-inventory.json",
        base / "output" / "inventory.json",
        base / "output" / "cam-inventory.json",
    ])
    for p in candidates:
        data = _read_json(p)
        if isinstance(data, list):
            return p, data
    raise FileNotFoundError("Inventário JSON não encontrado em data/ ou output/.")

def _pick(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return default

def _norm(v) -> str:
    s = str(v or "").strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip()

def _slug(v: str) -> str:
    s = _norm(v)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "todos"

def _ros_name(v: str) -> str:
    """Return a RouterOS-friendly identifier for script names."""
    s = str(v or "").strip()
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")
    return s or "unknown"

def _ros_string(v: str) -> str:
    """Escape a value for a RouterOS quoted string in .rsc files."""
    return str(v or "").replace("\\", "\\\\").replace('"', r'\"')

def _is_public_http_url(v: str) -> bool:
    s = str(v or "").strip()
    return bool(re.match(r"^https?://", s, flags=re.I))

def _public_photo_url(cam: dict) -> str:
    # Telegram precisa buscar a foto pela internet. Caminhos locais como
    # /data/snapshot/10_10_10_20.jpg nao funcionam no sendPhoto.
    for key in ("imgbb_url", "thumb_url", "snapshot_public_url", "photo_url"):
        v = _pick(cam, key, default="")
        if _is_public_http_url(v):
            return v
    snap = _pick(cam, "snapshot_url", default="")
    return snap if _is_public_http_url(snap) else ""

def _html(v: str) -> str:
    return html.escape(str(v or "-"), quote=False)

def _map_url(cam: dict) -> str:
    direct = _pick(cam, "map_url", "maps_url", "google_maps_url", "gmaps_url", default="")
    if direct:
        return direct
    lat = _pick(cam, "lat", "latitude", default="")
    lon = _pick(cam, "lon", "lng", "longitude", default="")
    if lat and lon:
        return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
    return "-"

def _telegram_map_button(url: str) -> str:
    if not _is_public_http_url(url):
        return ""
    payload = {"inline_keyboard": [[{"text": "Abrir no Google Maps", "url": url}]]}
    return "&reply_markup=" + quote(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), safe="")

def _row_site(row: dict) -> str:
    return _pick(row, "site", "site_name", "local", "LOCAL", default="")

def _filter_by_site(rows: list, site: str) -> list:
    wanted = _norm(site)
    if not wanted:
        return rows
    return [r for r in rows if isinstance(r, dict) and _norm(_row_site(r)) == wanted]

def _all_rows_without_site(rows: list) -> bool:
    valid = [r for r in rows if isinstance(r, dict)]
    return bool(valid) and all(not _norm(_row_site(r)) for r in valid)

def _caption(cam: dict, status: str) -> str:
    ip     = _pick(cam, "ip", "host", default="-")
    titulo = _pick(cam, "titulo", "title", "nome", "name", "camera_name", "description", default=ip)
    modelo = _pick(cam, "model", "modelo", "device_model", default=ip)
    local  = _pick(cam, "local", "location", "place", "site", "site_name", default="-")
    mac    = _pick(cam, "mac", "mac_address", default="-")
    onu_serial = _pick(cam, "onu_serial", "serial_onu", "gpon_sn", default="-")
    mapa = _map_url(cam)

    # --- GPON: tentar exibir PON e ONU (ID) SEM misturar os dois ---
    # Alguns fluxos guardam apenas 'pon_onu' (ex: '0/4/6'). Outros guardam 'pon' + 'onu_id'.
    pon_raw = _pick(cam, "pon_onu", "pon_onu_id", default="")
    pon     = _pick(cam, "pon", "pon_port", default="")
    onu_id  = _pick(cam, "onu_id", "onu-id", "onuIndex", "onu_index", "onu_number", "onu_num", default="")

    # Se vier 'pon' como '0/4/6' (já completo), separa automaticamente.
    if pon and pon.count("/") >= 2 and not onu_id:
        parts = [x for x in pon.split("/") if x.strip()]
        if len(parts) >= 3 and parts[-1].isdigit():
            onu_id = parts[-1]
            pon = "/".join(parts[:-1])

    # Se vier 'pon_onu' como '0/4/6', separa automaticamente.
    if pon_raw and pon_raw.count("/") >= 2 and not onu_id:
        parts = [x for x in pon_raw.split("/") if x.strip()]
        if len(parts) >= 3 and parts[-1].isdigit():
            onu_id = parts[-1]
            if not pon:
                pon = "/".join(parts[:-1])

    # Monta representação PON/ONU final
    pononu = "-"
    if pon_raw and pon_raw.count("/") >= 2:
        pononu = pon_raw
    elif pon and onu_id:
        # 4840e típico: pon='0/4' + onu_id='6' -> '0/4/6'
        if pon.count("/") == 1:
            pononu = f"{pon}/{onu_id}"
        else:
            # 8820i pode ser pon='2' (porta GPON) + onu_id='15' -> '2/15'
            pononu = f"{pon}/{onu_id}"
    elif pon:
        pononu = pon

    status_line = "✅ <b>STATUS:</b> ONLINE" if status == "ONLINE" else "❌ <b>STATUS:</b> OFFLINE"

    text = "\n".join([
        f"📷 <b>CÂMERA:</b> {_html(modelo)}",
        f"📍 <b>LOCAL:</b> {_html(local)}",
        f"💻 <b>MAC:</b> {_html(mac)}",
        f"🌐 <b>IP:</b> {_html(ip)}",
        f"🗺 <b>MAPA:</b> {_html(mapa)}",
        status_line,
        f"🔑 <b>ONU SERIAL:</b> {_html(onu_serial)}",
        f"🧩 <b>PON/ONU:</b> {_html(pononu)}",
    ])
    text = f"📌 <b>{_html(titulo)}</b>\n" + text
    text = "\n".join(line for line in text.splitlines() if "<b>MAPA:</b>" not in line)
    return text

def _event_http_data_suffix() -> str:
    return ' . [/system clock get date] . "%20" . [/system clock get time] . "'

def _tg_send_message_post(token: str, chat: str, text: str, map_url: str = "") -> str:
    # POST sem "?" para evitar o help do CLI
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text_prefix = quote(text + "\n🕒 <b>EVENTO:</b> ", safe='')
    data_prefix = f"chat_id={quote(chat, safe='')}&text={text_prefix}"
    data_suffix = "&parse_mode=HTML" + _telegram_map_button(map_url)
    return f'/tool fetch output=none check-certificate=no url="{url}" http-method=post http-data=("{data_prefix}"{_event_http_data_suffix()}{data_suffix}")'

def _tg_send_photo_post(token: str, chat: str, photo_url: str, caption: str, map_url: str = "") -> str:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    # encode completo para não quebrar em & etc.
    photo = quote(photo_url, safe='')
    cap = quote(caption + "\n🕒 <b>EVENTO:</b> ", safe='')
    data_prefix = f"chat_id={quote(chat, safe='')}&photo={photo}&caption={cap}"
    data_suffix = "&parse_mode=HTML" + _telegram_map_button(map_url)
    return f'/tool fetch output=none check-certificate=no url="{url}" http-method=post http-data=("{data_prefix}"{_event_http_data_suffix()}{data_suffix}")'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--chat", required=True)
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--timeout", default="2s")
    ap.add_argument("--site", default="", help="Filtra por site/local do inventario.")
    ap.add_argument("--tenant", default="", help="Slug do tenant para carregar data/tenants/<slug>/cam-inventory.json.")
    args = ap.parse_args()

    base = Path(__file__).resolve().parent.parent
    inv_path, inv_all = _load_inventory(base, args.tenant)
    inv = _filter_by_site(inv_all, args.site)
    site_fallback_all = False
    if str(args.site or "").strip() and not inv and _all_rows_without_site(inv_all):
        # Alguns deploys rodam por tenant/site, mas o JSON legado nao grava esse
        # nome em cada camera. Nesse caso, o site selecionado representa o inventario atual.
        inv = inv_all
        site_fallback_all = True

    out_dir = base / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"netwatch_setup_{_slug(args.site)}.rsc" if str(args.site or "").strip() else "netwatch_setup.rsc"
    out_path = out_dir / out_name

    lines = []
    lines.append("# Auto-gerado pelo cam-snapshot-web")
    lines.append(f"# Inventário: {inv_path.as_posix()}")
    if str(args.site or "").strip():
        lines.append(f"# Site: {args.site}")
        if site_fallback_all:
            lines.append("# Aviso: inventario sem campo de site; usando todas as cameras.")
    lines.append(f"# Cameras: {sum(1 for r in inv if isinstance(r, dict) and _pick(r, 'ip', 'host'))}")
    lines.append("")
    lines.append("/system script")

    netwatch = ["", "/tool netwatch"]

    for cam in inv:
        ip = _pick(cam, "ip", "host")
        if not ip:
            continue
        ip_name = _ros_name(ip)
        up_name = f"send_cam_up_{ip_name}"
        down_name = f"send_cam_down_{ip_name}"

        # Foto somente quando for URL publica http(s). URL local/relativa quebra o sendPhoto.
        snap = _public_photo_url(cam)
        comment = _pick(cam, "local", "location", "place", "title", "name", default=ip)

        up_text = _caption(cam, "ONLINE")
        dn_text = _caption(cam, "OFFLINE")
        map_button_url = _map_url(cam)

        if snap:
            up_cmd = _tg_send_photo_post(args.token, args.chat, snap, up_text, map_button_url)
            dn_cmd = _tg_send_photo_post(args.token, args.chat, snap, dn_text, map_button_url)
        else:
            up_cmd = _tg_send_message_post(args.token, args.chat, up_text, map_button_url)
            dn_cmd = _tg_send_message_post(args.token, args.chat, dn_text, map_button_url)

        # Remove antes de adicionar para o /import poder ser reexecutado sem erro
        # por nome duplicado. Os nomes usam "_" no IP para evitar ambiguidades no CLI.
        lines.append(f'remove [find name="{up_name}"]')
        lines.append(f'remove [find name="{down_name}"]')
        script_opts = 'policy=read,write,test dont-require-permissions=yes'
        lines.append(f'add name="{up_name}" {script_opts} source="{_ros_string(up_cmd)};"')
        lines.append(f'add name="{down_name}" {script_opts} source="{_ros_string(dn_cmd)};"')

        netwatch.append(
            f'remove [find host={ip}]'
        )
        netwatch.append(
            f'add host={ip} interval={args.interval} timeout={args.timeout} comment="{_ros_string(comment)}" '
            f'down-script="/system script run \\"{down_name}\\"" '
            f'up-script="/system script run \\"{up_name}\\""'
        )

    lines.extend(netwatch)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] Gerado: {out_path}")

if __name__ == "__main__":
    main()
