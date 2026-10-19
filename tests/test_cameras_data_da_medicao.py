"""GET /api/cameras precisa devolver a data da medicao.

JANGADEIROS, 19/10/2026: depois do exigir_data (status sem data = "nunca
verificado"), as 41 cameras sairam "Nao verificado" na gaveta do dashboard,
embora o inventario tivesse status_checked_at de minutos antes -- o dict da
rota e montado campo a campo e nao copiava a data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.api.endpoints import cameras as C


def test_rota_devolve_status_medido_com_data(monkeypatch):
    agora = datetime.now(timezone.utc).isoformat()
    linhas = [
        {"ip": "172.16.81.3", "titulo": "03 - ENTRADA I", "status": "online", "status_checked_at": agora,
         "status_detail": "zabbix_icmp_offline_but_tcp_online", "remote_connector_id": "gw"},
        {"ip": "172.16.81.1", "titulo": "02 - ACESSO A FABRICA", "status": "offline", "status_checked_at": agora,
         "status_detail": "zabbix_icmp_offline_tcp_unreachable", "remote_connector_id": "gw"},
        {"ip": "172.16.81.60", "titulo": "nunca medida", "status": "online", "remote_connector_id": "gw"},
    ]
    monkeypatch.setattr(C, "load_inventory_json", lambda *a, **k: [dict(x) for x in linhas])
    monkeypatch.setattr("app.services.status_efetivo.conectores_offline", lambda: set())
    saida = {c["ip"]: c for c in C.api_cameras(enrich="", mode="switch", site="", connector_id="")["cameras"]}
    assert saida["172.16.81.3"]["status"] == "online" and saida["172.16.81.3"]["status_checked_at"] == agora
    assert saida["172.16.81.1"]["status"] == "offline"
    assert saida["172.16.81.3"]["status_detail"] == "zabbix_icmp_offline_but_tcp_online"
    # a regra nova continua valendo para quem nunca foi medido
    assert saida["172.16.81.60"]["status"] == "unknown"
