"""Inventario Windows: historico, identificacao do computador, status e base do agente."""
from __future__ import annotations

import datetime as dt

import pytest

from app.services import windows_inventory_service as W


def _relatorio(**extra):
    base = {
        "hostname": "FIN-03", "primary_ipv4": "10.10.20.43", "bios_serial": "7KXQ2M3",
        "os_name": "Microsoft Windows 11 Pro", "os_build": "26100", "last_boot": "boot-1",
        "total_ram_gb": 16, "defender": {"enabled": True, "realtime": True},
        "bitlocker": [{"mount_point": "C:", "protection_status": 1}],
        "tpm": {"present": True, "ready": True},
        "hotfixes": [{"id": "KB1"}], "anydesk_id": "517204886",
        "volumes": [{"drive": "C:", "free_percent": 40}],
        "agent_version": "2.0", "agent_scheduled": True, "site": "Sede", "sector": "Financeiro",
    }
    base.update(extra)
    return base


@pytest.fixture
def inventario(monkeypatch, tmp_path):
    arq = tmp_path / "windows-inventory.json"
    monkeypatch.setattr(W, "_windows_inventory_path", lambda tenant_slug="": arq)
    return arq


def test_primeiro_relatorio_cria_com_evento_de_entrada(inventario):
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    rows = W.load_windows_inventory("t")
    assert len(rows) == 1
    assert rows[0]["first_seen"] and rows[0]["eventos"][0]["txt"].startswith("Entrou")
    assert rows[0]["agent_version"] == "2.0" and rows[0]["agent_scheduled"] is True


def test_troca_de_ip_nao_duplica_o_computador(inventario):
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    W.accept_windows_agent_report(_relatorio(primary_ipv4="10.10.20.99"), tenant_slug="t")
    rows = W.load_windows_inventory("t")
    assert len(rows) == 1 and rows[0]["ip"] == "10.10.20.99"


def test_serial_generico_nao_junta_computadores_diferentes(inventario):
    W.accept_windows_agent_report(_relatorio(bios_serial="Default string"), tenant_slug="t")
    W.accept_windows_agent_report(_relatorio(bios_serial="Default string", hostname="RECEP-01",
                                             primary_ipv4="10.10.20.11"), tenant_slug="t")
    assert len(W.load_windows_inventory("t")) == 2


def test_mudancas_viram_eventos(inventario):
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    W.accept_windows_agent_report(_relatorio(
        defender={"enabled": True, "realtime": False}, total_ram_gb=32, last_boot="boot-2",
        hotfixes=[{"id": "KB2"}, {"id": "KB1"}],
        bitlocker=[{"mount_point": "C:", "protection_status": 0}],
    ), tenant_slug="t")
    txts = [e["txt"] for e in W.load_windows_inventory("t")[0]["eventos"]]
    assert "Defender em tempo real foi desligado" in txts
    assert "Memoria passou de 16 GB para 32 GB" in txts
    assert "Computador reiniciado" in txts
    assert "Instalou a atualizacao KB2" in txts
    assert "BitLocker do C: deixou de proteger" in txts


def test_relatorio_igual_nao_gera_evento(inventario):
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    assert len(W.load_windows_inventory("t")[0]["eventos"]) == 1


def test_relatorio_silencioso_sem_site_mantem_o_site(inventario):
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    W.accept_windows_agent_report(_relatorio(site="", sector=""), tenant_slug="t")
    row = W.load_windows_inventory("t")[0]
    assert row["site"] == "Sede" and row["sector"] == "Financeiro"


def test_dado_manual_sobrevive_ao_relatorio(inventario):
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    rows = W.load_windows_inventory("t")
    rows[0]["physical"] = {"switch_name": "SW-SEDE-02", "switch_port": "14"}
    W.save_windows_inventory(rows, "t")
    W.accept_windows_agent_report(_relatorio(), tenant_slug="t")
    assert W.load_windows_inventory("t")[0]["physical"]["switch_port"] == "14"


def test_mesmo_hostname_em_clientes_diferentes_nao_se_mistura(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "_windows_inventory_path",
                        lambda tenant_slug="": tmp_path / f"{tenant_slug or 'sem'}.json")
    W.accept_windows_agent_report(_relatorio(), tenant_slug="cliente-a")
    W.accept_windows_agent_report(_relatorio(defender={"enabled": True, "realtime": False}), tenant_slug="cliente-b")
    a, b = W.load_windows_inventory("cliente-a"), W.load_windows_inventory("cliente-b")
    assert len(a) == 1 and len(b) == 1
    # O relatorio do B nao vira evento no A, e cada um comeca o proprio historico.
    assert [e["txt"] for e in a[0]["eventos"]] == ["Entrou no inventario pelo agente"]
    assert [e["txt"] for e in b[0]["eventos"]] == ["Entrou no inventario pelo agente"]
    assert a[0]["defender"]["realtime"] is True and b[0]["defender"]["realtime"] is False


def test_alertas_de_seguranca_e_windows_sem_suporte():
    row = W._normalize_inventory("10.0.0.1", _relatorio(
        os_name="Microsoft Windows 10 Pro", defender={"enabled": False, "realtime": False},
        bitlocker=[{"mount_point": "C:", "protection_status": 0}]))
    flags = row["health_flags"]
    assert "Windows sem suporte da Microsoft" in flags
    assert "Defender desativado" in flags
    assert "BitLocker desligado no C:" in flags


def _agora(min_atras):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=min_atras)).isoformat()


def test_status_windows_recente_e_online_velho_e_sem_contato():
    from app.services.monitoring_service import _status_windows
    assert _status_windows({"status": "agent_reported", "last_seen": _agora(5)}) == "online"
    assert _status_windows({"status": "agent_reported", "last_seen": _agora(120)}) == "unknown"
    assert _status_windows({"status": "agent_reported", "last_seen": ""}) == "unknown"


def test_falha_de_winrm_nao_vira_queda():
    from app.services.monitoring_service import _status_windows
    for st in ("timeout", "auth_failed", "winrm_closed", "error"):
        assert _status_windows({"status": st, "last_seen": _agora(5)}) == "unknown"


def test_metrica_velha_nao_vai_ao_zabbix_como_nova():
    from app.services.monitoring_service import _detalhe_windows
    row = {"last_seen": _agora(300), "volumes": [{"drive": "C:", "free_percent": 4}]}
    assert _detalhe_windows(row, "unknown")["checado_em"] == ""
    assert _detalhe_windows(row, "online")["checado_em"] == row["last_seen"]


def test_chave_do_host_estavel_entre_agente_e_winrm():
    from app.services.monitoring_service import _chave_windows
    assert _chave_windows({"hostname": "FIN-03"}) == _chave_windows({"hostname": "fin-03.empresa.local"})


def test_toda_metrica_do_zabbix_esta_no_item_get():
    """Chave em metricas_por_tipo fora de wanted_keys derruba o sync do tenant
    a partir do 2o ciclo (item.create duplicado). Achado do revisor-zabbix."""
    import inspect
    import re
    from app.services import zabbix_monitoring_service as Z
    fonte = inspect.getsource(Z.sync_monitoring_to_zabbix)
    wanted = fonte[fonte.index("wanted_keys = ["):]
    wanted = set(re.findall(r'"(sightops\.[a-z_]+)"', wanted[:wanted.index("]")]))
    metricas = fonte[fonte.index("metricas_por_tipo = {"):]
    metricas = set(re.findall(r'"(sightops\.[a-z_]+)"', metricas[:metricas.index("}")]))
    assert metricas and metricas <= wanted, metricas - wanted


class _Req:
    def __init__(self, host, base_url="http://sightops.exemplo/"):
        self.headers = {"host": host}
        self.base_url = base_url


@pytest.mark.parametrize("base, esperado", [
    ("https://sightops.exemplo/v3-api", "https://sightops.exemplo/v3-api"),
    ("https://outro.exemplo/v3-api", "http://sightops.exemplo"),          # outro dominio
    ('https://sightops.exemplo/v3"; Remove-Item', "http://sightops.exemplo"),  # injecao no script
    ("javascript:alert(1)", "http://sightops.exemplo"),
    ("", "http://sightops.exemplo"),
])
def test_base_do_agente(base, esperado):
    from app.api.endpoints.windows import _base_do_agente
    assert _base_do_agente(_Req("sightops.exemplo"), base) == esperado
