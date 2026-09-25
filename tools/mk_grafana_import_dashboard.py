#!/usr/bin/env python3
"""Importa/atualiza o dashboard padrão do projeto no Grafana.

Uso (via env vars):
  GRAFANA_URL=http://10.10.12.50:3000
  GRAFANA_API_KEY=... (API Key)
  GRAFANA_FOLDER_UID=... (opcional)
  GRAFANA_OVERWRITE=1|0

Este script foi criado para o fluxo do cam-snapshot-web:
Scripts -> Zabbix -> (opcional) Grafana.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

import requests


def build_dashboard() -> Dict[str, Any]:
    """Dashboard enxuto baseado no JSON final do usuário.

    Notas:
    - Não gravamos a lista gigante de 'current' em variáveis; o Grafana irá
      preencher pelo datasource Zabbix.
    - Mantém uid, título, variáveis GRUPO/CAMERAS e os paineis principais.
    """

    ds = {"type": "alexanderzobnin-zabbix-datasource", "uid": "ff9vhy5oekn40b"}

    def zbx_target(group_var: str = "$GRUPO", host_var: str = "$CAMERAS", item: str = "ICMP ping", ref: str = "A", query_type: str = "0"):
        return {
            "application": {"filter": ""},
            "countTriggersBy": "",
            "datasource": ds,
            "evaltype": "0",
            "functions": [],
            "group": {"filter": group_var},
            "host": {"filter": host_var},
            "item": {"filter": item},
            "itemTag": {"filter": ""},
            "macro": {"filter": ""},
            "options": {
                "count": False,
                "disableDataAlignment": False,
                "showDisabledItems": False,
                "skipEmptyValues": False,
                "useTrends": "default",
                "useZabbixValueMapping": False,
            },
            "proxy": {"filter": ""},
            "queryType": query_type,
            "refId": ref,
            "resultFormat": "time_series",
            "schema": 12,
            "table": {"skipEmptyValues": False},
            "tags": {"filter": ""},
            "textFilter": "",
            "trigger": {"filter": ""},
        }

    panel_online = {
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "dark-red", "value": 0},
                        {"color": "dark-green", "value": 1},
                    ],
                },
            },
            "overrides": [],
        },
        "gridPos": {"h": 4, "w": 7, "x": 0, "y": 0},
        "id": 39,
        "options": {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "value",
            "wideLayout": True,
        },
        "pluginVersion": "10.4.8",
        "targets": [zbx_target()],
        "title": "CAMERAS ONLINE",
        "transformations": [
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}},
            {
                "id": "calculateField",
                "options": {
                    "alias": "online",
                    "mode": "reduceRow",
                    "reduce": {"reducer": "sum"},
                    "replaceFields": True,
                },
            },
        ],
        "type": "stat",
    }

    panel_offline = {
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "dark-red", "value": 0},
                    ],
                },
            },
            "overrides": [],
        },
        "gridPos": {"h": 4, "w": 9, "x": 7, "y": 0},
        "id": 51,
        "options": {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "value",
            "wideLayout": True,
        },
        "pluginVersion": "10.4.8",
        "targets": [zbx_target()],
        "title": "CAMERAS OFFLINE",
        "transformations": [
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}},
            {"id": "calculateField", "options": {"alias": "TOTAL", "mode": "reduceRow", "reduce": {"reducer": "count"}}},
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}},
            {"id": "calculateField", "options": {"alias": "ONLINE", "mode": "reduceRow", "reduce": {"reducer": "sum"}}},
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}},
            {
                "id": "calculateField",
                "options": {
                    "alias": "RESUTADO",
                    "binary": {"left": "ONLINE", "operator": "-", "right": "TOTAL"},
                    "mode": "binary",
                },
            },
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}},
            {
                "id": "calculateField",
                "options": {
                    "binary": {"left": "TOTAL", "operator": "-", "right": "RESUTADO"},
                    "mode": "binary",
                    "replaceFields": True,
                },
            },
        ],
        "type": "stat",
    }

    panel_total = {
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "color": {"fixedColor": "green", "mode": "fixed"},
                "mappings": [],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 80}]},
            },
            "overrides": [],
        },
        "gridPos": {"h": 4, "w": 8, "x": 16, "y": 0},
        "id": 21,
        "options": {
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "auto",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "value",
            "wideLayout": True,
        },
        "pluginVersion": "10.4.8",
        "targets": [zbx_target()],
        "title": "TOTAL DE CAMERAS",
        "transformations": [
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}},
            {
                "id": "calculateField",
                "options": {
                    "alias": "total",
                    "mode": "reduceRow",
                    "reduce": {"reducer": "count"},
                    "replaceFields": True,
                },
            },
        ],
        "type": "stat",
    }

    row_cameras = {
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": 4},
        "id": 200,
        "panels": [],
        "title": "CÂMERAS",
        "type": "row",
    }

    panel_card = {
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "color": {"mode": "thresholds"},
                "mappings": [
                    {
                        "options": {
                            "0": {"color": "red", "index": 0, "text": "OFFLINE"},
                            "1": {"color": "green", "index": 1, "text": "ONLINE"},
                        },
                        "type": "value",
                    }
                ],
                "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}]},
            },
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "IP"},
                    "properties": [
                        {"id": "color", "value": {"fixedColor": "transparent", "mode": "fixed"}},
                    ],
                }
            ],
        },
        "gridPos": {"h": 4, "w": 2, "x": 0, "y": 5},
        "id": 201,
        "maxPerRow": 12,
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "center",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/", "values": False},
            "showPercentChange": False,
            "textMode": "value",
            "wideLayout": True,
        },
        "pluginVersion": "10.4.8",
        "repeat": "CAMERAS",
        "repeatDirection": "h",
        "targets": [
            zbx_target(host_var="$CAMERAS", item="ICMP ping", ref="A", query_type="0"),
            zbx_target(host_var="$CAMERAS", item="IP", ref="B", query_type="2"),
        ],
        "title": "$CAMERAS",
        "transformations": [
            {"id": "reduce", "options": {"includeTimeField": False, "mode": "reduceFields", "reducers": ["lastNotNull"]}}
        ],
        "type": "stat",
    }

    dashboard = {
        "annotations": {
            "list": [
                {
                    "builtIn": 1,
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "name": "Annotations & Alerts",
                    "type": "dashboard",
                }
            ]
        },
        "editable": True,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 0,
        "id": None,
        "links": [],
        "panels": [panel_online, panel_offline, panel_total, row_cameras, panel_card],
        "schemaVersion": 39,
        "tags": [],
        "templating": {
            "list": [
                {
                    "allValue": "",
                    "current": {"selected": False, "text": [], "value": []},
                    "datasource": ds,
                    "definition": "Zabbix - group",
                    "hide": 0,
                    "includeAll": False,
                    "multi": True,
                    "name": "GRUPO",
                    "options": [],
                    "query": {
                        "application": "",
                        "group": "/.*/",
                        "host": "",
                        "item": "",
                        "itemTag": "",
                        "queryType": "group",
                    },
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": False,
                    "sort": 0,
                    "type": "query",
                },
                {
                    "current": {"selected": False, "text": [], "value": []},
                    "datasource": ds,
                    "definition": "Zabbix - host",
                    "hide": 0,
                    "includeAll": False,
                    "multi": True,
                    "name": "CAMERAS",
                    "options": [],
                    "query": {
                        "application": "",
                        "group": "$GRUPO",
                        "host": "/.*./",
                        "item": "",
                        "itemTag": "",
                        "queryType": "host",
                    },
                    "refresh": 1,
                    "regex": "",
                    "skipUrlSync": False,
                    "sort": 0,
                    "type": "query",
                },
            ]
        },
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "title": "Câmeras - Status",
        "uid": "cams_status_top10_v1_12col",
        "version": 1,
        "weekStart": "",
    }

    return dashboard


def main() -> int:
    base_url = (os.getenv("GRAFANA_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("GRAFANA_API_KEY") or "").strip()
    folder_uid = (os.getenv("GRAFANA_FOLDER_UID") or "").strip()
    overwrite = (os.getenv("GRAFANA_OVERWRITE") or "1").strip() not in {"0", "false", "False"}

    if not base_url:
        print("ERRO: informe GRAFANA_URL", file=sys.stderr)
        return 2
    if not api_key:
        print("ERRO: informe GRAFANA_API_KEY", file=sys.stderr)
        return 2

    dash = build_dashboard()

    # Para o endpoint /api/dashboards/db, o payload deve ser:
    # {"dashboard": {...}, "overwrite": true, "folderUid": "..."}
    payload: Dict[str, Any] = {"dashboard": dash, "overwrite": overwrite}
    if folder_uid:
        payload["folderUid"] = folder_uid

    url = f"{base_url}/api/dashboards/db"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    except Exception as e:
        print(f"ERRO: falha ao conectar no Grafana: {e}", file=sys.stderr)
        return 3

    if r.status_code >= 300:
        # Grafana costuma devolver json com message
        try:
            err = r.json()
        except Exception:
            err = {"body": r.text}
        print(f"ERRO: Grafana respondeu {r.status_code}: {json.dumps(err, ensure_ascii=False)}", file=sys.stderr)
        return 4

    try:
        out = r.json()
    except Exception:
        out = {"body": r.text}

    # imprime um resumo amigável
    dash_uid = out.get("uid") or dash.get("uid")
    dash_url = out.get("url")
    print("OK: dashboard importado/atualizado")
    if dash_uid:
        print(f"uid={dash_uid}")
    if dash_url:
        print(f"url={dash_url}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
