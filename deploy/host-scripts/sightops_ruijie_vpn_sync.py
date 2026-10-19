#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reconciliacao automatica dos tuneis OpenVPN dos conectores Ruijie.

Roda FORA da imagem Docker, direto no HOST de producao (mesmo padrao do
sightops_wireguard_sync.py), via systemd timer. A cada ciclo:

1. Pergunta pro container sightops-v3-api (via `docker exec`) quais conectores
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
# No v3 o container e sightops-v3-api; "sightops-api" era o do v2 e, depois
# que ele saiu, o timer passou a falhar a cada minuto ("No such container").
API_CONTAINER = os.getenv("SIGHTOPS_API_CONTAINER", "sightops-v3-api")

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
        "iso_index": row.get("iso_index"),
    })
print(json.dumps(out))
"""


# Isolamento igual ao do MikroTik: cada tunel vive na PROPRIA rede Docker
# (namespace de rede proprio), com bridge de nome fixo rjc<N> no host. As rotas
# que o gateway empurra ficam presas dentro do container -- a tabela geral do
# servidor nao recebe rota de cliente nenhum. O iso-provisioner liga o host a
# esse container pela tabela 100<N> + faixa virtual (NETMAP), como faz com wgc<N>.
MODO_ISOLADO = "isolado-v1"


def rede_isolada(iso_index: Any) -> Dict[str, str]:
    """Rede Docker exclusiva do conector de indice N (10.203.N.0/29)."""
    n = int(iso_index)
    if not 1 <= n <= 254:
        raise ValueError(f"iso_index fora da faixa: {n}")
    return {
        "nome": f"sightops-rj{n}",
        "bridge": f"rjc{n}",
        "subnet": f"10.203.{n}.0/29",
        "gateway": f"10.203.{n}.1",
        "ip": f"10.203.{n}.2",
    }


# Firewall DENTRO do container: so passa o que o SightOps manda para o cliente
# (eth0 -> tun) e a resposta. Nada que nasce do lado do cliente atravessa o
# container -- nem para o servidor, nem para outro cliente, nem de volta pela
# eth0 (que cairia na tabela geral do host).
FIREWALL_INTERNO = (
    "iptables -P FORWARD DROP && "
    "iptables -A FORWARD -i eth0 -o tun+ -j ACCEPT && "
    "iptables -A FORWARD -i tun+ -o eth0 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT && "
    "iptables -t nat -A POSTROUTING -o tun+ -j MASQUERADE"
)


# Diretivas que executam comando / carregam codigo (o .ovpn vem do cliente e o
# OpenVPN roda como root no container). O app ja recusa no cadastro; aqui sai
# de novo, e o `--script-security 1` na linha de comando vale por cima do arquivo.
OVPN_PROIBIDAS = (
    "script-security", "up", "down", "route-up", "route-pre-down", "ipchange", "plugin",
    "learn-address", "client-connect", "client-disconnect", "auth-user-pass-verify",
    "tls-verify", "setenv", "setenv-safe", "management", "config", "cd", "chroot",
    "daemon", "log", "log-append", "writepid", "status", "dev-node", "iproute",
    "route-noexec", "ifconfig-noexec", "up-delay", "down-pre", "up-restart",
)


def ovpn_seguro(vpn_config: str) -> str:
    """O .ovpn sem nenhuma diretiva de OVPN_PROIBIDAS (fora dos blocos <...>)."""
    saida, dentro_bloco = [], False
    for linha in vpn_config.splitlines():
        crua = linha.strip()
        if crua.startswith("<") and not crua.startswith("</"):
            dentro_bloco = True
        if crua.startswith("</"):
            dentro_bloco = False
            saida.append(linha)
            continue
        partes = crua.split()
        # O OpenVPN aceita o nome da opcao entre aspas ("plugin" ...).
        if not dentro_bloco and partes and partes[0].strip("\"'").lstrip("-").lower() in OVPN_PROIBIDAS:
            continue
        saida.append(linha)
    return "\n".join(saida) + "\n"


def config_hash(vpn_config: str, vpn_username: str, vpn_password: str, iso_index: Any = "") -> str:
    """Hash estavel da config+credencial -- usado pra detectar mudanca sem
    guardar a senha em texto claro no arquivo de estado. O indice e o modo
    entram no hash: trocar o modo de rede recria o tunel."""
    digest = hashlib.sha256()
    digest.update(vpn_config.encode("utf-8"))
    digest.update(b"\0")
    digest.update(vpn_username.encode("utf-8"))
    digest.update(b"\0")
    digest.update(vpn_password.encode("utf-8"))
    if iso_index not in ("", None):
        digest.update(b"\0")
        digest.update(f"{MODO_ISOLADO}:{int(iso_index)}".encode("utf-8"))
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
        current_hash = config_hash(item["vpn_config"], item["vpn_username"], item["vpn_password"],
                                   item.get("iso_index") or "")
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


def write_connector_files(connector_id: str, vpn_username: str, vpn_password: str, vpn_config: str,
                          iso_index: Any = "") -> None:
    conn_dir = STATE_DIR / connector_id
    conn_dir.mkdir(parents=True, exist_ok=True)
    (conn_dir / "client.ovpn").write_text(ovpn_seguro(vpn_config), encoding="utf-8")
    auth_path = conn_dir / "auth.txt"
    auth_path.write_text(f"{vpn_username}\n{vpn_password}\n", encoding="utf-8")
    os.chmod(auth_path, 0o600)
    (conn_dir / "config.hash").write_text(
        config_hash(vpn_config, vpn_username, vpn_password, iso_index), encoding="utf-8"
    )


def ensure_network(rede: Dict[str, str]) -> None:
    """Cria a rede Docker exclusiva do conector, se ainda nao existe."""
    if _run(["docker", "network", "inspect", rede["nome"]]).returncode == 0:
        return
    result = _run([
        "docker", "network", "create", "--driver", "bridge",
        "--subnet", rede["subnet"], "--gateway", rede["gateway"],
        "-o", f"com.docker.network.bridge.name={rede['bridge']}",
        rede["nome"],
    ])
    if result.returncode != 0:
        raise RuntimeError(f"falha ao criar a rede {rede['nome']}: {result.stderr.strip()}")


def run_args(connector_id: str, iso_index: Any) -> List[str]:
    """Argumentos do `docker run` do tunel isolado. Nunca --network host."""
    conn_dir = STATE_DIR / connector_id
    rede = rede_isolada(iso_index)
    return [
        "docker", "run", "-d", "--name", f"{CONTAINER_PREFIX}{connector_id}",
        "--restart", "unless-stopped",
        "--network", rede["nome"], "--ip", rede["ip"],
        "--sysctl", "net.ipv4.ip_forward=1",
        # DNS publico: os resolvedores do host estao em faixa privada, que o
        # host barra para quem sai do rjc<N> (so internet).
        "--dns", "8.8.8.8", "--dns", "1.1.1.1",
        "--cap-add=NET_ADMIN", "--device", "/dev/net/tun",
        "-v", f"{conn_dir}/client.ovpn:/etc/openvpn/client.ovpn:ro",
        "-v", f"{conn_dir}/auth.txt:/etc/openvpn/auth.txt:ro",
        "alpine:3.20", "sh", "-c",
        "apk add --no-cache openvpn iptables >/dev/null 2>&1 && "
        + FIREWALL_INTERNO + " && "
        "exec openvpn --config /etc/openvpn/client.ovpn --script-security 1 "
        "--auth-user-pass /etc/openvpn/auth.txt --data-ciphers-fallback AES-128-CBC",
    ]


def remove_orphan_networks(desired_indices: List[int]) -> None:
    """Rede sightops-rj<N> sem container e sem conector (docker run que falhou
    depois do network create, container apagado na mao): sai. Uma sobra dessa
    faria o provisionador achar que o tunel N existe."""
    result = _run(["docker", "network", "ls", "--format", "{{.Name}}"])
    if result.returncode != 0:
        return
    for nome in result.stdout.split():
        if not nome.startswith("sightops-rj") or not nome[len("sightops-rj"):].isdigit():
            continue
        if int(nome[len("sightops-rj"):]) in desired_indices:
            continue
        uso = _run(["docker", "network", "inspect", "-f", "{{len .Containers}}", nome])
        if uso.returncode == 0 and uso.stdout.strip() == "0":
            _run(["docker", "network", "rm", nome])


def start_container(connector_id: str, iso_index: Any) -> None:
    ensure_network(rede_isolada(iso_index))
    _run(["docker", "rm", "-f", f"{CONTAINER_PREFIX}{connector_id}"])
    cmd = run_args(connector_id, iso_index)
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"falha ao subir container de {connector_id}: {result.stderr.strip()}")


def remove_container(connector_id: str) -> None:
    name = f"{CONTAINER_PREFIX}{connector_id}"
    # Rede exclusiva do tunel: descobre pelo proprio container antes de apagar.
    redes = _run(["docker", "inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}", name])
    _run(["docker", "rm", "-f", name])
    for rede in (redes.stdout or "").split():
        if rede.startswith("sightops-rj"):
            _run(["docker", "network", "rm", rede])
    conn_dir = STATE_DIR / connector_id
    for name in ("client.ovpn", "auth.txt", "config.hash"):
        path = conn_dir / name
        if path.is_file():
            path.unlink()


def main() -> None:
    desired = []
    for item in fetch_desired_state():
        # Sem indice nao ha como isolar: o tunel NAO sobe na rede geral do
        # host (era assim antes, e deixava as rotas do cliente na tabela main).
        # O app atribui o indice na proxima coleta.
        if not item.get("iso_index"):
            print(f"[{item.get('id')}] {item.get('name')}: aguardando indice de isolamento", flush=True)
            continue
        desired.append(item)
    running_ids = running_container_ids()
    cached_hashes = load_cached_hashes()
    plan = plan_actions(desired, running_ids, cached_hashes)

    desired_by_id = {str(item["id"]): item for item in desired}
    for connector_id in plan["create"] + plan["recreate"]:
        item = desired_by_id[connector_id]
        write_connector_files(connector_id, item["vpn_username"], item["vpn_password"], item["vpn_config"],
                              item["iso_index"])
        start_container(connector_id, item["iso_index"])
        print(f"[{connector_id}] {item.get('name')}: tunel criado/atualizado", flush=True)

    for connector_id in plan["remove"]:
        remove_container(connector_id)
        print(f"[{connector_id}]: VPN removida do cadastro, tunel derrubado", flush=True)

    remove_orphan_networks([int(item["iso_index"]) for item in desired])

    if plan["noop"]:
        print(f"{len(plan['noop'])} tunel(is) ja em dia, nada a fazer.", flush=True)
    if not any(plan.values()):
        print("Nenhum conector Ruijie com VPN configurada.", flush=True)


if __name__ == "__main__":
    main()
