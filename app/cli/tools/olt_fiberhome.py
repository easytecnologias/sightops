from __future__ import annotations

import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


IAC, DO, DONT, WILL, WONT, SB, SE = 255, 253, 254, 251, 252, 250, 240
GPON_BOARD_RE = re.compile(r"^\s*(\d+)\s+up\s+connected\s+(G\w+)", re.MULTILINE | re.IGNORECASE)


def _clean_output(value: str) -> str:
    value = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", value)
    value = value.replace("\x00", "").replace("\r", "")
    return value


def normalize_mac(value: str) -> str:
    raw = re.sub(r"[^0-9a-f]", "", str(value or "").lower())
    return ":".join(raw[index:index + 2] for index in range(0, 12, 2)) if len(raw) == 12 else raw


class FiberHomeTelnet:
    """Cliente somente de transporte para a CLI FiberHome AN5xxx/AN6xxx."""

    # A AN5516 permite somente uma sessao no modo administrativo. Serializar
    # as operacoes evita que monitoramento e a tela de implantacao se bloqueiem.
    _admin_lock = threading.Lock()

    def __init__(self, host: str, username: str, password: str, port: int = 23, timeout: float = 12.0):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._lock_acquired = False

    def __enter__(self) -> "FiberHomeTelnet":
        if not self._admin_lock.acquire(timeout=max(30.0, self.timeout * 4)):
            raise TimeoutError(
                "A OLT FiberHome esta ocupada com outra operacao do SightOps. "
                "Aguarde a operacao atual terminar e tente novamente."
            )
        self._lock_acquired = True
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.sock.settimeout(0.25)
            self._login()
            return self
        except Exception:
            # Se o enable falhar, nao deixe uma sessao VIEW abandonada na OLT.
            try:
                self.send("quit")
                self._read_quiet(maximum=1.5)
            except OSError:
                pass
            self._close_socket()
            self._release_lock()
            raise

    def __exit__(self, *_: Any) -> None:
        try:
            # Na AN5516, `quit` executado diretamente em Admin# pode deixar o
            # lock de configuracao preso. Desca primeiro para User> e so entao
            # encerre a sessao Telnet.
            self.send("exit")
            self._read_until(("User>", "Login:"), maximum=2.5)
            self.send("quit")
            self._read_quiet(maximum=2.0)
        except OSError:
            pass
        finally:
            self._close_socket()
            self._release_lock()

    def _close_socket(self) -> None:
        if self.sock is None:
            return
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.sock = None

    def _release_lock(self) -> None:
        if self._lock_acquired:
            self._lock_acquired = False
            self._admin_lock.release()

    def send(self, value: str) -> None:
        if self.sock is None:
            raise ConnectionError("Sessao FiberHome nao conectada.")
        self.sock.sendall(value.encode("ascii", errors="ignore") + b"\r\n")

    def _decode_telnet(self, data: bytes) -> bytes:
        clean = bytearray()
        index = 0
        while index < len(data):
            if data[index] != IAC:
                clean.append(data[index])
                index += 1
                continue
            if index + 1 >= len(data):
                break
            command = data[index + 1]
            if command in (DO, DONT, WILL, WONT) and index + 2 < len(data):
                option = data[index + 2]
                answer = WONT if command in (DO, DONT) else DONT
                self.sock.sendall(bytes((IAC, answer, option)))
                index += 3
            elif command == SB:
                end = data.find(bytes((IAC, SE)), index + 2)
                index = len(data) if end < 0 else end + 2
            else:
                index += 2
        return bytes(clean)

    def _read_quiet(self, quiet: float = 0.45, maximum: float | None = None) -> str:
        if self.sock is None:
            raise ConnectionError("Sessao FiberHome nao conectada.")
        chunks: list[bytes] = []
        started = time.monotonic()
        last = started
        maximum = maximum or self.timeout
        while time.monotonic() - started < maximum:
            try:
                chunk = self.sock.recv(65535)
            except socket.timeout:
                if chunks and time.monotonic() - last >= quiet:
                    break
                continue
            if not chunk:
                break
            chunks.append(self._decode_telnet(chunk))
            last = time.monotonic()
        return _clean_output(b"".join(chunks).decode("latin-1", errors="replace"))

    def _read_until(self, markers: tuple[str, ...], maximum: float | None = None) -> str:
        """Le ate um prompt conhecido, tolerando respostas FiberHome em pacotes separados."""
        output = ""
        started = time.monotonic()
        maximum = maximum or self.timeout
        while time.monotonic() - started < maximum:
            remaining = maximum - (time.monotonic() - started)
            output += self._read_quiet(quiet=0.2, maximum=min(0.8, max(0.1, remaining)))
            if any(marker in output for marker in markers):
                break
        return output

    def _login(self) -> None:
        banner = self._read_until(("Login:",), maximum=self.timeout)
        if "Login:" not in banner:
            raise ConnectionError("A OLT FiberHome nao apresentou o prompt de login.")
        self.send(self.username)
        password_prompt = self._read_until(("Password:", "Login:"), maximum=4.0)
        if "Password:" not in password_prompt:
            raise PermissionError("A OLT FiberHome nao aceitou o usuario informado.")
        self.send(self.password)
        output = self._read_until(("User>", "Login:", "Password:"), maximum=self.timeout)
        if "User>" not in output:
            raise PermissionError("Falha de autenticacao na OLT FiberHome.")
        administrative = ""
        for _attempt in range(2):
            self.send("enable")
            challenge = self._read_until(
                ("Admin#", "Password:", "Login:"),
                maximum=self.timeout,
            )
            administrative += challenge
            if "Password:" in challenge:
                self.send(self.password)
                administrative += self._read_until(
                    ("Admin#", "Login:"),
                    maximum=self.timeout,
                )
            if "Admin#" in administrative:
                break
            # Alguns firmwares voltam silenciosamente ao User> quando o prompt
            # do enable demora. Uma segunda tentativa evita falha intermitente.
            self._read_quiet(quiet=0.3, maximum=1.0)
        if "configuration is locked by other user" in administrative.lower():
            raise PermissionError(
                "A OLT FiberHome esta com o modo administrativo bloqueado por outra sessao. "
                "Feche o Telnet/ANM2000 que estiver conectado ou aguarde o timeout da OLT."
            )
        if "Admin#" not in administrative:
            raise PermissionError("Login aceito, mas nao foi possivel abrir o modo administrativo FiberHome.")

    def command(self, command: str, prompt: str = "Admin\\", maximum: float | None = None) -> str:
        self.send(command)
        output = ""
        started = time.monotonic()
        maximum = maximum or self.timeout
        while time.monotonic() - started < maximum:
            part = self._read_quiet(maximum=min(2.0, maximum))
            output += part
            tail = part[-600:]
            if "--Press any key" in tail:
                self.sock.sendall(b" ")
                continue
            tail_clean = output.rstrip()
            if tail_clean.endswith(prompt) or tail_clean.endswith("Admin#"):
                break
        if "% Unknown command." in output:
            raise RuntimeError(f"Comando FiberHome nao suportado: {command}")
        return _clean_output(output)

    def cd(self, directory: str) -> None:
        output = self.command(f"cd {directory}", prompt=f"Admin\\{directory}#")
        if "% Unknown command." in output:
            raise RuntimeError(f"Nao foi possivel acessar o modulo FiberHome {directory}.")


@dataclass(frozen=True)
class FiberHomeLayout:
    slots: tuple[int, ...]
    pons_per_slot: int = 8


def parse_layout(output: str) -> FiberHomeLayout:
    slots = tuple(sorted({int(match.group(1)) for match in GPON_BOARD_RE.finditer(output)}))
    if not slots:
        raise RuntimeError("Nenhuma placa GPON FiberHome foi encontrada.")
    return FiberHomeLayout(slots=slots)


def parse_online(output: str, slot: int, pon: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r"(?:^|\s)(\d+)\s+(\S+)\s+([A-Z0-9]{4}[0-9a-f]{8})\b", re.MULTILINE | re.IGNORECASE)
    for match in pattern.finditer(output):
        rows.append({
            "slot": slot,
            "pon": pon,
            "onu_id": int(match.group(1)),
            "onu_model": match.group(2),
            "onu_serial": match.group(3).upper(),
            "onu_name": f"gpon {pon} onu {int(match.group(1))}",
            "oper_status": "Active",
            "omci_status": "",
        })
    return rows


def parse_authorization(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\s)(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+([APR])\s+([A-Z0-9]{4}[0-9a-f]{8})\b",
        re.MULTILINE | re.IGNORECASE,
    )
    for match in pattern.finditer(output):
        rows.append({
            "slot": int(match.group(1)),
            "pon": int(match.group(2)),
            "onu_id": int(match.group(3)),
            "onu_model": match.group(4),
            "authorization": match.group(5).upper(),
            # onu_serial fica em upper por compatibilidade (comparacao,
            # exibicao, chave de historico -- ja usado assim em todo o
            # sistema). onu_serial_raw preserva a caixa EXATA que a OLT
            # devolveu -- o proprio padrao do regex ja captura isso certo
            # ([A-Z0-9]{4}[0-9a-f]{8}: prefixo do fabricante + 8 digitos hex
            # em minusculo). A whitelist da FiberHome e case-sensitive: um
            # comando `set whitelist ... action delete` com o serial em upper
            # quando a whitelist tem em lower falha com "sn is wrong!" --
            # confirmado com hardware real (PON1/ONU31, HWTCfa9e92ae).
            "onu_serial": match.group(6).upper(),
            "onu_serial_raw": match.group(6),
            "onu_name": f"gpon {int(match.group(2))} onu {int(match.group(3))}",
        })
    return rows


def parse_states(output: str) -> dict[int, str]:
    return {
        int(match.group(1)): match.group(2).capitalize()
        for match in re.finditer(r"\bonu\s+(\d+)\s+is\s+(active|inactive)\.", output, re.IGNORECASE)
    }


def parse_versions(output: str) -> dict[int, str]:
    versions: dict[int, str] = {}
    for line in output.splitlines():
        match = re.search(r"(?:^|\s)(\d+)\s+(\S+)\s+(\S+)\s+", line)
        if match and match.group(2).upper() not in {"CONFIG_TYPE", "ONU_TYPE"}:
            versions[int(match.group(1))] = match.group(3)
    return versions


def parse_signal(output: str) -> dict[str, str]:
    def value(label: str) -> str:
        match = re.search(rf"^{label}\s*:\s*(-?\d+(?:\.\d+)?)", output, re.MULTILINE | re.IGNORECASE)
        return match.group(1) if match else ""

    return {
        "onu_rx": value(r"RECV POWER"),
        "olt_rx": value(r"OLT RECV POWER"),
        "onu_tx": value(r"SEND POWER"),
    }


def parse_distance(output: str) -> str:
    match = re.search(r"ONU RTT VALUE\s*=\s*(\d+(?:\.\d+)?)\s*\(m\)", output, re.IGNORECASE)
    return f"{float(match.group(1)) / 1000:.3f}" if match else ""


def parse_last_on_off(output: str) -> dict[str, str]:
    """Extrai o historico nativo da ONU sem transformar data ausente em data real."""
    result = {"last_off_at": "", "last_on_at": ""}
    for field, label in (("last_off_at", "Off"), ("last_on_at", "On")):
        match = re.search(
            rf"Last\s+{label}\s+Time\s*=\s*(\d{{4}}-\d{{2}}-\d{{2}}\s+\d{{2}}:\d{{2}}:\d{{2}})",
            output or "",
            re.IGNORECASE,
        )
        value = match.group(1) if match else ""
        result[field] = "" if not value or value.startswith("0000-00-00") else value
    return result


def parse_macs(output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for match in re.finditer(
        r"(?:^|\n)\s*\d+\s+([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s+Vid:(\d+)",
        output,
        re.IGNORECASE,
    ):
        mac = normalize_mac(match.group(1))
        # Algumas ONTs FiberHome anunciam este endereco reservado como se
        # fosse um equipamento. Ele nao representa um CPE real.
        if mac in {"00:00:00:00:00:00", "00:00:00:00:00:01"}:
            continue
        raw_vlan = match.group(2)
        rows.append({
            "cpe_mac": mac,
            "vlan": "" if raw_vlan == "65535" else raw_vlan,
            "vlan_mode": "untagged" if raw_vlan == "65535" else "tagged",
        })
    return rows


def parse_fdb(output: str) -> dict[str, str]:
    """Retorna a VLAN real aprendida pela placa para cada MAC.

    A tabela ``gpononu/mac_list`` identifica a ONU, mas em modo transparente
    costuma informar ``Vid:65535``. A FDB da placa contém a VLAN de serviço
    após o encaminhamento interno da OLT.
    """
    rows: dict[str, str] = {}
    for match in re.finditer(
        r"\bMac:\s*([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s+Vid:\s*(\d+)",
        output,
        re.IGNORECASE,
    ):
        mac = normalize_mac(match.group(1))
        vlan = match.group(2)
        if mac not in {"00:00:00:00:00:00", "00:00:00:00:00:01"}:
            rows[mac] = vlan
    return rows


def parse_pon_macs(output: str) -> list[dict[str, Any]]:
    """Le a tabela da placa GPON, que relaciona MAC, VLAN e ONU."""
    rows: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?:^|\n)\s*\d+\s+"
        r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})\s+"
        r"Vid:\s*(\d+)\s+OnuId:\s*(\d+)",
        output,
        re.IGNORECASE,
    ):
        mac = normalize_mac(match.group(1))
        onu_id = int(match.group(3))
        if (
            mac in {"00:00:00:00:00:00", "00:00:00:00:00:01"}
            or onu_id <= 0
            or onu_id == 65535
        ):
            continue
        rows.append({
            "cpe_mac": mac,
            "vlan": match.group(2),
            "onu_id": onu_id,
            "vlan_mode": "mapped",
            "vlan_source": "pon_mac",
        })
    return rows


def _enrich_macs_from_fdb(
    macs: list[dict[str, str]],
    fdb_by_mac: dict[str, str],
) -> list[dict[str, str]]:
    for mac in macs:
        learned_vlan = fdb_by_mac.get(normalize_mac(mac.get("cpe_mac", "")), "")
        if not mac.get("vlan") and learned_vlan:
            mac["vlan"] = learned_vlan
            mac["vlan_mode"] = "mapped"
            mac["vlan_source"] = "fdb"
        elif mac.get("vlan"):
            mac["vlan_source"] = "onu_port"
    return macs


def _merge_pon_and_local_macs(
    pon_macs: list[dict[str, Any]],
    local_macs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Prioriza a tabela PON e preserva MACs locais que ainda nao subiram à FDB."""
    merged: dict[str, dict[str, Any]] = {
        normalize_mac(row.get("cpe_mac", "")): dict(row)
        for row in pon_macs
        if normalize_mac(row.get("cpe_mac", ""))
    }
    for row in local_macs:
        mac = normalize_mac(row.get("cpe_mac", ""))
        if not mac:
            continue
        current = merged.get(mac)
        if current:
            if not current.get("vlan") and row.get("vlan"):
                current["vlan"] = row["vlan"]
            continue
        merged[mac] = dict(row)
    return list(merged.values())


def parse_global_vlan_services(output: str) -> dict[int, dict[str, str]]:
    """Le os servicos globais criados em ``vlan/show service vlan``."""
    services: dict[int, dict[str, str]] = {}
    for block in re.split(r"\*{10,}", output):
        name = re.search(r"service name\s*:\s*(.+)", block, re.IGNORECASE)
        begin = re.search(r"begin vid\s*:\s*(\d+)", block, re.IGNORECASE)
        end = re.search(r"end vid\s*:\s*(\d+)", block, re.IGNORECASE)
        service_type = re.search(r"service type\s*:\s*(\S+)", block, re.IGNORECASE)
        if not (name and begin):
            continue
        first = int(begin.group(1))
        last = int(end.group(1)) if end else first
        for vlan in range(first, last + 1):
            services[vlan] = {
                "name": name.group(1).strip(),
                "type": service_type.group(1).strip().lower() if service_type else "data",
            }
    return services


def parse_discovery(output: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    current_pon = 0
    for line in output.splitlines():
        header = re.search(r"SLOT=(\d+)\s+PON=(\d+)\s+,ITEM=(\d+)", line, re.IGNORECASE)
        if header:
            current_pon = int(header.group(2))
            result.setdefault(str(current_pon), {"discovered": [], "free_slots": []})
            continue
        match = re.match(r"^\s*(\d+)\s+(\S+)\s+([A-Z0-9]{4}[0-9a-f]{8})\b", line, re.IGNORECASE)
        if match and current_pon:
            result[str(current_pon)]["discovered"].append({
                "serno_id": int(match.group(1)),
                "pon": current_pon,
                "model": match.group(2),
                "serial": match.group(3).upper(),
                # A whitelist da FiberHome e case-sensitive na autorizacao (mesmo
                # motivo do onu_serial_raw em parse_authorization): "serial" fica
                # uppercase pra exibicao/comparacao, mas o comando "set whitelist
                # ... action add" precisa da caixa exata que a OLT descobriu no ar.
                "serial_raw": match.group(3),
                "vendor": match.group(3)[:4].upper(),
            })
    return result


def fiberhome_onu_type(model: str) -> str:
    value = str(model or "").strip().upper().split()[-1]
    return value[2:] if value.startswith("AN") else value


def _command_failed(output: str) -> bool:
    lowered = output.lower()
    return any(value in lowered for value in ("failed", "error!", "% unknown", "[ err "))


def _layout(client: FiberHomeTelnet) -> FiberHomeLayout:
    client.cd("device")
    return parse_layout(client.command("show slot", prompt="Admin\\device#", maximum=20.0))


def discover_unauthorized_fiberhome(
    olt_ip: str, user: str, password: str, pon: str = "all", timeout: float = 12.0
) -> dict[str, Any]:
    with FiberHomeTelnet(olt_ip, user, password, timeout=timeout) as client:
        layout = _layout(client)
        client.cd("gpononu")
        output = client.command("show unauth_discovery", prompt="Admin\\gpononu#", maximum=25.0)
        pons = parse_discovery(output)
        wanted = str(pon or "all").strip().lower()
        if wanted != "all":
            pons = {wanted: pons.get(wanted, {"discovered": [], "free_slots": []})}
        return {"ok": True, "driver": "fiberhome", "slots": list(layout.slots), "pons": pons}


def collect_fiberhome(
    olt_ip: str,
    user: str,
    password: str,
    pon: str = "all",
    olt_name: str = "OLT-FiberHome",
    timeout: float = 12.0,
    include_macs: bool = True,
    include_signal: bool = True,
) -> list[dict[str, Any]]:
    with FiberHomeTelnet(olt_ip, user, password, timeout=timeout) as client:
        layout = _layout(client)
        pon_macs: dict[tuple[int, int], list[dict[str, Any]]] = {}
        if include_macs:
            client.cd("gponlinecard")
            for slot in layout.slots:
                for pon_id in range(1, layout.pons_per_slot + 1):
                    pon_macs[(slot, pon_id)] = parse_pon_macs(client.command(
                        f"show pon_mac slot {slot} link {pon_id}",
                        prompt="Admin\\gponline#",
                        maximum=45.0,
                    ))
        client.cd("gpononu")
        wanted = str(pon or "all").strip().lower()
        pon_ids = range(1, layout.pons_per_slot + 1) if wanted == "all" else (int(wanted),)
        rows: list[dict[str, Any]] = []
        for slot in layout.slots:
            for pon_id in pon_ids:
                authorized = parse_authorization(
                    client.command(
                        f"show authorization slot {slot} link {pon_id}",
                        prompt="Admin\\gpononu#",
                        maximum=20.0,
                    )
                )
                if not authorized:
                    continue
                online_ids = {
                    int(item["onu_id"])
                    for item in parse_online(
                        client.command(
                            f"show online slot {slot} link {pon_id}",
                            prompt="Admin\\gpononu#",
                            maximum=20.0,
                        ),
                        slot,
                        pon_id,
                    )
                }
                versions = parse_versions(
                    client.command(f"show onu_ver slot {slot} link {pon_id}", prompt="Admin\\gpononu#", maximum=20.0)
                )
                for onu in authorized:
                    onu_id = int(onu["onu_id"])
                    onu["onu_model"] = versions.get(onu_id) or onu["onu_model"]
                    onu["oper_status"] = "Active" if onu_id in online_ids else "Inactive"
                    onu["omci_status"] = "OK" if onu["oper_status"] == "Active" else ""
                    signal = {"onu_rx": "", "olt_rx": "", "onu_tx": ""}
                    distance = ""
                    if onu["oper_status"] == "Active" and include_signal:
                        signal = parse_signal(client.command(
                            f"show optic_module slot {slot} link {pon_id} onu {onu_id}",
                            prompt="Admin\\gpononu#",
                        ))
                        distance = parse_distance(client.command(
                            f"show rtt_value slot {slot} link {pon_id} onu {onu_id}",
                            prompt="Admin\\gpononu#",
                        ))
                    onu.update(signal)
                    onu["distance_km"] = distance
                    macs: list[dict[str, str]] = []
                    if include_macs and onu["oper_status"] == "Active":
                        port_count = 4 if "-04-" in str(onu["onu_model"]) else 1
                        for port in range(1, port_count + 1):
                            macs.extend(parse_macs(client.command(
                                f"show mac_list slot {slot} link {pon_id} onu {onu_id} port {port}",
                                prompt="Admin\\gpononu#",
                            )))
                        mapped = [
                            row for row in pon_macs.get((slot, pon_id), [])
                            if int(row.get("onu_id") or 0) == onu_id
                        ]
                        macs = _merge_pon_and_local_macs(mapped, macs)
                    base = {
                        **onu,
                        "olt_name": olt_name,
                        "olt_slot": slot,
                        "rx_olt": signal["olt_rx"],
                        "rx_onu": signal["onu_rx"],
                    }
                    if macs:
                        for mac in macs:
                            rows.append({**base, **mac})
                    else:
                        rows.append({
                            **base,
                            "cpe_mac": "",
                            "vlan": "",
                            "vlan_mode": "",
                            "device_state": "not_learned",
                        })
        return rows


def audit_offline_fiberhome(
    olt_ip: str,
    user: str,
    password: str,
    pon: str = "all",
    olt_name: str = "OLT-FiberHome",
    site: str = "",
    minimum_days: int = 30,
    timeout: float = 12.0,
) -> dict[str, Any]:
    """Lista ONUs inativas e consulta a data nativa da ultima queda.

    A AN5516 pode devolver ``0000-00-00`` quando nunca registrou o evento.
    Essas linhas ficam explicitamente sem idade e nunca sao apresentadas como
    candidatas automaticas a exclusao.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    threshold = max(0, int(minimum_days or 0))
    rows: list[dict[str, Any]] = []
    with FiberHomeTelnet(olt_ip, user, password, timeout=timeout) as client:
        layout = _layout(client)
        client.cd("gpononu")
        wanted = str(pon or "all").strip().lower()
        pon_ids = range(1, layout.pons_per_slot + 1) if wanted == "all" else (int(wanted),)
        for slot in layout.slots:
            for pon_id in pon_ids:
                authorized = parse_authorization(client.command(
                    f"show authorization slot {slot} link {pon_id}",
                    prompt="Admin\\gpononu#",
                    maximum=20.0,
                ))
                if not authorized:
                    continue
                online_ids = {
                    int(item["onu_id"])
                    for item in parse_online(
                        client.command(
                            f"show online slot {slot} link {pon_id}",
                            prompt="Admin\\gpononu#",
                            maximum=20.0,
                        ),
                        slot,
                        pon_id,
                    )
                }
                versions = parse_versions(client.command(
                    f"show onu_ver slot {slot} link {pon_id}",
                    prompt="Admin\\gpononu#",
                    maximum=20.0,
                ))
                for onu in authorized:
                    onu_id = int(onu["onu_id"])
                    if onu_id in online_ids:
                        continue
                    history = parse_last_on_off(client.command(
                        f"show onu_last_on_and_off_time slot {slot} link {pon_id} onu {onu_id}",
                        prompt="Admin\\gpononu#",
                        maximum=20.0,
                    ))
                    last_off = history["last_off_at"]
                    offline_days: int | None = None
                    clock_warning = False
                    if last_off:
                        try:
                            parsed = datetime.strptime(last_off, "%Y-%m-%d %H:%M:%S")
                            offline_days = max(0, int((now - parsed).total_seconds() // 86400))
                            clock_warning = parsed.year < 2020 or parsed > now
                        except ValueError:
                            last_off = ""
                    rows.append({
                        "olt_name": olt_name,
                        "olt_ip": olt_ip,
                        "site": site,
                        "slot": slot,
                        "pon": pon_id,
                        "onu_id": onu_id,
                        "onu_name": f"gpon {pon_id} onu {onu_id}",
                        "onu_serial": onu.get("onu_serial") or "",
                        "onu_model": versions.get(onu_id) or onu.get("onu_model") or "",
                        "oper_status": "Inactive",
                        "last_off_at": last_off,
                        "last_on_at": history["last_on_at"],
                        "offline_days": offline_days,
                        "history_available": offline_days is not None,
                        "clock_warning": clock_warning,
                        "meets_threshold": (
                            offline_days is not None
                            and offline_days >= threshold
                            and not clock_warning
                        ),
                    })
    rows.sort(key=lambda row: (
        row["offline_days"] is None,
        -(row["offline_days"] or 0),
        row["pon"],
        row["onu_id"],
    ))
    return {
        "ok": True,
        "olt_name": olt_name,
        "site": site,
        "minimum_days": threshold,
        "offline_total": len(rows),
        "review_total": sum(1 for row in rows if row["meets_threshold"]),
        "without_history_total": sum(1 for row in rows if not row["history_available"]),
        "clock_warning_total": sum(1 for row in rows if row["clock_warning"]),
        "rows": rows,
    }


def onu_signal_fiberhome(
    olt_ip: str,
    user: str,
    password: str,
    pon: int,
    onu: int,
    timeout: float = 12.0,
) -> dict[str, Any]:
    with FiberHomeTelnet(olt_ip, user, password, timeout=timeout) as client:
        layout = _layout(client)
        client.cd("gponlinecard")
        pon_macs_by_slot = {
            slot: parse_pon_macs(client.command(
                f"show pon_mac slot {slot} link {pon}",
                prompt="Admin\\gponline#",
                maximum=45.0,
            ))
            for slot in layout.slots
        }
        client.cd("gpononu")
        for slot in layout.slots:
            online = parse_online(
                client.command(f"show online slot {slot} link {pon}", prompt="Admin\\gpononu#"),
                slot,
                pon,
            )
            found = next((item for item in online if int(item["onu_id"]) == int(onu)), None)
            if not found:
                continue
            signal = parse_signal(client.command(
                f"show optic_module slot {slot} link {pon} onu {onu}", prompt="Admin\\gpononu#"
            ))
            macs: list[dict[str, str]] = []
            port_count = 4 if "-04-" in str(found["onu_model"]) else 1
            for port in range(1, port_count + 1):
                macs.extend(parse_macs(client.command(
                    f"show mac_list slot {slot} link {pon} onu {onu} port {port}",
                    prompt="Admin\\gpononu#",
                )))
            mapped = [
                row for row in pon_macs_by_slot.get(slot, [])
                if int(row.get("onu_id") or 0) == int(onu)
            ]
            macs = _merge_pon_and_local_macs(mapped, macs)
            return {
                "ok": True,
                "driver": "fiberhome",
                "slot": slot,
                "pon": int(pon),
                "onu": int(onu),
                "serial": found["onu_serial"],
                "model": found["onu_model"],
                "oper_status": found["oper_status"],
                "omci_status": "",
                # Campos canonicos usados pela API/tela. Manter os aliases
                # antigos porque o coletor em lote ainda trabalha com eles.
                "onu_rx": signal["onu_rx"],
                "olt_rx": signal["olt_rx"],
                "rx_onu": signal["onu_rx"],
                "rx_olt": signal["olt_rx"],
                "distance_km": parse_distance(client.command(
                    f"show rtt_value slot {slot} link {pon} onu {onu}", prompt="Admin\\gpononu#"
                )),
                "macs": [
                    {
                        **mac,
                        "mac": mac.get("mac") or mac.get("cpe_mac", ""),
                        "cpe_mac": mac.get("cpe_mac") or mac.get("mac", ""),
                    }
                    for mac in macs
                ],
            }
    return {"ok": False, "error": "ONU nao encontrada na OLT FiberHome."}


def add_onu_fiberhome(
    olt_ip: str,
    user: str,
    password: str,
    pon: int,
    serial: str,
    onu_model: str,
    services: list[dict[str, Any]] | None = None,
    terminal: str = "onu",
    tag_mode: str = "tagged",
    serial_raw: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    serial = str(serial or "").strip()
    # A whitelist da FiberHome e case-sensitive na autorizacao (mesmo motivo do
    # onu_serial_raw em delete_onu_fiberhome): usar a caixa exata que a OLT
    # descobriu (`serial_raw`, vindo de parse_discovery) evita o "[ERR -598]
    # physical address is error!" que a versao uppercased pode disparar.
    whitelist_serial = str(serial_raw or "").strip() or serial
    onu_type = fiberhome_onu_type(onu_model)
    if not serial or not onu_type:
        raise ValueError("A autorizacao FiberHome exige serial e modelo da ONU descoberta.")
    with FiberHomeTelnet(olt_ip, user, password, timeout=timeout) as client:
        layout = _layout(client)
        requested_services = [item for item in (services or []) if int(item.get("vlan") or 0) > 0]
        client.cd("vlan")
        global_services = parse_global_vlan_services(
            client.command("show service vlan", prompt="Admin\\vlan#", maximum=90)
        )
        missing_vlans = sorted({
            int(item["vlan"]) for item in requested_services
            if int(item["vlan"]) not in global_services
        })
        if missing_vlans:
            missing = ", ".join(str(value) for value in missing_vlans)
            raise RuntimeError(
                f"A(s) VLAN(s) {missing} ainda nao existem como servico global na OLT FiberHome."
            )
        applied_services = [
            {
                **item,
                "vlan": int(item["vlan"]),
                "olt_service": global_services[int(item["vlan"])]["name"],
                "olt_service_type": global_services[int(item["vlan"])]["type"],
                "provisioning": "global_transparent",
            }
            for item in requested_services
        ]
        client.cd("gpononu")
        for slot in layout.slots:
            authorized = parse_authorization(client.command(
                f"show authorization slot {slot} link {int(pon)}",
                prompt="Admin\\gpononu#",
                maximum=30,
            ))
            existing = next(
                (row for row in authorized if str(row["onu_serial"]).upper() == serial.upper()),
                None,
            )
            if existing:
                return {
                    "ok": True,
                    "driver": "fiberhome",
                    "pon": int(pon),
                    "slot": int(existing["onu_id"]),
                    "olt_slot": slot,
                    "serial": existing["onu_serial"],
                    "model": existing["onu_model"],
                    "already_authorized": True,
                    "terminal": terminal,
                    "tag_mode": tag_mode,
                    "services": applied_services,
                }
            used = {int(row["onu_id"]) for row in authorized}
            free_onu = next((value for value in range(1, 129) if value not in used), None)
            if free_onu is None:
                continue
            command = (
                f"set whitelist phy_addr address {whitelist_serial} password null action add "
                f"slot {slot} link {int(pon)} onu {free_onu} type {onu_type}"
            )
            output = client.command(command, prompt="Admin\\gpononu#", maximum=25)
            if _command_failed(output):
                raise RuntimeError(output.strip())
            time.sleep(3)
            after = parse_authorization(client.command(
                f"show authorization slot {slot} link {int(pon)}",
                prompt="Admin\\gpononu#",
                maximum=30,
            ))
            created = next(
                (
                    row for row in after
                    if int(row["onu_id"]) == free_onu
                    and str(row["onu_serial"]).upper() == serial.upper()
                ),
                None,
            )
            if not created:
                raise RuntimeError("A FiberHome aceitou o comando, mas a ONU nao apareceu na whitelist.")
            save = client.command("save", prompt="Admin\\gpononu#", maximum=45)
            if _command_failed(save):
                raise RuntimeError(f"ONU autorizada, mas o save falhou: {save.strip()}")
            return {
                "ok": True,
                "driver": "fiberhome",
                "pon": int(pon),
                "slot": free_onu,
                "olt_slot": slot,
                "serial": created["onu_serial"],
                "model": created["onu_model"],
                "commands_run": [command, "save"],
                "terminal": terminal,
                "tag_mode": tag_mode,
                "services": applied_services,
            }
    raise RuntimeError("Nao existe posicao livre para a ONU nessa PON FiberHome.")


def delete_onu_fiberhome(
    olt_ip: str,
    user: str,
    password: str,
    pon: int,
    onu: int,
    serial: str = "",
    timeout: float = 15.0,
) -> dict[str, Any]:
    with FiberHomeTelnet(olt_ip, user, password, timeout=timeout) as client:
        layout = _layout(client)
        client.cd("gpononu")
        for slot in layout.slots:
            authorized = parse_authorization(client.command(
                f"show authorization slot {slot} link {int(pon)}",
                prompt="Admin\\gpononu#",
                maximum=30,
            ))
            current = next((row for row in authorized if int(row["onu_id"]) == int(onu)), None)
            if not current:
                continue
            if serial and str(current["onu_serial"]).upper() != str(serial).strip().upper():
                raise RuntimeError("O serial informado nao pertence a PON/ONU selecionada.")
            onu_type = fiberhome_onu_type(str(current["onu_model"]))
            # A whitelist da FiberHome e case-sensitive. current["onu_serial"]
            # vem uppercased de parse_authorization (por compatibilidade com
            # o resto do sistema); onu_serial_raw preserva a caixa original
            # que a OLT devolveu, que e a que a whitelist realmente tem
            # gravada -- usar a versao em upper aqui faz a OLT recusar o
            # comando com "sn is wrong!" mesmo com o ONU certo selecionado.
            whitelist_serial = current.get("onu_serial_raw") or current["onu_serial"]
            command = (
                f"set whitelist phy_addr address {whitelist_serial} password null action delete "
                f"slot {slot} link {int(pon)} onu {int(onu)} type {onu_type}"
            )
            output = client.command(command, prompt="Admin\\gpononu#", maximum=25)
            if _command_failed(output):
                raise RuntimeError(output.strip())
            time.sleep(2)
            remaining = parse_authorization(client.command(
                f"show authorization slot {slot} link {int(pon)}",
                prompt="Admin\\gpononu#",
                maximum=30,
            ))
            if any(int(row["onu_id"]) == int(onu) for row in remaining):
                raise RuntimeError("A FiberHome nao removeu a ONU da whitelist.")
            save = client.command("save", prompt="Admin\\gpononu#", maximum=45)
            if _command_failed(save):
                raise RuntimeError(f"ONU removida, mas o save falhou: {save.strip()}")
            return {
                "ok": True,
                "driver": "fiberhome",
                "pon": int(pon),
                "onu": int(onu),
                "olt_slot": slot,
                "serial": current["onu_serial"],
                "model": current["onu_model"],
                "commands_run": [command, "save"],
            }
    return {"ok": False, "error": "ONU nao encontrada na whitelist FiberHome."}
