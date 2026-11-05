"""Trava de saida: nenhuma conexao TCP do processo vai ao IP REAL de LAN de
conector isolado.

O host tem rota para essas LANs pelo wg-sightops (17 delas medidas em
05/11/2026), entao conectar no IP real nao da "No route": cai no tunel de outro
cliente. A regra de destino (app.core.destino) confere as rotas; esta trava fica
no ponto em que o pacote nasce e pega o que nenhuma rota conferiu, inclusive
lacos de fundo, que rodam sem cliente no contexto.

Intercepta socket.socket.connect/connect_ex, por onde passam requests, urllib3,
http.client, telnetlib, paramiko e o asyncio (laco padrao; o uvicorn daqui nao
usa uvloop). NAO alcanca subprocesso (ffmpeg, ping, nmap) nem o go2rtc, que tem
processo proprio; nem connect() com nome (quem conecta resolve antes e passa IP).

Com cliente no contexto, recusa tambem a faixa VIRTUAL de conector de outro
cliente: redirect (302) ou DNS rebinding levariam a conexao para la depois de a
rota conferir o destino. Sem cliente (lacos internos), a faixa virtual passa.

Fica de fora (nunca recusado):
  - loopback e redes ligadas direto ao container (/proc/net/route, gateway
    0.0.0.0): a bridge do Docker pode sobrepor uma LAN de cliente, e nesse caso
    o pacote fica na bridge;
  - IP dos servicos configurados: nomes e URLs do ambiente e das configuracoes
    (go2rtc, postgres, zabbix, grafana, evolution...);
  - CIDRs de SIGHTOPS_SAIDA_PERMITIDA (virgula).

SIGHTOPS_SAIDA_MODO: "aviso" (padrao, so loga), "valer" (recusa) ou "desligado".
"""
from __future__ import annotations

import errno
import ipaddress
import logging
import os
import re
import socket
import threading
import time
import traceback
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlsplit

from app.core.tenant_context import get_current_tenant_slug

logger = logging.getLogger(__name__)

_RECARGA_S = 60.0     # LANs do mapa vnat (ou antes, se o arquivo mudou: _load_map confere)
_NOMES_S = 300.0      # nomes de servico: resolver custa DNS
_AVISO_S = 600.0      # mesmo destino + mesma origem: um aviso a cada 10 min
_NOMES_PADRAO = ("go2rtc", "postgres", "sightops-v3-postgres", "zabbix", "zabbix-web", "zabbix-server",
                 "grafana", "evolution", "evolution-api")
_URLS_PADRAO = ("http://10.10.12.7:8090",)  # Evolution, padrao de access_control_notifications

_Rede = ipaddress._BaseNetwork
_connect_original = None
_connect_ex_original = None


class SaidaRecusada(ConnectionRefusedError):
    """OSError de proposito: quem conecta ja trata como "nao alcancou"."""


class _Estado:
    __slots__ = ("reais", "virtuais", "excecoes", "ips", "decidido")

    def __init__(self, reais: List[_Rede], excecoes: List[_Rede], ips: FrozenSet[str],
                 virtuais: Optional[List[Tuple[_Rede, str]]] = None) -> None:
        self.reais = reais
        self.virtuais = virtuais or []  # (faixa virtual, cliente dono)
        self.excecoes = excecoes
        self.ips = ips
        # ip -> (LAN real?, dono da faixa virtual ou None). Caminho quente.
        self.decidido: Dict[str, Tuple[bool, Optional[str]]] = {}


_estado: Optional[_Estado] = None
_recarga_em = 0.0
_nomes_em = 0.0
_ips_servico: FrozenSet[str] = frozenset()
_recarregando = threading.Lock()
_ultimo_aviso: Dict[Tuple[str, str], float] = {}


def _modo() -> str:
    modo = os.getenv("SIGHTOPS_SAIDA_MODO", "aviso").strip().lower()
    return modo if modo in ("valer", "aviso", "desligado") else "aviso"


def _hosts_do_ambiente() -> Set[str]:
    """Hosts em variaveis *_URL/*_HOST/*_HOSTS e em qualquer valor com "://"."""
    hosts: Set[str] = set()
    for nome, valor in os.environ.items():
        valor = str(valor or "").strip()
        if not valor:
            continue
        if "://" in valor:
            hosts.update(_host_de_url(u) for u in re.split(r"[,;\s]+", valor) if "://" in u)
        elif re.search(r"(_HOST|_HOSTS|_ADDR|_SERVER)$", nome):
            hosts.update(h.split(":")[0].strip() for h in re.split(r"[,;\s]+", valor))
    return hosts


def _host_de_url(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _urls_em(valor: object, saida: Set[str], fundo: int = 0) -> None:
    if fundo > 8:
        return
    if isinstance(valor, dict):
        for v in valor.values():
            _urls_em(v, saida, fundo + 1)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            _urls_em(v, saida, fundo + 1)
    elif isinstance(valor, str) and "://" in valor and len(valor) < 500:
        saida.add(_host_de_url(valor.strip()))


def _hosts_das_configuracoes() -> Set[str]:
    hosts: Set[str] = set()
    try:
        from app.services.db_store import load_app_settings
        _urls_em(load_app_settings(), hosts)
    except Exception as exc:
        logger.warning("saida: configuracoes ilegiveis, servicos so pelo ambiente (%s)", exc)
    return hosts


def _nomes_de_servico() -> Set[str]:
    return (set(_NOMES_PADRAO) | {_host_de_url(u) for u in _URLS_PADRAO}
            | _hosts_do_ambiente() | _hosts_das_configuracoes()) - {""}


def _resolver(nomes: Iterable[str]) -> Set[str]:
    ips: Set[str] = set()
    for nome in nomes:
        try:
            ips.add(str(ipaddress.ip_address(nome)))
            continue
        except ValueError:
            pass
        try:
            ips.update(i[4][0].split("%")[0] for i in socket.getaddrinfo(nome, None, proto=socket.IPPROTO_TCP))
        except (OSError, UnicodeError):
            continue  # nome que nao existe nesta instalacao: normal
    return ips


def _permitidas() -> List[_Rede]:
    redes: List[_Rede] = []
    for parte in re.split(r"[,;\s]+", os.getenv("SIGHTOPS_SAIDA_PERMITIDA", "")):
        if parte:
            try:
                redes.append(ipaddress.ip_network(parte, strict=False))
            except ValueError:
                logger.warning("saida: CIDR invalido em SIGHTOPS_SAIDA_PERMITIDA: %r", parte)
    return redes


def _redes_do_mapa() -> Tuple[List[_Rede], List[Tuple[_Rede, str]]]:
    """(LANs reais, [(faixa virtual, cliente dono)]). Faixa de conector sem
    cadastro fica com dono "": alheia a todo cliente."""
    from app.services import connector_routing_vnat as vnat
    from app.services import connector_service as cs
    mapa = vnat._load_map() or {}
    if not mapa:
        return [], []
    donos = {str(r.get("id") or "").strip(): str(r.get("tenant_slug") or "").strip().lower()
             for r in cs._load_connectors() if isinstance(r, dict)}
    reais = list({real for pares in mapa.values() for real, _virt in pares})
    return reais, [(virt, donos.get(str(cid).strip(), "")) for cid, pares in mapa.items() for _real, virt in pares]


def recarregar(com_nomes: bool = True) -> None:
    """Monta o estado novo e troca de uma vez; quem esta conectando le o antigo."""
    global _estado, _recarga_em, _nomes_em, _ips_servico
    from app.core.destino import _redes_do_container
    if com_nomes:
        # Nome que parou de resolver nao tira o IP de servico: DNS instavel nao
        # pode derrubar o Zabbix em modo valer.
        _ips_servico = _ips_servico | frozenset(_resolver(_nomes_de_servico()))
        _nomes_em = time.monotonic() + _NOMES_S
    reais, virtuais = _redes_do_mapa()
    if not reais and _estado is not None and _estado.reais:
        # Mapa vazio ou ilegivel (o _load_map devolve {} nos dois casos) nao
        # esvazia a trava: segue a ultima lista boa.
        logger.warning("saida: mapa vnat vazio ou ilegivel, segue a lista anterior")
        reais, virtuais = _estado.reais, _estado.virtuais
    _estado = _Estado(reais, _redes_do_container() + _permitidas(), _ips_servico, virtuais)
    _recarga_em = time.monotonic() + _RECARGA_S


def _recarregar_em_fundo() -> None:
    try:
        recarregar(com_nomes=time.monotonic() >= _nomes_em)
    except Exception as exc:
        logger.warning("saida: nao consegui recarregar as LANs, segue a lista anterior (%s)", exc)
    finally:
        _recarregando.release()


def _disparar_recarga() -> None:
    """Quem chama ja tem _recarregando. Falha ao abrir a thread (limite do SO)
    nao pode subir para o connect de ninguem nem deixar o lock preso."""
    try:
        threading.Thread(target=_recarregar_em_fundo, name="saida-recarga", daemon=True).start()
    except RuntimeError as exc:
        _recarregando.release()
        logger.warning("saida: nao consegui abrir a recarga, segue a lista anterior (%s)", exc)


def _talvez_recarregar() -> None:
    global _recarga_em
    if time.monotonic() < _recarga_em or not _recarregando.acquire(blocking=False):
        return
    _recarga_em = time.monotonic() + _RECARGA_S  # um pedido por janela, mesmo com falha
    _disparar_recarga()


def _classificar(estado: _Estado, host: str) -> Tuple[bool, Optional[str]]:
    achado = estado.decidido.get(host)
    if achado is not None:
        return achado
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False, None  # nome: quem conecta resolve antes; aqui nao se consulta DNS
    resposta: Tuple[bool, Optional[str]] = (False, None)
    if not ip.is_loopback and host not in estado.ips and not any(ip in r for r in estado.excecoes):
        dono = next((d for v, d in estado.virtuais if ip in v), None)
        resposta = (any(ip in r for r in estado.reais), dono)
    if len(estado.decidido) < 65536:
        estado.decidido[host] = resposta
    return resposta


def _motivo(host: str) -> str:
    estado = _estado
    if estado is None:
        return ""  # sem estado ainda, nada
    real, dono = _classificar(estado, host)
    if real:
        return "IP real de LAN isolada"
    if dono is not None:
        cliente = get_current_tenant_slug()
        if cliente and dono != cliente:
            return "faixa virtual de outro cliente"
    return ""


def recusar(host: str) -> bool:
    """IP que a trava recusa no estado atual, para o cliente do contexto."""
    return bool(_motivo(host))


def pedir_mesmo_host(metodo: str, url: str, **kw: object):
    """requests.<metodo> sem seguir redirect para outro host: a senha iria
    junto e o IP novo nao passou pela regra de destino. Equipamento que manda
    de http para https no MESMO host segue funcionando; para outro host,
    devolve o proprio 3xx."""
    import requests

    kw["allow_redirects"] = False
    resposta = getattr(requests, metodo)(url, **kw)
    for _ in range(3):
        destino = (getattr(resposta, "headers", None) or {}).get("Location")
        if getattr(resposta, "status_code", 0) not in (301, 302, 303, 307, 308) or not destino:
            break
        proximo = urljoin(url, destino)
        if urlsplit(proximo).hostname != urlsplit(url).hostname:
            logger.warning("saida: redirect de %s para outro host (%s) nao seguido", urlsplit(url).hostname, proximo)
            break
        url = proximo
        resposta = getattr(requests, metodo)(url, **kw)
    return resposta


def _pilha_curta() -> Tuple[str, str]:
    quadros = [q for q in traceback.extract_stack(limit=40)
               if os.path.basename(q.filename) != "saida.py"
               and ("app" + os.sep in q.filename or "/app/" in q.filename)]
    linhas = [f"{os.path.basename(q.filename)}:{q.lineno}:{q.name}" for q in quadros[-4:]]
    return " < ".join(reversed(linhas)) or "(fora do app)", linhas[-1] if linhas else ""


def _avisar(host: str, porta: object, modo: str, motivo: str) -> None:
    pilha, origem = _pilha_curta()
    agora = time.monotonic()
    chave = (host, origem)
    if agora - _ultimo_aviso.get(chave, -_AVISO_S) < _AVISO_S:
        return
    if len(_ultimo_aviso) > 4096:
        _ultimo_aviso.clear()
    _ultimo_aviso[chave] = agora
    logger.warning("saida: %s conexao a %s %s:%s, cliente %s, origem %s",
                   "RECUSADA" if modo == "valer" else "seria recusada", motivo, host, porta,
                   get_current_tenant_slug() or "(sem cliente)", pilha)


def _conferir(sock: socket.socket, endereco: object) -> bool:
    """True = recusar agora. Caminho quente: so TCP com endereco (host, porta)."""
    if (not isinstance(endereco, tuple) or sock.family not in (socket.AF_INET, socket.AF_INET6)
            or not sock.type & socket.SOCK_STREAM):
        return False
    _talvez_recarregar()
    modo = _modo()
    motivo = "" if modo == "desligado" else _motivo(str(endereco[0]))
    if not motivo:
        return False
    _avisar(str(endereco[0]), endereco[1], modo, motivo)
    return modo == "valer"


def _connect(self: socket.socket, endereco: object) -> None:
    if _conferir(self, endereco):
        raise SaidaRecusada(errno.ECONNREFUSED, f"saida recusada: {endereco[0]} ({_motivo(str(endereco[0]))})")
    return _connect_original(self, endereco)


def _connect_ex(self: socket.socket, endereco: object) -> int:
    if _conferir(self, endereco):
        return errno.ECONNREFUSED
    return _connect_ex_original(self, endereco)


def instalar() -> str:
    """Instala a trava (idempotente) e devolve o modo. "desligado" nem instala:
    para voltar ao socket puro basta a variavel e reiniciar a API."""
    global _connect_original, _connect_ex_original
    modo = _modo()
    if modo == "desligado":
        logger.info("saida: trava desligada (SIGHTOPS_SAIDA_MODO)")
        return modo
    if _connect_original is None:
        _connect_original = socket.socket.connect
        _connect_ex_original = socket.socket.connect_ex
        socket.socket.connect = _connect  # type: ignore[method-assign]
        socket.socket.connect_ex = _connect_ex  # type: ignore[method-assign]
    if _recarregando.acquire(blocking=False):  # DNS fora do startup; ate terminar, nada e recusado
        _disparar_recarga()
    logger.info("saida: trava instalada, modo %s", modo)
    return modo


def desinstalar() -> None:
    """Para os testes: devolve o socket original e zera o estado."""
    global _connect_original, _connect_ex_original, _estado, _recarga_em, _nomes_em, _ips_servico
    if _connect_original is not None:
        socket.socket.connect = _connect_original  # type: ignore[method-assign]
        socket.socket.connect_ex = _connect_ex_original  # type: ignore[method-assign]
    _connect_original = _connect_ex_original = None
    _estado, _recarga_em, _nomes_em, _ips_servico = None, 0.0, 0.0, frozenset()
    _ultimo_aviso.clear()
