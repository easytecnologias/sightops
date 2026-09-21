from __future__ import annotations
import csv, os, subprocess, re, sys
from typing import List, Dict

def _run_ping_win(ip: str, timeout_ms: int = 1000) -> int | None:
    """
    Executa ping no Windows: 1 pacote, timeout configurável.
    Retorna tempo em ms (int) ou None se falhar.
    """
    try:
        # -n 1 => 1 pacote | -w timeout_ms
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), ip],
            capture_output=True, text=True, encoding="utf-8", errors="ignore"
        )
        out = (result.stdout or "") + "\n" + (result.stderr or "")
        # Procura padrões: time=XXms | tempo=XXms | time<1ms | Approximate round trip times ...
        m = re.search(r"time[=<]\s*(\d+)\s*ms", out, re.IGNORECASE)
        if not m:
            m = re.search(r"tempo[=<]\s*(\d+)\s*ms", out, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # "time<1ms" ou "tempo<1ms"
        if re.search(r"time<\s*1ms", out, re.IGNORECASE) or re.search(r"tempo<\s*1ms", out, re.IGNORECASE):
            return 1
        # Em PT-BR, resumo: "Mínimo = Xms, Máximo = Yms, Média = Zms"
        m = re.search(r"M[eé]dia\s*=\s*(\d+)\s*ms", out, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # Em EN: "Minimum = Xms, Maximum = Yms, Average = Zms"
        m = re.search(r"Average\s*=\s*(\d+)\s*ms", out, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None
    except Exception:
        return None

def add_ping_to_csv(csv_path: str, timeout_ms: int = 1000) -> None:
    """
    Abre o inventário, adiciona/atualiza a coluna 'ping' para linhas com status 'online'.
    Salva de volta no mesmo arquivo.
    """
    if not os.path.isfile(csv_path):
        print(f"[PING] CSV não encontrado: {csv_path}")
        return

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = list(reader)
        if not rows:
            print("[PING] CSV vazio.")
            return
        fieldnames = list(reader.fieldnames or [])

    if "ping" not in fieldnames:
        fieldnames.append("ping")

    # Atualiza somente online
    for r in rows:
        status = (r.get("status") or "").strip().lower()
        ip = (r.get("ip") or "").strip()
        if status == "online" and ip:
            ms = _run_ping_win(ip, timeout_ms=timeout_ms)
            if ms is None:
                r["ping"] = ""
            else:
                r["ping"] = f"{ms} ms"
        else:
            r.setdefault("ping", "")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print("[PING] Coluna 'ping' preenchida para IPs online.")
