#!/usr/bin/env python3
import argparse, csv, os, sys
from pathlib import Path
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.camsnapshot.ai import ocr_brand_model as ocr
from app.services.camsnapshot.ai.quality import score as quality_score

import requests
from requests.auth import HTTPDigestAuth
import xml.etree.ElementTree as ET

OUI_VENDOR = {
    "14:CC:20":"Hikvision","D8:BB:C1":"Hikvision","BC:EC:5D":"Hikvision",
    "64:09:80":"Hikvision","F0:81:73":"Hikvision","90:02:A9":"Hikvision",
    "38:AF:29":"Dahua","60:62:66":"Dahua","54:8D:5A":"Dahua",
    "10:6F:3F":"Dahua","B0:4A:39":"Dahua","3C:EF:8C":"Dahua"
}

def read_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append(r)
    return rdr.fieldnames, rows

def write_csv(path, headers, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def _oui(mac: str) -> str:
    mac = (mac or "").upper()
    return ":".join(mac.split(":")[:3])

def normalize_vendor_model(modelo, fabricante, mac):
    m = (modelo or "").strip()
    f = (fabricante or "").strip()
    oui = _oui(mac)
    low_m = m.lower()

    if oui in OUI_VENDOR:
        vend = OUI_VENDOR[oui]
        if vend == "Hikvision":
            looks_hilook = (low_m.startswith("ipc-") and not low_m.startswith("ipc-h")) or ("hilook" in low_m or "hi-look" in low_m)
            return m or None, ("Hilook" if looks_hilook else "Hikvision")
        return m or None, vend

    hik_signals = ["hikvision", "hi-look", "hilook", "ds-2", "isapi"]
    looks_hilook = (low_m.startswith("ipc-") and not low_m.startswith("ipc-h")) or ("hilook" in low_m or "hi-look" in low_m)
    if any(s in low_m for s in hik_signals) or looks_hilook:
        return m or None, ("Hilook" if looks_hilook else "Hikvision")

    if any(s in low_m for s in ["dahua","ipc-h","dh-"]):
        return m or None, "Dahua"

    return m or None, f or None

def _safe_get(url, user, pwd, timeout=5.0):
    try:
        r = requests.get(url, auth=HTTPDigestAuth(user, pwd), timeout=timeout, verify=False)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    try:
        r = requests.get(url, auth=(user, pwd), timeout=timeout, verify=False)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    return None

def _extract_name_from_json(obj):
    # tenta chaves comuns e, por fim, qualquer chave que termine com 'name'
    if not isinstance(obj, dict):
        return None
    # formatos conhecidos
    for k in ("VideoInputChannel","InputProxyChannel","StreamingChannel","Channel"):
        if k in obj and isinstance(obj[k], dict):
            sub = obj[k]
            for c in ("name","channelName","deviceName"):
                if sub.get(c):
                    return str(sub[c]).strip()
    # top-level
    for c in ("name","channelName","deviceName"):
        if obj.get(c):
            return str(obj[c]).strip()
    # busca genérica: qualquer chave que termine com 'name'
    for k, v in obj.items():
        if isinstance(v, (str, int)) and str(k).lower().endswith("name") and str(v).strip():
            return str(v).strip()
        if isinstance(v, dict):
            got = _extract_name_from_json(v)
            if got:
                return got
    return None

def _extract_name_from_xml(text):
    try:
        root = ET.fromstring(text)
    except Exception:
        return None
    # caminhos comuns
    for tag in ("name","channelName","deviceName"):
        node = root.find(f".//{tag}")
        if node is not None and node.text and node.text.strip():
            return node.text.strip()
    # genérico: QUALQUER tag cujo nome termine com 'name'
    for elem in root.iter():
        if elem.tag.lower().endswith("name") and elem.text and elem.text.strip():
            return elem.text.strip()
    return None

def hik_try_endpoints(host: str, port: int, user: str, pwd: str, channel: int, dump_dir=None, debug=False):
    base = f"http://{host}:{port}"
    endpoints = [
        f"/ISAPI/System/Video/inputs/channels/{channel}?format=json",
        f"/ISAPI/System/Video/inputs/channels/{channel}",
        f"/ISAPI/ContentMgmt/InputProxy/channels/{channel}?format=json",
        f"/ISAPI/ContentMgmt/InputProxy/channels/{channel}",
        f"/ISAPI/System/Video/inputs/channels/1?format=json",
        f"/ISAPI/System/Video/inputs/channels/1",
        f"/ISAPI/Streaming/channels/{channel}01?format=json",  # 101, 201...
        f"/ISAPI/Streaming/channels/{channel}01",
    ]
    for ep in endpoints:
        url = base + ep
        r = _safe_get(url, user, pwd)
        if debug:
            print(f"[AI][DEBUG] GET {url} ->", (r.status_code if r else "fail"))
        if not r:
            continue

        ctype = r.headers.get("Content-Type","").lower()
        body = r.text

        # opcional: salvar para debug fino
        if dump_dir:
            os.makedirs(dump_dir, exist_ok=True)
            safe_ep = ep.strip("/").replace("/", "_").replace("?", "_").replace("=", "_")
            with open(os.path.join(dump_dir, f"{host}_{safe_ep}.txt"), "w", encoding="utf-8", newline="") as f:
                f.write(body)

        # JSON
        if "json" in ctype:
            try:
                data = r.json()
                got = _extract_name_from_json(data)
                if got:
                    return got
            except Exception:
                pass

        # XML (ou texto simples)
        got = _extract_name_from_xml(body)
        if got:
            return got

    return None

def main():
    ap = argparse.ArgumentParser(description="Enriquecimento IA + Correções (vendor/título Hik/HiLook)")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--usuario", default=None, help="Usuário ISAPI (Hik/HiLook)")
    ap.add_argument("--senha", default=None, help="Senha ISAPI (Hik/HiLook)")
    ap.add_argument("--channel", type=int, default=1, help="Canal base (1) — 101 será tentado automaticamente")
    ap.add_argument("--http-port", type=int, default=80, help="Porta HTTP do ISAPI (default 80)")
    ap.add_argument("--debug", action="store_true", help="Loga endpoints testados e respostas")
    ap.add_argument("--dump-isapi", action="store_true", help="Salva respostas ISAPI em 'saida/isapi_dumps'")
    args = ap.parse_args()

    headers, rows = read_csv(args.csv)
    need_cols = ["fabricante","modelo","quality","blur_score","exposure","black_pct","anomalia","titulo"]
    for c in need_cols:
        if c not in headers:
            headers.append(c)

    base = Path(args.csv).parent
    dump_dir = os.path.join(base, "isapi_dumps") if args.dump_isapi else None

    for r in rows:
        ip = r.get("ip") or r.get("IP") or ""
        snap_path = r.get("snapshot_path") or ""
        if snap_path and not os.path.isabs(snap_path):
            snap_path = str((base / snap_path).resolve())

        modelo = r.get("modelo") or None
        fabricante = r.get("fabricante") or None
        mac = r.get("mac") or r.get("MAC") or None
        titulo = r.get("titulo") or ""

        # Normaliza vendor e tenta completar via OCR
        modelo, fabricante = normalize_vendor_model(modelo, fabricante, mac)

        if snap_path and os.path.exists(snap_path):
            try:
                modelo, fabricante = ocr.fill_gaps(snap_path, modelo, fabricante)
            except Exception:
                pass

        # Qualidade (se houver imagem)
        q = {"quality": 0.0, "blur_score": 0.0, "exposure": 0.0, "black_pct": 100.0}
        if snap_path and os.path.exists(snap_path):
            try:
                q = quality_score(snap_path)
            except Exception:
                pass

        # Nome de canal (ISAPI)
        if (fabricante in ("Hikvision","Hilook")) and (not titulo) and args.usuario and args.senha and ip:
            name = hik_try_endpoints(ip, args.http_port, args.usuario, args.senha, args.channel, dump_dir=dump_dir, debug=args.debug)
            if not name and args.channel == 1:
                name = hik_try_endpoints(ip, args.http_port, args.usuario, args.senha, 101, dump_dir=dump_dir, debug=args.debug)
            if name:
                titulo = name

        r["modelo"] = modelo or r.get("modelo") or ""
        r["fabricante"] = (fabricante or r.get("fabricante") or "").capitalize() if fabricante else (r.get("fabricante") or "")
        r["titulo"] = titulo

        r["quality"] = f"{q['quality']:.3f}"
        r["blur_score"] = f"{q['blur_score']:.2f}"
        r["exposure"] = f"{q['exposure']:.3f}"
        r["black_pct"] = f"{q['black_pct']:.2f}"

    out = args.out or (Path(args.csv).with_suffix("").as_posix() + ".ai.fixed.csv")
    write_csv(out, headers, rows)
    print(f"[OK] CSV corrigido/IA: {out} (linhas: {len(rows)})")

if __name__ == "__main__":
    sys.exit(main())
