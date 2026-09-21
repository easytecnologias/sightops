from __future__ import annotations

import re
import socket
import time
from typing import Any


_IAC = 255
_DONT = 254
_DO = 253
_WONT = 252
_WILL = 251
_SB = 250
_SE = 240

_PROMPT_RE = re.compile(r"[A-Za-z0-9_.-]+(?:\([^)]+\))?[>#]\s*$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _clean_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="ignore").replace("\r", "")
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    return text


class IntelbrasSwitchTelnetClient:
    def __init__(self, host: str, username: str, password: str, port: int = 23, timeout: float = 10.0):
        self.host = str(host or "").strip()
        self.username = str(username or "").strip()
        self.password = str(password or "")
        self.port = int(port or 23)
        self.timeout = float(timeout or 10.0)
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(0.5)

        banner = self._read_until(("Username:", "login:", "Login:"), timeout=self.timeout)
        if not any(x in banner for x in ("Username:", "login:", "Login:")):
            raise RuntimeError("Prompt de usuario nao encontrado no switch.")

        self._send_line(self.username)
        pw_prompt = self._read_until(("Password:", "password:"), timeout=self.timeout)
        if "assword:" not in pw_prompt:
            raise RuntimeError("Prompt de senha nao encontrado no switch.")

        self._send_line(self.password)
        logged = self._read_until_prompt(timeout=self.timeout)
        if "Username or password error" in logged:
            raise RuntimeError("Credenciais invalidas no switch.")
        if not _PROMPT_RE.search(logged):
            raise RuntimeError("Prompt do switch nao detectado apos login.")

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self._send_line("exit")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
        self.sock = None

    def __enter__(self) -> "IntelbrasSwitchTelnetClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def enable(self) -> str:
        out = self.run_command("enable", expect_prompt=True)
        if "assword:" in out:
            self._send_line(self.password)
            out = self._read_until_prompt(timeout=self.timeout)
            if "Username or password error" in out:
                raise RuntimeError("Falha ao entrar em modo enable.")
        return out

    def run_command(self, command: str, expect_prompt: bool = True, timeout: float | None = None) -> str:
        self._flush_read_buffer()
        self._send_line(command)
        if expect_prompt:
            return self._read_until_prompt(timeout=timeout or self.timeout)
        return self._read_until((), timeout=timeout or self.timeout)

    def _send_line(self, value: str) -> None:
        if self.sock is None:
            raise RuntimeError("Socket telnet nao conectado.")
        self.sock.sendall(value.encode("utf-8") + b"\n")

    def _read_until(self, markers: tuple[str, ...], timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = self._recv_chunk()
            if chunk:
                buf += chunk
                text = _clean_text(buf)
                if markers and any(m in text for m in markers):
                    return text
                continue
            time.sleep(0.05)
        return _clean_text(buf)

    def _read_until_prompt(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = self._recv_chunk()
            if chunk:
                buf += chunk
                text = _clean_text(buf)
                lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
                if lines and _PROMPT_RE.search(lines[-1]):
                    return text
                continue
            time.sleep(0.05)
        return _clean_text(buf)

    def _flush_read_buffer(self) -> None:
        end = time.monotonic() + 0.25
        while time.monotonic() < end:
            chunk = self._recv_chunk()
            if not chunk:
                time.sleep(0.02)

    def _recv_chunk(self) -> bytes:
        if self.sock is None:
            return b""
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return b""
        if not data:
            return b""
        return self._handle_telnet_negotiation(data)

    def _handle_telnet_negotiation(self, data: bytes) -> bytes:
        if self.sock is None:
            return data
        out = bytearray()
        i = 0
        ln = len(data)
        while i < ln:
            b = data[i]
            if b != _IAC:
                out.append(b)
                i += 1
                continue

            if i + 1 >= ln:
                break
            cmd = data[i + 1]
            if cmd in (_DO, _DONT, _WILL, _WONT):
                if i + 2 >= ln:
                    break
                opt = data[i + 2]
                if cmd in (_DO, _DONT):
                    self.sock.sendall(bytes([_IAC, _WONT, opt]))
                else:
                    self.sock.sendall(bytes([_IAC, _DONT, opt]))
                i += 3
                continue
            if cmd == _SB:
                end = data.find(bytes([_IAC, _SE]), i + 2)
                if end == -1:
                    break
                i = end + 2
                continue
            i += 2
        return bytes(out)


def _extract_first(pattern: str, text: str) -> str:
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def _extract_int(pattern: str, text: str) -> int | None:
    value = _extract_first(pattern, text)
    return int(value) if value.isdigit() else None


def parse_show_system(text: str) -> dict[str, Any]:
    software = _extract_first(r'Software Version:"([^"]+)"', text)
    brand = _extract_first(r'Brand:"([^"]+)"', text)
    product = _extract_first(r'Product Name:"([^"]+)"', text)
    hardware = _extract_first(r'Hardware Version:"([^"]+)"', text)
    compiled = _extract_first(r"Compiled\s*:\s*(.+)", text)
    cpu_usage = _extract_first(r"The cpu usage is:\s*([0-9.]+%)", text)
    memory_usage = _extract_first(r"The memory usage is:\s*([0-9.]+%)", text)
    total_bytes = _extract_first(r"Total\s+bytes:\s*([0-9]+)", text)
    available_bytes = _extract_first(r"Availably bytes:\s*([0-9]+)", text)
    system_time = _extract_first(r"The system time is:\s*([0-9:\-\s]+)", text)
    uptime = _extract_first(r"The system running time is:\s*(.+)", text)
    cpu_temp = _extract_first(r"The CPU temperature is:\s*([0-9]+\s+degrees)", text)
    return {
        "software_version": software,
        "brand": brand,
        "product_name": product,
        "hardware_version": hardware,
        "compiled": compiled,
        "cpu_usage": cpu_usage,
        "memory_usage": memory_usage,
        "memory_total_bytes": int(total_bytes) if total_bytes.isdigit() else None,
        "memory_available_bytes": int(available_bytes) if available_bytes.isdigit() else None,
        "system_time": system_time,
        "uptime": uptime,
        "cpu_temperature": cpu_temp,
    }


def parse_show_vlan(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith(("VLAN ID", "=======", "(S)-Static", "(D)-Dynamic")):
            continue

        if re.match(r"^\d+\s+", line):
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < 2:
                continue
            vlan_id = int(parts[0])
            name = parts[1].replace("(S)", "").replace("(D)", "").strip()
            state = parts[2] if len(parts) > 2 else ""
            instance = parts[3] if len(parts) > 3 else ""
            l3_if = parts[4] if len(parts) > 4 else ""
            port_blob = parts[5] if len(parts) > 5 else ""
            current = {
                "vlan_id": vlan_id,
                "name": name,
                "state": state,
                "instance": instance,
                "l3_interface": l3_if,
                "member_ports": [],
            }
            current["member_ports"].extend(_parse_vlan_ports(port_blob))
            rows.append(current)
            continue

        if current is not None:
            current["member_ports"].extend(_parse_vlan_ports(line.strip()))

    return rows


def _parse_vlan_ports(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for token in re.findall(r"([a-z]+\d+\([ut]\))", text, flags=re.IGNORECASE):
        port, mode = token[:-3], token[-2]
        out.append({"port": port, "tag_mode": "tagged" if mode == "t" else "untagged"})
    return out


def parse_show_interface(text: str) -> list[dict[str, Any]]:
    blocks = re.split(r"(?=^Interface\s+)", text, flags=re.MULTILINE)
    items: list[dict[str, Any]] = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("Interface "):
            continue
        lines = block.splitlines()
        name = lines[0].split(None, 1)[1].strip()
        hardware = _extract_first(r"Hardware is ([^,]+)", block)
        mac = _extract_first(r"address is ([0-9a-f.]+)", block)
        flags = _extract_first(r"<([^>]+)>", block)
        bandwidth = _extract_first(r"Bandwidth\s+([0-9A-Za-z]+)", block)
        inet = _extract_first(r"inet\s+([0-9./]+)", block)
        input_m = re.search(
            r"input packets\s+([0-9]+), bytes\s+([0-9]+), dropped\s+([0-9]+), multicast packets\s+([0-9]+)",
            block,
            flags=re.IGNORECASE,
        )
        output_m = re.search(
            r"output packets\s+([0-9]+), bytes\s+([0-9]+), multicast packets\s+([0-9]+), broadcast packets\s+([0-9]+)",
            block,
            flags=re.IGNORECASE,
        )
        items.append(
            {
                "name": name,
                "hardware": hardware,
                "mac": mac,
                "flags": [f.strip() for f in flags.split(",") if f.strip()],
                "bandwidth": bandwidth,
                "ip_cidr": inet,
                "input_packets": int(input_m.group(1)) if input_m else None,
                "input_bytes": int(input_m.group(2)) if input_m else None,
                "input_dropped": int(input_m.group(3)) if input_m else None,
                "input_multicast_packets": int(input_m.group(4)) if input_m else None,
                "output_packets": int(output_m.group(1)) if output_m else None,
                "output_bytes": int(output_m.group(2)) if output_m else None,
                "output_multicast_packets": int(output_m.group(3)) if output_m else None,
                "output_broadcast_packets": int(output_m.group(4)) if output_m else None,
            }
        )
    return items


def parse_show_mac_address_table(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("VLAN", "----")):
            continue
        m = re.match(r"^(\d+)\s+([0-9a-f.]+)\s+(\S+)\s+(\S+)$", line, flags=re.IGNORECASE)
        if not m:
            continue
        rows.append(
            {
                "vlan_id": int(m.group(1)),
                "mac": m.group(2).lower(),
                "entry_type": m.group(3).lower(),
                "port": m.group(4),
            }
        )
    return rows


def sanitize_running_config(text: str) -> str:
    sanitized: list[str] = []
    for line in text.splitlines():
        if re.search(r"^username\s+\S+\s+password\s+", line, flags=re.IGNORECASE):
            sanitized.append(re.sub(r"(password)\s+.+$", r"\1 <redacted>", line, flags=re.IGNORECASE))
        else:
            sanitized.append(line)
    return "\n".join(sanitized).strip()


def collect_switch_snapshot(
    host: str,
    username: str,
    password: str,
    include_config: bool = False,
    port: int = 23,
    timeout: float = 10.0,
) -> dict[str, Any]:
    with IntelbrasSwitchTelnetClient(host=host, username=username, password=password, port=port, timeout=timeout) as client:
        client.enable()
        system_raw = client.run_command("show system", timeout=max(timeout, 12.0))
        vlan_raw = client.run_command("show vlan", timeout=max(timeout, 12.0))
        interface_raw = client.run_command("show interface", timeout=max(timeout, 18.0))
        mac_raw = client.run_command("show mac-address-table", timeout=max(timeout, 18.0))
        lldp_raw = client.run_command("show lldp", timeout=max(timeout, 8.0))
        config_raw = ""
        if include_config:
            config_raw = client.run_command("show running-config", timeout=max(timeout, 20.0))

    system = parse_show_system(system_raw)
    vlans = parse_show_vlan(vlan_raw)
    interfaces = parse_show_interface(interface_raw)
    mac_table = parse_show_mac_address_table(mac_raw)

    data: dict[str, Any] = {
        "system": system,
        "vlans": vlans,
        "interfaces": interfaces,
        "mac_table": mac_table,
        "lldp": {
            "status": _extract_first(r"Status:\s*(\w+)", lldp_raw),
            "transmit_interval_seconds": _extract_int(r"Transmit interval in seconds:\s*(\d+)", lldp_raw),
            "holdtime_seconds": _extract_int(r"Holdtime in seconds:\s*(\d+)", lldp_raw),
            "reinit_time_seconds": _extract_int(r"Reinit-time in seconds:\s*(\d+)", lldp_raw),
        },
        "summary": {
            "interfaces_total": len(interfaces),
            "interfaces_up": sum(1 for row in interfaces if "RUNNING" in (row.get("flags") or [])),
            "vlans_total": len(vlans),
            "mac_entries_total": len(mac_table),
        },
    }
    if include_config:
        data["running_config"] = sanitize_running_config(config_raw)
    return data
