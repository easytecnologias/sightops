# patch_fabricante.py — adiciona "fabricante" no CSV, XLSX e CLI sem quebrar a lógica
from pathlib import Path
import re

root = Path(__file__).resolve().parent
pkg = root / "camsnapshot"

targets = {
    "utils": pkg / "utils.py",
    "device_info": pkg / "device_info.py",
    "export_xlsx": pkg / "export_xlsx.py",
    "post_csv": pkg / "post_csv.py",
    "cli": pkg / "cli.py",
}

def read(p): return p.read_text(encoding="utf-8", errors="ignore")
def write(p, t): p.write_text(t, encoding="utf-8")

# 1) utils.py → CSV_FIELDS inclui fabricante após modelo
u = read(targets["utils"])
if "CSV_FIELDS" in u and "fabricante" not in u:
    u = u.replace(
        'CSV_FIELDS = ["ip", "mac", "modelo", "titulo", "snapshot_path", "status"]',
        'CSV_FIELDS = ["ip", "mac", "modelo", "fabricante", "titulo", "snapshot_path", "status"]'
    )
    write(targets["utils"], u)

# 2) device_info.py → helpers + preencher fabricante no probe_device()
d = read(targets["device_info"])
if "_clean_brand" not in d:
    ins_after = d.find("MAC_RE")
    if ins_after != -1:
        nl = d.find("\n", ins_after)
        helpers = (
            '\nBRAND_MAP = {\n'
            '    "intelbras": "Intelbras",\n'
            '    "hikvision": "Hikvision",\n'
            '    "hilook": "HiLook",\n'
            '    "dahua": "Dahua",\n'
            '    "hua": "Dahua",\n'
            '    "axis": "Axis",\n'
            '    "tp-link": "TP-Link",\n'
            '    "tplink": "TP-Link",\n'
            '}\n\n'
            'def _clean_brand(s: str):\n'
            '    if not s:\n'
            '        return None\n'
            '    s = s.strip().strip("\\\"\'")\n'
            '    s = re.sub(r"[^A-Za-z0-9\\- ]+", "", s)\n'
            '    s_low = s.lower()\n'
            '    for k, v in BRAND_MAP.items():\n'
            '        if k in s_low:\n'
            '            return v\n'
            '    return s.title() if s else None\n\n'
            'def _brand_from_model(model: str | None) -> str | None:\n'
            '    if not model:\n'
            '        return None\n'
            '    m = model.upper()\n'
            '    if m.startswith(("VIP", "MIB", "VHD", "MHD")):\n'
            '        return "Intelbras"\n'
            '    if m.startswith(("IPC", "DHI", "DH-", "HFW", "HDP")):\n'
            '        return "Dahua"\n'
            '    if m.startswith(("DS-", "HWI", "HWP", "HK")):\n'
            '        return "Hikvision"\n'
            '    if "HILOOK" in m:\n'
            '        return "HiLook"\n'
            '    return None\n\n'
            'def _extract_brand_from_text(txt: str) -> str | None:\n'
            '    if not txt:\n'
            '        return None\n'
            '    for line in txt.splitlines():\n'
            '        low = line.lower()\n'
            '        if any(k in low for k in ("brand", "vendor", "manufacturer", "oem")):\n'
            '            if "=" in line:\n'
            '                val = line.split("=", 1)[1]\n'
            '            else:\n'
            '                val = line.split(":", 1)[-1]\n'
            '            brand = _clean_brand(val)\n'
            '            if brand:\n'
            '                return brand\n'
            '    return None\n'
        )
        d = d[:nl+1] + helpers + d[nl+1:]
# — patch na função probe_device
if 'def probe_device(' in d:
    s = d.find('def probe_device(')
    e = d.find('\ndef get_mac_http', s)
    if e == -1: e = len(d)
    blk = d[s:e]
    if '"fabricante"' not in blk:
        blk = blk.replace(
            'info = {"ip": ip, "modelo": None, "titulo": None}',
            'info = {"ip": ip, "modelo": None, "fabricante": None, "titulo": None}'
        )
    if 'info["fabricante"]' not in blk:
        blk = blk.replace(
            "txt = _get_text(model_urls, user, password, timeout, retries)",
            "txt = _get_text(model_urls, user, password, timeout, retries)\n    if txt:\n        info[\"fabricante\"] = _extract_brand_from_text(txt)"
        )
    if '_brand_from_model(guess)' not in blk:
        blk = blk.replace(
            '                info["modelo"] = guess',
            '                info["modelo"] = guess\n                if not info.get("fabricante"):\n                    info["fabricante"] = _brand_from_model(guess)'
        )
    if "return info" in blk and "_extract_brand_from_text(txt)" not in blk:
        blk = blk.replace(
            "    return info",
            "    if not info.get(\"fabricante\"):\n        info[\"fabricante\"] = _brand_from_model(info.get(\"modelo\")) or _extract_brand_from_text(txt)\n    return info"
        )
    d = d[:s] + blk + d[e:]
# corrige qualquer aspas malformada de tentativa anterior
d = d.replace("s = s.strip().strip('\"\\' )", "s = s.strip().strip(\"'\\\"\")")
write(targets["device_info"], d)

# 3) export_xlsx.py → ordem + largura com fabricante
if targets["export_xlsx"].exists():
    e = read(targets["export_xlsx"])
    if "fabricante" not in e:
        e = e.replace(
            'base_order = ["ip","mac","modelo","titulo","snapshot_path","status"]',
            'base_order = ["ip","mac","modelo","fabricante","titulo","snapshot_path","status"]'
        )
        e = e.replace(
            '"modelo":16,"titulo":28,"snapshot_path":30,',
            '"modelo":16,"fabricante":16,"titulo":28,"snapshot_path":30,'
        )
        write(targets["export_xlsx"], e)

# 4) post_csv.py → ordenação inclui fabricante
if targets["post_csv"].exists():
    p = read(targets["post_csv"])
    p = p.replace(
        'wanted = ["ip","mac","modelo","titulo","snapshot_path","status"]',
        'wanted = ["ip","mac","modelo","fabricante","titulo","snapshot_path","status"]'
    )
    write(targets["post_csv"], p)

# 5) cli.py → garante fabricante antes de salvar
c = read(targets["cli"])
if "_brand_from_model_cli" not in c:
    c = c.replace(
        "console = Console()",
        "console = Console()\n\ndef _brand_from_model_cli(model):\n"
        "    if not model:\n"
        "        return None\n"
        "    m = str(model).upper()\n"
        "    if m.startswith((\"VIP\",\"MIB\",\"VHD\",\"MHD\")):\n"
        "        return \"Intelbras\"\n"
        "    if m.startswith((\"IPC\",\"DHI\",\"DH-\",\"HFW\",\"HDP\")):\n"
        "        return \"Dahua\"\n"
        "    if m.startswith((\"DS-\",\"HWI\",\"HWP\",\"HK\")) or \"HIKVISION\" in m:\n"
        "        return \"Hikvision\"\n"
        "    if \"HILOOK\" in m:\n"
        "        return \"HiLook\"\n"
        "    return None"
    )
# após probe_device, garante data['fabricante']
c = c.replace(
    'data["titulo"] = info.get("titulo")',
    'data["titulo"] = info.get("titulo")\n                data["fabricante"] = info.get("fabricante") or _brand_from_model_cli(info.get("modelo"))'
)
c = c.replace(
    "resultados.append(data)",
    "if 'fabricante' not in data:\n                data['fabricante'] = _brand_from_model_cli(data.get('modelo'))\n            resultados.append(data)"
)
write(targets["cli"], c)

print("OK: patches aplicados. Agora execute o run_all.py normalmente.")
