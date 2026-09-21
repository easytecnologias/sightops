from __future__ import annotations

from typing import List
from pydantic import BaseModel

# Copiado do legado (main.py) para refatoração incremental (opção 1)
# Mantemos os mesmos campos/defaults para não quebrar o front.

class ScanRequest(BaseModel):
    alvo: str = "rede"
    usuario: str = "admin"
    senha: str = "admin"

    # Se marcado, define um "local" padrão para as câmeras encontradas nesta rodada
    set_local: bool = False
    local: str = ""

    capture_snapshot: bool = True
    append_inventory: bool = False
    reuse_inventory: bool = False
    nat_mode: bool = False  # se True, identifica câmeras por IP:PORTA (NAT), sem merge por MAC

    # etapas opcionais (legado)
    snapshot: bool = False
    imgbb: bool = False
    excel: bool = True
    thumbs: bool = False
    kmz: bool = False
    ia: bool = False
    olt_enrich: bool = False
    switch_enrich: bool = False
    inventory_mode: str = "olt"
    scan_origin: str | None = None
    connector_id: str | None = None
    remote_connector_id: str | None = None

    # OLT (enrich)
    olt_model: str | None = None
    olt_host: str | None = None
    olt_usuario: str | None = None
    olt_senha: str | None = None
    pon: str | None = None


class InventoryDeleteRequest(BaseModel):
    ips: List[str]
    mode: str = "olt"
    keys: List[str] = []
    connector_id: str | None = None
    site: str | None = None
    # apagar de vez: grava o bloqueio pra camera nao voltar na varredura
    permanent: bool = False


class RescanSingleIPRequest(BaseModel):
    ip: str
    usuario: str = "admin"
    senha: str = "admin"
    inventory_mode: str = "olt"
    # Se True, faz a captura do snapshot local (saida/snapshot)
    capture_snapshot: bool = True
class OltRegistryRequest(BaseModel):
    """Cadastro de OLT. `id` presente = edicao.

    `password` vazio numa edicao mantem a senha atual (ver olt_registry.save_olt):
    a tela nunca recebe a senha, entao nao teria como reenvia-la.
    """

    id: int | None = None
    name: str
    host: str
    vendor: str = ""
    model: str = ""
    username: str = ""
    password: str = ""
    site_id: int | None = None
    site: str = ""
    connector_id: str = ""
    notes: str = ""
    active: bool = True


class OltCollectMacsRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    pon: str = "all"
    olt_name: str | None = None
    olt_model: str | None = None
    olt_vendor: str | None = None
    site: str | None = None
    scan_origin: str | None = None
    connector_id: str | None = None
    remote_connector_id: str | None = None
    reuse_json: bool = False  # se True, faz append no olt-cpe-macs.json


class SwitchCollectMacsRequest(BaseModel):
    switch_ip: str
    user: str
    password: str
    site: str | None = None
    switch_name: str | None = None
    reuse_json: bool = False
    port: int = 23
    timeout: float = 12.0
    platform: str = "intelbras"
    connector_id: str | None = None


class OltDiscoverOnusRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    pon: str = "all"
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 12.0


class OnuServiceEntry(BaseModel):
    service: str = "downlink"
    vlan: int
    name: str = ""
    delivery: str = "auto"
    port: int = 0
    cos: int = 0


class OltAddOnuRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    pon: int
    serno_id: int
    onu_model: str = ""
    serial: str = ""
    vendor: str = ""
    site: str = ""
    olt_name: str = ""
    profile: str = ""
    description: str = ""
    service: str = "downlink"
    vlan: int
    services: List[OnuServiceEntry] = []
    tag_mode: str = "tagged"
    terminal: str = "onu"
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 15.0


class OltAddOnuBridgeRequest(BaseModel):
    """Retoma so o passo de bridge/servico/VLAN numa ONU 8820i ja autorizada
    (posicao pon/onu ja tem 'onu set' feito) -- recuperacao para quando
    `add_onu` autorizou mas o `bridge add` falhou."""

    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    pon: int
    onu: int
    site: str = ""
    olt_name: str = ""
    service: str = "downlink"
    vlan: int
    services: List[OnuServiceEntry] = []
    tag_mode: str = "tagged"
    terminal: str = "onu"
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 15.0


class OltFindOnuRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    serial: str
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 10.0


class OltDeleteOnuRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    pon: int
    onu: int
    serial: str = ""
    vlan_hint: str = ""
    site: str = ""
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 22.0


class OltRebootOnuRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    pon: int
    onu: int
    site: str = ""
    olt_name: str = ""
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 20.0


class OltOnuSignalRequest(BaseModel):
    olt_id: int | None = None
    olt_ip: str = ""
    user: str = ""
    password: str = ""
    olt_vendor: str = ""
    olt_model: str = ""
    pon: int = 0
    onu: int = 0
    serial: str = ""
    site: str = ""
    olt_name: str = ""
    connector_id: str = ""
    remote_connector_id: str = ""
    connector_name: str = ""
    timeout: float = 12.0
