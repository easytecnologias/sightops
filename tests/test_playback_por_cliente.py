"""Clipe exportado fica na pasta do cliente e so sai para ele."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.endpoints import playback as P
from app.core import tenant_context as TC
from app.services import recorder_media_service as M


@pytest.fixture
def clientes(monkeypatch, tmp_path):
    monkeypatch.setattr(TC, "DATA_DIR", tmp_path)
    token = TC.set_current_tenant_slug("cliente-a")
    yield tmp_path
    TC.reset_current_tenant_slug(token)


def test_pasta_e_do_cliente(clientes):
    assert M.export_dir() == clientes / "tenants" / "cliente-a" / "playback_exports"


def test_arquivo_de_outro_cliente_da_404(clientes):
    (M.export_dir() / "gravador_1.mp4").write_bytes(b"video")
    assert str(P.get_playback_file("gravador_1.mp4").path).endswith("gravador_1.mp4")
    token = TC.set_current_tenant_slug("cliente-b")
    try:
        with pytest.raises(HTTPException) as exc:
            P.get_playback_file("gravador_1.mp4")
        assert exc.value.status_code == 404
    finally:
        TC.reset_current_tenant_slug(token)
