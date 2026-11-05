"""Para onde a API pode abrir conexao em nome de um cliente.

Ferramentas de rede, varredura de portas, snapshot, video e os lotes de
manutencao recebem o IP do navegador. Sem uma regra unica, o cliente A
digitava o IP VIRTUAL (vnat) de um conector do cliente B -- o host faz o
NETMAP e o pacote cai na LAN do B -- ou apontava a API para ela mesma
(127.0.0.1, rede do Docker, metadados link-local).

`destino_permitido(tenant_slug, ip)` e a regra unica. Recusa SEMPRE (em
qualquer modo de permissao):
  - loopback, link-local, nao especificado, multicast, reservado (inclui o
    IP_BLOQUEADO 240.0.0.1 que o vnat devolve para conector de outro cliente);
  - redes do Docker/host vistas pelo container (rotas diretas em
    /proc/net/route) e as de DESTINO_REDES_BLOQUEADAS (CIDRs, virgula);
  - IP dentro da faixa VIRTUAL de conector de outro cliente.
E exige dono para IP nao publico: equipamento do inventario do cliente,
LAN de conector do cliente ou faixa virtual de conector do cliente.
IP publico (internet) passa: nao e rede de cliente nenhum.

Sem cliente no contexto (tarefa de fundo, autenticacao desligada) so as
recusas fixas valem -- mesmo criterio de `_conector_do_cliente` no vnat.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
from typing import Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)

_BLOCO_MAXIMO = 4096  # acima disto a varredura nao confere IP por IP

_Rede = ipaddress._BaseNetwork


def _redes_de_texto(texto: str) -> List[_Rede]:
    redes: List[_Rede] = []
    for parte in str(texto or "").replace(";", ",").split(","):
        parte = parte.strip()
        if not parte:
            continue
        try:
            redes.append(ipaddress.ip_network(parte, strict=False))
        except ValueError:
            logger.warning("destino: CIDR invalido em DESTINO_REDES_BLOQUEADAS: %r", parte)
    return redes


def _redes_do_container(caminho: str = "/proc/net/route") -> List[_Rede]:
    """Redes ligadas direto as interfaces do container (rede do Docker) e o
    gateway (o host). Fora do Linux o arquivo nao existe: lista vazia."""
    redes: List[_Rede] = []
    try:
        with open(caminho, encoding="ascii") as fh:
            linhas = fh.read().splitlines()[1:]
    except OSError:
        return redes
    for linha in linhas:
        campos = linha.split()
        if len(campos) < 8 or campos[0] == "lo":
            continue
        try:
            destino = socket.inet_ntoa(int(campos[1], 16).to_bytes(4, "little"))
            gateway = socket.inet_ntoa(int(campos[2], 16).to_bytes(4, "little"))
            mascara = socket.inet_ntoa(int(campos[7], 16).to_bytes(4, "little"))
        except (ValueError, OverflowError, OSError):
            continue
        if destino != "0.0.0.0" and gateway == "0.0.0.0":
            redes.append(ipaddress.ip_network(f"{destino}/{mascara}", strict=False))
        elif destino == "0.0.0.0" and gateway != "0.0.0.0":
            redes.append(ipaddress.ip_network(f"{gateway}/32"))
    return redes


def redes_bloqueadas() -> List[_Rede]:
    return _redes_do_container() + _redes_de_texto(os.getenv("DESTINO_REDES_BLOQUEADAS", ""))


def _motivo_fixo(ip: ipaddress._BaseAddress, bloqueadas: Iterable[_Rede]) -> str:
    if ip.is_loopback:
        return "loopback nao e destino de equipamento"
    if ip.is_link_local:
        return "link-local nao e destino de equipamento"
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return "endereco reservado: destino recusado"
    for rede in bloqueadas:
        if ip.version == rede.version and ip in rede:
            return "rede interna do servidor: destino recusado"
    return ""


class _Contexto:
    """O que se sabe do cliente, carregado uma vez por chamada (um lote de
    1024 IPs nao rele o arquivo de conectores 1024 vezes)."""

    def __init__(self, tenant_slug: str) -> None:
        self.slug = str(tenant_slug or "").strip().lower()
        self.bloqueadas = redes_bloqueadas()
        self.virtuais: List[Tuple[_Rede, str]] = []  # (faixa virtual, conector)
        self.meus: set = set()
        self.minhas_redes: List[_Rede] = []
        self._inventario: Dict[str, bool] = {}
        try:
            from app.services import connector_routing_vnat as vnat
            mapa = vnat._load_map() or {}
        except Exception as exc:
            logger.warning("destino: mapa do vnat ilegivel (%s) -- faixas virtuais sem dono conhecido", exc)
            mapa = {}
        for cid, pares in mapa.items():
            for _real, virt in pares:
                self.virtuais.append((virt, str(cid)))
        if not self.slug:
            return
        try:
            from app.services import connector_service as cs
            linhas = [r for r in cs._load_connectors() if isinstance(r, dict)
                      and str(r.get("tenant_slug") or "").strip().lower() == self.slug]
        except Exception as exc:
            logger.warning("destino: conectores do cliente %s ilegiveis (%s)", self.slug, exc)
            linhas = []
        for row in linhas:
            cid = str(row.get("id") or "").strip()
            if cid:
                self.meus.add(cid)
            try:
                lans = cs._extract_connector_lans(row)
            except Exception as exc:
                logger.warning("destino: LANs do conector %s ilegiveis (%s)", cid, exc)
                lans = []
            for cidr in lans:
                try:
                    self.minhas_redes.append(ipaddress.ip_network(str(cidr), strict=False))
                except ValueError:
                    continue
            for real, _virt in mapa.get(cid, []):
                self.minhas_redes.append(real)

    def _no_inventario(self, ip: str) -> bool:
        if ip not in self._inventario:
            try:
                from app.core.tenant_context import get_current_tenant_slug
                if get_current_tenant_slug() != self.slug:
                    # o inventario e lido pelo contexto: outro cliente, nao confere
                    self._inventario[ip] = False
                else:
                    from app.api.endpoints.maintenance import _ip_belongs_to_current_tenant
                    self._inventario[ip] = bool(_ip_belongs_to_current_tenant(ip))
            except Exception as exc:
                logger.warning("destino: inventario do cliente %s ilegivel para %s (%s)", self.slug, ip, exc)
                self._inventario[ip] = False
        return self._inventario[ip]

    def conferir_ip(self, ip: ipaddress._BaseAddress, exigir_dono: bool = True) -> str:
        motivo = _motivo_fixo(ip, self.bloqueadas)
        if motivo:
            return motivo
        for virt, cid in self.virtuais:
            if ip.version == virt.version and ip in virt:
                if not self.slug or cid in self.meus:
                    return ""
                return "IP virtual de conector de outro cliente"
        if ip.is_global or not self.slug or not exigir_dono:
            return ""
        for rede in self.minhas_redes:
            if ip.version == rede.version and ip in rede:
                return ""
        if self._no_inventario(str(ip)):
            return ""
        return "IP nao pertence a equipamento nem rede deste cliente"

    def dentro_de_rede_minha(self, inicio: int, fim: int) -> bool:
        """Bloco inteiro numa LAN/faixa virtual do cliente, sem tocar faixa
        alheia nem rede interna (bloco grande demais para olhar IP por IP)."""
        minhas = self.minhas_redes + [v for v, cid in self.virtuais if cid in self.meus]
        if not any(int(r.network_address) <= inicio and fim <= int(r.broadcast_address) for r in minhas):
            return False
        alheias = list(self.bloqueadas) + [v for v, cid in self.virtuais if cid not in self.meus]
        return not any(inicio <= int(r.broadcast_address) and int(r.network_address) <= fim for r in alheias)

    def conferir_bloco(self, inicio: int, fim: int, exigir_dono: bool) -> str:
        if fim - inicio >= _BLOCO_MAXIMO:
            return "" if self.dentro_de_rede_minha(inicio, fim) else "faixa grande demais fora das redes deste cliente"
        for valor in range(inicio, fim + 1):
            ip = ipaddress.ip_address(valor)
            motivo = self.conferir_ip(ip, exigir_dono)
            if motivo:
                return f"{ip}: {motivo}"
        return ""

    def conferir_varredura(self, alvo: str, exigir_dono: bool) -> str:
        for item in re.split(r"[,;\s]+", str(alvo or "").strip()):
            if not item:
                continue
            item = re.sub(r"^(\d+\.\d+\.\d+\.\d+):\d+$", r"\1", item)  # IP:PORTA (NAT)
            try:
                if "/" in item:
                    rede = ipaddress.ip_network(item, strict=False)
                    motivo = self.conferir_bloco(int(rede.network_address), int(rede.broadcast_address), exigir_dono)
                elif "-" in item:
                    esquerda, direita = [p.strip() for p in item.split("-", 1)]
                    fim = direita if "." in direita else f"{esquerda.rsplit('.', 1)[0]}.{direita}"
                    limites = sorted((int(ipaddress.ip_address(esquerda)), int(ipaddress.ip_address(fim))))
                    motivo = self.conferir_bloco(limites[0], limites[1], exigir_dono)
                else:
                    motivo = self.conferir(item, exigir_dono)
            except ValueError:
                motivo = "alvo invalido"
            if motivo:
                return f"{item}: {motivo}"
        return ""

    def conferir(self, alvo: str, exigir_dono: bool = True) -> str:
        alvo = str(alvo or "").strip().strip("[]")
        if not alvo:
            return "destino vazio"
        try:
            enderecos = [ipaddress.ip_address(alvo)]
        except ValueError:
            try:
                infos = socket.getaddrinfo(alvo, None)
                enderecos = list({ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos if i and i[4]})
            except (OSError, ValueError, UnicodeError) as exc:
                return f"nome nao resolvido ({exc})"
            if not enderecos:
                return "nome nao resolvido"
        for ip in enderecos:
            motivo = self.conferir_ip(ip, exigir_dono)
            if motivo:
                return motivo
        return ""


def destinos_permitidos(tenant_slug: str, alvos: Iterable[str]) -> Tuple[List[str], Dict[str, str]]:
    """(permitidos na ordem de entrada, {recusado: motivo})."""
    ctx = _Contexto(tenant_slug)
    ok: List[str] = []
    recusados: Dict[str, str] = {}
    for alvo in alvos:
        motivo = ctx.conferir(alvo)
        if motivo:
            recusados[str(alvo)] = motivo
        else:
            ok.append(alvo)
    if recusados:
        amostra = ", ".join(f"{k} ({v})" for k, v in list(recusados.items())[:5])
        logger.warning("destino: cliente %s, %d destino(s) recusado(s): %s",
                       tenant_slug or "(sem cliente)", len(recusados), amostra)
    return ok, recusados


def destino_permitido(tenant_slug: str, ip: str) -> Tuple[bool, str]:
    """(pode, motivo). Ver o docstring do modulo."""
    _ok, recusados = destinos_permitidos(tenant_slug, [ip])
    motivo = recusados.get(str(ip), "")
    return (not motivo), motivo


def destino_permitido_atual(ip: str) -> Tuple[bool, str]:
    """Atalho com o cliente do contexto da requisicao."""
    from app.core.tenant_context import get_current_tenant_slug
    return destino_permitido(get_current_tenant_slug(), ip)


def varredura_recusada(tenant_slug: str, alvo: str, exigir_dono: bool = True) -> str:
    """Motivo para recusar a varredura de `alvo` (IP, CIDR, faixa, lista); "" =
    pode. Um destino recusado derruba a varredura inteira: ela grava inventario
    e tenta senha padrao em quem responder. `exigir_dono=False` e para a
    varredura que sai do MikroTik do proprio cliente: a LAN pode nem ter sido
    coletada ainda, mas destino interno ou faixa alheia continuam recusados."""
    motivo = _Contexto(tenant_slug).conferir_varredura(alvo, exigir_dono)
    if motivo:
        logger.warning("destino: cliente %s, varredura recusada: %s", tenant_slug or "(sem cliente)", motivo)
    return motivo


def sem_faixa_virtual_alheia(tenant_slug: str, linhas: List[Dict]) -> List[Dict]:
    """Tira do inventario a linha cujo IP e da faixa virtual de conector de
    outro cliente: IP gravado vira posse em toda conferencia por inventario."""
    if not tenant_slug or not linhas:
        return linhas
    ctx = _Contexto(tenant_slug)
    saida: List[Dict] = []
    for linha in linhas:
        bruto = str((linha or {}).get("ip") or "").strip() if isinstance(linha, dict) else ""
        try:
            ip = ipaddress.ip_address(re.sub(r":\d+$", "", bruto))
        except ValueError:
            saida.append(linha)
            continue
        if any(ip.version == v.version and ip in v and cid not in ctx.meus for v, cid in ctx.virtuais):
            logger.warning("destino: cliente %s tentou gravar %s, faixa virtual de outro cliente", tenant_slug, bruto)
            continue
        saida.append(linha)
    return saida


__all__ = ["destino_permitido", "destinos_permitidos", "destino_permitido_atual", "redes_bloqueadas",
           "sem_faixa_virtual_alheia", "varredura_recusada"]
