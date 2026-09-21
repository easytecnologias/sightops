#!/usr/bin/env python3
"""Sincroniza o WireGuard do servidor (wg-sightops) com o que cada conector
tem cadastrado em `client_lans`.

Por que existe
--------------
`ensure_wireguard_tunnel()` (app/services/connector_service.py) grava
`client_lans` no cadastro do conector, mas roda dentro do container da API --
que nao tem acesso a rede do host (sem NET_ADMIN, sem network_mode host),
entao NUNCA conseguiu aplicar isso no `wg` de verdade nem nas rotas do kernel.
`wg-quick` so le o arquivo de config e cria as rotas UMA VEZ, quando a
interface sobe -- qualquer rede cadastrada depois disso fica esquecida ate
alguem rodar `wg set`/`ip route add` na mao. Foi assim que a SIERRA ficou 4 de
5 redes sem rota (so 192.168.20.0/24, que existia desde o boot, funcionava).

Este script roda FORA do container, direto no host, com root (via systemd
timer). Ele:
  1. le o cadastro (connectors.json, no volume Docker, no host);
  2. le o estado real do `wg-sightops` (`wg show ... dump`) e das rotas do
     kernel;
  3. para cada rede cadastrada que ainda nao esta aplicada, roda `wg set`
     (nunca `wg-quick down/up` -- a interface nunca reinicia, nenhum peer cai)
     e `ip route add`;
  4. atualiza o arquivo /etc/wireguard/wg-sightops.conf para o mesmo estado
     sobreviver a um reboot.

Seguranca
---------
- Nunca REMOVE uma rede que um peer ja tem -- so soma.
- Se a mesma rede exata aparecer no cadastro de dois conectores diferentes,
  nao aplica a rede inteira em nenhum dos dois. Para CGNAT com LAN repetida
  (ex: dois clientes usando 192.168.1.0/24), aplica somente /32 dos IPs
  conhecidos no inventario daquele conector. Assim uma escola nao enxerga a
  outra por acidente.
- Se a rede ja estiver roteada por OUTRA interface (nao wg-sightops), pula e
  avisa -- nunca reatribui uma rota que ja existe por outro motivo.

Uso
---
    sudo python3 scripts/sightops_wireguard_sync.py --check   # so mostra o que faria
    sudo python3 scripts/sightops_wireguard_sync.py           # aplica

Instalado via systemd timer (ver deploy/systemd/), roda sozinho a cada 60s.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

WG_INTERFACE = "wg-sightops"
WG_CONF_PATH = Path("/etc/wireguard/wg-sightops.conf")
CONNECTORS_JSON_CANDIDATES = [
    Path("/var/lib/docker/volumes/sightops-prod-release_sightops_prod_data/_data/connectors.json"),
    Path("/var/lib/docker/volumes/sightops-v3-release_sightops_v3_data/_data/connectors.json"),
    Path("/var/lib/docker/volumes/cam-snapshot-web_sightops_data/_data/connectors.json"),
]
IPTABLES_CANDIDATES = [
    "iptables",
    "iptables-nft",
    "/usr/sbin/iptables",
    "/usr/sbin/iptables-nft",
    "/sbin/iptables",
    "/sbin/iptables-nft",
]
_IPTABLES_BIN: Optional[str] = None
_IPTABLES_MISSING_WARNED = False


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


# --- Logica pura (sem I/O), testada em sightops_wireguard_sync_test.py -------


def canon_cidr(value: str) -> Optional[str]:
    """Valida e normaliza um IP/CIDR. None se invalido."""
    text = str(value or "").strip()
    if not text:
        return None
    if "/" not in text:
        text = f"{text}/32"
    try:
        return str(ipaddress.ip_network(text, strict=False))
    except ValueError:
        return None


def compute_target_state(connectors: List[Dict]) -> Dict[str, Dict]:
    """{pubkey: {"name": str, "allowed": set[str]}} a partir do cadastro.

    So entram conectores com tunel WireGuard habilitado e chave publica --
    sem isso nao ha peer no wg-sightops pra sincronizar. Conector com
    isolamento por namespace ativo (tunnel.netns_listen_port) fica de fora
    de proposito: o dele e' um tunel dedicado dentro do proprio namespace
    (ver ops/netns_provisioner), nunca deve existir um peer duplicado dele
    na interface compartilhada -- foi exatamente isso que manteve o roteador
    de Mata Grande grudado na porta velha mesmo depois do endpoint-port ser
    corrigido: este script recriava o peer aqui a cada 60s.
    """
    out: Dict[str, Dict] = {}
    for row in connectors or []:
        tunnel = row.get("tunnel") if isinstance(row.get("tunnel"), dict) else {}
        if not tunnel.get("enabled") or str(tunnel.get("type") or "").lower() != "wireguard":
            continue
        if tunnel.get("netns_listen_port"):
            continue
        pubkey = str(tunnel.get("client_public_key") or "").strip()
        if not pubkey:
            continue
        raw_allowed = [tunnel.get("client_address")] + list(tunnel.get("client_lans") or [])
        allowed = {c for c in (canon_cidr(v) for v in raw_allowed) if c}
        if not allowed:
            continue
        out[pubkey] = {"name": str(row.get("name") or row.get("id") or pubkey[:12]), "allowed": allowed}
    return out


def _connector_pubkey(row: Dict[str, Any]) -> str:
    tunnel = row.get("tunnel") if isinstance(row.get("tunnel"), dict) else {}
    if not tunnel.get("enabled") or str(tunnel.get("type") or "").lower() != "wireguard":
        return ""
    return str(tunnel.get("client_public_key") or "").strip()


def isolated_pubkeys(connectors: List[Dict]) -> Dict[str, str]:
    """{pubkey: nome} dos conectores ja migrados para namespace isolado.

    Esses tem o proprio tunel WireGuard dedicado (porta/interface propria
    dentro do namespace, gerenciado pelo ops/netns_provisioner) -- nunca
    devem ter um peer na interface compartilhada wg-sightops.
    """
    out: Dict[str, str] = {}
    for row in connectors or []:
        tunnel = row.get("tunnel") if isinstance(row.get("tunnel"), dict) else {}
        if not tunnel.get("netns_listen_port"):
            continue
        pubkey = str(tunnel.get("client_public_key") or "").strip()
        if pubkey:
            out[pubkey] = str(row.get("name") or row.get("id") or pubkey[:12])
    return out


def render_conf_without_peer(conf_text: str, pubkey: str) -> str:
    """Remove o bloco [Peer] com esta chave do wg-sightops.conf.

    Usado quando um conector migra para isolamento por namespace: o bloco
    dele na interface compartilhada tem que sumir, nao so parar de ganhar
    redes novas.
    """
    blocks = conf_text.split("[Peer]")
    out = [blocks[0]]
    changed = False
    for block in blocks[1:]:
        m = re.search(r"PublicKey\s*=\s*([^\n]+)", block)
        if m and m.group(1).strip() == pubkey:
            changed = True
            continue
        out.append("[Peer]" + block)
    return "".join(out) if changed else conf_text


def _iter_private_ips_from_value(value: Any) -> Iterable[str]:
    """Extrai IPs privados/CGNAT de textos ou listas vindos do inventario."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_private_ips_from_value(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_private_ips_from_value(item)
        return
    text = str(value or "")
    for raw in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.version == 4 and (ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")):
            yield str(ip)


def _known_host_routes_for_connector(row: Dict[str, Any], conflicted_cidrs: Set[str]) -> Set[str]:
    """Retorna IPs /32 conhecidos que pertencem a redes em conflito.

    Quando dois clientes usam a mesma LAN privada, nao podemos anunciar a LAN
    inteira no mesmo roteador Linux. Mas podemos anunciar hosts unicos ja
    vistos naquele conector, como cameras descobertas por ARP/DHCP ou por
    inventario remoto.
    """
    if not conflicted_cidrs:
        return set()
    networks = []
    for cidr in conflicted_cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue
    if not networks:
        return set()

    inventory = row.get("inventory") if isinstance(row.get("inventory"), dict) else {}
    host = row.get("host") if isinstance(row.get("host"), dict) else {}
    candidates: list[Any] = [inventory, host]
    routes: Set[str] = set()
    for raw in _iter_private_ips_from_value(candidates):
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if any(ip in net and ip not in (net.network_address, net.broadcast_address) for net in networks):
            routes.add(f"{ip}/32")
    return routes


def expand_conflicted_lans_with_known_hosts(
    target_state: Dict[str, Dict],
    connectors: List[Dict],
    conflicts: Dict[str, List[str]],
) -> Dict[str, Dict]:
    """Adiciona /32 conhecidos para LANs privadas duplicadas entre conectores."""
    conflicted_cidrs = set(conflicts.keys())
    if not conflicted_cidrs:
        return target_state
    expanded = {
        pubkey: {"name": info["name"], "allowed": set(info["allowed"])}
        for pubkey, info in target_state.items()
    }
    for row in connectors or []:
        pubkey = _connector_pubkey(row)
        if not pubkey or pubkey not in expanded:
            continue
        host_routes = _known_host_routes_for_connector(row, conflicted_cidrs)
        if host_routes:
            expanded[pubkey]["allowed"].update(host_routes)
    return expanded


def find_exact_conflicts(target_state: Dict[str, Dict]) -> Dict[str, List[str]]:
    """CIDR exato reivindicado por mais de um conector -> lista de nomes.

    Prefixos de tamanho diferente que se sobrepoem (ex: /24 dentro de um /23
    de outro cliente) NAO entram aqui -- o kernel resolve isso corretamente
    por longest-prefix-match. So o caso de duplicata exata e ambiguo.
    """
    owners: Dict[str, List[str]] = {}
    for info in target_state.values():
        for cidr in info["allowed"]:
            owners.setdefault(cidr, []).append(info["name"])
    return {cidr: names for cidr, names in owners.items() if len(set(names)) > 1}


def parse_wg_dump(text: str) -> Dict[str, Set[str]]:
    """Parseia `wg show <iface> dump`. {pubkey: set(allowed_ips)}.

    Primeira linha e a propria interface (sem endpoint), o resto sao peers:
    pubkey  psk  endpoint  allowed-ips  latest-handshake  rx  tx  keepalive
    """
    out: Dict[str, Set[str]] = {}
    lines = [l for l in str(text or "").splitlines() if l.strip()]
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) < 4:
            continue
        pubkey = cols[0].strip()
        allowed_raw = cols[3].strip()
        allowed = {c.strip() for c in allowed_raw.split(",") if c.strip() and c.strip() != "(none)"}
        out[pubkey] = allowed
    return out


def plan_updates(
    target_state: Dict[str, Dict],
    current_state: Dict[str, Set[str]],
    conflicts: Dict[str, List[str]],
) -> Dict[str, Dict]:
    """Para cada peer, o que falta aplicar.

    {pubkey: {"name", "missing": set, "full_set": set, "peer_exists": bool}}
    `missing` ja exclui CIDRs em conflito exato entre conectores.
    Peer que nao existe ainda no wg-sightops (conector novo, ainda sem peer no
    servidor) e listado com peer_exists=False e `missing`/`full_set` ja com o
    conjunto desejado -- o chamador decide se cria o peer do zero.
    """
    conflicted_cidrs = set(conflicts.keys())
    plan: Dict[str, Dict] = {}
    for pubkey, info in target_state.items():
        wanted = info["allowed"] - conflicted_cidrs
        current = current_state.get(pubkey)
        if current is None:
            plan[pubkey] = {"name": info["name"], "missing": set(wanted), "full_set": set(wanted), "peer_exists": False}
            continue
        missing = wanted - current
        plan[pubkey] = {
            "name": info["name"],
            "missing": missing,
            "full_set": current | wanted,
            "peer_exists": True,
        }
    return plan


_PEER_BLOCK_RE = re.compile(
    r"(\[Peer\]\s*\n(?:[^\[]*?\n)?\s*PublicKey\s*=\s*)"  # grupo 1: cabecalho ate 'PublicKey ='
    r"([^\n]+)\n"                                          # grupo 2: a chave em si
    r"((?:(?!\[Peer\]|\[Interface\]).)*)",                  # grupo 3: resto do bloco deste peer
    re.DOTALL,
)


def render_conf_with_updated_peer(conf_text: str, pubkey: str, new_allowed_ips: Set[str]) -> str:
    """Atualiza (ou insere) a linha AllowedIPs do bloco [Peer] com esta chave.

    So mexe no bloco do peer indicado; os demais blocos saem identicos. Se a
    chave nao existir no arquivo, devolve o texto sem alteracao (o peer
    provavelmente ainda nao foi instalado -- nada a persistir).
    """
    allowed_str = ", ".join(sorted(new_allowed_ips, key=lambda s: (":" in s, s)))
    blocks = conf_text.split("[Peer]")
    out = [blocks[0]]
    found = False
    for block in blocks[1:]:
        m = re.search(r"PublicKey\s*=\s*([^\n]+)", block)
        if m and m.group(1).strip() == pubkey:
            found = True
            if re.search(r"^\s*AllowedIPs\s*=.*$", block, re.MULTILINE):
                block = re.sub(
                    r"^\s*AllowedIPs\s*=.*$",
                    f"AllowedIPs = {allowed_str}",
                    block,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                block = block.rstrip("\n") + f"\nAllowedIPs = {allowed_str}\n"
        out.append("[Peer]" + block)
    return "".join(out) if found else conf_text


def append_new_peer_block(conf_text: str, pubkey: str, allowed_ips: Set[str]) -> str:
    """Acrescenta um bloco [Peer] novo ao final do arquivo de config.

    Usado quando o conector tem chave publica cadastrada mas o servidor
    ainda nunca viu esse peer (nem no `wg show`, nem no .conf) -- caso do
    conector recem-criado, antes da primeira sincronizacao.
    """
    allowed_str = ", ".join(sorted(allowed_ips, key=lambda s: (":" in s, s)))
    bloco = f"\n[Peer]\nPublicKey = {pubkey}\nAllowedIPs = {allowed_str}\nPersistentKeepalive = 25\n"
    return conf_text.rstrip("\n") + "\n" + bloco


# --- I/O real (nao coberto por teste automatico -- precisa de wg/ip/root) ----


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _connectors_json_path() -> Path:
    for path in CONNECTORS_JSON_CANDIDATES:
        if path.exists():
            return path
    return CONNECTORS_JSON_CANDIDATES[0]


def _route_device_for(cidr: str) -> Optional[str]:
    proc = _run(["ip", "route", "show", cidr])
    out = (proc.stdout or "").strip()
    if not out:
        return None
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else "?"


def _docker_bridge_subnets() -> Set[str]:
    """Retorna sub-redes dos bridges Docker que precisam de NAT ate a WG."""
    proc = _run(["docker", "network", "ls", "--format", "{{.Name}}"])
    if proc.returncode != 0:
        return set()

    subnets: Set[str] = set()
    for name in [line.strip() for line in proc.stdout.splitlines() if line.strip()]:
        inspect = _run(["docker", "network", "inspect", name, "--format", "{{json .IPAM.Config}}"])
        if inspect.returncode != 0:
            continue
        for cidr in re.findall(r'"Subnet"\s*:\s*"([^"]+)"', inspect.stdout or ""):
            canon = canon_cidr(cidr)
            if canon:
                subnets.add(canon)
    return subnets


def _iptables_check_or_add(args: List[str], dry_run: bool) -> None:
    global _IPTABLES_BIN, _IPTABLES_MISSING_WARNED
    iptables_bin = _IPTABLES_BIN
    if not iptables_bin:
        for candidate in IPTABLES_CANDIDATES:
            resolved = shutil.which(candidate) if "/" not in candidate else candidate
            if resolved and Path(resolved).exists():
                iptables_bin = resolved
                _IPTABLES_BIN = resolved
                break
    if not iptables_bin:
        if not _IPTABLES_MISSING_WARNED:
            _log("AVISO: iptables nao encontrado; NAT Docker->WireGuard nao gerenciado por este script.")
            _IPTABLES_MISSING_WARNED = True
        return

    if args[:2] == ["-t", "nat"]:
        chain = args[2]
        rule = args[3:]
        check_args = ["-t", "nat", "-C", chain] + rule
        add_args = ["-t", "nat", "-A", chain] + rule
    else:
        chain = args[0]
        rule = args[1:]
        check_args = ["-C", chain] + rule
        add_args = ["-A", chain] + rule

    check = _run([iptables_bin] + check_args)
    if check.returncode == 0:
        return
    if dry_run:
        _log("DRY-RUN iptables " + " ".join(add_args))
        return
    proc = _run([iptables_bin] + add_args)
    if proc.returncode != 0:
        _log(f"AVISO: falhou iptables {' '.join(add_args)}: {proc.stderr.strip()}")


def ensure_docker_nat_to_wg(client_cidr: str, dry_run: bool) -> None:
    """Permite containers Docker acessarem a LAN remota pelo WireGuard.

    O host pode rotear a LAN do cliente corretamente e mesmo assim o container
    falhar, porque a resposta da camera volta para o IP do servidor WG
    (10.250.0.1), nao para a sub-rede Docker. O MASQUERADE corrige isso.
    """
    docker_subnets = _docker_bridge_subnets()
    for source in sorted(docker_subnets, key=lambda s: tuple(map(int, s.split("/")[0].split("."))) if "." in s else (999,)):
        _iptables_check_or_add(
            ["-t", "nat", "POSTROUTING", "-s", source, "-d", client_cidr, "-o", WG_INTERFACE, "-j", "MASQUERADE"],
            dry_run,
        )
        _iptables_check_or_add(
            ["FORWARD", "-s", source, "-d", client_cidr, "-o", WG_INTERFACE, "-j", "ACCEPT"],
            dry_run,
        )
        _iptables_check_or_add(
            ["FORWARD", "-i", WG_INTERFACE, "-d", source, "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
            dry_run,
        )


def main() -> int:
    dry_run = "--check" in sys.argv or "--dry-run" in sys.argv

    connectors_path = _connectors_json_path()
    if not connectors_path.exists():
        _log(f"ERRO: nenhum connectors.json encontrado em: {', '.join(str(p) for p in CONNECTORS_JSON_CANDIDATES)}")
        return 1
    _log(f"Lendo conectores de {connectors_path}")
    connectors = json.loads(connectors_path.read_text(encoding="utf-8"))
    target_state = compute_target_state(connectors)

    lan_conflicts = find_exact_conflicts(target_state)
    if lan_conflicts:
        target_state = expand_conflicted_lans_with_known_hosts(target_state, connectors, lan_conflicts)

    conflicts = find_exact_conflicts(target_state)
    for cidr, names in conflicts.items():
        if cidr in lan_conflicts:
            _log(
                f"AVISO: {cidr} esta cadastrado em mais de um conector ({', '.join(names)}). "
                "Ignorando a rede inteira e usando apenas IPs conhecidos unicos."
            )
        else:
            _log(f"AVISO: {cidr} esta cadastrado em mais de um conector ({', '.join(names)}). Ignorando este IP/rede.")

    dump = _run(["wg", "show", WG_INTERFACE, "dump"])
    if dump.returncode != 0:
        _log(f"ERRO ao ler '{WG_INTERFACE}': {dump.stderr.strip()}")
        return 1
    current_state = parse_wg_dump(dump.stdout)

    plan = plan_updates(target_state, current_state, conflicts)

    applied_any = False

    isolated = isolated_pubkeys(connectors)
    stale_isolated = set(isolated) & set(current_state.keys())
    for pubkey in stale_isolated:
        name = isolated[pubkey]
        _log(f"{name}: conector isolado por namespace -- removendo peer de {WG_INTERFACE} (nunca deveria estar aqui).")
        applied_any = True
        if dry_run:
            continue
        r = _run(["wg", "set", WG_INTERFACE, "peer", pubkey, "remove"])
        if r.returncode != 0:
            _log(f"{name}: FALHOU wg set ... remove: {r.stderr.strip()}")
            continue
        if WG_CONF_PATH.exists():
            try:
                original = WG_CONF_PATH.read_text(encoding="utf-8")
                updated = render_conf_without_peer(original, pubkey)
                if updated != original:
                    backup = WG_CONF_PATH.with_suffix(
                        f".conf.bak-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                    )
                    backup.write_text(original, encoding="utf-8")
                    WG_CONF_PATH.write_text(updated, encoding="utf-8")
                    _log(f"{name}: {WG_CONF_PATH} atualizado (peer removido, backup em {backup.name}).")
            except Exception as exc:
                _log(f"{name}: nao consegui persistir remocao em {WG_CONF_PATH}: {exc}")

    for pubkey, item in plan.items():
        name = item["name"]
        is_new_peer = not item["peer_exists"]
        if not item["missing"]:
            continue

        # cada rede nova so entra se nao estiver roteada por OUTRA interface
        safe_new = set()
        for cidr in item["missing"]:
            dev = _route_device_for(cidr)
            if dev is None or dev == WG_INTERFACE:
                safe_new.add(cidr)
            else:
                _log(f"{name}: {cidr} ja roteado por '{dev}', nao mexendo. Confira manualmente.")
        if not safe_new:
            continue

        full_set = current_state.get(pubkey, set()) | safe_new
        allowed_str = ",".join(sorted(full_set, key=lambda s: (":" in s, s)))
        acao = "criando peer novo" if is_new_peer else "aplicando"
        _log(f"{name}: {acao} {sorted(safe_new)} (peer {pubkey[:16]}...)")
        applied_any = True
        if dry_run:
            continue

        r1 = _run(["wg", "set", WG_INTERFACE, "peer", pubkey, "allowed-ips", allowed_str])
        if r1.returncode != 0:
            _log(f"{name}: FALHOU wg set: {r1.stderr.strip()}")
            continue
        for cidr in safe_new:
            r2 = _run(["ip", "route", "replace", cidr, "dev", WG_INTERFACE])
            if r2.returncode != 0 and "File exists" not in (r2.stderr or ""):
                _log(f"{name}: FALHOU ip route replace {cidr}: {r2.stderr.strip()}")
            ensure_docker_nat_to_wg(cidr, dry_run)

        if WG_CONF_PATH.exists():
            try:
                original = WG_CONF_PATH.read_text(encoding="utf-8")
                updated = render_conf_with_updated_peer(original, pubkey, full_set)
                if updated == original and is_new_peer:
                    updated = append_new_peer_block(original, pubkey, full_set)
                if updated != original:
                    backup = WG_CONF_PATH.with_suffix(
                        f".conf.bak-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                    )
                    backup.write_text(original, encoding="utf-8")
                    WG_CONF_PATH.write_text(updated, encoding="utf-8")
                    _log(f"{name}: {WG_CONF_PATH} atualizado (backup em {backup.name}).")
            except Exception as exc:
                _log(f"{name}: nao consegui persistir em {WG_CONF_PATH}: {exc}")

    if not applied_any:
        _log("Nada a fazer -- todos os conectores ja estao sincronizados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
