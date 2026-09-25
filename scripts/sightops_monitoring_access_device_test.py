from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path


def _shim_broken_olt_service() -> None:
    """app/cli/tools/olt_4840e_collect_macs.py esta com um refactor incompleto
    (varios nomes que app/services/olt_service.py e app/cli/tools/olt_vsol_epon.py
    esperam importar nao existem mais no arquivo) -- isso e trabalho de terceiros
    em andamento, sem relacao com Controle de Acesso/WhatsApp, e nao deve ser
    tocado aqui. refresh_from_inventory() importa app.services.olt_service so
    para o bloco de OLT/ONU (fora do escopo deste teste), entao "pre-populamos"
    esse modulo no sys.modules com um shim minimo antes de importar qualquer
    coisa -- isso evita que o Python execute a cadeia de import quebrada, sem
    tocar em nenhum arquivo real. Se este shim comecar a falhar porque
    refresh_from_inventory() passou a depender de mais funcoes de list_macs,
    isso e sinal de que o bloco de OLT mudou -- nao que este teste esta errado.
    """
    if "app.services.olt_service" in sys.modules:
        return
    fake = types.ModuleType("app.services.olt_service")
    fake.list_macs = lambda *a, **k: {"rows": []}
    sys.modules["app.services.olt_service"] = fake


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _shim_broken_olt_service()

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-monitoring-access.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-monitoring-access-test-key"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.db_store import init_db
        from app.services.access_control_store import (
            ensure_access_control_schema,
            save_device,
            update_device_health,
        )
        from app.services.monitoring_service import list_entities, refresh_from_inventory

        init_db()
        token = set_current_tenant_slug("escola-monitoring-test")
        try:
            ensure_access_control_schema()

            # save_device() nao aceita "status" no payload -- o schema grava
            # sempre o default ('unknown') na criacao; status so muda via
            # update_device_health(), do mesmo jeito que o poll real (Task 1)
            # e o botao "Testar" fazem.
            online = save_device({"name": "Portaria Online", "site": "ESCOLA", "host": "10.10.13.10"})
            update_device_health(online["id"], status="online")
            offline = save_device({"name": "Portaria Offline", "site": "ESCOLA", "host": "10.10.13.11"})
            update_device_health(offline["id"], status="offline")

            # DEFAULT_PROFILES usa threshold=2 pra access_device (mesmo valor
            # de olt/connector/etc, ver monitoring_service.py) -- a maquina de
            # histerese em _observe_entity_on so marca "down" na SEGUNDA
            # observacao consecutiva de falha (a primeira vira "unstable", pra
            # nao alarmar por uma falha isolada/transitoria). Chamar duas vezes
            # reproduz o comportamento real de dois ciclos consecutivos do loop
            # de fundo com a controladora ainda offline.
            refresh_from_inventory()
            refresh_from_inventory()

            rows = list_entities(entity_type="access_device")
            assert len(rows) == 2, f"esperado 2 controladoras monitoradas, veio {len(rows)}"
            by_name = {r["display_name"]: r["status"] for r in rows}
            assert by_name.get("Portaria Online") == "up", by_name
            assert by_name.get("Portaria Offline") == "down", by_name
            print("OK: controladoras aparecem em monitoring_entities com status certo")
        finally:
            reset_current_tenant_slug(token)


if __name__ == "__main__":
    main()
