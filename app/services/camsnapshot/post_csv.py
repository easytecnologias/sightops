# camsnapshot/post_csv.py (v1.11  ordenar IP + colocar status antes do ping)
import pandas as pd
import ipaddress

def tidy_inventory(csv_path: str):
    df = pd.read_csv(csv_path, encoding="utf-8")

    # ordenar por IP
    if "ip" in df.columns:
        df["_ip_num"] = df["ip"].apply(lambda x: int(ipaddress.ip_address(str(x).strip())))
        df = df.sort_values("_ip_num").drop(columns=["_ip_num"])

    # ordem preferida para as colunas "base"
wanted = ["ip","mac","fabricante","modelo","titulo","snapshot_path","status"]

def reorder_rows(rows):
    """
    Reordena as colunas preservando extras (snapshot_url, thumb_url, etc.).
    Se 'fabricante' não existir numa linha, cria vazio.
    """
    # cabeçalho base com fabricante após modelo
    base = list(wanted)
    seen = set(base)
    extras = []
    for r in rows or []:
        for k in (r or {}).keys():
            if k not in seen:
                extras.append(k); seen.add(k)

    # preferências para extras
    prefer = ["snapshot_url","thumb_url"]
    ordered_extras = [k for k in prefer if k in extras] + [k for k in extras if k not in prefer]
    header = base + ordered_extras

    out = []
    for r in rows or []:
        r = dict(r or {})
        if "fabricante" not in r or r["fabricante"] in (None,""):
            try:
                from .cli import _brand_from_model_cli
                r["fabricante"] = _brand_from_model_cli(r.get("modelo")) or ""
            except Exception:
                r["fabricante"] = ""
        out.append({k: r.get(k, "") for k in header})
    return header, out


    # deduplicar por IP
    df = df.drop_duplicates(subset=["ip"], keep="first")
    df.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"[Ordenação] CSV ordenado por IP e colunas reordenadas: {csv_path}")
