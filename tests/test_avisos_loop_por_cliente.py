"""A1: erro do Zabbix ou de um cliente nao cala os avisos dos outros.

Tudo falso (sem banco, sem Zabbix, sem Telegram)."""
from __future__ import annotations

import asyncio

import pytest

import app.main as M
from app.core.tenant_context import get_current_tenant_slug
from app.services.zabbix_monitoring_service import ultimo_sync


def _rodar_uma_volta(monkeypatch, loop_fn):
    """Roda o laco ate o primeiro sleep depois da volta."""
    chamadas = {"n": 0}
    real_sleep = asyncio.sleep

    async def sleep_falso(s, *a, **k):
        chamadas["n"] += 1
        if chamadas["n"] > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(M.asyncio, "sleep", sleep_falso)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loop_fn())


def test_telegram_roda_com_zabbix_fora(monkeypatch):
    feito = []

    def zabbix_cai():
        raise RuntimeError("Zabbix fora do ar")

    monkeypatch.setattr(M, "refresh_from_inventory", lambda: {"ok": True, "total": 3})
    monkeypatch.setattr(M, "sync_monitoring_to_zabbix", zabbix_cai)
    monkeypatch.setattr(M, "process_monitoring_notifications",
                        lambda: feito.append(get_current_tenant_slug()) or {"ok": True, "sent": 1})
    r = M._refresh_monitoring_tenant("cliente-a")
    assert feito == ["cliente-a"]
    assert r["telegram"]["sent"] == 1
    assert r["zabbix"]["ok"] is False and "Zabbix fora do ar" in r["erros"]["zabbix"]


def test_inventario_quebrado_ainda_avisa(monkeypatch):
    def cai():
        raise ValueError("banco")

    monkeypatch.setattr(M, "refresh_from_inventory", cai)
    def sync_nao_pode_rodar():
        raise AssertionError("sync enviaria status congelado")

    monkeypatch.setattr(M, "sync_monitoring_to_zabbix", sync_nao_pode_rodar)
    monkeypatch.setattr(M, "process_monitoring_notifications", lambda: {"ok": True, "sent": 0})
    r = M._refresh_monitoring_tenant("cliente-a")
    assert r["telegram"]["ok"] and "banco" in r["erros"]["refresh"]
    # O painel acusa a falha em vez de continuar em "Sincronizado".
    assert r["zabbix"]["ok"] is False
    u = ultimo_sync("cliente-a")
    assert u["ok"] is False and "banco" in u["erro"]


def test_um_cliente_quebrado_nao_para_os_outros(monkeypatch):
    vistos = []

    def refresh(tenant):
        if tenant == "cliente-a":
            raise RuntimeError("explodiu")
        vistos.append(tenant)
        return {"ok": True}

    monkeypatch.setattr(M, "list_monitoring_tenants", lambda: ["cliente-a", "cliente-b"])
    monkeypatch.setattr(M, "_refresh_monitoring_tenant", refresh)
    _rodar_uma_volta(monkeypatch, M._monitoring_refresh_loop)
    last = M.app.state.monitoring_refresh_last
    assert vistos == ["cliente-b"]
    assert last["ok"] is False
    assert "explodiu" in last["tenants"]["cliente-a"]["error"]
    assert last["tenants"]["cliente-b"] == {"ok": True}


def test_rack_links_um_cliente_quebrado(monkeypatch):
    vistos = []

    def coletar(tenant):
        if tenant == "cliente-a":
            raise RuntimeError("switch")
        vistos.append(tenant)
        return {"switches": 1}

    monkeypatch.setattr(M, "list_monitoring_tenants", lambda: ["cliente-a", "cliente-b"])
    monkeypatch.setattr(M, "_coletar_links_tenant", coletar)
    _rodar_uma_volta(monkeypatch, M._rack_links_loop)
    assert vistos == ["cliente-b"]
    assert M.app.state.rack_links_last["tenants"]["cliente-a"]["ok"] is False


def test_zabbix_status_um_cliente_quebrado(monkeypatch):
    vistos = []

    def sync(mode, tenant):
        if tenant == "cliente-a":
            raise RuntimeError("zbx")
        vistos.append((tenant, mode))
        return {"ok": True, "online": 1, "total": 1}

    monkeypatch.setattr(M, "_zabbix_status_tenant_slugs", lambda: ["cliente-a", "cliente-b"])
    monkeypatch.setattr(M, "_run_zabbix_status_sync_for_mode", sync)
    _rodar_uma_volta(monkeypatch, M._zabbix_status_sync_loop)
    last = M.app.state.zabbix_status_last
    assert ("cliente-b", "basic") in vistos
    assert last["tenants"]["cliente-a"]["ok"] is False and last["tenants"]["cliente-b"]["ok"] is True


def test_zabbix_status_excecao_nao_pula_os_outros_modos(monkeypatch):
    vistos = []

    def sync(mode, tenant):
        if mode == "basic":
            raise RuntimeError("zbx")
        vistos.append(mode)
        return {"ok": True, "online": 1, "total": 1}

    monkeypatch.setattr(M, "_zabbix_status_tenant_slugs", lambda: ["cliente-a"])
    monkeypatch.setattr(M, "_run_zabbix_status_sync_for_mode", sync)
    _rodar_uma_volta(monkeypatch, M._zabbix_status_sync_loop)
    assert vistos == ["olt", "switch"]
    assert M.app.state.zabbix_status_last["tenants"]["cliente-a"]["ok"] is False
