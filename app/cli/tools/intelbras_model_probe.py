import argparse
import re
import requests


HEADERS = {
    "User-Agent": "cam-snapshot-intelbras-probe/1.0"
}


def safe_get(url, user, password, timeout=3.0):
    """GET simples com tratamento de erro. Nunca levanta exceção pra fora."""
    try:
        auth = (user, password) if user else None
        r = requests.get(url, auth=auth, timeout=timeout, headers=HEADERS)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        return None
    return None


def extract_model_from_text(txt: str) -> str | None:
    """Procura modelo em qualquer texto retornado pela câmera."""
    if not txt:
        return None

    # 1) Linhas com chaves típicas
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue

        if any(k in line for k in ("devType", "DeviceType", "deviceType", "Model", "model")):
            if "=" in line:
                val = line.split("=", 1)[1]
            elif ":" in line:
                val = line.split(":", 1)[1]
            else:
                continue
            val = val.strip().strip('"').strip("'")
            if not val:
                continue

            m = re.search(r"VIP[-\s]?[0-9A-Za-z\-]{2,}", val, re.IGNORECASE)
            if m:
                return m.group(0).replace("  ", " ").upper()
            return val

    # 2) Fallback: qualquer VIP-XXXX no texto inteiro
    m = re.search(r"VIP[-\s]?[0-9A-Za-z\-]{2,}", txt, re.IGNORECASE)
    if m:
        return m.group(0).replace("  ", " ").upper()

    return None


def probe_intelbras_model(ip: str, user: str, password: str) -> str | None:
    """Tenta descobrir o modelo da Intelbras via algumas URLs comuns."""

    # 1) CGIs de sistema
    cgi_urls = [
        f"http://{ip}/cgi-bin/systeminfo.cgi",
        f"http://{ip}/admin/systeminfo.cgi",
        f"http://{ip}/cgi-bin/devType.cgi",
        f"http://{ip}/cgi-bin/param.cgi?get_device_conf",
        f"http://{ip}/request.cgi?cmd=GetDeviceType",
        f"http://{ip}/ajax/getDeviceInfo",
    ]

    for url in cgi_urls:
        txt = safe_get(url, user, password, timeout=3.0)
        if not txt:
            continue
        modelo = extract_model_from_text(txt)
        if modelo:
            print(f"[OK CGI ] {url} -> {modelo}")
            return modelo
        else:
            print(f"[CGI    ] {url} respondeu, mas não achei modelo claro.")

    # 2) Arquivos JS comuns na interface web
    js_candidates = [
        "app.js",
        "rpc.js",
        "rpcBase.js",
        "common.js",
        "plugin.js",
        "index.js",
        "main.js",
    ]

    for js_name in js_candidates:
        url = f"http://{ip}/{js_name}"
        txt = safe_get(url, user, password, timeout=3.0)
        if not txt:
            continue

        # Padrão: deviceType:"VIP-3220-B" ou model='VIP-5450'
        m = re.search(
            r'(deviceType|devType|model|deviceModel)[\"\']?\s*[:=]\s*[\"\']([^\"\']+)[\"\']',
            txt,
            re.IGNORECASE,
        )
        if m:
            val = m.group(2).strip()
            m2 = re.search(r"VIP[-\s]?[0-9A-Za-z\-]{2,}", val, re.IGNORECASE)
            if m2:
                modelo = m2.group(0).replace("  ", " ").upper()
            else:
                modelo = val
            print(f"[OK JS  ] {url} -> {modelo}")
            return modelo

        # fallback: VIP-XXXX em qualquer lugar do JS
        m = re.search(r"VIP[-\s]?[0-9A-Za-z\-]{2,}", txt, re.IGNORECASE)
        if m:
            modelo = m.group(0).replace("  ", " ").upper()
            print(f"[OK JS* ] {url} -> {modelo}")
            return modelo

    print("[WARN] Não consegui descobrir o modelo por CGI/JS.")
    return None


def main():
    parser = argparse.ArgumentParser(description="Probe Intelbras model via CGI/JS")
    parser.add_argument("--ip", required=True, help="IP da câmera Intelbras")
    parser.add_argument("--usuario", "--user", default="admin")
    parser.add_argument("--senha", "--password", default="")
    args = parser.parse_args()

    model = probe_intelbras_model(args.ip, args.usuario, args.senha)
    if model:
        print(f"\nModelo detectado: {model}")
    else:
        print("\nModelo não encontrado.")


if __name__ == "__main__":
    main()
