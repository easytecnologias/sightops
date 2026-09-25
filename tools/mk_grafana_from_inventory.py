#!/usr/bin/env python3
"""
mk_grafana_from_inventory.py
- Cria/atualiza pasta e dashboards no Grafana via HTTP API.
- Objetivo: operador do cam-snapshot-web não precisa saber Grafana — só clicar "Criar/Atualizar Dashboards".

Requisitos:
- Token (Service Account) com permissão de: folders:write, dashboards:write (ou Admin).
- Grafana com plugin Zabbix já instalado/configurado (datasource "Zabbix" ou UID informado).

Observação: Esta versão (v1) cria dashboards "skeleton" (estrutura), para evoluirmos as queries depois.
"""

import os, sys, json, re, requests
from typing import Any, Dict, Optional, List

GRAFANA_URL = os.getenv("GRAFANA_URL", "").rstrip("/")
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN", "").strip()
CLIENT = os.getenv("GRAFANA_CLIENT", "Cliente").strip() or "Cliente"
ZBX_GROUP = os.getenv("GRAFANA_ZBX_GROUP", "").strip()
DATASOURCE = os.getenv("GRAFANA_DATASOURCE", "Zabbix").strip() or "Zabbix"

DASH_COMPLETO = os.getenv("GRAFANA_DASH_COMPLETO", "1") == "1"
DASH_STATUS = os.getenv("GRAFANA_DASH_STATUS", "0") == "1"
DASH_ESTABILIDADE = os.getenv("GRAFANA_DASH_ESTABILIDADE", "0") == "1"
DASH_HISTORICO = os.getenv("GRAFANA_DASH_HISTORICO", "0") == "1"

TIMEZONE = "browser"

def die(msg: str, code: int = 2):
    print("ERRO:", msg)
    sys.exit(code)

def api(method: str, path: str, payload: Optional[dict]=None) -> Any:
    if not GRAFANA_URL:
        die("GRAFANA_URL vazio")
    if not GRAFANA_TOKEN:
        die("GRAFANA_TOKEN vazio")

    url = GRAFANA_URL + path
    headers = {
        "Authorization": f"Bearer {GRAFANA_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    r = requests.request(method, url, headers=headers, json=payload, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
    if r.text.strip() == "":
        return None
    return r.json()

def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "cliente"

def find_folder_by_title(title: str) -> Optional[dict]:
    # /api/search?type=dash-folder&query=...
    res = api("GET", f"/api/search?type=dash-folder&query={requests.utils.quote(title)}")
    for it in res or []:
        if (it.get("title") or "").strip().lower() == title.strip().lower():
            return it
    return None

def get_folder(uid: str) -> dict:
    return api("GET", f"/api/folders/{uid}")

def create_folder(title: str) -> dict:
    return api("POST", "/api/folders", {"title": title})

def upsert_dashboard(folder_uid: str, dash: dict, overwrite: bool=True) -> dict:
    payload = {"dashboard": dash, "folderUid": folder_uid, "overwrite": overwrite}
    return api("POST", "/api/dashboards/db", payload)

def text_panel(pid: int, title: str, text: str, y: int, h: int=6, w: int=24) -> dict:
    return {
        "id": pid,
        "type": "text",
        "title": title,
        "gridPos": {"x": 0, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": text},
        "transparent": True,
    }

def stat_placeholder_panel(pid: int, title: str, y: int, x: int, w: int=6, h: int=5) -> dict:
    # Painel "stat" sem query (placeholder) para garantir import sempre.
    return {
        "id": pid,
        "type": "stat",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [],
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
        "fieldConfig": {"defaults": {"unit": "none"}, "overrides": []},
    }

def build_dashboard_completo_v1(title: str) -> dict:
    # Estrutura do "Dashboard Completo – v1" (skeleton).
    panels: List[dict] = []
    y = 0
    pid = 1
    header = f"""# ✅ {title}

**Criado automaticamente pelo cam-snapshot-web.**  
Este é o *Dashboard Completo (v1)*: visão rápida do ambiente.

- Cliente: **{CLIENT}**
- Grupo Zabbix: **{ZBX_GROUP or '(não informado)'}**
- Datasource: **{DATASOURCE}**

> Próximo passo: na v1.1 vamos plugar as métricas do Zabbix nestes blocos (sem mudar a interface do operador).
"""
    panels.append(text_panel(pid, "Sobre", header, y=y, h=7)); pid += 1
    y += 7

    # Resumo geral (4 cards)
    panels.append(stat_placeholder_panel(pid, "Total de câmeras", y, x=0)); pid += 1
    panels.append(stat_placeholder_panel(pid, "Online", y, x=6)); pid += 1
    panels.append(stat_placeholder_panel(pid, "Offline", y, x=12)); pid += 1
    panels.append(stat_placeholder_panel(pid, "Última atualização", y, x=18)); pid += 1
    y += 5

    # Seções (placeholders)
    panels.append(text_panel(pid, "Câmeras com problema", "Aqui vai entrar a lista de câmeras offline/instáveis.", y=y, h=5)); pid += 1
    y += 5
    panels.append(text_panel(pid, "Estabilidade", "Aqui vai entrar latência / perda de pacotes (rede x câmera).", y=y, h=5)); pid += 1
    y += 5
    panels.append(text_panel(pid, "Histórico recente", "Aqui vai entrar o histórico de quedas (24h / 7d).", y=y, h=5)); pid += 1

    return {
        "title": title,
        "tags": ["cam-snapshot", "v1", slugify(CLIENT)],
        "timezone": TIMEZONE,
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "panels": panels,
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "annotations": {"list": []},
    }

def build_simple_dashboard_v1(title: str, kind: str) -> dict:
    panels = [
        text_panel(1, "Sobre", f"# {title}\n\nDashboard **{kind} (v1)** criado automaticamente pelo cam-snapshot-web.\n\n> Vamos evoluir este dashboard nas próximas versões.", y=0, h=7)
    ]
    return {
        "title": title,
        "tags": ["cam-snapshot", "v1", kind, slugify(CLIENT)],
        "timezone": TIMEZONE,
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "panels": panels,
        "time": {"from": "now-6h", "to": "now"},
        "templating": {"list": []},
        "annotations": {"list": []},
    }

def main():
    if not GRAFANA_URL:
        die("GRAFANA_URL não informado")
    if not GRAFANA_TOKEN:
        die("GRAFANA_TOKEN não informado")
    if not CLIENT:
        die("GRAFANA_CLIENT não informado")

    folder_title = f"cam-snapshot · {CLIENT}"
    folder = find_folder_by_title(folder_title)
    if folder:
        fuid = folder.get("uid")
        print(f"ℹ️ Pasta já existe: {folder_title} (uid={fuid})")
        folder_full = get_folder(fuid)
    else:
        folder_full = create_folder(folder_title)
        fuid = folder_full.get("uid")
        print(f"✅ Pasta criada: {folder_title} (uid={fuid})")

    links: List[str] = []
    base_dash_url = GRAFANA_URL  # user will access via browser; ok.

    def mk_and_upsert(dash: dict):
        res = upsert_dashboard(fuid, dash, overwrite=True)
        url = res.get("url") or res.get("slug") or ""
        if url:
            links.append(base_dash_url + url)
        print(f"✅ Dashboard atualizado: {dash['title']}")

    if DASH_COMPLETO:
        mk_and_upsert(build_dashboard_completo_v1(f"{CLIENT} · Completo (v1)"))
    if DASH_STATUS:
        mk_and_upsert(build_simple_dashboard_v1(f"{CLIENT} · Status (v1)", "status"))
    if DASH_ESTABILIDADE:
        mk_and_upsert(build_simple_dashboard_v1(f"{CLIENT} · Estabilidade (v1)", "estabilidade"))
    if DASH_HISTORICO:
        mk_and_upsert(build_simple_dashboard_v1(f"{CLIENT} · Histórico (v1)", "historico"))

    # print links as JSON on stderr? We'll print in stdout marker
    if links:
        print("LINKS_JSON=" + json.dumps(links, ensure_ascii=False))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        die(str(e), 3)
