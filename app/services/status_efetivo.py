"""Status que a tela pode acreditar: o lido, mas so enquanto valer.

Por que existe
--------------
Em 2026-10-01 o tunel de SANTANA caiu e o sistema seguiu mostrando as 224
cameras do site como **online**. Nada mentia de proposito: o status vinha da
ultima varredura e simplesmente **nunca envelhecia**. Com o tunel caido
ninguem conseguia revalidar, entao a ultima verdade conhecida -- de tres dias
antes -- ficou congelada na tela parecendo informacao de agora. O operador
perdeu o acesso ao site inteiro sem nenhum aviso.

Duas regras, nesta ordem:

1. **Conector offline derruba tudo que depende dele.** Se o caminho ate o
   equipamento caiu, nao ha como ele estar online -- e so o que sabemos e que
   nao sabemos. Vira `unknown`, nunca `up`.
2. **Leitura velha nao vale como leitura.** Acima do limite, `unknown`.
   Medido no parque real: equipamento saudavel e checado em menos de 15
   minutos, entao 30 minutos de folga nao gera alarme falso.

`unknown` e deliberado em vez de `down`: dizer "caiu" tambem seria inventar.
O honesto e "nao sei", e a tela mostra o motivo junto.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Set, Tuple

# Folga em minutos antes de uma leitura deixar de valer.
LIMITE_LEITURA_MIN = float(os.environ.get("SIGHTOPS_LEITURA_VALIDA_MIN", "30"))

MOTIVO_CONECTOR = "conector offline"
MOTIVO_VELHO = "sem leitura recente"
MOTIVO_NUNCA = "nunca verificado"


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def conectores_offline() -> Set[str]:
    """Ids dos conectores que NAO estao online agora.

    Falha de leitura devolve conjunto vazio de proposito: na duvida, nao
    rebaixar o status de ninguem -- o efeito seria o inverso do desejado,
    apagando informacao boa.
    """
    try:
        from app.services.connector_service import list_connectors
        linhas = list_connectors(False).get("connectors", [])
    except Exception:
        return set()
    return {
        _texto(c.get("id")) for c in linhas
        if _texto(c.get("id")) and _texto(c.get("status")).lower() != "online"
    }


# Por tenant: list_connectors e do cliente da sessao, e uma lista so servia a
# tela do cliente B com os conectores fora do cliente A por ate 15 s.
_cache: Dict[str, Any] = {}


def conectores_offline_cache(ttl: float = 15.0) -> Set[str]:
    """Mesma lista, com validade curta.

    O dashboard avalia centenas de linhas numa so resposta; sem cache seria
    uma leitura do arquivo de conectores por linha.
    """
    import time as _t
    try:
        from app.core.tenant_context import get_current_tenant_slug
        tenant = str(get_current_tenant_slug() or "")
    except Exception:
        tenant = ""
    agora = _t.time()
    guardado = _cache.get(tenant)
    if not guardado or agora - guardado[0] > ttl:
        guardado = (agora, conectores_offline())
        _cache[tenant] = guardado
    return guardado[1]


def idade_minutos(quando: Any) -> float | None:
    """Minutos desde o carimbo, ou None se nao der para saber."""
    bruto = _texto(quando)
    if not bruto:
        return None
    try:
        marca = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
    except Exception:
        return None
    if marca.tzinfo is None:
        marca = marca.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - marca).total_seconds() / 60.0


def avaliar(
    status: Any,
    connector_id: Any = "",
    checado_em: Any = "",
    offline: Iterable[str] | None = None,
    limite_min: float | None = None,
    exigir_data: bool = False,
) -> Tuple[str, str]:
    """Devolve (status, motivo). Motivo vazio quando o status lido vale.

    Nao normaliza o status de entrada: quem chama decide se trabalha com
    "online"/"offline" (inventario) ou "up"/"down" (monitoramento).

    `exigir_data`: status sem carimbo de medicao vira unknown. Em 19/10/2026
    38 das 41 cameras da JANGADEIROS nunca tinham sido medidas (sem host no
    Zabbix) e seguiam "online" desde a importacao -- duas delas caidas. Fica
    opcional porque OLT, gravador e conector ainda nao gravam a data em todo
    caminho; ligar para eles apagaria status bom.
    """
    cid = _texto(connector_id)
    fora = set(offline or ())
    if cid and cid in fora:
        return ("unknown", MOTIVO_CONECTOR)

    limite = LIMITE_LEITURA_MIN if limite_min is None else float(limite_min)
    idade = idade_minutos(checado_em)
    if idade is None and exigir_data and _texto(status):
        return ("unknown", MOTIVO_NUNCA)
    if idade is not None and idade > limite:
        horas = idade / 60.0
        quanto = f"{idade:.0f} min" if idade < 90 else (
            f"{horas:.0f} h" if horas < 48 else f"{horas / 24:.0f} dias")
        return ("unknown", f"{MOTIVO_VELHO} ({quanto})")

    return (_texto(status), "")


def aplicar_em_linha(linha: Dict[str, Any], offline: Iterable[str] | None = None,
                     campo_status: str = "status", campo_data: str = "status_checked_at",
                     limite_min: float | None = None, exigir_data: bool = False) -> Dict[str, Any]:
    """Marca a linha do inventario com o status efetivo, sem perder o lido.

    Mantem o valor original em `status_lido` para quem precisar auditar o que
    o equipamento respondeu da ultima vez.

    Status medido pelo proprio gravador (`status_origem == "gravador"`) vale
    por LIMITE_GRAVADOR_MIN: o ciclo do nvr_status_service roda a cada ~40 min,
    entao com os 30 min da camera o canal virava "nao verificado" entre duas
    rodadas.
    """
    if limite_min is None and linha.get("status_origem") == "gravador":
        limite_min = LIMITE_GRAVADOR_MIN
    status, motivo = avaliar(
        linha.get(campo_status),
        linha.get("remote_connector_id") or linha.get("connector_id"),
        linha.get(campo_data),
        offline,
        limite_min=limite_min,
        exigir_data=exigir_data,
    )
    if motivo:
        linha["status_lido"] = linha.get(campo_status)
        linha[campo_status] = status
        linha["status_motivo"] = motivo
    return linha


MOTIVO_SEM_CAMERA = "a camera deste canal nao esta no inventario IP"
MOTIVO_SEM_IMAGEM = "a camera responde na rede, mas o gravador nao recebe imagem dela"

# Mesma validade da leitura de canal em nvr_status_service.LIMITE_CANAL_MIN.
LIMITE_GRAVADOR_MIN = 120.0

# Canal com camera viva e gravador sem imagem. Nao e "camera offline" (a
# camera esta no ar) nem "online" (nao esta gravando): e o pior caso, porque
# tudo parece normal ate alguem precisar da gravacao.
SEM_IMAGEM = "sem_imagem"
_GRAVADOR_SEM_IMAGEM = {"camera_offline", "offline"}
_MAC_INVALIDO = {"", "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"}


def _mac_valido(valor: Any) -> str:
    mac = _texto(valor).lower().replace("-", ":")
    return "" if mac in _MAC_INVALIDO else mac


def sem_imagem_no_gravador(linha: Dict[str, Any], medida: Dict[str, Any] | None) -> bool:
    """O gravador mediu o canal sem imagem e a camera dele esta no ar.

    Em 19/10/2026 o NVR 01 da SIERRA ficou sem 14 cameras (Hikvision em ONVIF)
    enquanto todas respondiam na rede: a tela de Gravadores mostrava 48/48
    online, porque o canal herdava o "online" da camera, e ninguem foi avisado.
    So o relatorio em PDF, que le o status cru, mostrou.

    Exige leitura do proprio gravador (verificacao_leve) dentro da validade e
    medicao da camera "online" -- sem as duas, nao ha divergencia, ha falta de
    dado.
    """
    if not medida or _texto(medida.get("status")).lower() != "online":
        return False
    if _texto(linha.get("status")).lower() not in _GRAVADOR_SEM_IMAGEM:
        return False
    if linha.get("status_source") != "verificacao_leve":
        return False
    idade = idade_minutos(linha.get("status_checked_at"))
    return idade is not None and idade <= LIMITE_GRAVADOR_MIN


# Por tenant: a tela de um cliente nao pode herdar o mapa de outro.
_cache_medidas: Dict[str, Any] = {}
TTL_MEDIDAS = 20.0


def estado_medido_por_ip() -> Dict[str, Dict[str, Any]]:
    """Mapa IP -> estado MEDIDO da camera, juntando os tres modos de inventario.

    O canal de gravador nunca teve medicao propria: a varredura cataloga o
    canal e grava "online" porque ele EXISTE no equipamento, nao porque a
    camera respondeu. Resultado em 07/10/2026 no tenant rads: 332 canais, todos
    "online", enquanto 17 das cameras desses mesmos canais estavam offline no
    inventario IP -- medidas, com data, pelo caminho que funciona.

    Em vez de criar uma segunda telemetria, o canal herda o que ja foi medido.
    A chave e o IP da camera, que a linha do gravador ja guarda.
    """
    from app.services.inventory_json import load_inventory_json

    # Remontar isto custava ~120 ms, metade do tempo de /api/nvr/inventory --
    # e a tela refaz a busca a cada troca de aba. O inventario de camera nao
    # muda de segundo em segundo; 20 s de validade nao atrasa nenhuma decisao
    # e devolve a metade do tempo.
    import time
    try:
        from app.core.tenant_context import get_current_tenant_slug
        tenant = str(get_current_tenant_slug() or "")
    except Exception:
        tenant = ""
    agora = time.time()
    guardado = _cache_medidas.get(tenant)
    if guardado and (agora - guardado[0]) < TTL_MEDIDAS:
        return guardado[1]

    mapa: Dict[str, Dict[str, Any]] = {}
    # O mesmo IP pode estar em mais de um modo com estados diferentes. Deixar o
    # modo decidir e arbitrario: na pratica isso fez 2 cameras offline voltarem
    # a "online" so porque o inventario principal era mais velho. Quem vence e
    # a medicao MAIS RECENTE; sem data, a primeira encontrada.
    for modo in ("olt", "basic", "switch"):
        try:
            linhas = load_inventory_json(mode=modo) or []
        except Exception:
            continue
        for c in linhas:
            if not isinstance(c, dict):
                continue
            ip = _texto(c.get("ip") or c.get("camera_ip"))
            if not ip:
                continue
            nova = {
                "modo": modo,
                "status": _texto(c.get("status")),
                "status_checked_at": c.get("status_checked_at") or c.get("last_seen"),
                "connector_id": c.get("remote_connector_id") or c.get("connector_id"),
                "mac": _texto(c.get("mac")),
            }
            atual = mapa.get(ip)
            if atual is None or _mais_nova(nova, atual):
                mapa[ip] = nova
    _cache_medidas[tenant] = (agora, mapa)
    return mapa


def _mais_nova(nova: Dict[str, Any], atual: Dict[str, Any]) -> bool:
    """A medicao com data mais recente vence. Sem data, nao desbanca quem tem."""
    d_nova = _texto(nova.get("status_checked_at"))
    d_atual = _texto(atual.get("status_checked_at"))
    if not d_nova:
        return False
    if not d_atual:
        return True
    return d_nova > d_atual


def herdar_da_camera(linha: Dict[str, Any], medidas: Dict[str, Dict[str, Any]],
                     campo_ip: str = "camera_ip") -> Dict[str, Any]:
    """Troca o status do canal pelo da camera medida. Sem medicao, assume unknown.

    Canal sem camera no inventario NAO pode seguir "online": ninguem mediu. Dizer
    "online" ali e a mesma mentira de antes, so que num lugar novo -- e dessa vez
    com a confianca de quem acha que o problema foi resolvido.
    """
    ip = _texto(linha.get(campo_ip))
    medida = medidas.get(ip) if ip else None
    # Camera no inventario mas nunca medida (sem data) nao e medicao: o canal
    # herdaria o "online" da importacao.
    if medida and not _texto(medida.get("status_checked_at")):
        medida = None
    linha["status_gravador"] = linha.get("status")   # o que a varredura catalogou
    # O MAC medido na rede vence o que o gravador informa: o Intelbras devolve
    # ff:ff:ff:ff:ff:ff em canal ONVIF, e no NVR 02 da SIERRA os canais 9-12
    # ficaram com o MAC de outras cameras (19/10/2026).
    mac_medido = _mac_valido((medida or {}).get("mac"))
    if mac_medido:
        if _texto(linha.get("camera_mac")) and _mac_valido(linha.get("camera_mac")) != mac_medido:
            linha["camera_mac_gravador"] = linha.get("camera_mac")
        for campo in ("camera_mac", "mac_camera", "mac"):
            linha[campo] = mac_medido
    if sem_imagem_no_gravador(linha, medida):
        # Os dois lados sao verdade e a diferenca e o diagnostico: mostra o do
        # gravador, com o motivo, em vez de esconder atras do "online".
        linha["status"] = SEM_IMAGEM
        linha["status_origem"] = "gravador"
        linha["status_motivo"] = MOTIVO_SEM_IMAGEM
        linha["status_camera"] = medida.get("status")
        return linha
    if (not medida or not medida.get("status")) and linha.get("status_source") == "verificacao_leve"             and linha.get("status_checked_at"):
        # O proprio gravador foi medido (nvr_status_service: consulta canal a
        # canal, com hora). Sem camera no inventario IP, vale essa medicao --
        # antes ela era jogada fora e 8 NVRs da RADS (07, 08, Praia Bonita,
        # Medea...) apareciam "Nao verificado / nunca" sendo lidos a cada
        # poucos minutos (15/10/2026). Conector caido e leitura velha continuam
        # valendo depois, em aplicar_em_linha.
        linha["status_origem"] = "gravador"
        return linha
    if not medida or not medida.get("status"):
        linha["status"] = "unknown"
        linha["status_motivo"] = MOTIVO_SEM_CAMERA
        linha.pop("status_checked_at", None)
        return linha
    linha["status"] = medida["status"]
    linha["status_origem"] = "camera"
    # Como a camera chega na rede e propriedade DELA, nao do canal. O
    # `inventory_mode` guardado na linha do gravador nunca classificou nada:
    # ficava no que a varredura pos ("basic") ou no que o assistente de
    # implantacao deixou, pela aba em que alguem estava. Resultado: as abas
    # "Via OLT" e "Via Switch" abriam vazias em todos os clientes, embora o
    # inventario de cameras soubesse exatamente a resposta.
    if medida.get("modo"):
        linha["inventory_mode_gravador"] = linha.get("inventory_mode")
        linha["inventory_mode"] = medida["modo"]
    if medida.get("status_checked_at"):
        linha["status_checked_at"] = medida["status_checked_at"]
    if medida.get("connector_id") and not linha.get("remote_connector_id"):
        linha["remote_connector_id"] = medida["connector_id"]
    return linha
