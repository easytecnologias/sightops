"""Consulta ao vivo de um MAC no MikroTik (job mac_lookup).

Caso real (PERUCABA, 26/10/2026): ARP com 1997 entradas, o agente manda so
500; a camera 44:3B:32:82:AA:9D estava em 10.10.10.186 (reachable), mas o
SightOps so via o lease de DHCP velho 10.10.10.10.
"""
from app.api.endpoints.deployments import _parse_mac_lookup
from app.services.connector_service import _routeros_job_script_template, _routeros_safe_mac


def test_ip_que_responde_vem_primeiro_e_o_failed_fica_antigo():
    texto = ("mac_lookup;arp|10.10.10.10|44:3B:32:82:AA:9D|failed|0;"
             "arp|10.10.10.186|44:3B:32:82:AA:9D|reachable|1;"
             "dhcp|10.10.10.10|44:3B:32:82:AA:9D|bound|0;")
    linhas = _parse_mac_lookup(texto)
    assert [l["ip"] for l in linhas] == ["10.10.10.186", "10.10.10.10"]
    assert linhas[0]["responde"] and not linhas[0]["antigo"]
    assert linhas[1]["antigo"] and linhas[1]["source"] == "arp + dhcp"


def test_lease_bound_sem_arp_nao_e_marcado_antigo_so_por_nao_responder():
    linhas = _parse_mac_lookup("mac_lookup;dhcp|10.10.10.10|44:3B:32:82:AA:9D|bound|0;")
    assert linhas[0]["responde"] is False and linhas[0]["antigo"] is False


def test_mac_vai_normalizado_e_lixo_nao_entra_no_script():
    assert _routeros_safe_mac("44-3b-32-82-aa-9d") == "44:3B:32:82:AA:9D"
    assert _routeros_safe_mac('44:3B:32:82:AA:9D"; /system reboot') == ""
    job = {"id": "j1", "type": "mac_lookup", "payload": {"mac": "443b3282aa9d"}}
    script = _routeros_job_script_template("https://x", "c1", "tok", job)
    assert ':local alvo "44:3B:32:82:AA:9D";' in script
    assert "/ip arp find where mac-address=$alvo" in script
    # So leitura: nada de add/set/remove no roteador do cliente.
    for proibido in (" add ", " set [", " remove ", "/system"):
        assert proibido not in script.replace(":set ", "")
