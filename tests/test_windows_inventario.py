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


def test_exe_leva_cliente_e_script_no_formato_do_instalador(monkeypatch):
    monkeypatch.setattr(W, "get_windows_agent_token", lambda tenant_slug="": "T" * 32)
    if not W.AGENTE_EXE_BASE.exists():
        pytest.skip("instalador base nao compilado")
    monkeypatch.setattr(W, "sites_do_cliente", lambda slug="": [
        {"site": "RESERVA", "connector_id": "c1"}, {"site": "JARDINS I", "connector_id": "c1"}])
    base = W.AGENTE_EXE_BASE.read_bytes()
    exe = W.build_windows_agent_exe("https://sightops.exemplo/v3-api", "Mega  Alarmes")
    assert exe[:len(base)] == base and exe[-8:] == b"SOPSAG01"
    n = int.from_bytes(exe[-12:-8], "little")
    cliente, sites, script = exe[-12 - n:-12].decode("utf-8").split("\n", 2)
    assert cliente == "Mega Alarmes"
    assert sites.split("\t") == ["SITES", "RESERVA", "JARDINS I"]
    assert '$SightOpsUrl = "https://sightops.exemplo/v3-api"' in script and "[switch]$InstalarAnyDesk" in script


def test_senha_do_anydesk_vem_do_instalador_e_nao_vai_ao_servidor(monkeypatch):
    """O .exe roda o script em -Silencioso, que antes respondia "nao" sozinho a
    pergunta da senha: nenhum PC instalado pelo .exe ficava sem supervisao."""
    monkeypatch.setattr(W, "get_windows_agent_token", lambda tenant_slug="": "T" * 32)
    script = W.build_windows_agent_script("https://sightops.exemplo/v3-api")
    assert '$env:SIGHTOPS_ANYDESK_SENHA' in script
    assert 'Remove-Item Env:SIGHTOPS_ANYDESK_SENHA' in script
    assert '$setPass = if ($Silencioso) { "n" }' not in script
    # a senha nunca entra no payload enviado; so a marcacao de que foi definida
    payload = script.split("$payload = [PSCustomObject]@{", 1)[1].split("$json =", 1)[0]
    assert "AnyDeskSenha" not in payload and "plainPass" not in payload
    assert "anydesk_senha_definida = $AnyDeskSenhaDefinida" in script


def test_anydesk_existente_passa_a_iniciar_com_o_windows(monkeypatch):
    """AnyDesk que ja estava no PC (portatil, sem servico) sumia no reboot."""
    monkeypatch.setattr(W, "get_windows_agent_token", lambda tenant_slug="": "T" * 32)
    script = W.build_windows_agent_script("https://sightops.exemplo/v3-api")
    funcao = script.split("function Set-AnyDeskInicioAutomatico {", 1)[1].split("\nfunction ", 1)[0]
    assert '"--start-with-win"' in funcao and "-StartupType Automatic" in funcao
    # a tarefa de 15 min (silenciosa) tambem mantem o servico ligado
    silencioso = script.split("if ($Silencioso -and -not $InstalarAnyDesk -and -not $AnyDeskSenha) {", 1)[1].split("}", 1)[0]
    assert "Set-AnyDeskInicioAutomatico" in silencioso


def test_sites_do_cliente_herdam_o_conector_dos_equipamentos(monkeypatch, tmp_path):
    """No cliente default, RESERVA nao tem conector proprio: seus 185
    equipamentos sao alcancados pelo conector PERUCABA."""
    import json as _json
    from app.core import tenant_context
    from app.services import connector_service, db_store
    pasta = tmp_path / "cliente"
    pasta.mkdir()
    (pasta / "cam-inventory.json").write_text(_json.dumps(
        [{"site": "RESERVA", "remote_connector_id": "perucaba"}] * 3 + [{"site": "SIERRA", "remote_connector_id": "outro"}]))
    (pasta / "windows-inventory.json").write_text(_json.dumps([{"site": "RESERVA PERUCABA"}]))
    monkeypatch.setattr(tenant_context, "tenant_data_dir", lambda slug="": pasta)
    monkeypatch.setattr(db_store, "list_sites", lambda *a, **k: [{"name": "RESERVA"}, {"name": "JARDINS I"}])
    monkeypatch.setattr(connector_service, "list_connectors",
                        lambda *a, **k: {"connectors": [{"id": "perucaba", "site": "PERUCABA"}]})
    sites = {s["site"]: s["connector_id"] for s in W.sites_do_cliente("cliente")}
    assert sites["RESERVA"] == "perucaba"          # herdado dos equipamentos
    assert sites["PERUCABA"] == "perucaba"         # conector proprio
    assert sites["JARDINS I"] == ""                # cadastrado, sem equipamento
    assert "RESERVA PERUCABA" not in sites         # o computador nao cria site
    assert W.sites_do_cliente("") == []            # sem cliente, nada


def test_relatorio_grava_site_oficial_e_conector(inventario, monkeypatch):
    monkeypatch.setattr(W, "sites_do_cliente", lambda slug="": [{"site": "RESERVA", "connector_id": "perucaba"}])
    W.accept_windows_agent_report(_relatorio(site="reserva"), tenant_slug="t")
    row = W.load_windows_inventory("t")[0]
    assert row["site"] == "RESERVA" and row["connector_id"] == "perucaba"


def test_script_nao_instala_mais_zabbix_agent():
    with pytest.MonkeyPatch.context() as m:
        m.setattr(W, "get_windows_agent_token", lambda tenant_slug="": "T" * 32)
        script = W.build_windows_agent_script("https://x")
    assert "msiexec" not in script and "zabbix_agent2-7.0" not in script


def test_download_do_agente_exige_operador():
    from app.core.security import ApiAuthMiddleware
    from types import SimpleNamespace
    mw = ApiAuthMiddleware.__new__(ApiAuthMiddleware)
    try:
        ApiAuthMiddleware.__init__(mw, lambda *a: None, SimpleNamespace(auth_legacy_open=False))
    except Exception:
        pytest.skip("middleware nao instanciavel isolado")
    assert mw._match_role_rule("/api/windows/agent-exe", "GET") == "operator"
    assert mw._match_role_rule("/api/windows/agent-script", "GET") == "operator"
    assert mw._match_role_rule("/api/windows/inventory", "GET") != "operator"


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
