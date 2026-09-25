from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import HTTPException

from app.services import olt_service
from app.models.requests import OltCollectMacsRequest, OltDiscoverOnusRequest


def main() -> int:
    # Dois "clientes" com faixa de IP privada distinta atras de conectores
    # diferentes -- exatamente o cenario relatado: IP da OLT de um site
    # (Barra de Sao Miguel) sendo aceito atraves do conector de outro
    # site/cliente (Telha), porque nada validava se o alvo pertence a rede
    # daquele conector.
    connector_telha = {
        "id": "conn-telha",
        "name": "Telha",
        "site": "TELHA",
        "status": "online",
        "tunnel": {"enabled": True, "client_lans": ["100.64.20.0/24"]},
    }
    connector_barra = {
        "id": "conn-barra",
        "name": "Barra de Sao Miguel",
        "site": "BARRA",
        "status": "online",
        "tunnel": {"enabled": True, "client_lans": ["100.65.10.0/24"]},
    }
    connectors = {"conn-telha": connector_telha, "conn-barra": connector_barra}

    original_get_connector = olt_service.get_connector
    olt_service.get_connector = lambda cid, *_, **__: connectors.get(cid)

    try:
        # 1) IP da OLT de Barra de Sao Miguel (100.65.10.200) atraves do
        #    conector de Telha (so alcanca 100.64.20.0/24) -- tem que ser
        #    bloqueado agora.
        req_leak = OltCollectMacsRequest(
            olt_ip="100.65.10.200",
            user="admin",
            password="x",
            olt_model="4840E",
            site="BARRA",
            connector_id="conn-telha",
            scan_origin="connector",
        )
        try:
            olt_service._validate_olt_network_context(req_leak)
            raise AssertionError("IP de outro site nao foi bloqueado pelo conector errado")
        except HTTPException as exc:
            assert exc.status_code == 400, exc.detail
            assert "fora das redes do conector" in str(exc.detail), exc.detail

        # 2) Mesmo IP, conector certo (Barra) -- tem que passar.
        req_ok = OltCollectMacsRequest(
            olt_ip="100.65.10.200",
            user="admin",
            password="x",
            olt_model="4840E",
            site="BARRA",
            connector_id="conn-barra",
            scan_origin="connector",
        )
        connector = olt_service._validate_olt_network_context(req_ok)
        assert connector is not None and connector["id"] == "conn-barra"

        # 3) Mesma checagem, agora no guard usado por discover/find/delete/
        #    onu_signal (nao tinham NENHUMA validacao de conector antes).
        req_discover_leak = OltDiscoverOnusRequest(
            olt_ip="100.65.10.200",
            user="admin",
            password="x",
            connector_id="conn-telha",
            remote_connector_id="conn-telha",
        )
        try:
            olt_service._validate_olt_target_connector(req_discover_leak)
            raise AssertionError("discover/find/delete via conector errado nao foi bloqueado")
        except HTTPException as exc:
            assert exc.status_code == 400, exc.detail

        # 4) Sem connector_id (acao local, a maioria dos casos hoje) continua
        #    sem exigir nada -- nao pode virar regressao pro fluxo local.
        req_local = OltDiscoverOnusRequest(olt_ip="192.168.1.5", user="admin", password="x")
        olt_service._validate_olt_target_connector(req_local)  # nao deve levantar
    finally:
        olt_service.get_connector = original_get_connector

    print("OK conector so confirma alvo dentro da propria LAN (collect_macs, telemetry e discover/find/delete/onu_signal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
