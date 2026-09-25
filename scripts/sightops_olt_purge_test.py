"""Testa a fila de exclusao de ONUs offline SEM tocar em equipamento real.

A exclusao (olt_service.delete_onu) e substituida por um duble que registra a
ordem das chamadas e simula sucesso/falha. Prova as propriedades que importam:
  - processa UMA por vez, na ordem enviada;
  - o progresso (done/failed/processed/total) fecha a conta;
  - uma falha nao para a fila -- a proxima segue;
  - ONU sem serial e recusada no enfileiramento, nunca chega a delete_onu;
  - a senha da OLT nunca aparece na resposta das rotas.

Roda direto:  python scripts/sightops_olt_purge_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="olt-purge-test-"))
    os.environ["DATA_DIR"] = str(tmp / "data")
    os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
    os.environ["DATABASE_BACKEND"] = "sqlite"
    os.environ["AUTH_DATABASE_BACKEND"] = "sqlite"
    os.environ["SIGHTOPS_SECRET_KEY"] = "chave-de-teste"
    os.environ["AUTH_ENABLED"] = "0"
    os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
    os.environ.pop("DATABASE_URL", None)

    from fastapi.testclient import TestClient
    import app.api.endpoints.olt as olt_ep
    from app.services import db_store, olt_registry
    import app.main as m

    db_store.init_db()

    # cadastra uma OLT FiberHome de teste (host inalcancavel de proposito -- o
    # delete e simulado, nunca chega na rede)
    from app.core.tenant_context import set_current_tenant_slug, reset_current_tenant_slug
    tok = set_current_tenant_slug("default")
    try:
        olt = olt_registry.save_olt({
            "name": "OLT SIERRA (teste)", "host": "10.255.255.1",
            "vendor": "FiberHome", "model": "AN5516-06",
            "username": "admin", "password": "segredo-nunca-vaza",
        })
        olt_id = olt["id"]
    finally:
        reset_current_tenant_slug(tok)

    # duble de delete_onu: registra ordem e simula. PON 6 falha de proposito.
    chamadas: list[tuple[int, int, str]] = []

    def fake_delete_onu(req):
        chamadas.append((int(req.pon), int(req.onu), str(req.serial)))
        # a OLT so aceita uma sessao por vez -- se duas rodassem juntas, o teste
        # de ordem pegaria intercalacao. Simulamos trabalho.
        time.sleep(0.01)
        if int(req.pon) == 6:
            return {"ok": False, "error": "PON 6 recusou (simulado)"}
        return {"ok": True}

    olt_ep.delete_onu = fake_delete_onu  # o worker chama olt_ep.delete_onu

    with TestClient(m.app) as c:
        # 4 validos (um deles PON 6 = falha simulada) + 1 sem serial (recusado)
        payload = {"items": [
            {"pon": 4, "onu": 5, "serial": "AAA111"},
            {"pon": 6, "onu": 55, "serial": "BBB222"},
            {"pon": 7, "onu": 118, "serial": "CCC333"},
            {"pon": 6, "onu": 23, "serial": "DDD444"},
            {"pon": 9, "onu": 9, "serial": ""},        # sem serial -> recusado
        ]}
        r = c.post(f"/api/olt/registry/{olt_id}/purge", json=payload)
        check(r.status_code == 200, f"enfileirar falhou: {r.status_code} {r.text[:200]}")
        check("segredo-nunca-vaza" not in r.text, "A SENHA VAZOU na resposta de enfileirar")
        job = r.json()
        check(job.get("status") == "running", f"deveria iniciar running: {job}")
        check(job.get("total") == 5, f"total deveria ser 5 (itens enviados): {job}")
        check(job.get("failed") == 1, f"o item sem serial deveria ja contar como falha: {job}")

        # aguarda a fila terminar (polling, como o frontend faz)
        final = {}
        for _ in range(100):
            s = c.get(f"/api/olt/registry/{olt_id}/purge-status")
            final = s.json()
            check("segredo-nunca-vaza" not in s.text, "A SENHA VAZOU no status")
            if final.get("status") in ("done", "error"):
                break
            time.sleep(0.05)

        check(final.get("status") == "done", f"fila deveria terminar 'done': {final}")
        # 4 validos chegaram ao delete, na ordem; o sem-serial nunca chamou
        check(chamadas == [(4, 5, "AAA111"), (6, 55, "BBB222"), (7, 118, "CCC333"), (6, 23, "DDD444")],
              f"ordem/conteudo das chamadas errado: {chamadas}")
        check(all(s != "" for _, _, s in chamadas), "delete_onu foi chamado sem serial")
        # progresso final: 2 sucesso (PON 4 e 7), 3 falha (2x PON 6 + sem serial)
        check(final.get("done") == 2, f"done deveria ser 2: {final}")
        check(final.get("failed") == 3, f"failed deveria ser 3 (2 PON6 + sem serial): {final}")
        check(final.get("processed") == 5, f"processed deveria ser 5: {final}")
        check(len(final.get("results", [])) == 5, f"deveria ter 5 resultados: {final}")
        # a falha do meio nao parou a fila: PON 7 (depois do PON 6) foi processado
        pon7 = [x for x in final.get("results", []) if x.get("pon") == 7]
        check(pon7 and pon7[0].get("ok") is True, "PON 7 (apos a falha) deveria ter sido excluido")

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print("  -", f)
        raise SystemExit(1)
    print("OK fila de exclusao: serial obrigatorio, ordem preservada, falha nao para a fila, senha nao vaza")


if __name__ == "__main__":
    main()
