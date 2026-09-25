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
  nao aplica em nenhum dos dois (conflito exige correcao manual no cadastro).
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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

WG_INTERFACE = "wg-sightops"
WG_CONF_PATH = Path("/etc/wireguard/wg-sightops.conf")
CONNECTORS_JSON_PATH = Path(
    "/var/lib/docker/volumes/cam-snapshot-web_sightops_data/_data/connectors.json"
)


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
    sem isso nao ha peer no wg-sightops pra sincronizar.
    """
    out: Dict[str, Dict] = {}
    for row in connectors or []:
        tunnel = row.get("tunnel") if isinstance(row.get("tunnel"), dict) else {}
        if not tunnel.get("enabled") or str(tunnel.get("type") or "").lower() != "wireguard":
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
    Peer que nao existe ainda no wg-sightops (nunca instalou a VPN) e listado
    com peer_exists=False -- nada e aplicado, so reportado.
    """
    conflicted_cidrs = set(conflicts.keys())
    plan: Dict[str, Dict] = {}
    for pubkey, info in target_state.items():
        wanted = info["allowed"] - conflicted_cidrs
        current = current_state.get(pubkey)
        if current is None:
            plan[pubkey] = {"name": info["name"], "missing": set(), "full_set": set(), "peer_exists": False}
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


# --- I/O real (nao coberto por teste automatico -- precisa de wg/ip/root) ----


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _route_device_for(cidr: str) -> Optional[str]:
    proc = _run(["ip", "route", "show", cidr])
    out = (proc.stdout or "").strip()
    if not out:
        return None
    m = re.search(r"\bdev\s+(\S+)", out)
    return m.group(1) if m else "?"


def main() -> int:
    dry_run = "--check" in sys.argv or "--dry-run" in sys.argv

    if not CONNECTORS_JSON_PATH.exists():
        _log(f"ERRO: {CONNECTORS_JSON_PATH} nao encontrado. Nada a fazer.")
        return 1
    connectors = json.loads(CONNECTORS_JSON_PATH.read_text(encoding="utf-8"))
    target_state = compute_target_state(connectors)

    conflicts = find_exact_conflicts(target_state)
    for cidr, names in conflicts.items():
        _log(f"AVISO: {cidr} esta cadastrado em mais de um conector ({', '.join(names)}). Ignorando esta rede ate corrigir o cadastro.")

    dump = _run(["wg", "show", WG_INTERFACE, "dump"])
    if dump.returncode != 0:
        _log(f"ERRO ao ler '{WG_INTERFACE}': {dump.stderr.strip()}")
        return 1
    current_state = parse_wg_dump(dump.stdout)

    plan = plan_updates(target_state, current_state, conflicts)

    applied_any = False
    for pubkey, item in plan.items():
        name = item["name"]
        if not item["peer_exists"]:
            _log(f"{name}: peer {pubkey[:16]}... nao existe ainda em {WG_INTERFACE} (VPN nao instalada). Pulando.")
            continue
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
        _log(f"{name}: aplicando {sorted(safe_new)} (peer {pubkey[:16]}...)")
        applied_any = True
        if dry_run:
            continue

        r1 = _run(["wg", "set", WG_INTERFACE, "peer", pubkey, "allowed-ips", allowed_str])
        if r1.returncode != 0:
            _log(f"{name}: FALHOU wg set: {r1.stderr.strip()}")
            continue
        for cidr in safe_new:
            r2 = _run(["ip", "route", "add", cidr, "dev", WG_INTERFACE])
            if r2.returncode != 0 and "File exists" not in (r2.stderr or ""):
                _log(f"{name}: FALHOU ip route add {cidr}: {r2.stderr.strip()}")

        if WG_CONF_PATH.exists():
            try:
                original = WG_CONF_PATH.read_text(encoding="utf-8")
                updated = render_conf_with_updated_peer(original, pubkey, full_set)
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
