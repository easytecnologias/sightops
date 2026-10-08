"""Estado dos tuneis e o caminho ate um equipamento.

A tela de Operacoes perguntava o que voce queria testar. A pergunta que o
operador faz de verdade e outra: **o que esta quebrado agora, e onde**. Estes
dois endpoints respondem isso antes de oferecer ferramenta nenhuma.

MEDICAO, NAO LEMBRANCA

Nada aqui repete campo guardado: a latencia, a perda e o MTU sao medidos na
hora, a cada chamada. O handshake vem do `last_seen` do conector, que o
provisionador deriva do handshake do `wgc` -- nao de ping, que mentiria junto
com a rede.

ICMP SEM ROOT

O container nao tem o binario `ping` (foi por isso que o "ping inteligente"
da tela antiga sempre caia no teste de porta TCP, que acha fechada uma camera
viva). Mas um socket ICMP de datagrama (SOCK_DGRAM + IPPROTO_ICMP) funciona
sem privilegio nenhum, com DF, e e o que o modulo usa -- medido no servidor
antes de escrever isto: payload de 1472 passa, 1600 e recusado pelo kernel.

E assim o MTU vira medicao de verdade: manda pacote cheio com "nao
fragmente" e ve onde corta. Esse e o sintoma que mais confunde no parque --
o tunel parece de pe, o ping comum responde e o video trava, porque o pacote
cheio nao passa.
"""

from __future__ import annotations

import ipaddress
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Query

from app.services import connector_service
from app.services.inventory_json import load_inventory_json

router = APIRouter(prefix="/api/network", tags=["network-map"])


# ── ICMP ──────────────────────────────────────────────────────────────────────

_ICMP_ECHO = 8
# Constantes do Linux: nao estao no modulo socket do Python.
_IP_MTU_DISCOVER = 10
_IP_PMTUDISC_DO = 2  # "nao fragmente" -- sem isto o kernel quebra o pacote e
                     # o teste de MTU aprova qualquer tamanho.


def _ping(destino: str, payload: int = 56, timeout: float = 1.5, df: bool = False) -> Optional[float]:
    """Um eco ICMP. Devolve o tempo em ms, ou None se nao voltou.

    `df` ligado faz o kernel recusar na hora (OSError) quando o pacote nao
    cabe no caminho -- e isso que mede o MTU.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP)
    except OSError:
        return None
    try:
        sock.settimeout(timeout)
        if df:
            try:
                sock.setsockopt(socket.IPPROTO_IP, _IP_MTU_DISCOVER, _IP_PMTUDISC_DO)
            except OSError:
                return None
        # O kernel preenche checksum e identificador num socket de datagrama.
        pacote = struct.pack("!BBHHH", _ICMP_ECHO, 0, 0, 1, 1) + b"\x58" * max(0, payload)
        comeco = time.perf_counter()
        sock.sendto(pacote, (destino, 0))
        sock.recvfrom(4096)
        return round((time.perf_counter() - comeco) * 1000, 1)
    except Exception:
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _latencia_e_perda(destino: str, tentativas: int = 4) -> Tuple[Optional[float], int]:
    """Media das respostas e perda em %. Usa a MEDIA, nao a melhor: o link que
    responde em 30 ms e as vezes em 400 ms e um link ruim, e a melhor resposta
    esconderia isso."""
    tempos = [t for t in (_ping(destino) for _ in range(tentativas)) if t is not None]
    perda = round(100 * (tentativas - len(tempos)) / tentativas)
    if not tempos:
        return None, 100
    return round(sum(tempos) / len(tempos), 1), perda


# Degraus de payload ICMP -> MTU do caminho (payload + 8 de ICMP + 20 de IP).
_DEGRAUS_MTU = (1472, 1422, 1372, 1272, 972, 472)


def _mtu_do_caminho(destino: str) -> Optional[int]:
    """Maior MTU que passa inteiro. None quando o destino nao responde."""
    for payload in _DEGRAUS_MTU:
        if _ping(destino, payload=payload, timeout=1.5, df=True) is not None:
            return payload + 28
    return None


# ── Idade e textos ────────────────────────────────────────────────────────────

def _idade_min(carimbo: Any) -> Optional[float]:
    if not carimbo:
        return None
    try:
        texto = str(carimbo).replace("Z", "+00:00")
        quando = datetime.fromisoformat(texto)
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - quando).total_seconds() / 60.0)
    except Exception:
        return None


def _quanto_faz(minutos: Optional[float]) -> str:
    if minutos is None:
        return "nunca"
    if minutos < 1:
        return "há %d s" % max(1, int(minutos * 60))
    if minutos < 90:
        return "há %d min" % int(minutos)
    if minutos < 48 * 60:
        return "há %d h" % int(minutos / 60)
    return "há %d dias" % int(minutos / 1440)


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


# ── O que esta atras de cada tunel ────────────────────────────────────────────

def _contar_atras() -> Dict[str, Dict[str, int]]:
    """Quantas cameras/OLTs/gravadores dependem de cada conector.

    E a coluna que faltava: "o tunel caiu" nao diz nada; "o tunel caiu e 48
    cameras ficaram sem leitura" diz.
    """
    por_conector: Dict[str, Dict[str, int]] = {}

    def soma(cid: str, campo: str) -> None:
        cid = _texto(cid)
        if not cid:
            return
        por_conector.setdefault(cid, {"cameras": 0, "olts": 0, "gravadores": 0})[campo] += 1

    for modo in ("olt", "basic", "switch"):
        try:
            for linha in load_inventory_json(mode=modo) or []:
                if linha.get("ip"):
                    soma(linha.get("remote_connector_id") or linha.get("connector_id"), "cameras")
        except Exception:
            continue

    try:
        from app.services import olt_registry

        for olt in olt_registry.list_olts(False) or []:
            soma(olt.get("connector_id"), "olts")
    except Exception:
        pass

    try:
        from app.services.db_store import _conn, _current_tenant_slug

        with _conn() as c:
            linhas = c.execute(
                "SELECT source FROM recorders WHERE tenant_slug = ?", (_current_tenant_slug(),)
            ).fetchall()
        # O gravador nao guarda connector_id: a contagem dele fica fora e o
        # front nao mostra numero inventado.
        _ = linhas
    except Exception:
        pass

    return por_conector


def _wg_reportado(linha: Dict[str, Any]) -> str:
    """Endereco do tunel que o PROPRIO MikroTik informa no heartbeat.

    Deduzir pelo indice de isolamento nao serve: conector antigo vive em
    10.250.0.x e so os novos em 10.201.0.x -- quem sabe e o roteador.
    """
    inv = linha.get("inventory") if isinstance(linha.get("inventory"), dict) else {}
    for parte in _texto(inv.get("address_sample")).split(";"):
        if "|" not in parte:
            continue
        endereco, _, interface = parte.partition("|")
        if "wg" in interface.lower():
            return endereco.split("/")[0].strip()
    return ""


def _equipamentos_por_conector() -> Dict[str, List[str]]:
    """IPs de equipamento de cada conector, da OLT para a camera.

    A OLT vem primeiro porque e o que menos sai do ar: medir o tunel por uma
    camera que o cliente desligou daria "tunel ruim" sem tunel ruim nenhum.
    """
    mapa: Dict[str, List[str]] = {}
    try:
        from app.services import olt_registry

        for olt in olt_registry.list_olts(False) or []:
            cid = _texto(olt.get("connector_id"))
            ip = _texto(olt.get("host"))
            if cid and ip:
                mapa.setdefault(cid, []).append(ip)
    except Exception:
        pass
    for modo in ("olt", "basic", "switch"):
        try:
            for linha in load_inventory_json(mode=modo) or []:
                cid = _texto(linha.get("remote_connector_id") or linha.get("connector_id"))
                ip = _texto(linha.get("ip"))
                if cid and ip and len(mapa.setdefault(cid, [])) < 6:
                    mapa[cid].append(ip)
        except Exception:
            continue
    return mapa


def _alvo_de_referencia(linha: Dict[str, Any], equipamentos: Dict[str, List[str]]) -> Tuple[str, str]:
    """(endereco a medir, o que ele e). Vazio quando nao ha o que medir."""
    cid = _texto(linha.get("id"))
    try:
        from app.api.endpoints.maintenance import _reach
    except Exception:
        _reach = lambda ip, c="": ip  # noqa: E731

    # Testa ate achar um que responda: parar no primeiro da lista fazia o
    # silencio de UM aparelho (a OLT, que vem primeiro) valer como silencio
    # do site inteiro.
    candidatos = [(_reach(ip, cid) or ip) for ip in (equipamentos.get(cid) or [])[:5]]
    for alvo in candidatos:
        if alvo and _ping(alvo, timeout=1.2) is not None:
            return alvo, "equipamento do site"

    wg = _wg_reportado(linha)
    if wg and _ping(wg, timeout=1.2) is not None:
        return wg, "MikroTik, pelo túnel"
    # Ninguem respondeu. Devolve o primeiro candidato assim mesmo, para a
    # medicao registrar a perda em cima de um alvo com nome -- e nao sumir.
    if candidatos:
        return candidatos[0], "equipamento do site"
    if wg:
        return wg, "MikroTik, pelo túnel"
    return "", ""


# ── GET /api/network/tunnels ──────────────────────────────────────────────────

@router.get("/tunnels")
def api_network_tunnels(medir: bool = Query(True)) -> Dict[str, Any]:
    """Estado de todos os tuneis do cliente, medido agora."""
    conectores = (connector_service.list_connectors() or {}).get("connectors", []) or []
    atras = _contar_atras()
    equipamentos = _equipamentos_por_conector()

    def um(linha: Dict[str, Any]) -> Dict[str, Any]:
        cid = _texto(linha.get("id"))
        transito, tipo_alvo = _alvo_de_referencia(linha, equipamentos)
        idade = _idade_min(linha.get("last_seen"))
        de_pe = _texto(linha.get("status")).lower() == "online"

        latencia: Optional[float] = None
        perda: Optional[int] = None
        mtu: Optional[int] = None
        # Sem handshake nao ha o que medir, e insistir so gasta timeout: o
        # caminho inteiro esta fechado, nao so o equipamento.
        if medir and de_pe and transito:
            latencia, perda = _latencia_e_perda(transito)
            if latencia is not None:
                mtu = _mtu_do_caminho(transito)

        avisos: List[str] = []
        if not de_pe:
            avisos.append("sem handshake " + _quanto_faz(idade))
        elif not transito:
            # Nao e queda: e que nao ha equipamento cadastrado para medir.
            # Dizer "offline" aqui seria a mentira que esta tela combate.
            avisos.append("nada cadastrado atrás deste túnel para medir")
        elif perda is not None and perda >= 100:
            # Sem equipamento, o alvo e o proprio MikroTik -- e RouterOS costuma
            # bloquear ping no input. Dizer "caiu" com essa evidencia seria
            # chutar; o texto conta o que foi medido e o que isso pode ser.
            avisos.append(
                "o MikroTik não responde a ping dentro do túnel (pode ser firewall)"
                if tipo_alvo.startswith("MikroTik")
                else "o túnel está de pé, mas nada do site responde"
            )
        elif perda:
            avisos.append("perdendo %d%% dos pacotes" % perda)
        if mtu is not None and mtu < 1400:
            avisos.append("o pacote cheio não passa (MTU %d)" % mtu)

        conta = atras.get(cid) or {}
        return {
            "id": cid,
            "name": _texto(linha.get("name")) or cid,
            "site": _texto(linha.get("site")),
            "client": _texto(linha.get("client")),
            "status": _texto(linha.get("status")),
            "last_seen": linha.get("last_seen"),
            "handshake_min": idade,
            "handshake_texto": _quanto_faz(idade),
            "medido_em_ip": transito,
            "medido_em": tipo_alvo,
            "modelo": _texto((linha.get("host") or {}).get("model")) if isinstance(linha.get("host"), dict) else "",
            "latencia_ms": latencia,
            "perda_pct": perda,
            "mtu": mtu,
            "atras": {
                "cameras": conta.get("cameras", 0),
                "olts": conta.get("olts", 0),
            },
            "avisos": avisos,
        }

    # Em paralelo: 13 tuneis em serie seriam ~13x o tempo de um, e a tela
    # inteira depende desta chamada.
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(conectores)))) as pool:
        itens = list(pool.map(um, conectores))

    itens.sort(key=lambda x: (x["status"] == "online", -(x["handshake_min"] or 0)))
    de_pe = sum(1 for x in itens if x["status"] == "online")
    instaveis = sum(1 for x in itens if x["status"] == "online" and x["avisos"])
    return {
        "ok": True,
        "medido_em": datetime.now(timezone.utc).isoformat(),
        "total": len(itens),
        "de_pe": de_pe,
        "caiu": len(itens) - de_pe,
        "instavel": instaveis,
        "equipamentos": sum(x["atras"]["cameras"] + x["atras"]["olts"] for x in itens),
        "items": itens,
    }


# ── GET /api/network/path ─────────────────────────────────────────────────────

def _salto(nome: str, detalhe: str, estado: str, ms: Optional[float] = None, nota: str = "") -> Dict[str, Any]:
    return {"nome": nome, "detalhe": detalhe, "estado": estado, "ms": ms, "nota": nota}


@router.get("/path")
def api_network_path(
    connector_id: str = Query(""),
    ip: str = Query(""),
) -> Dict[str, Any]:
    """O caminho inteiro ate o equipamento, salto a salto.

    O primeiro salto que falha e o culpado; os de baixo saem como "nao
    medido" em vez de "offline". Marcar como caido o que esta atras de um
    tunel fechado seria inventar: o sistema nao sabe se caiu, sabe que nao
    consegue perguntar.
    """
    cid = _texto(connector_id)
    alvo_real = _texto(ip)

    linha = connector_service.get_connector(cid, enforce_tenant=True) if cid else None
    if not linha:
        return {"ok": False, "error": "conector não encontrado"}

    transito, _tipo = _alvo_de_referencia(linha, _equipamentos_por_conector())
    de_pe = _texto(linha.get("status")).lower() == "online"
    idade = _idade_min(linha.get("last_seen"))
    saltos: List[Dict[str, Any]] = [
        _salto("Servidor SightOps", "interface do túnel de pé", "ok", 0.1),
    ]

    if not de_pe:
        saltos.append(_salto(
            "Handshake do WireGuard",
            "%s · último handshake %s" % (_texto(linha.get("name")), _quanto_faz(idade)),
            "falhou",
            nota="O endereço público pode até responder, mas a chave não fecha a sessão. "
                 "Quando isso aconteceu antes, era o NAT da operadora trocando a porta de origem: "
                 "o MikroTik segue mandando para uma porta que não existe mais.",
        ))
        saltos.append(_salto("Rede do site", transito or "—", "nao_medido",
                             nota="não dá para tentar sem o túnel"))
        saltos.append(_salto("Equipamento", alvo_real or "—", "nao_medido"))
        return {"ok": True, "conector": _texto(linha.get("name")), "quebrou_em": 1, "saltos": saltos}

    saltos.append(_salto("Handshake do WireGuard",
                         "%s · %s" % (_texto(linha.get("name")), _quanto_faz(idade)), "ok"))

    if not transito:
        saltos.append(_salto("Rede do site", "—", "nao_medido",
                             nota="Não há equipamento cadastrado neste conector para medir o caminho."))
        return {"ok": True, "conector": _texto(linha.get("name")), "quebrou_em": -1, "saltos": saltos}

    ms_mk, perda_mk = _latencia_e_perda(transito)
    if ms_mk is None:
        saltos.append(_salto("Rede do site", transito, "falhou",
                             nota="O túnel fechou, mas o roteador do outro lado não responde dentro dele. "
                                  "Costuma ser rota de volta faltando ou regra de firewall no MikroTik."))
        saltos.append(_salto("Equipamento", alvo_real or "—", "nao_medido"))
        return {"ok": True, "conector": _texto(linha.get("name")), "quebrou_em": 2, "saltos": saltos}

    mtu = _mtu_do_caminho(transito)
    saltos.append(_salto("Rede do site", transito, "ok", ms_mk,
                         nota=("Pacote cheio não passa: MTU de %d. O túnel parece de pé e o vídeo trava." % mtu)
                              if (mtu is not None and mtu < 1400) else ""))

    # Equipamento: em conector isolado so o IP virtual alcanca. Testar o real
    # devolve "No route to host" e parece queda -- e nao e.
    virtual = alvo_real
    try:
        from app.api.endpoints.maintenance import _reach

        virtual = _reach(alvo_real, cid) if alvo_real else ""
    except Exception:
        pass

    if alvo_real:
        ms_eq, perda_eq = _latencia_e_perda(virtual or alvo_real, tentativas=3)
        saltos.append(_salto(
            "Equipamento",
            (virtual or alvo_real) + ((" · real %s" % alvo_real) if virtual and virtual != alvo_real else ""),
            "ok" if ms_eq is not None else "falhou",
            ms_eq,
            nota="" if ms_eq is not None else
                 "O caminho inteiro até o site está de pé. O que não responde é o equipamento.",
        ))

    quebrou = next((i for i, s in enumerate(saltos) if s["estado"] == "falhou"), -1)
    return {
        "ok": True,
        "conector": _texto(linha.get("name")),
        "quebrou_em": quebrou,
        "mtu": mtu,
        "ip_real": alvo_real,
        "ip_virtual": virtual if virtual != alvo_real else "",
        "saltos": saltos,
    }
