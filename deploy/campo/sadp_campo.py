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
import select
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


def _ips_locais() -> List[str]:
    """Todos os IPv4 desta maquina, sem loopback."""
    saida: List[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in saida:
                saida.append(ip)
    except Exception:
        pass
    return saida


def _broadcast_de(ip: str) -> str:
    partes = ip.split(".")
    return ".".join(partes[:3]) + ".255" if len(partes) == 4 else "255.255.255.255"


def _abrir(ip: str) -> socket.socket | None:
    """Um socket preso a UMA interface. Preso de proposito: num notebook com
    Wi-Fi + VPN + Hyper-V, um socket solto manda tudo pela rota padrao -- e
    se a rota padrao for a VPN (foi o caso no NOTEBOOK-EASY, PPP com metrica
    46), a pergunta entra no tunel e nunca chega na rede das cameras."""
    for porta in PORTAS_DE_ESCUTA:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind((ip, porta))
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                s.setsockopt(
                    socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                    struct.pack("4s4s", socket.inet_aton(GRUPO_SADP), socket.inet_aton(ip)),
                )
            except OSError:
                pass
            return s
        except OSError:
            continue
    return None


def descobrir(segundos: float = 8.0, verboso: bool = False,
              origens: List[str] | None = None) -> List[Dict[str, Any]]:
    """Pergunta por TODAS as interfaces e junta quem responder.

    Uma interface que recusa nao interrompe as outras: numa maquina com VPN e
    adaptadores virtuais varias recusam, e desistir na primeira deixaria a
    varredura vazia sem motivo.
    """
    ips = origens or _ips_locais()
    if not ips:
        raise RuntimeError("nao encontrei nenhum IPv4 nesta maquina")

    socks: List[tuple[str, socket.socket]] = []
    for ip in ips:
        s = _abrir(ip)
        if s is not None:
            socks.append((ip, s))
            if verboso:
                print(f"[i] perguntando por {ip} (porta {s.getsockname()[1]})", file=sys.stderr)
        elif verboso:
            print(f"[i] {ip}: nao consegui abrir socket", file=sys.stderr)
    if not socks:
        raise RuntimeError("nao consegui abrir socket UDP em nenhuma interface")

    try:
        achados: Dict[str, Dict[str, Any]] = {}
        fim = time.monotonic() + segundos
        proxima_pergunta = 0.0

        while time.monotonic() < fim:
            # Repergunta a cada 2s: camera que estava reiniciando no primeiro
            # pacote responde no segundo, e e exatamente o caso das que estao
            # em conflito de IP.
            if time.monotonic() >= proxima_pergunta:
                pacote = _probe()
                for ip, s in socks:
                    for alvo in ((GRUPO_SADP, PORTA_SADP), (_broadcast_de(ip), PORTA_SADP),
                                 ("255.255.255.255", PORTA_SADP)):
                        try:
                            s.sendto(pacote, alvo)
                        except OSError:
                            continue
                proxima_pergunta = time.monotonic() + 2.0

            prontos, _, _ = select.select([s for _, s in socks], [], [], 0.5)
            for s in prontos:
                try:
                    dados, origem = s.recvfrom(8192)
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
        for _, s in socks:
            try:
                s.close()
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
        print()
        print("ATENCAO: estar numa VPN do site NAO e estar na rede das cameras. Multicast nao")
        print("atravessa tunel. Para esta descoberta funcionar, a maquina precisa estar ligada")
        print("no MESMO switch das cameras. Interfaces usadas nesta tentativa:")
        for ip in (_ips_locais() or ["(nenhuma)"]):
            print("   ", ip)
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
    p.add_argument("--origem", action="append", metavar="IP",
                   help="manda a pergunta SO por este IP local (repetivel). "
                        "Use quando houver VPN ativa roubando a rota padrao.")
    p.add_argument("-v", "--verboso", action="store_true")
    args = p.parse_args()

    print(f"Perguntando na rede por {args.segundos:.0f}s (multicast {GRUPO_SADP}:{PORTA_SADP} + broadcast)...\n")
    try:
        itens = descobrir(segundos=args.segundos, verboso=args.verboso, origens=args.origem)
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
