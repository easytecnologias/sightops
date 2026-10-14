from __future__ import annotations

import ipaddress
import json
import socket
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.core.paths import DATA_DIR
from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_path

# Caminhos legados (pre-isolamento por tenant) -- mantidos so para o fallback
# de compatibilidade em validate_windows_agent_token, ver comentario la.
WINDOWS_INVENTORY_PATH = DATA_DIR / "windows-inventory.json"
WINDOWS_AGENT_TOKEN_PATH = DATA_DIR / "windows-agent-token.txt"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _windows_token_path(tenant_slug: str = "") -> Path:
    return tenant_scoped_path("windows-agent-token.txt", tenant_slug)


def get_windows_agent_token(tenant_slug: str = "") -> str:
    path = _windows_token_path(tenant_slug or get_current_tenant_slug())
    try:
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 24:
            return token
    except Exception:
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    return token


def validate_windows_agent_token(token: str) -> str:
    """Retorna o tenant_slug dono do token, ou "" se invalido/nao encontrado.

    Antes, um unico token global valia para agentes de todos os clientes --
    agora cada tenant tem o seu (ver get_windows_agent_token). Escaneia as
    pastas de tenant conhecidas em busca de quem é dono do token recebido.
    Mantem tambem o token legado global (de antes deste isolamento) mapeado
    pro tenant "default", para nao quebrar um agente ja instalado em campo
    antes desta correcao.
    """
    tok = _text(token)
    if not tok:
        return ""
    tenants_root = DATA_DIR / "tenants"
    if tenants_root.is_dir():
        for tenant_dir in tenants_root.iterdir():
            if not tenant_dir.is_dir():
                continue
            candidate_path = tenant_dir / "windows-agent-token.txt"
            try:
                expected = candidate_path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if expected and secrets.compare_digest(tok, expected):
                return tenant_dir.name
    try:
        legacy = WINDOWS_AGENT_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        legacy = ""
    if legacy and secrets.compare_digest(tok, legacy):
        return "default"
    return ""


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0] or ""
    except Exception:
        return ""


def _disk_kind(disks: List[Dict[str, Any]]) -> str:
    found_ssd = False
    found_hdd = False
    for disk in disks or []:
        raw = " ".join(
            _text(disk.get(key))
            for key in ("media_type", "model", "interface_type")
        ).lower()
        if "ssd" in raw or "nvme" in raw:
            found_ssd = True
        elif raw:
            found_hdd = True
    if found_ssd and found_hdd:
        return "mixed"
    if found_ssd:
        return "ssd"
    if found_hdd:
        return "hdd_or_unknown"
    return "unknown"


def _disk_total_gb(disks: List[Dict[str, Any]]) -> float | None:
    total = 0.0
    found = False
    for disk in disks or []:
        if not isinstance(disk, dict):
            continue
        try:
            value = disk.get("size_gb")
            if value is None or value == "":
                continue
            total += float(value)
            found = True
        except Exception:
            continue
    return round(total, 2) if found else None


def _memory_summary(modules: List[Dict[str, Any]], total_ram_gb: Any) -> str:
    normalized = [m for m in modules or [] if isinstance(m, dict)]
    if not normalized:
        return f"{total_ram_gb} GB" if total_ram_gb else ""
    capacities = []
    ddr_values = []
    speeds = []
    manufacturers = []
    for module in normalized:
        cap = module.get("capacity_gb")
        try:
            if cap is not None and cap != "":
                capacities.append(float(cap))
        except Exception:
            pass
        ddr = _text(module.get("ddr"))
        if ddr and ddr not in ddr_values:
            ddr_values.append(ddr)
        speed = _text(module.get("configured_speed_mhz") or module.get("speed_mhz"))
        if speed and speed not in speeds:
            speeds.append(speed)
        manufacturer = _text(module.get("manufacturer"))
        if manufacturer and manufacturer not in manufacturers:
            manufacturers.append(manufacturer)
    parts: list[str] = []
    if capacities:
        equal = len(set(capacities)) == 1
        if equal:
            cap = int(capacities[0]) if capacities[0].is_integer() else capacities[0]
            parts.append(f"{len(capacities)}x {cap} GB")
        else:
            parts.append(" + ".join(f"{int(v) if v.is_integer() else v} GB" for v in capacities))
    elif total_ram_gb:
        parts.append(f"{total_ram_gb} GB")
    if ddr_values:
        parts.append("/".join(ddr_values))
    if speeds:
        parts.append("/".join(str(s) for s in speeds) + " MHz")
    if manufacturers:
        parts.append(", ".join(manufacturers[:2]))
    return " - ".join(parts)


def _disk_summary(disks: List[Dict[str, Any]]) -> str:
    normalized = [d for d in disks or [] if isinstance(d, dict)]
    if not normalized:
        return ""
    labels = []
    for disk in normalized[:3]:
        size = disk.get("size_gb")
        size_text = ""
        try:
            value = float(size)
            size_text = f"{round(value / 1024, 2)} TB" if value >= 1024 else f"{round(value)} GB"
        except Exception:
            pass
        model = _text(disk.get("model"))
        manufacturer = _text(disk.get("manufacturer"))
        media = _text(disk.get("media_type"))
        bits = [bit for bit in (size_text, media, manufacturer, model) if bit]
        labels.append(" ".join(bits))
    return " | ".join(labels)


def _security_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    tpm = data.get("tpm") if isinstance(data.get("tpm"), dict) else {}
    defender = data.get("defender") if isinstance(data.get("defender"), dict) else {}
    bitlocker = data.get("bitlocker") if isinstance(data.get("bitlocker"), list) else []
    protected = 0
    for item in bitlocker:
        if isinstance(item, dict) and _text(item.get("protection_status")).lower() in ("on", "1", "true"):
            protected += 1
    return {
        "secure_boot": data.get("secure_boot"),
        "tpm_present": tpm.get("present"),
        "tpm_ready": tpm.get("ready"),
        "defender_enabled": defender.get("enabled"),
        "defender_realtime": defender.get("realtime"),
        "bitlocker_protected_volumes": protected,
        "bitlocker_total_volumes": len([x for x in bitlocker if isinstance(x, dict)]),
    }


def _health_flags(row: Dict[str, Any]) -> List[str]:
    flags: list[str] = []
    if row.get("has_ssd") is False:
        flags.append("Sem SSD detectado")
    try:
        # 7,5 e nao 8: PC com 8 GB reporta ~7,7 GB utilizaveis (video integrado
        # reserva parte) e era marcado como "abaixo de 8 GB".
        ram = float(row.get("ram_gb") or 0)
        if 0 < ram < 7.5:
            flags.append("Memoria abaixo de 8 GB")
    except Exception:
        pass
    for volume in row.get("volumes") or []:
        if not isinstance(volume, dict):
            continue
        try:
            if float(volume.get("free_percent") or 100) < 15:
                flags.append(f"Pouco espaco livre em {volume.get('drive')}")
        except Exception:
            pass
    security = row.get("security") if isinstance(row.get("security"), dict) else {}
    if security.get("defender_realtime") is False:
        flags.append("Defender em tempo real desativado")
    if security.get("tpm_ready") is False:
        flags.append("TPM nao pronto")
    if security.get("defender_enabled") is False:
        flags.append("Defender desativado")
    if _bitlocker_c(row) is False:
        flags.append("BitLocker desligado no C:")
    os_name = _text((row.get("os") or {}).get("name"))
    if "windows 10" in os_name.lower() or "windows 8" in os_name.lower() or "windows 7" in os_name.lower():
        # Windows 10 deixou de receber atualizacao de seguranca em 14/10/2025.
        flags.append("Windows sem suporte da Microsoft")
    return flags


def _normalize_inventory(ip: str, payload: Dict[str, Any], status: str = "online", error: str = "") -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    disks = data.get("disks") if isinstance(data.get("disks"), list) else []
    memory_modules = data.get("memory_modules") if isinstance(data.get("memory_modules"), list) else []
    volumes = data.get("volumes") if isinstance(data.get("volumes"), list) else []
    gpus = data.get("gpus") if isinstance(data.get("gpus"), list) else []
    batteries = data.get("batteries") if isinstance(data.get("batteries"), list) else []
    bitlocker = data.get("bitlocker") if isinstance(data.get("bitlocker"), list) else []
    hotfixes = data.get("hotfixes") if isinstance(data.get("hotfixes"), list) else []
    network = data.get("network") if isinstance(data.get("network"), list) else []
    remote_access = data.get("remote_access") if isinstance(data.get("remote_access"), dict) else {}
    anydesk = remote_access.get("anydesk") if isinstance(remote_access.get("anydesk"), dict) else {}
    zabbix_agent = data.get("zabbix_agent") if isinstance(data.get("zabbix_agent"), dict) else {}
    mac = ""
    if network and isinstance(network[0], dict):
        mac = _text(network[0].get("mac"))
    normalized_disks = [d for d in disks if isinstance(d, dict)]
    disk_kind = _disk_kind(normalized_disks)
    row = {
        "ip": ip,
        "hostname": _text(data.get("hostname")) or _hostname(ip),
        "status": status,
        "error": error,
        "source": _text(data.get("source")) or ("agent" if status == "agent_reported" else "winrm"),
        "domain": _text(data.get("domain")),
        "site": _text(data.get("site")),
        "sector": _text(data.get("sector") or data.get("setor")),
        "logged_user": _text(data.get("logged_user")),
        "manufacturer": _text(data.get("manufacturer")),
        "model": _text(data.get("model")),
        "system_sku": _text(data.get("system_sku")),
        "pc_system_type": data.get("pc_system_type"),
        "chassis_types": data.get("chassis_types") if isinstance(data.get("chassis_types"), list) else [],
        "timezone": _text(data.get("timezone")),
        "serial": _text(data.get("bios_serial")),
        "motherboard": {
            "manufacturer": _text(data.get("motherboard_manufacturer")),
            "model": _text(data.get("motherboard_model")),
            "serial": _text(data.get("motherboard_serial")),
        },
        "os": {
            "name": _text(data.get("os_name")),
            "version": _text(data.get("os_version")),
            "build": _text(data.get("os_build")),
            "arch": _text(data.get("os_arch")),
            "last_boot": _text(data.get("last_boot")),
        },
        "cpu": {
            "name": _text(data.get("cpu")),
            "cores": data.get("cpu_cores"),
            "threads": data.get("cpu_threads"),
        },
        "gpus": gpus,
        "batteries": batteries,
        "ram_gb": data.get("total_ram_gb"),
        "memory_slots": data.get("memory_slots"),
        "memory_modules": memory_modules,
        "memory_summary": _memory_summary([m for m in memory_modules if isinstance(m, dict)], data.get("total_ram_gb")),
        "disk_kind": disk_kind,
        "disk_total_gb": _disk_total_gb(normalized_disks),
        "disk_summary": _disk_summary(normalized_disks),
        "has_ssd": disk_kind in ("ssd", "mixed"),
        "disks": disks,
        "volumes": volumes,
        "network": network,
        "remote_access": remote_access,
        "anydesk_id": _text(data.get("anydesk_id")) or _text(anydesk.get("id")),
        "anydesk_installed": bool(anydesk.get("installed")),
        "anydesk_status": _text(anydesk.get("service_status")),
        "zabbix_agent": {
            "installed": bool(zabbix_agent.get("installed")),
            "service_status": _text(zabbix_agent.get("service_status")),
            "server": _text(zabbix_agent.get("server")),
            "server_active": _text(zabbix_agent.get("server_active")),
            "hostname": _text(zabbix_agent.get("hostname")),
            "version": _text(zabbix_agent.get("version")),
            "error": _text(zabbix_agent.get("error")),
        },
        "tpm": data.get("tpm") if isinstance(data.get("tpm"), dict) else {},
        "secure_boot": data.get("secure_boot"),
        "bitlocker": bitlocker,
        "defender": data.get("defender") if isinstance(data.get("defender"), dict) else {},
        "hotfixes": hotfixes,
        "security": _security_summary(data),
        "mac": mac,
        "last_seen": _now() if status in ("online", "agent_reported") else "",
        "updated_at": _now(),
    }
    row["health_flags"] = _health_flags(row)
    return row


def _windows_inventory_path(tenant_slug: str = "") -> Path:
    return tenant_scoped_path("windows-inventory.json", tenant_slug)


def load_windows_inventory(tenant_slug: str = "") -> List[Dict[str, Any]]:
    path = _windows_inventory_path(tenant_slug)
    try:
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get("inventory"), list):
        return [row for row in data["inventory"] if isinstance(row, dict)]
    return []


def save_windows_inventory(rows: List[Dict[str, Any]], tenant_slug: str = "") -> None:
    path = _windows_inventory_path(tenant_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clear_windows_inventory(tenant_slug: str = "") -> Dict[str, Any]:
    save_windows_inventory([], tenant_slug=tenant_slug)
    return {"ok": True, "cleared": True}


def accept_windows_agent_report(payload: Dict[str, Any], remote_ip: str = "", tenant_slug: str = "") -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Payload do agente invalido.")
    data = dict(payload)
    data["source"] = "agent"
    candidates = []
    for key in ("ip", "primary_ip", "primary_ipv4"):
        value = _text(data.get(key))
        if value:
            candidates.append(value)
    network = data.get("network")
    if isinstance(network, list):
        for item in network:
            if not isinstance(item, dict):
                continue
            ips = item.get("ip")
            if isinstance(ips, list):
                candidates.extend(_text(v) for v in ips)
            else:
                candidates.append(_text(ips))
    candidates.append(_text(remote_ip))
    ip = ""
    for candidate in candidates:
        try:
            parsed = ipaddress.ip_address(candidate)
            if parsed.version == 4 and not parsed.is_loopback:
                ip = str(parsed)
                break
        except Exception:
            continue
    if not ip:
        raise ValueError("Agente nao informou IPv4 valido.")
    row = _normalize_inventory(ip, data, status="agent_reported")
    row["agent_version"] = _text(data.get("agent_version"))
    row["agent_scheduled"] = bool(data.get("agent_scheduled"))
    # Site com o nome oficial e o conector que o alcanca (para o Ping ir pelo
    # IP virtual). Site digitado fora da lista fica como veio, sem conector.
    if _text(row.get("site")):
        try:
            oficial = _site_oficial(row["site"], sites_do_cliente(tenant_slug))
        except Exception:
            oficial = {}
        if oficial:
            row["site"] = oficial["site"]
            row["connector_id"] = oficial["connector_id"]
    current = load_windows_inventory(tenant_slug=tenant_slug)
    # O mesmo computador e achado por serial/hostname antes do IP: com o agente
    # reportando a cada 15 min, PC em DHCP trocava de IP e virava outra linha.
    pos = _achar_computador(current, row)
    if pos is None:
        row["first_seen"] = row.get("updated_at")
        row["eventos"] = [{"em": row.get("updated_at"), "txt": "Entrou no inventario pelo agente"}]
        current.append(row)
    else:
        antigo = current[pos]
        novo = dict(antigo)
        novo.update(row)
        for manter in ("site", "sector"):
            if not _text(row.get(manter)) and _text(antigo.get(manter)):
                novo[manter] = antigo[manter]
        novo["first_seen"] = antigo.get("first_seen") or antigo.get("updated_at") or row.get("updated_at")
        eventos = list(antigo.get("eventos") or []) if isinstance(antigo.get("eventos"), list) else []
        eventos.extend({"em": row.get("updated_at"), "txt": t} for t in _eventos_de_mudanca(antigo, row))
        novo["eventos"] = eventos[-_MAX_EVENTOS:]
        current[pos] = novo
        row = novo
    save_windows_inventory(current, tenant_slug=tenant_slug)
    return {"ok": True, "saved": True, "row": row}


def sites_do_cliente(tenant_slug: str = "") -> List[Dict[str, str]]:
    """Sites do cliente com o conector que alcanca cada um.

    O site e escolhido numa lista no instalador (antes era texto livre e o
    primeiro computador entrou como "RESERVA PERUCABA" num cliente cujo site e
    "RESERVA"). O conector vem do proprio conector do site ou, se o site nao
    tem conector proprio, de por onde os equipamentos daquele site sao
    alcancados -- no cliente default, RESERVA, JARDINS e PERUCABA estao todos
    atras do conector PERUCABA. Com ele o servidor alcanca o computador pelo IP
    virtual (vnat), igual as cameras.
    """
    from collections import Counter

    from app.core.tenant_context import (get_current_tenant_slug, reset_current_tenant_slug,
                                         set_current_tenant_slug, tenant_data_dir)

    # O relatorio do agente chega por rota publica (so o token): sem usuario
    # logado nao ha cliente no contexto, e list_sites/list_connectors leriam o
    # de ninguem -- ou o legado global. Fixa o cliente dono do token aqui.
    slug = _text(tenant_slug) or get_current_tenant_slug()
    if not slug:
        return []
    marca = set_current_tenant_slug(slug)
    try:
        return _sites_do_cliente(slug, Counter, tenant_data_dir)
    finally:
        reset_current_tenant_slug(marca)


def _sites_do_cliente(tenant_slug: str, Counter: Any, tenant_data_dir: Any) -> List[Dict[str, str]]:
    nomes: Dict[str, str] = {}
    por_site: Dict[str, Counter] = {}

    def _anotar(nome: Any, conector: Any = "") -> None:
        n = " ".join(_text(nome).split())
        if not n:
            return
        k = n.upper()
        nomes.setdefault(k, n)
        if _text(conector):
            por_site.setdefault(k, Counter())[_text(conector)] += 1

    try:
        from app.services.db_store import list_sites
        for s in list_sites() or []:
            _anotar(s.get("name"))
    except Exception:
        pass
    proprio: Dict[str, str] = {}
    try:
        from app.services.connector_service import list_connectors
        for c in (list_connectors() or {}).get("connectors") or []:
            _anotar(c.get("site"))
            if _text(c.get("site")) and _text(c.get("id")):
                proprio[_text(c.get("site")).upper()] = _text(c.get("id"))
    except Exception:
        pass
    pasta = tenant_data_dir(tenant_slug)
    for arq in pasta.glob("*inventory*.json"):
        if arq.name.startswith("windows"):
            continue  # o computador nao define site de ninguem
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(dados, dict):
            dados = dados.get("inventory") or []
        for r in dados if isinstance(dados, list) else []:
            if isinstance(r, dict):
                _anotar(r.get("site") or r.get("local"), r.get("remote_connector_id") or r.get("connector_id"))
    saida = []
    for k, nome in sorted(nomes.items()):
        cid = proprio.get(k) or (por_site[k].most_common(1)[0][0] if por_site.get(k) else "")
        saida.append({"site": nome, "connector_id": cid})
    return saida


def _site_oficial(site: str, sites: List[Dict[str, str]]) -> Dict[str, str]:
    alvo = " ".join(_text(site).split()).upper()
    for s in sites:
        if s["site"].upper() == alvo:
            return s
    return {}


_MAX_EVENTOS = 40
# Serial de placa generica: varios PCs montados repetem o mesmo texto e virariam
# um computador so.
_SERIAL_GENERICO = {"", "default string", "to be filled by o.e.m.", "system serial number",
                    "none", "0", "00000000", "123456789", "not applicable", "n/a"}


def _achar_computador(rows: List[Dict[str, Any]], row: Dict[str, Any]) -> Any:
    serial = _text(row.get("serial")).lower()
    host = _text(row.get("hostname")).lower()
    if serial not in _SERIAL_GENERICO:
        for i, r in enumerate(rows):
            if _text(r.get("serial")).lower() == serial and (not host or _text(r.get("hostname")).lower() == host):
                return i
    if host:
        for i, r in enumerate(rows):
            if _text(r.get("hostname")).lower() == host:
                return i
    ip = _text(row.get("ip"))
    for i, r in enumerate(rows):
        if ip and _text(r.get("ip")) == ip and not _text(r.get("hostname")):
            return i
    return None


def _defender_rt(row: Dict[str, Any]) -> Any:
    d = row.get("defender") if isinstance(row.get("defender"), dict) else {}
    return d.get("realtime")


def _bitlocker_c(row: Dict[str, Any]) -> Any:
    for v in row.get("bitlocker") or []:
        if isinstance(v, dict) and _text(v.get("mount_point")).upper().startswith("C"):
            st = _text(v.get("protection_status")).lower()
            return st in ("1", "on", "true")
    return None


def _ultimo_hotfix(row: Dict[str, Any]) -> str:
    ids = [_text(h.get("id")) for h in (row.get("hotfixes") or []) if isinstance(h, dict) and _text(h.get("id"))]
    return ids[0] if ids else ""


def _eventos_de_mudanca(antigo: Dict[str, Any], novo: Dict[str, Any]) -> List[str]:
    """O que mudou entre dois relatorios do mesmo computador, em frase de operacao.

    So o que importa para quem cuida do parque: seguranca, hardware, sistema e
    acesso. Usuario logado e IP mudam o tempo todo e nao viram evento.
    """
    ev: List[str] = []
    so_a, so_n = antigo.get("os") or {}, novo.get("os") or {}
    win_a = " ".join(x for x in (_text(so_a.get("name")), _text(so_a.get("build"))) if x)
    win_n = " ".join(x for x in (_text(so_n.get("name")), _text(so_n.get("build"))) if x)
    if win_a and win_n and win_a != win_n:
        ev.append(f"Windows mudou de {win_a} para {win_n}")
    try:
        ra, rn = float(antigo.get("ram_gb") or 0), float(novo.get("ram_gb") or 0)
        if ra and rn and abs(ra - rn) >= 0.5:
            ev.append(f"Memoria passou de {ra:g} GB para {rn:g} GB")
    except (TypeError, ValueError):
        pass
    da, dn = _text(antigo.get("disk_summary")), _text(novo.get("disk_summary"))
    if da and dn and da != dn:
        ev.append(f"Discos mudaram: {da} -> {dn}")
    fa, fn = _defender_rt(antigo), _defender_rt(novo)
    if fa is True and fn is False:
        ev.append("Defender em tempo real foi desligado")
    elif fa is False and fn is True:
        ev.append("Defender em tempo real foi religado")
    ba, bn = _bitlocker_c(antigo), _bitlocker_c(novo)
    if ba is True and bn is False:
        ev.append("BitLocker do C: deixou de proteger")
    elif ba is False and bn is True:
        ev.append("BitLocker do C: passou a proteger")
    ta = (antigo.get("security") or {}).get("tpm_ready")
    tn = (novo.get("security") or {}).get("tpm_ready")
    if ta is True and tn is False:
        ev.append("TPM deixou de estar pronto")
    boot_a, boot_n = _text(so_a.get("last_boot")), _text(so_n.get("last_boot"))
    if boot_a and boot_n and boot_a != boot_n:
        ev.append("Computador reiniciado")
    ha, hn = _ultimo_hotfix(antigo), _ultimo_hotfix(novo)
    if hn and hn != ha:
        ev.append(f"Instalou a atualizacao {hn}")
    aa, an = _text(antigo.get("anydesk_id")), _text(novo.get("anydesk_id"))
    if an and aa != an:
        ev.append(f"AnyDesk ID {'mudou para' if aa else 'registrado:'} {an}")
    if _text(antigo.get("hostname")) and _text(novo.get("hostname")) and \
            _text(antigo.get("hostname")).lower() != _text(novo.get("hostname")).lower():
        ev.append(f"Nome mudou de {antigo.get('hostname')} para {novo.get('hostname')}")
    return ev


AGENTE_VERSAO = "2.1"
# Instalador com janela (tools/agente-windows). O mesmo binario para todos os
# clientes: a configuracao de cada um vai colada no fim, a cada download.
AGENTE_EXE_BASE = Path(__file__).resolve().parent / "assets" / "SightOpsAgente.exe"
_AGENTE_EXE_MARCA = b"SOPSAG01"


def build_windows_agent_exe(base_url: str, cliente: str = "") -> bytes:
    """O instalador .exe com o script do agente deste cliente colado no fim.

    Formato lido pelo SightOpsAgente.cs:
    [exe][cliente \\n "SITES" \\t site1 \\t site2... \\n script][int32 little-endian tamanho][b"SOPSAG01"]

    Os sites viram a lista do instalador: o operador escolhe em vez de digitar.
    """
    from app.core.tenant_context import get_current_tenant_slug

    base = AGENTE_EXE_BASE.read_bytes()
    nome = " ".join(_text(cliente).split())[:80]
    sites = [s["site"].replace("\t", " ") for s in sites_do_cliente(get_current_tenant_slug())]
    linha_sites = "\t".join(["SITES"] + sites)
    dados = (nome + "\n" + linha_sites + "\n" + build_windows_agent_script(base_url=base_url)).encode("utf-8")
    return base + dados + len(dados).to_bytes(4, "little") + _AGENTE_EXE_MARCA


def build_windows_agent_script(base_url: str) -> str:
    server = _text(base_url).rstrip("/") or "http://127.0.0.1"
    token = get_windows_agent_token()
    return f"""# SightOps - Agente de Inventario Windows {AGENTE_VERSAO}
# Execute em qualquer computador Windows que consiga acessar o servidor SightOps.
# Nao precisa senha remota, WinRM, dominio ou PIN. O computador envia o inventario para o servidor.
#
# Rodando como Administrador, o agente se copia para C:\\ProgramData\\SightOps e
# cria a tarefa "SightOps Inventario" (a cada 15 min e ao ligar), que reenvia
# o inventario sozinha. Sem isso o computador aparece como "sem contato".
#
# Instalar em varios computadores sem perguntas (GPO, AnyDesk, script):
#   powershell -ExecutionPolicy Bypass -File sightops-agente-windows.ps1 -Silencioso -Site "Sede" -Setor "Financeiro"
param(
  [switch]$Silencioso,
  [string]$Site = "",
  [string]$Setor = "",
  [switch]$SemAgendar,
  [switch]$InstalarAnyDesk
)

$ErrorActionPreference = "Stop"
$SightOpsUrl = "{server}"
$AgentToken = "{token}"
$AgentVersion = "{AGENTE_VERSAO}"
$SightOpsDir = Join-Path $env:ProgramData "SightOps"
$SightOpsCopia = Join-Path $SightOpsDir "agente.ps1"
$SightOpsCfg = Join-Path $SightOpsDir "agente.json"
$SightOpsTarefa = "SightOps Inventario"

Write-Host "Coletando inventario local para o SightOps..." -ForegroundColor Cyan
$cfgSalva = $null
if (Test-Path $SightOpsCfg) {{ try {{ $cfgSalva = Get-Content $SightOpsCfg -Raw | ConvertFrom-Json }} catch {{}} }}
if (-not $Site -and $cfgSalva) {{ $Site = [string]$cfgSalva.site }}
if (-not $Setor -and $cfgSalva) {{ $Setor = [string]$cfgSalva.setor }}
if (-not $Silencioso) {{
  if (-not $Site) {{ $Site = Read-Host "Site/unidade deste computador (ex: Matriz, Clinica Centro)" }}
  if (-not $Setor) {{ $Setor = Read-Host "Setor deste computador (ex: Recepcao, Financeiro, Consultorio 1)" }}
}}
$SightOpsSite = $Site
$SightOpsSector = $Setor

$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Register-SightOpsAgendamento {{
  # A copia em ProgramData e quem a tarefa roda: o .ps1 baixado costuma ficar
  # em Downloads e ser apagado.
  try {{
    New-Item -ItemType Directory -Force -Path $SightOpsDir | Out-Null
    if ($PSCommandPath -and ($PSCommandPath -ne $SightOpsCopia)) {{
      Copy-Item -Path $PSCommandPath -Destination $SightOpsCopia -Force
    }}
    if (-not (Test-Path $SightOpsCopia)) {{ throw "rode o arquivo .ps1 (nao colado no console) para instalar a tarefa" }}
    [PSCustomObject]@{{ site = $SightOpsSite; setor = $SightOpsSector }} | ConvertTo-Json | Set-Content -Path $SightOpsCfg -Encoding UTF8
    $argumento = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $SightOpsCopia + '" -Silencioso'
    $acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumento
    $aCada15 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
    $aoLigar = New-ScheduledTaskTrigger -AtStartup
    $quem = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $como = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $SightOpsTarefa -Action $acao -Trigger @($aCada15, $aoLigar) -Principal $quem -Settings $como -Force | Out-Null
    Write-Host "Tarefa '$SightOpsTarefa' criada: o inventario sera reenviado a cada 15 min." -ForegroundColor Green
  }} catch {{
    Write-Host ("Nao consegui criar a tarefa agendada: " + $_.Exception.Message) -ForegroundColor Yellow
  }}
}}

function Test-SightOpsAgendado {{
  try {{ return [bool](Get-ScheduledTask -TaskName $SightOpsTarefa -ErrorAction Stop) }} catch {{ return $false }}
}}

function Convert-SightOpsSecureStringToPlainText {{
  param([Security.SecureString]$SecureText)
  if (-not $SecureText) {{ return "" }}
  $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureText)
  try {{ return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }}
  finally {{ if ($bstr -ne [IntPtr]::Zero) {{ [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }} }}
}}

function Get-AnyDeskExecutable {{
  $candidates = @(
    "$env:ProgramFiles\AnyDesk\AnyDesk.exe",
    "${{env:ProgramFiles(x86)}}\AnyDesk\AnyDesk.exe",
    "$env:ProgramData\AnyDesk\AnyDesk.exe"
  )
  foreach ($candidate in $candidates) {{
    if ($candidate -and (Test-Path $candidate)) {{ return $candidate }}
  }}
  $cmd = Get-Command AnyDesk.exe -ErrorAction SilentlyContinue
  if ($cmd) {{ return $cmd.Source }}
  return ""
}}

function Get-AnyDeskInventory {{
  param([string]$ExePath, [bool]$ConfiguredPassword = $false, [string]$ErrorMessage = "")
  $service = Get-Service -Name AnyDesk -ErrorAction SilentlyContinue
  $id = ""
  if ($ExePath -and (Test-Path $ExePath)) {{
    $tentativas = if ($Silencioso) {{ 2 }} else {{ 12 }}
    for ($i = 0; $i -lt $tentativas; $i++) {{
      try {{
        $raw = & $ExePath --get-id 2>$null | Select-Object -First 1
        $id = ($raw -as [string]).Trim()
      }} catch {{}}
      if ($id) {{ break }}
      Start-Sleep -Seconds 5
    }}
  }}
  return [PSCustomObject]@{{
    installed = [bool]($ExePath -and (Test-Path $ExePath))
    id = $id
    service_status = if ($service) {{ $service.Status.ToString() }} else {{ "" }}
    path = $ExePath
    unattended_password_configured = $ConfiguredPassword
    error = $ErrorMessage
  }}
}}

function Install-And-Configure-AnyDesk {{
  $exe = Get-AnyDeskExecutable
  $passwordConfigured = $false
  $errorMessage = ""
  if ($Silencioso -and -not $InstalarAnyDesk) {{
    # Sem ninguem na frente e sem pedido de instalar: so le o que ja existe.
    return Get-AnyDeskInventory -ExePath $exe -ConfiguredPassword $false -ErrorMessage ""
  }}
  try {{
    if (-not $Silencioso) {{
      $choice = Read-Host "Instalar/configurar AnyDesk para acesso remoto? [S/n]"
      if ($choice -match '^[Nn]') {{
        return Get-AnyDeskInventory -ExePath $exe -ConfiguredPassword $false -ErrorMessage "Instalacao ignorada pelo operador"
      }}
    }}
    if (-not $IsAdmin) {{
      return Get-AnyDeskInventory -ExePath $exe -ConfiguredPassword $false -ErrorMessage "Execute como Administrador para instalar/configurar AnyDesk"
    }}
    if (-not $exe) {{
      $installer = Join-Path $env:TEMP "AnyDesk.exe"
      Write-Host "Baixando AnyDesk..." -ForegroundColor Cyan
      Invoke-WebRequest -Uri "https://download.anydesk.com/AnyDesk.exe" -OutFile $installer -UseBasicParsing -TimeoutSec 300
      $installDir = "$env:ProgramFiles\AnyDesk"
      Write-Host "Instalando AnyDesk em modo silencioso..." -ForegroundColor Cyan
      $proc = Start-Process -FilePath $installer -ArgumentList @("--install", "`"$installDir`"", "--start-with-win", "--create-shortcuts", "--create-desktop-icon", "--silent") -Wait -PassThru
      if ($proc.ExitCode -ne 0) {{ Write-Host "Instalador retornou codigo $($proc.ExitCode). Continuando validacao..." -ForegroundColor Yellow }}
      Start-Sleep -Seconds 8
      $exe = Get-AnyDeskExecutable
    }}
    if ($exe -and (Test-Path $exe)) {{
      $service = Get-Service -Name AnyDesk -ErrorAction SilentlyContinue
      if ($service) {{
        Set-Service -Name AnyDesk -StartupType Automatic -ErrorAction SilentlyContinue
        Start-Service -Name AnyDesk -ErrorAction SilentlyContinue
      }}
      $setPass = if ($Silencioso) {{ "n" }} else {{ Read-Host "Definir senha para acesso nao supervisionado no AnyDesk? [s/N]" }}
      if ($setPass -match '^[Ss]') {{
        $securePass = Read-Host "Digite a senha do AnyDesk" -AsSecureString
        $plainPass = Convert-SightOpsSecureStringToPlainText -SecureText $securePass
        if ($plainPass) {{
          $plainPass | & $exe --set-password | Out-Null
          $passwordConfigured = $true
          $plainPass = $null
        }}
      }}
    }} else {{
      $errorMessage = "AnyDesk nao encontrado apos instalacao"
    }}
  }} catch {{
    $errorMessage = $_.Exception.Message
    Write-Host ("AnyDesk: " + $errorMessage) -ForegroundColor Yellow
  }}
  return Get-AnyDeskInventory -ExePath $exe -ConfiguredPassword $passwordConfigured -ErrorMessage $errorMessage
}}

function Get-SightOpsServerHost {{
  try {{
    $uri = [Uri]$SightOpsUrl
    if ($uri.Host) {{ return $uri.Host }}
  }} catch {{}}
  return "10.10.12.7"
}}

function Get-ZabbixAgentInventory {{
  param([string]$ServerHost = "", [string]$ErrorMessage = "")
  $service = Get-Service -Name "Zabbix Agent 2" -ErrorAction SilentlyContinue
  if (-not $service) {{ $service = Get-Service -Name "Zabbix Agent" -ErrorAction SilentlyContinue }}
  $confCandidates = @(
    "$env:ProgramFiles\Zabbix Agent 2\zabbix_agent2.conf",
    "$env:ProgramFiles\Zabbix Agent\zabbix_agentd.conf",
    "${{env:ProgramFiles(x86)}}\Zabbix Agent 2\zabbix_agent2.conf",
    "${{env:ProgramFiles(x86)}}\Zabbix Agent\zabbix_agentd.conf"
  )
  $conf = $confCandidates | Where-Object {{ $_ -and (Test-Path $_) }} | Select-Object -First 1
  $server = $ServerHost
  $serverActive = $ServerHost
  $agentHost = $env:COMPUTERNAME
  if ($conf) {{
    try {{
      $lines = Get-Content $conf -ErrorAction SilentlyContinue
      $serverLine = $lines | Where-Object {{ $_ -match '^Server=' }} | Select-Object -Last 1
      $activeLine = $lines | Where-Object {{ $_ -match '^ServerActive=' }} | Select-Object -Last 1
      $hostLine = $lines | Where-Object {{ $_ -match '^Hostname=' }} | Select-Object -Last 1
      if ($serverLine) {{ $server = ($serverLine -replace '^Server=', '').Trim() }}
      if ($activeLine) {{ $serverActive = ($activeLine -replace '^ServerActive=', '').Trim() }}
      if ($hostLine) {{ $agentHost = ($hostLine -replace '^Hostname=', '').Trim() }}
    }} catch {{}}
  }}
  $version = ""
  try {{
    $cmd = Get-Command zabbix_agent2.exe -ErrorAction SilentlyContinue
    if ($cmd) {{
      $raw = & $cmd.Source --version 2>$null | Select-Object -First 1
      $version = ($raw -as [string]).Trim()
    }}
  }} catch {{}}
  return [PSCustomObject]@{{
    installed = [bool]$service
    service_status = if ($service) {{ $service.Status.ToString() }} else {{ "" }}
    server = $server
    server_active = $serverActive
    hostname = $agentHost
    config_path = $conf
    version = $version
    error = $ErrorMessage
  }}
}}

function Install-And-Configure-ZabbixAgent {{
  # So registra o Zabbix Agent se ja existir. A instalacao saiu (14/10/2026):
  # o PC do cliente nao alcanca o Zabbix pelo dominio (so passa HTTP), entao o
  # agente instalado nunca conversava com o servidor. O computador chega ao
  # Zabbix pelo proprio SightOps, com o inventario que este agente envia.
  return Get-ZabbixAgentInventory -ServerHost (Get-SightOpsServerHost) -ErrorMessage ""
}}

$anydeskInfo = Install-And-Configure-AnyDesk
if ($anydeskInfo.id) {{
  Write-Host ("AnyDesk ID: " + $anydeskInfo.id) -ForegroundColor Green
}} elseif ($anydeskInfo.error) {{
  Write-Host ("AnyDesk sem ID: " + $anydeskInfo.error) -ForegroundColor Yellow
}}

$zabbixInfo = Install-And-Configure-ZabbixAgent

$cs = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$bb = Get-CimInstance Win32_BaseBoard
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$mem = Get-CimInstance Win32_PhysicalMemory
$gpu = Get-CimInstance Win32_VideoController | ForEach-Object {{
  [PSCustomObject]@{{
    name = $_.Name
    processor = $_.VideoProcessor
    driver_version = $_.DriverVersion
    adapter_ram_gb = if ($_.AdapterRAM) {{ [math]::Round([double]$_.AdapterRAM / 1GB, 2) }} else {{ $null }}
    resolution = if ($_.CurrentHorizontalResolution -and $_.CurrentVerticalResolution) {{ "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)" }} else {{ "" }}
  }}
}}
$battery = Get-CimInstance Win32_Battery | ForEach-Object {{
  [PSCustomObject]@{{
    name = $_.Name
    status = $_.Status
    estimated_charge = $_.EstimatedChargeRemaining
    chemistry = $_.Chemistry
  }}
}}
$volumes = Get-CimInstance Win32_LogicalDisk -Filter "DriveType = 3" | ForEach-Object {{
  [PSCustomObject]@{{
    drive = $_.DeviceID
    label = $_.VolumeName
    file_system = $_.FileSystem
    size_gb = if ($_.Size) {{ [math]::Round([double]$_.Size / 1GB, 2) }} else {{ $null }}
    free_gb = if ($_.FreeSpace) {{ [math]::Round([double]$_.FreeSpace / 1GB, 2) }} else {{ $null }}
    free_percent = if ($_.Size) {{ [math]::Round(([double]$_.FreeSpace / [double]$_.Size) * 100, 1) }} else {{ $null }}
  }}
}}
$tpmInfo = $null
try {{
  $tpm = Get-Tpm
  $tpmInfo = [PSCustomObject]@{{
    present = $tpm.TpmPresent
    ready = $tpm.TpmReady
    enabled = $tpm.TpmEnabled
    activated = $tpm.TpmActivated
    owned = $tpm.TpmOwned
  }}
}} catch {{}}
$secureBoot = $null
try {{ $secureBoot = Confirm-SecureBootUEFI }} catch {{}}
$bitlocker = @()
try {{
  $bitlocker = Get-BitLockerVolume | ForEach-Object {{
    [PSCustomObject]@{{
      mount_point = $_.MountPoint
      volume_status = $_.VolumeStatus
      protection_status = $_.ProtectionStatus
      encryption_method = $_.EncryptionMethod
      encryption_percentage = $_.EncryptionPercentage
    }}
  }}
}} catch {{}}
$defender = $null
try {{
  $mp = Get-MpComputerStatus
  $defender = [PSCustomObject]@{{
    enabled = $mp.AntivirusEnabled
    realtime = $mp.RealTimeProtectionEnabled
    signature_version = $mp.AntivirusSignatureVersion
    last_quick_scan = $mp.QuickScanEndTime
    last_full_scan = $mp.FullScanEndTime
  }}
}} catch {{}}
$hotfixes = @()
try {{
  $hotfixes = Get-CimInstance Win32_QuickFixEngineering | ForEach-Object {{
    $installed = ""
    try {{ $installed = ($_.InstalledOn -as [string]).Trim() }} catch {{}}
    [PSCustomObject]@{{ id = $_.HotFixID; installed_on = $installed; description = $_.Description; quando = ($_.InstalledOn -as [datetime]) }}
  }} | Sort-Object -Property quando -Descending | Select-Object -First 8 | Select-Object id, installed_on, description
}} catch {{}}
$memoryModules = $mem | ForEach-Object {{
  $ddr = switch ([int]$_.SMBIOSMemoryType) {{
    20 {{ "DDR" }}
    21 {{ "DDR2" }}
    24 {{ "DDR3" }}
    26 {{ "DDR4" }}
    34 {{ "DDR5" }}
    default {{ if ($_.MemoryType) {{ "Tipo " + $_.MemoryType }} else {{ "" }} }}
  }}
  [PSCustomObject]@{{
    bank = $_.BankLabel
    slot = $_.DeviceLocator
    manufacturer = $_.Manufacturer
    part_number = ($_.PartNumber -as [string]).Trim()
    serial = $_.SerialNumber
    capacity_gb = if ($_.Capacity) {{ [math]::Round([double]$_.Capacity / 1GB, 2) }} else {{ $null }}
    speed_mhz = $_.Speed
    configured_speed_mhz = $_.ConfiguredClockSpeed
    memory_type = $_.MemoryType
    smbios_memory_type = $_.SMBIOSMemoryType
    ddr = $ddr
    form_factor = $_.FormFactor
  }}
}}
$disks = Get-CimInstance Win32_DiskDrive | ForEach-Object {{
  [PSCustomObject]@{{
    model = $_.Model
    manufacturer = $_.Manufacturer
    serial = $_.SerialNumber
    firmware = $_.FirmwareRevision
    interface_type = $_.InterfaceType
    media_type = $_.MediaType
    pnp_device_id = $_.PNPDeviceID
    size_gb = if ($_.Size) {{ [math]::Round([double]$_.Size / 1GB, 2) }} else {{ $null }}
  }}
}}
$net = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled = True" | ForEach-Object {{
  [PSCustomObject]@{{
    description = $_.Description
    mac = $_.MACAddress
    ip = @($_.IPAddress)
    gateway = @($_.DefaultIPGateway)
    dns = @($_.DNSServerSearchOrder)
  }}
}}
$primaryIpv4 = @($net | ForEach-Object {{ @($_.ip) }} | Where-Object {{ $_ -match '^\\d+\\.\\d+\\.\\d+\\.\\d+$' -and $_ -notmatch '^127\\.' }}) | Select-Object -First 1
$Agendar = $IsAdmin -and -not $SemAgendar -and ($PSCommandPath -ne $SightOpsCopia)
$payload = [PSCustomObject]@{{
  source = "agent"
  agent_version = $AgentVersion
  agent_scheduled = ($Agendar -or (Test-SightOpsAgendado))
  hostname = $env:COMPUTERNAME
  primary_ipv4 = $primaryIpv4
  site = $SightOpsSite
  sector = $SightOpsSector
  domain = $cs.Domain
  manufacturer = $cs.Manufacturer
  model = $cs.Model
  logged_user = $cs.UserName
  total_ram_gb = if ($cs.TotalPhysicalMemory) {{ [math]::Round([double]$cs.TotalPhysicalMemory / 1GB, 2) }} else {{ $null }}
  chassis_types = @($cs.ChassisTypes)
  system_sku = $cs.SystemSKUNumber
  pc_system_type = $cs.PCSystemType
  timezone = (Get-TimeZone).Id
  memory_slots = @($mem).Count
  memory_modules = @($memoryModules)
  os_name = $os.Caption
  os_version = $os.Version
  os_build = $os.BuildNumber
  os_arch = $os.OSArchitecture
  install_date = $os.InstallDate
  last_boot = $os.LastBootUpTime
  cpu = $cpu.Name
  cpu_cores = $cpu.NumberOfCores
  cpu_threads = $cpu.NumberOfLogicalProcessors
  gpus = @($gpu)
  batteries = @($battery)
  bios_serial = $bios.SerialNumber
  bios_version = $bios.SMBIOSBIOSVersion
  bios_release_date = $bios.ReleaseDate
  motherboard_manufacturer = $bb.Manufacturer
  motherboard_model = $bb.Product
  motherboard_serial = $bb.SerialNumber
  disks = @($disks)
  volumes = @($volumes)
  network = @($net)
  tpm = $tpmInfo
  secure_boot = $secureBoot
  bitlocker = @($bitlocker)
  defender = $defender
  hotfixes = @($hotfixes)
  anydesk_id = $anydeskInfo.id
  zabbix_agent = $zabbixInfo
  remote_access = [PSCustomObject]@{{
    anydesk = $anydeskInfo
  }}
}}

$json = $payload | ConvertTo-Json -Depth 8
$endpoint = "$SightOpsUrl/api/windows/agent/report"
Write-Host "Enviando inventario para $endpoint ..." -ForegroundColor Cyan
$resp = Invoke-RestMethod -Method Post -Uri $endpoint -ContentType "application/json; charset=utf-8" -Headers @{{ "X-SightOps-Agent-Token" = $AgentToken }} -Body $json
Write-Host "Inventario enviado com sucesso." -ForegroundColor Green
Write-Host ("Host: " + $resp.row.hostname + " / IP: " + $resp.row.ip)
if ($Agendar) {{
  Register-SightOpsAgendamento
}} elseif (-not $IsAdmin -and -not $Silencioso) {{
  Write-Host "Rodou sem Administrador: o inventario foi enviado uma vez, mas a tarefa que reenvia a cada 15 min nao foi criada." -ForegroundColor Yellow
}}
"""
