"""Cliente fantasma nao pode entrar na lista de monitoramento.

Caso real (2026-09-23): a migracao gravou o slug "easy-tecnologias" (nome do
cliente) em monitoring_profiles, mas o cadastro so tem "default". Os loops de
fundo passaram a monitorar esse cliente inexistente: 1.397 entidades
duplicadas, 16 grupos no Zabbix e o dobro de trabalho sobre o mesmo inventario.

Roda: python scripts/sightops_tenant_fantasma_test.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import db_store, monitoring_service


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="sightops-fantasma-", ignore_cleanup_errors=True) as tmp:
        db_store.SIGHTOPS_DB_PATH = Path(tmp) / "t.db"
        db_store.init_db()
        with db_store._conn() as c:
            for slug in ("default", "rads", "easy-tecnologias"):
                c.execute(
                    "INSERT INTO monitoring_profiles(tenant_slug, profile_key, name, entity_type) VALUES(?,?,?,?)",
                    (slug, "camera-padrao", "Camera padrao", "camera"),
                )

        # cadastro real tem so default e rads
        with patch("app.services.auth_store.existing_tenant_slugs", return_value={"default", "rads"}):
            slugs = monitoring_service.list_monitoring_tenants()
        assert slugs == ["default", "rads"], slugs
        assert "easy-tecnologias" not in slugs

        # cadastro vazio ou ilegivel: nao inventa filtro, devolve o que achou
        with patch("app.services.auth_store.existing_tenant_slugs", return_value=set()):
            slugs = monitoring_service.list_monitoring_tenants()
        assert "easy-tecnologias" in slugs, slugs

        with patch("app.services.auth_store.existing_tenant_slugs", side_effect=RuntimeError("banco fora")):
            slugs = monitoring_service.list_monitoring_tenants()
        assert "easy-tecnologias" in slugs, slugs

        # nunca devolve lista vazia (o loop pararia de monitorar tudo)
        with patch("app.services.auth_store.existing_tenant_slugs", return_value={"outro-cliente"}):
            slugs = monitoring_service.list_monitoring_tenants()
        assert slugs == ["default"], slugs
    print("OK cliente fantasma: fica de fora do monitoramento; sem cadastro legivel, nada muda")


if __name__ == "__main__":
    main()
