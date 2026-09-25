"""Confere que o provider volta a ser lido da configuracao salva, com
cloud_api como default seguro (nunca evolution sem escolha explicita), e
que o nome de instancia do Evolution e unico por tenant+site (nao uma
string fixa, que colidiria no container compartilhado entre clientes).

Roda direto: python scripts/sightops_whatsapp_evolution_provider_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-whatsapp-provider.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-whatsapp-provider-test-key"
        os.environ["SIGHTOPS_EVOLUTION_URL"] = "http://evolution.teste:8090"
        os.environ["SIGHTOPS_EVOLUTION_API_KEY"] = "chave-teste"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.access_control_notifications import (
            _whatsapp_provider,
            _evolution_platform_cfg,
            _evolution_default_instance,
        )

        assert _whatsapp_provider({}) == "cloud_api", "config vazia tem que cair em cloud_api"
        assert _whatsapp_provider({"provider": "cloud_api"}) == "cloud_api"
        assert _whatsapp_provider({"provider": "EVOLUTION"}) == "evolution", "provider deve ser normalizado (case-insensitive)"
        assert _whatsapp_provider({"provider": "algo-invalido"}) == "cloud_api", "provider desconhecido tem que cair em cloud_api, nunca evolution"

        plataforma = _evolution_platform_cfg()
        assert plataforma["base_url"] == "http://evolution.teste:8090", plataforma
        assert plataforma["api_key"] == "chave-teste", plataforma

        token = set_current_tenant_slug("escola-testes")
        try:
            assert _evolution_default_instance("") == "escola-testes-padrao"
            assert _evolution_default_instance("Unidade Centro") == "escola-testes-unidade-centro"
        finally:
            reset_current_tenant_slug(token)

    print("whatsapp evolution provider regression ok")


if __name__ == "__main__":
    main()
