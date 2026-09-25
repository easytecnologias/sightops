#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reconciliacao automatica dos tuneis OpenVPN dos conectores Ruijie.

Roda FORA da imagem Docker, direto no HOST de producao (mesmo padrao do
sightops_wireguard_sync.py), via systemd timer. A cada ciclo:

1. Pergunta pro container sightops-api (via `docker exec`) quais conectores
   Ruijie tem VPN configurada (usuario/senha/config .ovpn), ja decifrados --
   a chave de criptografia nunca sai do container.
2. Compara com os containers `sightops-vpn-<id>` que ja estao rodando no
   host (e um hash da config salvo em disco, pra saber se mudou).
3. Cria, recria (se a config mudou) ou remove (se a VPN foi desabilitada
   nesse conector) o container correspondente. Container roda com
   `--network host --restart unless-stopped`: uma vez criado, o proprio
   Docker mantem ele de pe (sobrevive a crash e reboot do host) sem
   depender desse script rodar de novo -- o timer so cuida de criar/
   atualizar/remover quando o cadastro no SightOps muda.

Sem isso, cada conector Ruijie com VPN precisaria de alguem rodando
`docker run` na mao toda vez que a config mudasse (foi assim que o
primeiro cliente, JANGADEIROS, foi ligado -- este script substitui esse
passo manual).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

CONTAINER_PREFIX = "sightops-vpn-"
STATE_DIR = Path("/home/central/sightops-vpn")
API_CONTAINER = "sightops-api"

_FETCH_SCRIPT = r"""
import json
from app.core.tenant_context import set_current_tenant_slug
from app.core.crypto import decrypt
from app.services.connector_service import _load_connectors

out = []
for row in _load_connectors():
    if str(row.get("type") or "").lower() != "ruijie":
        continue
    vpn_config = str(row.get("vpn_config") or "").strip()
    vpn_username = str(row.get("vpn_username") or "").strip()
    vpn_password_enc = str(row.get("vpn_password_enc") or "").strip()
    if not (vpn_config and vpn_username and vpn_password_enc):
        continue
    out.append({
        "id": row.get("id"),
        "name": row.get("name"),
        "vpn_username": vpn_username,
        "vpn_password": decrypt(vpn_password_enc),
        "vpn_config": vpn_config,
    })
print(json.dumps(out))
"""


def config_hash(vpn_config: str, vpn_username: str, vpn_password: str) -> str:
    """Hash estavel da config+credencial -- usado pra detectar mudanca sem
    guardar a senha em texto claro no arquivo de estado."""
    digest = hashlib.sha256()
    digest.update(vpn_config.encode("utf-8"))
    digest.update(b"\0")
    digest.update(vpn_username.encode("utf-8"))
    digest.update(b"\0")
    digest.update(vpn_password.encode("utf-8"))
    return digest.hexdigest()


def plan_actions(
    desired: List[Dict[str, Any]],
    running_ids: List[str],
    cached_hashes: Dict[str, str],
) -> Dict[str, List[str]]:
    """Decide o que fazer com cada conector, sem tocar em Docker/disco --
    so compara os dados. `desired` = conectores Ruijie com VPN configurada
    agora; `running_ids` = ids com container `sightops-vpn-<id>` no ar;
    `cached_hashes` = ultimo hash aplicado por id (arquivo de estado).

    Devolve {"create": [...], "recreate": [...], "remove": [...], "noop": [...]}.
    """
    desired_by_id = {str(item["id"]): item for item in desired}
    running_set = set(running_ids)
    plan: Dict[str, List[str]] = {"create": [], "recreate": [], "remove": [], "noop": []}

    for connector_id, item in desired_by_id.items():
        current_hash = config_hash(item["vpn_config"], item["vpn_username"], item["vpn_password"])
        if connector_id not in running_set:
            plan["create"].append(connector_id)
        elif cached_hashes.get(connector_id) != current_hash:
            plan["recreate"].append(connector_id)
        else:
            plan["noop"].append(connector_id)

    for connector_id in running_set:
        if connector_id not in desired_by_id:
            plan["remove"].append(connector_id)

    return plan


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def fetch_desired_state() -> List[Dict[str, Any]]:
    result = _run(["docker", "exec", "-e", "PYTHONPATH=/app", API_CONTAINER, "python", "-c", _FETCH_SCRIPT])
    if result.returncode != 0:
        raise RuntimeError(f"falha ao consultar conectores Ruijie: {result.stderr.strip()}")
    return json.loads(result.stdout.strip() or "[]")


def running_container_ids() -> List[str]:
    result = _run(["docker", "ps", "--format", "{{.Names}}"])
    if result.returncode != 0:
        raise RuntimeError(f"falha ao listar containers: {result.stderr.strip()}")
    ids = []
    for name in result.stdout.splitlines():
        name = name.strip()
        if name.startswith(CONTAINER_PREFIX):
            ids.append(name[len(CONTAINER_PREFIX):])
    return ids


def load_cached_hashes() -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    if not STATE_DIR.is_dir():
        return hashes
    for child in STATE_DIR.iterdir():
        hash_file = child / "config.hash"
        if hash_file.is_file():
            hashes[child.name] = hash_file.read_text(encoding="utf-8").strip()
    return hashes


def write_connector_files(connector_id: str, vpn_username: str, vpn_password: str, vpn_config: str) -> None:
    conn_dir = STATE_DIR / connector_id
    conn_dir.mkdir(parents=True, exist_ok=True)
    (conn_dir / "client.ovpn").write_text(vpn_config, encoding="utf-8")
    auth_path = conn_dir / "auth.txt"
    auth_path.write_text(f"{vpn_username}\n{vpn_password}\n", encoding="utf-8")
    os.chmod(auth_path, 0o600)
    (conn_dir / "config.hash").write_text(
        config_hash(vpn_config, vpn_username, vpn_password), encoding="utf-8"
    )


def start_container(connector_id: str) -> None:
    conn_dir = STATE_DIR / connector_id
    name = f"{CONTAINER_PREFIX}{connector_id}"
    _run(["docker", "rm", "-f", name])
    cmd = [
        "docker", "run", "-d", "--name", name,
        "--restart", "unless-stopped", "--network", "host",
        "--cap-add=NET_ADMIN", "--device", "/dev/net/tun",
        "-v", f"{conn_dir}/client.ovpn:/etc/openvpn/client.ovpn:ro",
        "-v", f"{conn_dir}/auth.txt:/etc/openvpn/auth.txt:ro",
        "alpine:latest", "sh", "-c",
        "apk add --no-cache openvpn >/dev/null 2>&1 && "
        "exec openvpn --config /etc/openvpn/client.ovpn "
        "--auth-user-pass /etc/openvpn/auth.txt --data-ciphers-fallback AES-128-CBC",
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"falha ao subir container de {connector_id}: {result.stderr.strip()}")


def remove_container(connector_id: str) -> None:
    _run(["docker", "rm", "-f", f"{CONTAINER_PREFIX}{connector_id}"])
    conn_dir = STATE_DIR / connector_id
    for name in ("client.ovpn", "auth.txt", "config.hash"):
        path = conn_dir / name
        if path.is_file():
            path.unlink()


def main() -> None:
    desired = fetch_desired_state()
    running_ids = running_container_ids()
    cached_hashes = load_cached_hashes()
    plan = plan_actions(desired, running_ids, cached_hashes)

    desired_by_id = {str(item["id"]): item for item in desired}
    for connector_id in plan["create"] + plan["recreate"]:
        item = desired_by_id[connector_id]
        write_connector_files(connector_id, item["vpn_username"], item["vpn_password"], item["vpn_config"])
        start_container(connector_id)
        print(f"[{connector_id}] {item.get('name')}: tunel criado/atualizado", flush=True)

    for connector_id in plan["remove"]:
        remove_container(connector_id)
        print(f"[{connector_id}]: VPN removida do cadastro, tunel derrubado", flush=True)

    if plan["noop"]:
        print(f"{len(plan['noop'])} tunel(is) ja em dia, nada a fazer.", flush=True)
    if not any(plan.values()):
        print("Nenhum conector Ruijie com VPN configurada.", flush=True)


if __name__ == "__main__":
    main()
