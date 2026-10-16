"""Gravador > Rede, abas de leitura: portas pela configuracao, onde a camera
esta ligada pelo inventario de cameras e horario do monitoramento em UTC.
Gravador falso; nada e escrito."""
from __future__ import annotations

from app.services import recorder_rede_leitura as RL


class GravadorFalso:
    marca = "intelbras"
    CONFIG = {
        "Web": {"Web.Enable": "true", "Web.Port": "8081"},
        "RTSP": {"RTSP.Enable": "true", "RTSP.Port": "554"},
        "DVRIP": {"DVRIP.TCPPort": "30000", "DVRIP.UDPPort": "37778", "DVRIP.SSLPort": "8443"},
        "UPnP": {"UPnP.Enable": "false", "UPnP.MapTable[0].Enable": "true", "UPnP.MapTable[1].Enable": "true"},
        "T2UServer": {"T2UServer[0].Enable": "true", "T2UServer[0].Address": "intelbrasp2p.com.br"},
        "Https": {"Https.Enable": "false"},
        "SNMP": {"SNMP.Enable": "false"},
        "Network": {"Network.eth0.DhcpEnable": "false"},
    }

    def ler_config(self, sec):
        return dict(self.CONFIG[sec])

    def _get(self, caminho):
        if "getInterfaces" in caminho:
            return "netInterface[0].Name=eth0\r\nnetInterface[0].Speed=0\r\nnetInterface[0].ConnStatus=Connected\r\n"
        return "result=2026-10-16 09:00:00"


def test_portas_e_acessos_lidas_da_configuracao():
    p = RL.portas_intelbras(GravadorFalso())
    assert p["web"] == {"ligado": True, "porta": "8081"} and p["rtsp"]["porta"] == "554" and p["sdk"]["porta"] == "30000"
    assert p["p2p"] == {"ligado": True, "servidor": "intelbrasp2p.com.br"}
    assert p["snmp"]["ligado"] is False and p["upnp"] == {"ligado": False, "mapeamentos": 2}
    assert p["rede"]["dhcp"] is False and p["placa"] == {"nome": "eth0", "velocidade_mbps": 0, "conectada": True}
    assert p["falhas"] == []


def test_resposta_medida_pelo_caminho_real():
    r = RL.medir_resposta(GravadorFalso(), vezes=2)
    assert r["ok"] and r["amostras"] == 2 and r["perdidas"] == 0


def test_onde_esta_usa_o_mac_do_inventario_de_cameras_e_marca_ip_repetido(monkeypatch):
    import app.services.inventory_json as IJ
    cams = {"olt": [{"ip": "10.10.10.20", "mac": "18:0d:2c:e6:d6:10", "olt_name": "OLT A", "pon": "3", "onu_name": "gpon 3 onu 2"}]}
    monkeypatch.setattr(IJ, "load_inventory_json", lambda mode="": cams.get(mode, []))
    nvr = [{"host": "h", "channel": 1, "camera_mac": "18:0d:2c:e6:d6:0b"}]   # MAC errado nas linhas do gravador
    r = RL.onde_estao([{"canal": 1, "ip": "10.10.10.20"}, {"canal": 2, "ip": "10.10.10.20"}], nvr, "h")
    assert r[0]["mac"] == "18:0d:2c:e6:d6:10"                      # o do inventario de cameras, que e o certo
    assert r[0]["onde"] == {"tipo": "onu", "texto": "OLT A · PON 3 · gpon 3 onu 2"}
    assert r[0]["duplicado"] and r[1]["duplicado"]


def test_horario_do_monitoramento_sai_em_utc():
    assert RL._utc_iso("2026-10-16 12:49:19.344033+00") == "2026-10-16T12:49:19Z"
