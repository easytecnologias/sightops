from __future__ import annotations

import ipaddress
import json
import socket
import base64
import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _parse_targets(raw: str, limit: int = 2048) -> List[str]:
    targets: list[str] = []
    seen: set[str] = set()
    chunks = (
        str(raw or "")
        .replace("\r", "\n")
        .replace(",", "\n")
        .replace(";", "\n")
        .split()
    )
    for chunk in chunks:
        item = chunk.strip()
        if not item:
            continue
        try:
            if "/" in item:
                net = ipaddress.ip_network(item, strict=False)
                if net.version != 4:
                    continue
                for ip in net.hosts():
                    value = str(ip)
                    if value not in seen:
                        seen.add(value)
                        targets.append(value)
                    if len(targets) >= limit:
                        return targets
                continue
            if "-" in item:
                left, right = item.split("-", 1)
                start = ipaddress.ip_address(left.strip())
                if "." in right:
                    end = ipaddress.ip_address(right.strip())
                else:
                    octets = left.strip().split(".")
                    octets[-1] = right.strip()
                    end = ipaddress.ip_address(".".join(octets))
                if start.version != 4 or end.version != 4:
                    continue
                a, b = int(start), int(end)
                if b < a:
                    a, b = b, a
                for value_int in range(a, b + 1):
                    value = str(ipaddress.ip_address(value_int))
                    if value not in seen:
                        seen.add(value)
                        targets.append(value)
                    if len(targets) >= limit:
                        return targets
                continue
            ip = ipaddress.ip_address(item)
            if ip.version == 4:
                value = str(ip)
                if value not in seen:
                    seen.add(value)
                    targets.append(value)
        except Exception:
            continue
        if len(targets) >= limit:
            return targets
    return targets


def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, int(port)), timeout=max(0.2, float(timeout or 1.0))):
            return True
    except Exception:
        return False


def _hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0] or ""
    except Exception:
        return ""


def _powershell_inventory_script() -> str:
    return r"""
$ErrorActionPreference = "SilentlyContinue"
$cs = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$bb = Get-CimInstance Win32_BaseBoard
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$mem = Get-CimInstance Win32_PhysicalMemory
$gpu = Get-CimInstance Win32_VideoController | ForEach-Object {
  [PSCustomObject]@{
    name = $_.Name
    processor = $_.VideoProcessor
    driver_version = $_.DriverVersion
    adapter_ram_gb = if ($_.AdapterRAM) { [math]::Round([double]$_.AdapterRAM / 1GB, 2) } else { $null }
    resolution = if ($_.CurrentHorizontalResolution -and $_.CurrentVerticalResolution) { "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)" } else { "" }
  }
}
$battery = Get-CimInstance Win32_Battery | ForEach-Object {
  [PSCustomObject]@{
    name = $_.Name
    status = $_.Status
    estimated_charge = $_.EstimatedChargeRemaining
    chemistry = $_.Chemistry
  }
}
$volumes = Get-CimInstance Win32_LogicalDisk -Filter "DriveType = 3" | ForEach-Object {
  [PSCustomObject]@{
    drive = $_.DeviceID
    label = $_.VolumeName
    file_system = $_.FileSystem
    size_gb = if ($_.Size) { [math]::Round([double]$_.Size / 1GB, 2) } else { $null }
    free_gb = if ($_.FreeSpace) { [math]::Round([double]$_.FreeSpace / 1GB, 2) } else { $null }
    free_percent = if ($_.Size) { [math]::Round(([double]$_.FreeSpace / [double]$_.Size) * 100, 1) } else { $null }
  }
}
$tpmInfo = $null
try {
  $tpm = Get-Tpm
  $tpmInfo = [PSCustomObject]@{
    present = $tpm.TpmPresent
    ready = $tpm.TpmReady
    enabled = $tpm.TpmEnabled
    activated = $tpm.TpmActivated
    owned = $tpm.TpmOwned
  }
} catch {}
$secureBoot = $null
try { $secureBoot = Confirm-SecureBootUEFI } catch {}
$bitlocker = @()
try {
  $bitlocker = Get-BitLockerVolume | ForEach-Object {
    [PSCustomObject]@{
      mount_point = $_.MountPoint
      volume_status = $_.VolumeStatus
      protection_status = $_.ProtectionStatus
      encryption_method = $_.EncryptionMethod
      encryption_percentage = $_.EncryptionPercentage
    }
  }
} catch {}
$defender = $null
try {
  $mp = Get-MpComputerStatus
  $defender = [PSCustomObject]@{
    enabled = $mp.AntivirusEnabled
    realtime = $mp.RealTimeProtectionEnabled
    signature_version = $mp.AntivirusSignatureVersion
    last_quick_scan = $mp.QuickScanEndTime
    last_full_scan = $mp.FullScanEndTime
  }
} catch {}
$hotfixes = @()
try {
  $hotfixes = Get-CimInstance Win32_QuickFixEngineering | ForEach-Object {
    $installed = ""
    try { $installed = ($_.InstalledOn -as [string]).Trim() } catch {}
    [PSCustomObject]@{ id = $_.HotFixID; installed_on = $installed; description = $_.Description }
  } | Select-Object -First 8
} catch {}
$memoryModules = $mem | ForEach-Object {
  $ddr = switch ([int]$_.SMBIOSMemoryType) {
    20 { "DDR" }
    21 { "DDR2" }
    24 { "DDR3" }
    26 { "DDR4" }
    34 { "DDR5" }
    default { if ($_.MemoryType) { "Tipo " + $_.MemoryType } else { "" } }
  }
  [PSCustomObject]@{
    bank = $_.BankLabel
    slot = $_.DeviceLocator
    manufacturer = $_.Manufacturer
    part_number = ($_.PartNumber -as [string]).Trim()
    serial = $_.SerialNumber
    capacity_gb = if ($_.Capacity) { [math]::Round([double]$_.Capacity / 1GB, 2) } else { $null }
    speed_mhz = $_.Speed
    configured_speed_mhz = $_.ConfiguredClockSpeed
    memory_type = $_.MemoryType
    smbios_memory_type = $_.SMBIOSMemoryType
    ddr = $ddr
    form_factor = $_.FormFactor
  }
}
$disks = Get-CimInstance Win32_DiskDrive | ForEach-Object {
  [PSCustomObject]@{
    model = $_.Model
    manufacturer = $_.Manufacturer
    serial = $_.SerialNumber
    firmware = $_.FirmwareRevision
    interface_type = $_.InterfaceType
    media_type = $_.MediaType
    pnp_device_id = $_.PNPDeviceID
    size_gb = if ($_.Size) { [math]::Round([double]$_.Size / 1GB, 2) } else { $null }
  }
}
$net = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled = True" | ForEach-Object {
  [PSCustomObject]@{
    description = $_.Description
    mac = $_.MACAddress
    ip = @($_.IPAddress)
    gateway = @($_.DefaultIPGateway)
    dns = @($_.DNSServerSearchOrder)
  }
}
$payload = [PSCustomObject]@{
  hostname = $env:COMPUTERNAME
  domain = $cs.Domain
  manufacturer = $cs.Manufacturer
  model = $cs.Model
  logged_user = $cs.UserName
  total_ram_gb = if ($cs.TotalPhysicalMemory) { [math]::Round([double]$cs.TotalPhysicalMemory / 1GB, 2) } else { $null }
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
}
$payload | ConvertTo-Json -Depth 6 -Compress
"""


def _encoded_powershell_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _load_winrm_module() -> Any:
    try:
        import winrm  # type: ignore

        return winrm
    except Exception:
        return None


def _collect_winrm(
    ip: str,
    username: str,
    password: str,
    *,
    domain: str = "",
    use_https: bool = False,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    winrm = _load_winrm_module()
    if winrm is None:
        return {
            "ok": False,
            "status": "dependency_missing",
            "error": "Dependencia pywinrm nao instalada no ambiente da API.",
        }

    user = _text(username)
    if domain and "\\" not in user and "@" not in user:
        user = f"{_text(domain)}\\{user}"

    scheme = "https" if use_https else "http"
    port = 5986 if use_https else 5985
    endpoint = f"{scheme}://{ip}:{port}/wsman"
    try:
        session = winrm.Session(
            endpoint,
            auth=(user, password),
            transport="ntlm",
            server_cert_validation="ignore",
            read_timeout_sec=max(10, int(timeout) + 8),
            operation_timeout_sec=max(6, int(timeout)),
        )
        script = _powershell_inventory_script()
        try:
            result = session.run_ps(script)
        except Exception:
            result = session.run_cmd(
                "powershell.exe",
                [
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    _encoded_powershell_command(script),
                ],
            )
    except Exception as exc:
        return {"ok": False, "status": "auth_or_connection_failed", "error": str(exc)[:500]}

    stdout = bytes(result.std_out or b"").decode("utf-8", errors="replace").strip()
    stderr = bytes(result.std_err or b"").decode("utf-8", errors="replace").strip()
    if int(result.status_code or 0) != 0:
        return {
            "ok": False,
            "status": "command_failed",
            "error": (stderr or stdout or f"PowerShell retornou codigo {result.status_code}")[:500],
        }
    try:
        data = json.loads(stdout)
    except Exception:
        return {"ok": False, "status": "invalid_json", "error": stdout[:500]}
    if not isinstance(data, dict):
        return {"ok": False, "status": "invalid_payload", "error": "Payload WinRM inesperado."}
    return {"ok": True, "status": "online", "data": data}


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
        if float(row.get("ram_gb") or 0) < 8:
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
    current = load_windows_inventory(tenant_slug=tenant_slug)
    merged = _merge_rows(current, [row])
    save_windows_inventory(merged, tenant_slug=tenant_slug)
    return {"ok": True, "saved": True, "row": row}


def build_windows_agent_script(base_url: str) -> str:
    server = _text(base_url).rstrip("/") or "http://127.0.0.1"
    token = get_windows_agent_token()
    return f"""# SightOps - Agente de Inventario Windows
# Execute em qualquer computador Windows que consiga acessar o servidor SightOps.
# Nao precisa senha remota, WinRM, dominio ou PIN. O computador envia o inventario para o servidor.

$ErrorActionPreference = "Stop"
$SightOpsUrl = "{server}"
$AgentToken = "{token}"

Write-Host "Coletando inventario local para o SightOps..." -ForegroundColor Cyan
$SightOpsSite = Read-Host "Site/unidade deste computador (ex: Matriz, Clinica Centro)"
$SightOpsSector = Read-Host "Setor deste computador (ex: Recepcao, Financeiro, Consultorio 1)"

$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

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
    for ($i = 0; $i -lt 12; $i++) {{
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
  try {{
    $choice = Read-Host "Instalar/configurar AnyDesk para acesso remoto? [S/n]"
    if ($choice -match '^[Nn]') {{
      return Get-AnyDeskInventory -ExePath $exe -ConfiguredPassword $false -ErrorMessage "Instalacao ignorada pelo operador"
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
      $setPass = Read-Host "Definir senha para acesso nao supervisionado no AnyDesk? [s/N]"
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
  $serverHost = Get-SightOpsServerHost
  $errorMessage = ""
  try {{
    $choice = Read-Host "Instalar/configurar Zabbix Agent 2 para monitoramento? [S/n]"
    if ($choice -match '^[Nn]') {{
      return Get-ZabbixAgentInventory -ServerHost $serverHost -ErrorMessage "Instalacao ignorada pelo operador"
    }}
    if (-not $IsAdmin) {{
      return Get-ZabbixAgentInventory -ServerHost $serverHost -ErrorMessage "Execute como Administrador para instalar/configurar Zabbix Agent"
    }}
    $service = Get-Service -Name "Zabbix Agent 2" -ErrorAction SilentlyContinue
    if (-not $service) {{
      $installer = Join-Path $env:TEMP "zabbix_agent2_latest.msi"
      $urls = @(
        "https://cdn.zabbix.com/zabbix/binaries/stable/7.0/latest/zabbix_agent2-7.0-latest-windows-amd64-openssl.msi",
        "https://cdn.zabbix.com/zabbix/binaries/stable/6.0/latest/zabbix_agent2-6.0-latest-windows-amd64-openssl.msi"
      )
      foreach ($url in $urls) {{
        try {{
          Write-Host ("Baixando Zabbix Agent 2: " + $url) -ForegroundColor Cyan
          Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing -TimeoutSec 300
          if (Test-Path $installer) {{ break }}
        }} catch {{
          $errorMessage = $_.Exception.Message
        }}
      }}
      if (-not (Test-Path $installer)) {{ throw "Nao foi possivel baixar o instalador do Zabbix Agent 2. $errorMessage" }}
      $args = @(
        "/i", "`"$installer`"",
        "/qn",
        "SERVER=$serverHost",
        "SERVERACTIVE=$serverHost",
        "HOSTNAME=$env:COMPUTERNAME",
        "LISTENPORT=10050"
      )
      Write-Host "Instalando Zabbix Agent 2 em modo silencioso..." -ForegroundColor Cyan
      $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList $args -Wait -PassThru
      if ($proc.ExitCode -ne 0) {{ Write-Host "Instalador Zabbix retornou codigo $($proc.ExitCode). Continuando validacao..." -ForegroundColor Yellow }}
      Start-Sleep -Seconds 5
    }}
    $service = Get-Service -Name "Zabbix Agent 2" -ErrorAction SilentlyContinue
    if ($service) {{
      Set-Service -Name "Zabbix Agent 2" -StartupType Automatic -ErrorAction SilentlyContinue
      Start-Service -Name "Zabbix Agent 2" -ErrorAction SilentlyContinue
      New-NetFirewallRule -DisplayName "SightOps Zabbix Agent 10050" -Direction Inbound -Protocol TCP -LocalPort 10050 -Action Allow -Profile Any -ErrorAction SilentlyContinue | Out-Null
    }}
  }} catch {{
    $errorMessage = $_.Exception.Message
    Write-Host ("Zabbix Agent: " + $errorMessage) -ForegroundColor Yellow
  }}
  return Get-ZabbixAgentInventory -ServerHost $serverHost -ErrorMessage $errorMessage
}}

$anydeskInfo = Install-And-Configure-AnyDesk
if ($anydeskInfo.id) {{
  Write-Host ("AnyDesk ID: " + $anydeskInfo.id) -ForegroundColor Green
}} elseif ($anydeskInfo.error) {{
  Write-Host ("AnyDesk sem ID: " + $anydeskInfo.error) -ForegroundColor Yellow
}}

$zabbixInfo = Install-And-Configure-ZabbixAgent
if ($zabbixInfo.installed) {{
  Write-Host ("Zabbix Agent: " + $zabbixInfo.service_status + " / Server: " + $zabbixInfo.server_active) -ForegroundColor Green
}} elseif ($zabbixInfo.error) {{
  Write-Host ("Zabbix Agent nao instalado: " + $zabbixInfo.error) -ForegroundColor Yellow
}}

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
    [PSCustomObject]@{{ id = $_.HotFixID; installed_on = $installed; description = $_.Description }}
  }} | Select-Object -First 8
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
$payload = [PSCustomObject]@{{
  source = "agent"
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
"""


def build_windows_prepare_script(username: str = "sightops_inv") -> str:
    user = _text(username) or "sightops_inv"
    safe_user = "".join(ch for ch in user if ch.isalnum() or ch in ("_", "-", "."))
    if not safe_user:
        safe_user = "sightops_inv"
    return f"""# SightOps - Preparar Windows para inventario remoto
# Execute este arquivo como Administrador no computador Windows alvo.
# O script NAO contem senha gravada: ele pede a senha localmente.

$ErrorActionPreference = "Stop"
$UserName = "{safe_user}"

Write-Host "Preparando WinRM/WMI para inventario SightOps..." -ForegroundColor Cyan

$IsAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {{
  if ($PSCommandPath) {{
    Write-Host "Solicitando permissao de Administrador..." -ForegroundColor Yellow
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-File", "`"$PSCommandPath`""
    )
    exit 0
  }}
  Write-Error "Execute este PowerShell como Administrador."
  exit 1
}}

$Password = Read-Host "Digite a senha que sera usada para o usuario local $UserName" -AsSecureString
if (-not $Password) {{
  Write-Error "Senha obrigatoria."
  exit 1
}}

$Existing = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
if ($Existing) {{
  Set-LocalUser -Name $UserName -Password $Password -PasswordNeverExpires $true
  Enable-LocalUser -Name $UserName
  Write-Host "Usuario $UserName atualizado." -ForegroundColor Green
}} else {{
  New-LocalUser -Name $UserName -Password $Password -FullName "SightOps Inventory" -Description "Usuario local para inventario remoto SightOps" -PasswordNeverExpires
  Write-Host "Usuario $UserName criado." -ForegroundColor Green
}}

function Add-UserToLocalGroupBySid($Sid, $Member) {{
  $Group = Get-LocalGroup | Where-Object {{ $_.SID.Value -eq $Sid }} | Select-Object -First 1
  if (-not $Group) {{
    Write-Host "Aviso: grupo local com SID $Sid nao encontrado." -ForegroundColor Yellow
    return
  }}
  try {{
    Add-LocalGroupMember -Group $Group.Name -Member $Member -ErrorAction Stop
    Write-Host "Usuario $Member adicionado ao grupo $($Group.Name)." -ForegroundColor Green
  }} catch {{
    if ($_.Exception.Message -match "ja.*membro|already.*member") {{
      Write-Host "Usuario $Member ja pertence ao grupo $($Group.Name)." -ForegroundColor DarkGray
    }} else {{
      Write-Host "Aviso: nao foi possivel adicionar $Member ao grupo $($Group.Name): $($_.Exception.Message)" -ForegroundColor Yellow
    }}
  }}
}}

Add-UserToLocalGroupBySid "S-1-5-32-544" $UserName
Add-UserToLocalGroupBySid "S-1-5-32-580" $UserName

try {{
  $PublicProfiles = Get-NetConnectionProfile -ErrorAction Stop | Where-Object {{ $_.NetworkCategory -eq "Public" }}
  if ($PublicProfiles) {{
    Write-Host "Rede publica detectada. Alterando perfil ativo para Privada para liberar WinRM com seguranca operacional." -ForegroundColor Yellow
    $PublicProfiles | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction Stop
  }}
}} catch {{
  Write-Host "Aviso: nao foi possivel alterar o perfil de rede automaticamente: $($_.Exception.Message)" -ForegroundColor Yellow
}}

Set-Service -Name WinRM -StartupType Automatic
Start-Service -Name WinRM
Enable-PSRemoting -Force -SkipNetworkProfileCheck
winrm set winrm/config/service/auth '@{{Basic="false"; Kerberos="true"; Negotiate="true"}}' | Out-Null
winrm set winrm/config/service '@{{AllowUnencrypted="true"}}' | Out-Null

Write-Host "Reparando endpoints do PowerShell Remoting..." -ForegroundColor Cyan
$SessionConfigs = Get-PSSessionConfiguration -ErrorAction SilentlyContinue
if (-not ($SessionConfigs | Where-Object {{ $_.Name -eq "Microsoft.PowerShell" }})) {{
  Register-PSSessionConfiguration -Name "Microsoft.PowerShell" -Force | Out-Null
}}
if (-not ($SessionConfigs | Where-Object {{ $_.Name -eq "Microsoft.PowerShell32" }}) -and (Test-Path "$env:WINDIR\\SysWOW64\\WindowsPowerShell\\v1.0\\powershell.exe")) {{
  Register-PSSessionConfiguration -Name "Microsoft.PowerShell32" -ProcessorArchitecture x86 -Force | Out-Null
}}
Enable-PSSessionConfiguration -Name "Microsoft.PowerShell" -Force -ErrorAction SilentlyContinue | Out-Null
Enable-PSSessionConfiguration -Name "Microsoft.PowerShell32" -Force -ErrorAction SilentlyContinue | Out-Null
Restart-Service -Name WinRM -Force

Get-NetFirewallRule -DisplayName "SightOps WinRM HTTP 5985" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "SightOps WinRM HTTP 5985" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5985 -Profile Any | Out-Null

$LocalAccountTokenFilterPolicy = "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\System"
New-Item -Path $LocalAccountTokenFilterPolicy -Force | Out-Null
New-ItemProperty -Path $LocalAccountTokenFilterPolicy -Name LocalAccountTokenFilterPolicy -Value 1 -PropertyType DWord -Force | Out-Null

Write-Host ""
Write-Host "Validando WinRM local..." -ForegroundColor Cyan
Test-WSMan localhost | Out-Null
try {{
  $Credential = New-Object System.Management.Automation.PSCredential("$env:COMPUTERNAME\\$UserName", $Password)
  Invoke-Command -ComputerName 127.0.0.1 -Credential $Credential -Authentication Negotiate -ScriptBlock {{ hostname }} | Out-Null
  Write-Host "Validacao de login remoto OK." -ForegroundColor Green
}} catch {{
  Write-Host "Aviso: WinRM respondeu, mas o login remoto ainda falhou: $($_.Exception.Message)" -ForegroundColor Yellow
  Write-Host "Confira a senha digitada e rode este preparador novamente como Administrador." -ForegroundColor Yellow
}}

Write-Host ""
Write-Host "Preparacao concluida." -ForegroundColor Green
Write-Host "No SightOps, use:" -ForegroundColor Cyan
Write-Host "  Usuario: .\\$UserName"
Write-Host "  Senha: a senha digitada neste script"
Write-Host "  Porta: WinRM HTTP 5985"
Write-Host ""
Write-Host "Teste local opcional:"
Write-Host "  Test-WSMan localhost"
"""


def _merge_rows(old_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index: dict[str, Dict[str, Any]] = {}
    order: list[str] = []
    for row in old_rows or []:
        ip = _text(row.get("ip"))
        if not ip:
            continue
        if ip not in index:
            order.append(ip)
        index[ip] = dict(row)
    for row in new_rows or []:
        ip = _text(row.get("ip"))
        if not ip:
            continue
        if ip not in index:
            order.append(ip)
        merged = dict(index.get(ip) or {})
        merged.update(row)
        for keep_key in ("site", "sector"):
            if not _text(merged.get(keep_key)) and _text(index.get(ip, {}).get(keep_key)):
                merged[keep_key] = index[ip][keep_key]
        if isinstance(index.get(ip, {}).get("physical"), dict) and not isinstance(row.get("physical"), dict):
            merged["physical"] = index[ip]["physical"]
        index[ip] = merged
    return [index[ip] for ip in order if ip in index]


def scan_windows_inventory(payload: Dict[str, Any]) -> Dict[str, Any]:
    targets = _parse_targets(_text(payload.get("targets") or payload.get("alvo")), limit=int(payload.get("limit") or 2048))
    username = _text(payload.get("username") or payload.get("usuario") or payload.get("user"))
    password = _text(payload.get("password") or payload.get("senha") or payload.get("pass"))
    domain = _text(payload.get("domain") or payload.get("dominio"))
    use_https = bool(payload.get("use_https") or False)
    timeout = max(1.0, min(float(payload.get("timeout_sec") or 8.0), 30.0))
    concurrency = max(1, min(int(payload.get("concurrency") or 32), 128))
    save = bool(payload.get("save", True))

    if not targets:
        raise ValueError("Informe ao menos um alvo Windows.")
    if not username or not password:
        raise ValueError("Usuario e senha sao obrigatorios para inventario Windows remoto.")

    port = 5986 if use_https else 5985
    rows: list[dict[str, Any]] = []

    def scan_one(ip: str) -> Dict[str, Any]:
        host = _hostname(ip)
        if not _tcp_open(ip, port, timeout=min(timeout, 3.0)):
            return {
                "ip": ip,
                "hostname": host,
                "status": "winrm_closed",
                "error": f"Porta WinRM {port} fechada ou sem resposta.",
                "updated_at": _now(),
            }
        collected = _collect_winrm(
            ip,
            username,
            password,
            domain=domain,
            use_https=use_https,
            timeout=timeout,
        )
        if not collected.get("ok"):
            return {
                "ip": ip,
                "hostname": host,
                "status": _text(collected.get("status")) or "error",
                "error": _text(collected.get("error")),
                "updated_at": _now(),
            }
        return _normalize_inventory(ip, collected.get("data") or {}, status="online")

    with ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(targets)))) as executor:
        futures = [executor.submit(scan_one, ip) for ip in targets]
        for future in as_completed(futures):
            rows.append(future.result())

    rows.sort(key=lambda row: tuple(int(part) for part in str(row.get("ip") or "0.0.0.0").split(".") if part.isdigit()))
    if save:
        current = load_windows_inventory()
        merged = _merge_rows(current, rows)
        save_windows_inventory(merged)
    online = sum(1 for row in rows if row.get("status") == "online")
    return {
        "ok": True,
        "scanned": len(targets),
        "online": online,
        "failed": max(0, len(rows) - online),
        "saved": save,
        "inventory_path": str(_windows_inventory_path()),
        "rows": rows,
    }
