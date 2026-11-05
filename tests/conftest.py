"""Nenhum teste dispara o aviso do Alerta em thread solta: ela sobreviveria ao
banco temporario do teste e cairia no banco/Telegram do ambiente."""
from __future__ import annotations

import pytest

from app.services import alert_store


@pytest.fixture(autouse=True)
def _alerta_sem_thread_de_aviso(monkeypatch):
    monkeypatch.setattr(alert_store, "notify_async", lambda tenant, incident_id, reason: None)
