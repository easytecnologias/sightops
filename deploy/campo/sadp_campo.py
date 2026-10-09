#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descoberta de cameras Hikvision na rede local -- o SADP, do nosso jeito.

POR QUE ISTO EXISTE

Camera Hikvision de fabrica nasce em 192.168.1.64. Quando varias sobem na
mesma rede, elas DETECTAM o conflito e se recolhem: param de responder ping,
HTTP e ate a porta 8000 do SDK. Medido na SIERRA em 08/10/2026 -- sete
cameras atras de uma ONU, todas no mesmo IP, nenhuma alcancavel nem do
roteador que estava na mesma rede.

Nesse estado, a UNICA forma de enxerga-las e nao usar IP nenhum. E o que o
SADP faz: pergunta em UDP multicast e cada camera se identifica por MAC e
serial dentro do proprio pacote. Conflito de camada 3 nao atrapalha a
camada 2.

POR QUE NAO O SADP.EXE DA HIKVISION

Porque ele nao conversa com o SightOps: o tecnico le na tela e digita de
novo no sistema. Aqui a saida tambem sai em JSON (--json), pronta para a
proxima fase -- a fila de ativacao.

ONDE RODAR

Numa maquina DENTRO da rede das cameras: o notebook do tecnico no site.
Multicast nao atravessa o tunel WireGuard, entao o servidor nao consegue
fazer isto de fora -- nao e limitacao de software, e de camada 2.

    python sadp_campo.py                 # tabela na tela
    python sadp_campo.py --json saida.json
    python sadp_campo.py --segundos 15   # rede grande/lenta

Nao escreve nada em camera nenhuma. So pergunta.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import struct
import sys
import time
import uuid
from typing import Any, Dict, List

# O grupo e a porta do SADP. Nao sao configuraveis na camera: valem para
# todo equipamento Hikvision e derivados (Intelbras OEM incluso).
GRUPO_SADP = "239.255.255.250"
PORTA_SADP = 37020

# A camera responde para a porta de onde veio a pergunta. Parte dos firmwares
# antigos ignora isso e responde SEMPRE na 37020 -- por isso tentamos ocupar
# essa porta; se outro programa (o proprio SADP.exe) ja estiver nela, caimos
# numa porta qualquer e ainda assim a maioria responde.
PORTAS_DE_ESCUTA = (PORTA_SADP, 0)

_CAMPOS = (
    "MAC", "IPv4Address", "IPv4SubnetMask", "IPv4Gateway", "DeviceSN",
    "DeviceDescription", "DeviceType", "SoftwareVersion", "DSPVersion",
    "CommandPort", "HttpPort", "Activated", "DHCP", "BootTime",
)


def _probe() -> bytes:
    """O pacote de pergunta. `Types: inquiry` e o que faz todas responderem."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<Probe>\n"
        f"<Uuid>{str(uuid.uuid4()).upper()}</Uuid>\n"
        "<Types>inquiry</Types>\n"
        "</Probe>\n"
    ).encode("utf-8")


def _valor(xml: str, campo: str) -> str:
    m = re.search(rf"<{campo}>(.*?)</{campo}>", xml, re.IGNORECASE | re.DOTALL)
    return (m.group(1) or "").strip() if m else ""


def _normalizar_mac(valor: str) -> str:
    so_hex = re.sub(r"[^0-9A-Fa-f]", "", valor or "")
    if len(so_hex) != 12:
        return (valor or "").strip().upper()
    return ":".join(so_hex[i:i + 2] for i in range(0, 12, 2)).upper()


def _enderecos_de_broadcast() -> List[str]:
    """Broadcast alem do multicast: switch barato e rede com IGMP snooping mal
    configurado engolem multicast, e ai so o broadcast chega."""
    alvos = {"255.255.255.255"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127."):
                continue
            partes = ip.split(".")
            if len(partes) == 4:
                alvos.add(".".join(partes[:3]) + ".255")
    except Exception:
        pass
    return sorted(alvos)


def descobrir(segundos: float = 8.0, verboso: bool = False) -> List[Dict[str, Any]]:
    """Pergunta na rede e junta quem responder. Nao levanta excecao por
    interface que recusa: numa maquina com VPN/Hyper-V varias recusam, e
    desistir na primeira deixaria a varredura vazia sem motivo."""
    sock = None
    for porta in PORTAS_DE_ESCUTA:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("", porta))
            sock = s
            if verboso:
                print(f"[i] escutando na porta UDP {s.getsockname()[1]}", file=sys.stderr)
            break
        except OSError:
            continue
    if sock is None:
        raise RuntimeError("nao consegui abrir socket UDP para a descoberta")

    try:
        # Entrar no grupo multicast em TODAS as interfaces: numa maquina com
        # Wi-Fi + cabo + VPN, entrar so na padrao costuma ser a interface
        # errada -- e a camera esta justamente na outra.
        try:
            sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                struct.pack("4sl", socket.inet_aton(GRUPO_SADP), socket.INADDR_ANY),
            )
        except OSError:
            pass
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        alvos = [(GRUPO_SADP, PORTA_SADP)] + [(b, PORTA_SADP) for b in _enderecos_de_broadcast()]
        achados: Dict[str, Dict[str, Any]] = {}
        sock.settimeout(0.5)
        fim = time.monotonic() + segundos
        proxima_pergunta = 0.0

        while time.monotonic() < fim:
            # Repergunta a cada 2s: camera que estava reiniciando no primeiro
            # pacote responde no segundo, e e exatamente o caso das que estao
            # em conflito de IP.
            if time.monotonic() >= proxima_pergunta:
                pacote = _probe()
                for alvo in alvos:
                    try:
                        sock.sendto(pacote, alvo)
                    except OSError:
                        continue
                proxima_pergunta = time.monotonic() + 2.0
            try:
                dados, origem = sock.recvfrom(8192)
            except socket.timeout:
                continue
            except OSError:
                continue
            xml = dados.decode("utf-8", "replace")
            if "ProbeMatch" not in xml:
                continue
            item = {campo: _valor(xml, campo) for campo in _CAMPOS}
            item["MAC"] = _normalizar_mac(item.get("MAC", ""))
            item["origem_pacote"] = origem[0]
            chave = item["MAC"] or f"{origem[0]}:{item.get('DeviceSN')}"
            if chave:
                achados[chave] = item
            if verboso:
                print(f"[+] {chave} respondeu", file=sys.stderr)
        return sorted(achados.values(), key=lambda x: (x.get("IPv4Address") or "", x.get("MAC") or ""))
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _ativada(item: Dict[str, Any]) -> bool:
    return str(item.get("Activated", "")).strip().lower() in ("true", "1", "yes")


def imprimir(itens: List[Dict[str, Any]]) -> None:
    if not itens:
        print("Nenhuma camera respondeu.")
        print()
        print("Se voce SABE que existem cameras aqui, o motivo costuma ser um destes:")
        print("  - a maquina nao esta na mesma rede fisica das cameras (multicast nao passa por roteador)")
        print("  - o Windows Firewall bloqueou a resposta UDP (libere o python.exe na rede privada)")
        print("  - a porta 37020 esta ocupada pelo SADP.exe da Hikvision -- feche ele e rode de novo")
        return

    print(f"{len(itens)} camera(s) responderam\n")
    cab = f"{'IP':<16}{'MAC':<19}{'MODELO':<22}{'SERIAL':<22}{'ESTADO':<20}PORTAS"
    print(cab)
    print("-" * len(cab))
    for i in itens:
        estado = "ativada" if _ativada(i) else ">> PRECISA ATIVAR"
        portas = "/".join(x for x in (i.get("HttpPort"), i.get("CommandPort")) if x)
        print(
            f"{i.get('IPv4Address',''):<16}{i.get('MAC',''):<19}"
            f"{(i.get('DeviceDescription') or i.get('DeviceType') or '')[:21]:<22}"
            f"{(i.get('DeviceSN') or '')[:21]:<22}{estado:<20}{portas}"
        )

    # O valor que o SADP.exe nao da: dizer na cara que ha conflito, e quantas.
    por_ip: Dict[str, List[Dict[str, Any]]] = {}
    for i in itens:
        ip = i.get("IPv4Address") or ""
        if ip:
            por_ip.setdefault(ip, []).append(i)
    conflitos = {ip: lista for ip, lista in por_ip.items() if len(lista) > 1}
    faltam = [i for i in itens if not _ativada(i)]

    print()
    if conflitos:
        for ip, lista in sorted(conflitos.items()):
            print(f"!! CONFLITO: {len(lista)} cameras disputando {ip}")
            for i in lista:
                print(f"     {i.get('MAC')}  {i.get('DeviceSN') or ''}")
        print()
        print("   Em conflito elas se recolhem: nao respondem ping, HTTP nem a porta 8000.")
        print("   So da para ativar uma de cada vez -- as outras precisam estar desligadas,")
        print("   ou entao ative por aqui (proxima fase) e deixe cada uma sair do IP antes da seguinte.")
        print()
    if faltam:
        print(f"-> {len(faltam)} camera(s) ainda precisam ser ativadas.")
    else:
        print("-> Todas ativadas.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Descobre cameras Hikvision na rede local (protocolo SADP).",
    )
    p.add_argument("--segundos", type=float, default=8.0,
                   help="tempo de escuta (padrao 8; use 15 em rede grande)")
    p.add_argument("--json", metavar="ARQUIVO",
                   help="grava o resultado em JSON para o SightOps consumir")
    p.add_argument("-v", "--verboso", action="store_true")
    args = p.parse_args()

    print(f"Perguntando na rede por {args.segundos:.0f}s (multicast {GRUPO_SADP}:{PORTA_SADP} + broadcast)...\n")
    try:
        itens = descobrir(segundos=args.segundos, verboso=args.verboso)
    except Exception as exc:
        print(f"Falhou: {exc}", file=sys.stderr)
        return 1

    imprimir(itens)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"geradoEm": time.strftime("%Y-%m-%dT%H:%M:%S"), "cameras": itens},
                      fh, ensure_ascii=False, indent=2)
        print(f"\nJSON gravado em {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
