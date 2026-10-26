"""Console de Configuracoes do cliente: saude da configuracao e "falhas seguidas"
por tipo. SQLite temporario; so dados ficticios."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import db_store
from app.services import monitoring_service as M


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    db_store.init_db()
    yield tmp_path


def _como(slug):
    return tenant_context.set_current_tenant_slug(slug)


def _ent(slug, key, tipo, status, hostid="10"):
    with db_store._conn() as c:
        c.execute(
            "INSERT INTO monitoring_entities(tenant_slug, entity_key, entity_type, display_name, status, zabbix_hostid)"
            " VALUES(?,?,?,?,?,?)",
            (slug, key, tipo, key, status, hostid),
        )


def test_saude_conta_so_o_cliente_atual(banco):
    _ent("cliente-a", "cam1", "camera", "up")
    _ent("cliente-a", "cam2", "camera", "down")
    _ent("cliente-a", "cam3", "camera", "unknown", hostid="")
    _ent("cliente-a", "con1", "connector", "up")
    _ent("cliente-b", "cam9", "camera", "down")
    tok = _como("cliente-a")
    try:
        h = M.config_health()
    finally:
        tenant_context.reset_current_tenant_slug(tok)
    assert (h["total"], h["fora"], h["sem_informacao"], h["sem_zabbix"]) == (4, 1, 1, 1)
    assert h["conectores"] == {"up": 1}
    assert h["intervalo_verificacao_s"] == 120  # padrao do laco, nao o do perfil


def test_falhas_seguidas_valida_e_nao_vaza_para_outro_cliente(banco):
    tok = _como("cliente-a")
    try:
        p = M.set_profile_threshold("camera-default", 4)
        assert p["failure_threshold"] == 4 and p["tenant_slug"] == "cliente-a"
        for ruim in (0, 11, "abc", None):
            with pytest.raises(ValueError):
                M.set_profile_threshold("camera-default", ruim)
        with pytest.raises(LookupError):
            M.set_profile_threshold("nao-existe", 3)
    finally:
        tenant_context.reset_current_tenant_slug(tok)
    tok = _como("cliente-b")
    try:
        outro = {p["profile_key"]: p["failure_threshold"] for p in M.list_profiles()}
    finally:
        tenant_context.reset_current_tenant_slug(tok)
    assert outro["camera-default"] == 2


def test_limiar_novo_vale_na_proxima_verificacao(banco):
    tok = _como("cliente-a")
    try:
        M.set_profile_threshold("camera-default", 3)
        # Falha isolada nao gera evento (histerese, 26/10/2026): equipamento
        # novo fica "unknown" ate o limite configurado (3) e entao cai.
        for esperado in ("unknown", "unknown", "down"):
            r = M.observe_entity({"entity_key": "cam1", "entity_type": "camera", "status": "down"})
            assert r["status"] == esperado
    finally:
        tenant_context.reset_current_tenant_slug(tok)


def test_ultimo_sync_do_zabbix_registra_sucesso_falha_e_separa_cliente(banco, monkeypatch):
    from app.services import zabbix_monitoring_service as Z

    monkeypatch.setattr(Z, "_ULTIMO_SYNC", {})
    monkeypatch.setattr(Z, "_sync_monitoring_to_zabbix", lambda tipos: {"ok": True, "total": 5, "pushed": 9})
    tok = _como("cliente-a")
    try:
        Z.sync_monitoring_to_zabbix()
        assert M.config_health()["zabbix_ultimo_sync"]["pushed"] == 9

        def quebra(tipos):
            raise RuntimeError("item duplicado")

        monkeypatch.setattr(Z, "_sync_monitoring_to_zabbix", quebra)
        with pytest.raises(RuntimeError):
            Z.sync_monitoring_to_zabbix()
        u = M.config_health()["zabbix_ultimo_sync"]
        assert u["ok"] is False and "item duplicado" in u["erro"]

        monkeypatch.setattr(Z, "_sync_monitoring_to_zabbix", lambda tipos: {"ok": False, "error": "Zabbix nao configurado automaticamente."})
        Z.sync_monitoring_to_zabbix()
        assert M.config_health()["zabbix_ultimo_sync"]["ok"] is False
    finally:
        tenant_context.reset_current_tenant_slug(tok)
    tok = _como("cliente-b")
    try:
        assert M.config_health()["zabbix_ultimo_sync"] == {}  # nada do cliente-a aparece aqui
    finally:
        tenant_context.reset_current_tenant_slug(tok)
