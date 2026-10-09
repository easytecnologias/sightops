"""Padroniza gravadores para a Investigacao, um a um ou o parque de um cliente.

Sem --aplicar so mostra o diagnostico (nao escreve nada). Com --aplicar,
aplica, le de volta e diz o que nao pegou. Backup da configuracao antes da
mudanca vai para data/tenants/<cliente>/gravador_backups/.

  docker exec -w /app sightops-v3-api python -m app.cli.tools.gravador_padronizar \\
      --tenant default --host 10.10.9.120
  ... --tenant rads --todos --aplicar
"""
from __future__ import annotations

import argparse
import json
import sys

from app.core.tenant_context import set_current_tenant_slug, tenant_recorder_inventory_path, tenant_scoped_path
from app.services.recorder_credentials import resolve_recorder_credential
from app.services.recorder_driver import ErroDriver, Gravador


def _gravadores(tenant: str) -> list:
    vistos, saida = set(), []
    for fonte in ("nvr", "dvr"):
        p = tenant_recorder_inventory_path(fonte, tenant)
        if not p.exists():
            continue
        linhas = json.loads(p.read_text(encoding="utf-8") or "[]")
        for r in linhas if isinstance(linhas, list) else []:
            host = str(r.get("host") or "").strip()
            if host and host not in vistos:
                vistos.add(host)
                saida.append({"host": host, "porta": r.get("http_port") or 80,
                              "conector": r.get("remote_connector_id") or r.get("connector_id") or "",
                              "modelo": r.get("nvr_model") or r.get("modelo") or ""})
    return saida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="slug do cliente (default = Easy)")
    ap.add_argument("--host", action="append", default=[], help="IP do gravador (repetivel)")
    ap.add_argument("--todos", action="store_true", help="todos os gravadores do inventario do cliente")
    ap.add_argument("--aplicar", action="store_true", help="escreve no gravador (sem isto, so diagnostica)")
    a = ap.parse_args()

    set_current_tenant_slug("" if a.tenant == "default" else a.tenant)
    inventario = {g["host"]: g for g in _gravadores(a.tenant)}
    alvos = list(inventario) if a.todos else a.host
    if not alvos:
        ap.error("informe --host ou --todos")

    falhas = 0
    for host in alvos:
        info = inventario.get(host, {"porta": 80, "conector": "", "modelo": ""})
        print(f"\n=== {host} {info['modelo']}")
        cred = resolve_recorder_credential(host, info["porta"]) or {}
        if not cred.get("password"):
            print("  sem senha salva -- pulado")
            falhas += 1
            continue
        try:
            g = Gravador(host, cred.get("username") or "admin", cred["password"], info["porta"], info["conector"])
            d = g.diagnostico()
        except ErroDriver as exc:
            print(f"  {exc}")
            falhas += 1
            continue
        print(f"  marca={d['marca']} canais={d['canais']} relogio={d['relogio']}")
        resumo: dict = {}
        for m in d["mudancas"]:
            chave = m["chave"].split("]", 1)[-1].lstrip(".") or m["chave"]
            resumo.setdefault(f"{chave}: {m['de']} -> {m['para']}", 0)
            resumo[f"{chave}: {m['de']} -> {m['para']}"] += 1
        for linha, n in sorted(resumo.items()):
            print(f"  {n:3d}x {linha}")
        for alerta in d["alertas"]:
            print(f"  ALERTA: {alerta}")
        if not d["mudancas"]:
            print("  ja esta no perfil")
            continue
        if not a.aplicar:
            continue
        r = g.aplicar(d["mudancas"], backup_dir=tenant_scoped_path("gravador_backups", a.tenant))
        print(f"  aplicadas={r['aplicadas']} nao_pegaram={len(r['nao_pegaram'])} backup={r['backup']}")
        for k in r["nao_pegaram"][:20]:
            print(f"    NAO PEGOU: {k}")
        for rec in r["recusas"][:10]:
            print(f"    recusa: {rec}")
        falhas += 0 if r["ok"] else 1
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
