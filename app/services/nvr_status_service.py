"""Status dos canais de NVR, verificado de verdade e periodicamente.

Ate 07/10/2026 nenhum canal de NVR era reverificado no v3: os 388 da Easy, 47
da SIERRA e 332 da RADS tinham o status da migracao (todos "online", sem data),
e o painel mostrava 388/388 online com 5 cameras de verdade fora do ar.

Verificacao LEVE (sem snapshot, que e o caro da coleta completa), um NVR por
vez -- gravador com rede lenta ja caiu com consulta em paralelo:

- Hikvision: estado do canal pelo proprio NVR (InputProxy status).
- Intelbras/Dahua: perda de video pelo NVR (eventManager VideoLoss).
- Os dois: a camera do canal online no inventario (o Zabbix confere a cada min).

"Nao consegui perguntar" NUNCA vira online: NVR sem resposta marca os canais
como "nvr_offline"; consulta de perda de video que falhou nao conta.

Quem roda: `_nvr_status_loop` em app/main.py, cliente por cliente. Em
14/10/2026 este modulo existia ha uma semana sem ninguem chama-lo, e os 803
canais dos cinco clientes continuavam "online" sem data nenhuma.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

logger = logging.getLogger("cam-snapshot")


# Mesmo vocabulario da coleta completa (nvr.py), mais os dois desta verificacao.
CANAL_ONLINE = {"online"}
CANAL_OFFLINE = {"offline", "camera_offline", "nvr_offline"}
CANAL_VAZIO = {"sem_camera"}  # canal sem camera ligada: nao e queda
# Leitura de canal vale por 2 h: o ciclo roda a cada ~40 min, entao so perde a
# validade quem ficou duas rodadas seguidas sem resposta.
LIMITE_CANAL_MIN = 120


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def resumo_gravador(linhas: List[Dict[str, Any]], conectores_fora: Set[str] = frozenset(),
                    limite_min: float = LIMITE_CANAL_MIN) -> Dict[str, Any]:
    """Estado de UM gravador a partir de todos os seus canais (puro, testavel).

    Antes o host do gravador no monitoramento/Zabbix herdava o status do
    PRIMEIRO canal da lista: canal 1 "online" sem data = gravador online, ainda
    que nunca tivesse sido consultado.

    status: "online" (respondeu na ultima leitura valida), "offline" (todas as
    leituras validas dizem que o gravador nao respondeu) ou "unknown".
    """
    from app.services.status_efetivo import avaliar

    total = online = offline = 0
    gravador_respondeu = gravador_fora = False
    ultima = ""
    for l in linhas:
        lido = str(l.get("status") or "").strip().lower()
        if lido in CANAL_VAZIO:
            continue
        checado = l.get("status_checked_at") or ""
        efetivo, motivo = avaliar(lido, l.get("remote_connector_id") or l.get("connector_id"),
                                  checado, conectores_fora, limite_min=limite_min)
        if motivo or not checado:
            continue  # sem data ou velha demais: nao conta para nada
        if efetivo not in CANAL_ONLINE and efetivo not in CANAL_OFFLINE:
            # "sem_leitura" tem data, mas nao e resposta: contar no total
            # mandava "0 de 19 canais com imagem" ao Zabbix quando o gravador
            # so demorou a responder a perda de video.
            continue
        total += 1
        ultima = max(ultima, str(checado))
        if efetivo in CANAL_ONLINE:
            online += 1
            gravador_respondeu = True
        elif efetivo in CANAL_OFFLINE:
            offline += 1
            if efetivo == "nvr_offline":
                gravador_fora = True
            else:
                gravador_respondeu = True  # camera fora, mas o gravador falou
    if gravador_respondeu:
        status = "online"
    elif gravador_fora:
        status = "offline"
    else:
        status = "unknown"
    return {"status": status, "canais_total": total, "canais_online": online,
            "canais_offline": offline, "checado_em": ultima}


def _perda_de_video(base: str, auth: Any, timeout: float) -> Optional[Set[int]]:
    """Canais com perda de video (Dahua/Intelbras). None = nao deu para perguntar
    (a funcao da coleta completa devolve conjunto vazio nesse caso)."""
    url = f"{base}/cgi-bin/eventManager.cgi?action=getEventIndexes&code=VideoLoss"
    try:
        r = requests.get(url, auth=auth, timeout=timeout)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    return {int(v) + 1 for v in re.findall(r"channels\[\d+\]=(\d+)", r.text or "")}  # indice base-0


def decidir(canal: int, titulo: str, camera_ip: str, runtime: Optional[bool], perda: Optional[Set[int]],
            cameras_online: Set[str]) -> str:
    """Status de um canal a partir do que deu para ler (puro, testavel)."""
    padrao = bool(re.fullmatch(r"canal\s*\d*", str(titulo or "").strip().lower()))
    if runtime is True:
        return "online"
    if runtime is False:
        return "sem_camera" if padrao else "camera_offline"
    if perda is not None:
        if canal in perda:
            return "sem_camera" if padrao else "camera_offline"
        return "online"
    if camera_ip and camera_ip in cameras_online:
        return "online"
    return "sem_leitura"


def _cameras_online_recentes() -> Set[str]:
    """IPs de camera online com leitura de ate 30 min (o Zabbix confere a cada
    minuto). No v3 as cameras ficam no inventario JSON, nao no banco."""
    from app.api.endpoints.cameras import load_inventory_json
    from app.services.status_efetivo import idade_minutos

    out: Set[str] = set()
    for modo in ("basic", "olt", "switch"):
        for r in load_inventory_json(mode=modo) or []:
            if not isinstance(r, dict) or str(r.get("status") or "").lower() != "online":
                continue
            idade = idade_minutos(r.get("status_checked_at"))
            if idade is not None and idade <= 30 and r.get("ip"):
                out.add(str(r["ip"]).strip())
    return out


def _verificar_nvr(host: str, porta: int, linhas: List[Dict[str, Any]], cameras_online: Set[str]) -> Dict[int, Tuple[str, bool]]:
    """{canal: (status, perda_de_video)} de UM NVR."""
    from app.api.endpoints import nvr as N
    from app.services.recorder_credentials import resolve_recorder_credential

    cred = resolve_recorder_credential(host, porta) or {}
    if not cred.get("password"):
        raise RuntimeError("sem senha salva para este gravador")
    conector = str(next((l.get("remote_connector_id") or l.get("connector_id") for l in linhas
                         if l.get("remote_connector_id") or l.get("connector_id")), "") or "")
    if conector:
        # Mesma guarda do tr069_service: o laco roda sem ninguem olhando, entao
        # gravador atras de conector so e consultado pelo IP virtual. IP real
        # (fora das LANs do conector) pode cair na rede de outro cliente -- e
        # o probe manda a senha em Basic se o Digest falhar. IP_BLOQUEADO =
        # conector nao e deste cliente: sondar so geraria "gravador fora" falso.
        from app.services import connector_routing_vnat as vnat
        virtual = vnat.virtual_ip_for(conector, host)
        if not virtual or virtual == vnat.IP_BLOQUEADO:
            raise RuntimeError("conector do gravador nao pertence a este cliente")
        if virtual == host and vnat.has_mapping(conector):
            raise RuntimeError("IP fora das LANs mapeadas do conector; nao consultado")
    tok = N._rec_req_connector.set(conector)
    try:
        base = N._base(host, porta)
        probe = N._probe_nvr_stack(base, cred.get("username") or "admin", cred["password"], 5.0)
        canais = sorted({int(l.get("channel") or 0) for l in linhas if int(l.get("channel") or 0) > 0})
        if not probe.get("ok"):
            return {ch: ("nvr_offline", False) for ch in canais}
        auth, modo = probe.get("auth"), str(probe.get("mode") or "")
        runtime: Dict[int, Optional[bool]] = {}
        perda: Optional[Set[int]] = None
        if modo == "hik":
            for ch, info in N._hik_collect_channel_runtime_statuses(base, auth, 5.0, canais).items():
                runtime[int(ch)] = info.get("online")
        else:
            # 10 s e nao 5: o 192.168.1.118 (RADS, link lento) leva 14 s so no
            # probe e respondeu a perda de video ora em 3 s, ora depois dos 5 --
            # e cada estouro virava 19 canais "sem_leitura".
            perda = _perda_de_video(base, auth, 10.0)
    finally:
        N._rec_req_connector.reset(tok)
    out = {}
    for l in linhas:
        ch = int(l.get("channel") or 0)
        if ch <= 0:
            continue
        cip = str(l.get("camera_ip") or "").strip()
        st = decidir(ch, l.get("title") or "", cip, runtime.get(ch), perda, cameras_online)
        out[ch] = (st, bool(perda and ch in perda) or runtime.get(ch) is False)
    return out


def verificar_cliente(max_nvrs: int = 0) -> Dict[str, Any]:
    """Verifica os NVRs do cliente da sessao, um por vez, e grava o status.

    O cliente vem do contexto (set_current_tenant_slug): _read_rows/_write_rows
    resolvem o arquivo do tenant por ele. Chamar fora desse contexto leria e
    gravaria o inventario de outro cliente.
    """
    from app.api.endpoints import nvr as N

    linhas = N._read_rows()
    grupos: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for l in linhas:
        host = str(l.get("host") or "").strip()
        if host:
            grupos.setdefault((host, int(l.get("http_port") or 80)), []).append(l)
    cameras_online = _cameras_online_recentes()
    resultados: Dict[Tuple[str, int], Dict[int, Tuple[str, bool]]] = {}
    erros: Dict[str, str] = {}
    for i, ((host, porta), ls) in enumerate(sorted(grupos.items())):
        if max_nvrs and i >= max_nvrs:
            break
        try:
            resultados[(host, porta)] = _verificar_nvr(host, porta, ls, cameras_online)
        except Exception as exc:
            erros[f"{host}:{porta}"] = str(exc)[:160]
    if not resultados:
        return {"ok": True, "nvrs": 0, "erros": erros}
    agora = _agora()
    # rele antes de gravar: a coleta completa pode ter rodado no meio
    atuais = N._read_rows()
    mudou = 0
    for l in atuais:
        chave = (str(l.get("host") or "").strip(), int(l.get("http_port") or 80))
        st = resultados.get(chave, {}).get(int(l.get("channel") or 0))
        if st is None:
            continue
        l["status"], l["video_loss"] = st[0], st[1]
        l["status_checked_at"] = agora
        l["status_source"] = "verificacao_leve"
        mudou += 1
    N._write_rows(atuais)
    contagem: Dict[str, int] = {}
    for r in resultados.values():
        for st, _ in r.values():
            contagem[st] = contagem.get(st, 0) + 1
    return {"ok": True, "nvrs": len(resultados), "canais": mudou, "status": contagem, "erros": erros}
