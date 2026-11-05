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
  - IP do proprio roteador (tunel) de conector de outro cliente.
E exige dono para IP nao publico: LAN ou faixa virtual de conector do cliente,
ou equipamento cuja linha aponta para conector dele. Linha sem conector NAO
prova posse: POST /api/cameras/save grava qualquer IP.
IP publico (internet) passa: nao e rede de cliente nenhum.

Cliente SEM nenhum conector tem rede direta e nao teria como provar dono: passa
sem a exigencia (as recusas acima continuam). DESTINO_REDE_DIRETA=nunca desliga
isso. DESTINO_REDES_BLOQUEADAS substitui o padrao (a wg-sightops compartilhada,
10.250.0.0/24: fora do transito isolado o pacote cai no roteador de outro
cliente -- ver _connector_tunnel_ip_owner).

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
_REDES_PADRAO = "10.250.0.0/24"  # wg-sightops, compartilhada entre conectores
# De onde saem as faixas virtuais dos conectores. Fica fora para quem nao e dono
# mesmo com o mapa vazio ou desatualizado.
_FAIXA_VIRTUAL = ipaddress.ip_network("10.208.0.0/12")

_Rede = ipaddress._BaseNetwork
# (conector, cidr) de client_lans ja avisados neste processo: o _Contexto e
# montado a cada requisicao, e o aviso repetia a cada uma.
_AVISADAS: set = set()


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
    return _redes_do_container() + _redes_de_texto(os.getenv("DESTINO_REDES_BLOQUEADAS", _REDES_PADRAO))


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
        self.redes_do_conector: Dict[str, List[_Rede]] = {}  # cid -> LANs dele
        self.tuneis_alheios: set = set()
        self.lans_alheias: List[_Rede] = []
        # LAN REAL de conector isolado (tem mapa vnat), de qualquer cliente: o
        # host roteia parte delas pelo wg-sightops (10.0.0.0/23 em 05/11/2026),
        # entao conectar no IP real cai no conector de outro cliente. So o IP
        # virtual e destino de conexao. Excecao: LAN de conector SEM mapa deste
        # cliente (rede direta dele).
        self.reais_isoladas: List[_Rede] = []
        self.diretas_minhas: List[_Rede] = []
        self.falhou = False  # mapa ou conectores ilegiveis: nega em vez de liberar
        self.sem_conector = False
        self.tem_ruijie = False
        self._equipamentos: set | None = None
        try:
            from app.services import connector_routing_vnat as vnat
            mapa = vnat._load_map() or {}
        except Exception as exc:
            logger.warning("destino: mapa do vnat ilegivel (%s) -- faixas virtuais sem dono conhecido", exc)
            mapa = {}
            self.falhou = True
        for cid, pares in mapa.items():
            for real, virt in pares:
                self.virtuais.append((virt, str(cid)))
                self.reais_isoladas.append(real)
        if not self.slug:
            return
        try:
            from app.services import connector_service as cs
            todas = [r for r in cs._load_connectors() if isinstance(r, dict)]
            linhas = [r for r in todas if str(r.get("tenant_slug") or "").strip().lower() == self.slug]
            # falha ao ler NAO conta como cliente sem conector: abriria a rede direta
            self.sem_conector = not linhas
        except Exception as exc:
            logger.warning("destino: conectores do cliente %s ilegiveis (%s)", self.slug, exc)
            todas = linhas = []
            self.falhou = True
        for row in todas:
            if row in linhas:
                continue
            if isinstance(row.get("tunnel"), dict):
                endereco = str(row["tunnel"].get("client_address") or "").split("/")[0].strip()
                if endereco:
                    self.tuneis_alheios.add(endereco)
            self.lans_alheias.extend(real for real, _virt in mapa.get(str(row.get("id") or "").strip(), []))
            try:
                # so a LAN detectada: a digitada de outro cliente nao tira rede de ninguem
                self.lans_alheias.extend(ipaddress.ip_network(str(c), strict=False)
                                         for c in cs._extract_connector_lans(row, include_saved_tunnel=False))
            except (ValueError, TypeError, AttributeError) as exc:
                logger.warning("destino: LANs do conector %s ilegiveis (%s)", row.get("id"), exc)
        for row in linhas:
            cid = str(row.get("id") or "").strip()
            if cid:
                self.meus.add(cid)
            if str(row.get("type") or "").strip().lower() == "ruijie":
                self.tem_ruijie = True
            redes: List[_Rede] = [real for real, _virt in mapa.get(cid, [])]
            try:
                detectadas = cs._extract_connector_lans(row, include_saved_tunnel=False)
                tunel = row.get("tunnel") if isinstance(row.get("tunnel"), dict) else {}
                digitadas = [c for c in cs._split_cidr_values(tunel.get("client_lans")) if c not in detectadas]
            except Exception as exc:
                logger.warning("destino: LANs do conector %s ilegiveis (%s)", cid, exc)
                detectadas, digitadas = [], []
            for cidr in detectadas:
                try:
                    redes.append(ipaddress.ip_network(str(cidr), strict=False))
                except ValueError:
                    continue
            for cidr in digitadas:
                try:
                    rede = ipaddress.ip_network(str(cidr), strict=False)
                except ValueError:
                    continue
                # client_lans e digitado pelo admin: sobrepondo LAN de conector de
                # outro cliente, nao prova nada (seria so declarar a rede alheia)
                if any(rede.version == a.version and rede.overlaps(a) for a in self.lans_alheias):
                    # ja coberta pelo mapa/detectadas dele: ignorar nao muda nada, nao avisa;
                    # nos demais casos, um aviso por (conector, cidr) por processo
                    coberta = any(rede.version == r.version and rede.subnet_of(r) for r in redes)
                    if not coberta and (cid, str(rede)) not in _AVISADAS:
                        _AVISADAS.add((cid, str(rede)))
                        logger.warning("destino: client_lans %s do conector %s sobrepoe LAN de outro cliente -- ignorada",
                                       cidr, cid)
                    continue
                redes.append(rede)
            self.minhas_redes.extend(redes)
            if cid:
                self.redes_do_conector[cid] = redes
            if not mapa.get(cid):
                self.diretas_minhas.extend(redes)

    def _equipamento_meu(self, ip: str) -> bool:
        """IP de equipamento com linha apontando para conector deste cliente."""
        try:
            from app.core.tenant_context import get_current_tenant_slug
            if get_current_tenant_slug() != self.slug:
                return False  # o inventario e lido pelo contexto: outro cliente, nao confere
            from app.api.endpoints import maintenance as m
            if self._equipamentos is None:
                self._equipamentos = m._equipamentos_com_conector(self.redes_do_conector)
            if ip in self._equipamentos:
                return True
            return bool(self.tem_ruijie) and m._ruijie_gateway_owner(ip) in self.meus
        except Exception as exc:
            logger.warning("destino: equipamentos do cliente %s ilegiveis para %s (%s)", self.slug, ip, exc)
            return False

    def _real_isolada(self, ip: ipaddress._BaseAddress) -> bool:
        if ip.is_global or any(ip.version == d.version and ip in d for d in self.diretas_minhas):
            return False
        return any(ip.version == r.version and ip in r for r in self.reais_isoladas)

    def _em_rede_minha(self, ip: ipaddress._BaseAddress) -> bool:
        return any(ip.version == r.version and ip in r for r in self.minhas_redes)

    def conferir_ip(self, ip: ipaddress._BaseAddress, exigir_dono: bool = True) -> str:
        motivo = _motivo_fixo(ip, self.bloqueadas)
        if motivo:
            return motivo
        if self.falhou and self.slug and not ip.is_global:
            return "nao foi possivel conferir o dono deste IP"
        for virt, cid in self.virtuais:
            if ip.version == virt.version and ip in virt:
                if not self.slug or cid in self.meus:
                    return ""
                return "IP virtual de conector de outro cliente"
        if self.slug and ip.version == 4 and ip in _FAIXA_VIRTUAL and not self._em_rede_minha(ip):
            return "faixa virtual de conector sem dono neste cliente"
        if str(ip) in self.tuneis_alheios:
            return "IP de conector de outro cliente"
        if self.slug and self._real_isolada(ip):
            return "IP real de rede atras de conector isolado: use o IP virtual do conector"
        if ip.is_global or not self.slug or not exigir_dono:
            return ""
        if self._em_rede_minha(ip):
            return ""
        if self._equipamento_meu(str(ip)):
            return ""
        if any(ip.version == r.version and ip in r for r in self.lans_alheias) and self.sem_conector:
            return "IP em rede de conector de outro cliente"
        if self.sem_conector and os.getenv("DESTINO_REDE_DIRETA", "").strip().lower() != "nunca":
            return ""
        return "IP nao pertence a equipamento nem rede deste cliente"

    def dentro_de_rede_minha(self, inicio: int, fim: int) -> bool:
        """Bloco inteiro numa LAN/faixa virtual do cliente, sem tocar faixa
        alheia nem rede interna (bloco grande demais para olhar IP por IP)."""
        minhas = self.minhas_redes + [v for v, cid in self.virtuais if cid in self.meus]
        if not any(int(r.network_address) <= inicio and fim <= int(r.broadcast_address) for r in minhas):
            return False
        alheias = list(self.bloqueadas) + [v for v, cid in self.virtuais if cid not in self.meus]
        if any(inicio <= int(r.broadcast_address) and int(r.network_address) <= fim and self._real_isolada(r.network_address)
               for r in self.reais_isoladas):
            return False
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

    def fixar(self, alvo: str, exigir_dono: bool = True) -> Tuple[str, str]:
        """(IP aprovado, motivo da recusa). Resolve o nome uma vez so: quem
        conecta usa este IP, ou o DNS responderia outro na segunda consulta."""
        alvo = str(alvo or "").strip().strip("[]")
        if not alvo:
            return "", "destino vazio"
        try:
            enderecos = [ipaddress.ip_address(alvo)]
        except ValueError:
            try:
                infos = socket.getaddrinfo(alvo, None)
                enderecos = list({ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos if i and i[4]})
            except (OSError, ValueError, UnicodeError) as exc:
                return "", f"nome nao resolvido ({exc})"
            if not enderecos:
                return "", "nome nao resolvido"
        for ip in enderecos:
            motivo = self.conferir_ip(ip, exigir_dono)
            if motivo:
                return "", motivo
        enderecos.sort(key=lambda ip: ip.version)  # IPv4 primeiro: as ferramentas usam AF_INET
        return str(enderecos[0]), ""

    def conferir(self, alvo: str, exigir_dono: bool = True) -> str:
        return self.fixar(alvo, exigir_dono)[1]


def destinos_fixados(tenant_slug: str, alvos: Iterable[str],
                     exigir_dono: bool = True) -> Tuple[Dict[str, str], Dict[str, str]]:
    """({alvo: IP aprovado}, {recusado: motivo}). Quem abre a conexao usa o IP
    aprovado, nunca o nome de novo (DNS rebinding)."""
    ctx = _Contexto(tenant_slug)
    fixos: Dict[str, str] = {}
    recusados: Dict[str, str] = {}
    for alvo in alvos:
        ip, motivo = ctx.fixar(alvo, exigir_dono)
        if motivo:
            recusados[str(alvo)] = motivo
        else:
            fixos[alvo] = ip
    if recusados:
        amostra = ", ".join(f"{k} ({v})" for k, v in list(recusados.items())[:5])
        logger.warning("destino: cliente %s, %d destino(s) recusado(s): %s",
                       tenant_slug or "(sem cliente)", len(recusados), amostra)
    return fixos, recusados


def destinos_permitidos(tenant_slug: str, alvos: Iterable[str]) -> Tuple[List[str], Dict[str, str]]:
    """(permitidos na ordem de entrada, {recusado: motivo})."""
    lista = list(alvos)
    fixos, recusados = destinos_fixados(tenant_slug, lista)
    return [alvo for alvo in lista if alvo in fixos], recusados


def destino_permitido(tenant_slug: str, ip: str, exigir_dono: bool = True) -> Tuple[bool, str]:
    """(pode, motivo). Ver o docstring do modulo. `exigir_dono=False` so para
    equipamento ja cadastrado no cliente (ex. OLT do registro por tenant)."""
    _fixos, recusados = destinos_fixados(tenant_slug, [ip], exigir_dono)
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


def ip_canonico(texto: str) -> str:
    """O IP literal, na forma canonica, de `texto` (aceita IPv4:porta); "" se
    nao for. "cam.exemplo", "10.208.261" e "181403909" nao sao IP de linha:
    nome resolve para onde o DNS quiser, e forma curta engana a comparacao."""
    bruto = str(texto or "").strip()
    host = re.sub(r"^(\d+\.\d+\.\d+\.\d+):\d+$", r"\1", bruto).strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    return str(ip) if str(ip) == host else ""


def _linha_alheia(ctx: "_Contexto", linha: Dict) -> str:
    bruto = str(linha.get("ip") or "").strip()
    canonico = ip_canonico(bruto)
    if not canonico:
        return "IP precisa ser literal (ex. 192.168.1.10), sem nome nem forma curta"
    cid = str(linha.get("remote_connector_id") or linha.get("connector_id") or "").strip()
    if cid and cid in ctx.meus:
        return ""  # IP real atras de conector dele, mesmo que caia numa faixa virtual
    ip = ipaddress.ip_address(canonico)
    if any(ip.version == v.version and ip in v and c not in ctx.meus for v, c in ctx.virtuais):
        return "IP da faixa virtual de conector de outro cliente"
    return ""


def linhas_recusadas(tenant_slug: str, linhas: List[Dict]) -> Dict[str, str]:
    """{ip: motivo} das linhas que nao podem entrar no inventario pela tela.
    Para a rota de gravacao responder erro claro em vez de sumir com a linha."""
    if not tenant_slug or not linhas:
        return {}
    ctx = _Contexto(tenant_slug)
    if ctx.falhou:
        return {}
    saida: Dict[str, str] = {}
    for linha in linhas:
        if isinstance(linha, dict):
            motivo = _linha_alheia(ctx, linha)
            if motivo:
                saida[str(linha.get("ip") or "")] = motivo
    return saida


def sem_faixa_virtual_alheia(tenant_slug: str, linhas: List[Dict]) -> List[Dict]:
    """Rede de seguranca do save global: tira so a linha SEM conector do cliente
    cujo IP e da faixa virtual de outro (vinda de varredura). Linha com IP nao
    literal fica (nao vira posse: ip_canonico). Leitura falhou: nada sai."""
    if not tenant_slug or not linhas:
        return linhas
    ctx = _Contexto(tenant_slug)
    if ctx.falhou:
        logger.warning("destino: cliente %s, conectores/mapa ilegiveis -- inventario gravado sem filtro", tenant_slug)
        return linhas
    saida: List[Dict] = []
    for linha in linhas:
        motivo = _linha_alheia(ctx, linha) if isinstance(linha, dict) else ""
        if motivo.startswith("IP da faixa virtual"):
            logger.warning("destino: cliente %s tentou gravar %s: %s", tenant_slug, linha.get("ip"), motivo)
            continue
        saida.append(linha)
    return saida


__all__ = ["destino_permitido", "destinos_fixados", "destinos_permitidos", "destino_permitido_atual", "redes_bloqueadas",
           "ip_canonico", "linhas_recusadas", "sem_faixa_virtual_alheia", "varredura_recusada"]
