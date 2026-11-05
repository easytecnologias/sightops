"""E7: versao do app vem da tag da imagem no ar."""
from __future__ import annotations

import pytest

from app.core import settings as S


@pytest.fixture(autouse=True)
def _limpa(monkeypatch):
    for nome in ("APP_VERSION", "SIGHTOPS_IMAGE_TAG", "CAM_SNAPSHOT_IMAGE"):
        monkeypatch.delenv(nome, raising=False)


def test_padrao_continua_1_1_0():
    assert S._app_version() == "1.1.0"


def test_tag_da_imagem(monkeypatch):
    monkeypatch.setenv("CAM_SNAPSHOT_IMAGE", "sightops-prod-api:20261104-maquete-assinatura")
    assert S._app_version() == "20261104-maquete-assinatura"
    monkeypatch.setenv("CAM_SNAPSHOT_IMAGE", "localhost:5000/sightops-prod-api")
    assert S._app_version() == "1.1.0"   # porta do registry nao e tag


def test_ordem_de_preferencia(monkeypatch):
    monkeypatch.setenv("CAM_SNAPSHOT_IMAGE", "x:imagem")
    monkeypatch.setenv("SIGHTOPS_IMAGE_TAG", "tag-build")
    assert S._app_version() == "tag-build"
    monkeypatch.setenv("APP_VERSION", "2.0.0")
    assert S._app_version() == "2.0.0"
