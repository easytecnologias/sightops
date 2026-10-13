"""Rotas do driver de gravador (app/services/recorder_driver.py).

Ficam sob /api/nvr/ de proposito: a regra de perfil `POST /api/nvr/ -> operator`
ja cobre a escrita, sem abrir excecao nova em security.py.

A senha nunca passa pelo navegador: sai de recorder_credentials (cifrada por
tenant). O conector vem do inventario do proprio tenant, para o pedido sair
pelo IP virtual quando o cliente e isolado.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.tenant_context import tenant_scoped_path
from app.services.recorder_credentials import resolve_recorder_credential
from app.services.recorder_driver import FMT, ErroDriver, Gravador

router = APIRouter(prefix="/api/nvr/driver", tags=["nvr"])


def _conector(host: str) -> str:
    from app.api.endpoints.nvr import _recorder_connector_for_host
    try:
        return _recorder_connector_for_host(host)
    except Exception:
        return ""


def _abrir(host: str, http_port: int, connector_id: str = "") -> Gravador:
    host = str(host or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="informe o gravador")
    cred = resolve_recorder_credential(host, http_port) or {}
    if not cred.get("password"):
        raise HTTPException(status_code=428, detail="SEM_CREDENCIAL")
    try:
        return Gravador(host, cred.get("username") or "admin", cred["password"], http_port,
                        connector_id or _conector(host))
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _data(valor: str, campo: str) -> datetime:
    try:
        return datetime.strptime(str(valor).replace("T", " ")[:19], FMT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{campo} invalido; use AAAA-MM-DD HH:MM:SS") from exc


@router.get("/diagnostico")
def api_driver_diagnostico(host: str, http_port: int = 80, connector_id: str = "") -> Dict[str, Any]:
    """O que falta para o gravador ser investigavel. Nao escreve nada."""
    g = _abrir(host, http_port, connector_id)
    try:
        return g.diagnostico()
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class PadronizarRequest(BaseModel):
    host: str
    http_port: int = Field(default=80, ge=1, le=65535)
    connector_id: str = ""
    # Subconjunto opcional das chaves do diagnostico. O VALOR novo nunca vem do
    # navegador: e recalculado aqui a partir do perfil.
    chaves: List[str] = Field(default_factory=list)


@router.post("/padronizar")
def api_driver_padronizar(req: PadronizarRequest) -> Dict[str, Any]:
    g = _abrir(req.host, req.http_port, req.connector_id)
    try:
        diag = g.diagnostico()
        mudancas = diag["mudancas"]
        if req.chaves:
            pedidas = set(req.chaves)
            mudancas = [m for m in mudancas if m["chave"] in pedidas]
        resultado = g.aplicar(mudancas, backup_dir=tenant_scoped_path("gravador_backups"))
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    resultado["alertas"] = diag["alertas"]
    resultado["mudancas"] = mudancas
    return resultado


@router.get("/indice")
def api_driver_indice(host: str, canal: int, inicio: str = "", fim: str = "",
                      http_port: int = 80, connector_id: str = "") -> Dict[str, Any]:
    """Linha do tempo de um canal: trechos gravados e quais tiveram movimento."""
    fim_dt = _data(fim, "fim") if fim else datetime.now()
    ini_dt = _data(inicio, "inicio") if inicio else fim_dt - timedelta(hours=24)
    if not (timedelta(0) < fim_dt - ini_dt <= timedelta(days=7)):
        raise HTTPException(status_code=400, detail="periodo precisa ser positivo e de ate 7 dias")
    g = _abrir(host, http_port, connector_id)
    try:
        segs = g.indice(int(canal), ini_dt, fim_dt)
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    def segundos(s) -> float:
        return (datetime.strptime(s.fim, FMT) - datetime.strptime(s.inicio, FMT)).total_seconds()

    return {
        "host": host, "canal": int(canal), "inicio": ini_dt.strftime(FMT), "fim": fim_dt.strftime(FMT),
        "segmentos": [s.__dict__ for s in segs],
        "resumo": {
            "arquivos": len(segs),
            "movimento_s": int(sum(segundos(s) for s in segs if s.tipo == "movimento")),
            "gravado_s": int(sum(segundos(s) for s in segs)),
        },
    }


@router.get("/relogio")
def api_driver_relogio(host: str, http_port: int = 80, connector_id: str = "") -> Dict[str, Any]:
    g = _abrir(host, http_port, connector_id)
    try:
        return g.relogio()
    except ErroDriver as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ------------------------------------------------------------- Investigacao
class PlaybackRequest(BaseModel):
    host: str
    http_port: int = Field(default=80, ge=1, le=65535)
    canal: int = Field(ge=1, le=256)
    inicio: str
    connector_id: str = ""


@router.post("/playback")
def api_driver_playback(req: PlaybackRequest) -> Dict[str, Any]:
    """Registra no go2rtc a GRAVACAO a partir de um horario e devolve o stream.

    Mesmo caminho do ao vivo de gravador (ffmpeg:...#video=h264: H.264 so e
    copiado, H.265 e convertido). O prefixo `rec_` faz o reap periodico limpar
    o stream -- e a senha RTSP junto -- quando ninguem mais assiste.
    """
    import hashlib

    import requests as _rq

    from app.services import live_stream_service as lss

    inicio = _data(req.inicio, "inicio")
    fim = min(inicio + timedelta(hours=4), datetime.now())
    if fim <= inicio:
        raise HTTPException(status_code=400, detail="esse horario ainda nao foi gravado")
    g = _abrir(req.host, req.http_port, req.connector_id)
    fonte = f"ffmpeg:{g.url_playback(req.canal, inicio, fim)}#video=h264"
    nome = "rec_pb_" + hashlib.sha1(f"{req.host}|{req.canal}|{inicio}".encode()).hexdigest()[:12]
    lss._registered_at[nome] = time.time()
    try:
        if not lss._stream_registered_with_source(nome, fonte):
            put = _rq.put(f"{lss.GO2RTC_BASE_URL}/api/streams", params={"name": nome, "src": fonte}, timeout=8)
            if put.status_code not in (200, 201, 204) and not lss._stream_registered_with_source(nome, fonte):
                raise HTTPException(status_code=502, detail=f"go2rtc recusou o playback (HTTP {put.status_code})")
    except _rq.RequestException as exc:
        raise HTTPException(status_code=502, detail="go2rtc fora do ar") from exc
    return {"stream_name": nome, "inicio": inicio.strftime(FMT), "fim": fim.strftime(FMT)}


@router.get("/quadro")
def api_driver_quadro(host: str, canal: int, ts: str, http_port: int = 80, connector_id: str = ""):
    """Foto (640 px) da gravacao num instante. Cache por tenant.

    E o mesmo arquivo que a classificacao usa: o retangulo desenhado na tela
    cai em cima do que foi detectado. O gravador Intelbras trava calado quando
    passa do numero de sessoes RTSP -- no maximo 2 por gravador, somando a
    classificacao (investigation_classify.sessao_do_gravador).
    """
    from fastapi.responses import FileResponse

    from app.services import investigation_classify as ic

    momento = _data(ts, "ts")
    arq = ic.arquivo_quadro(host, int(canal), momento)
    if not arq.exists():
        g = _abrir(host, http_port, connector_id)
        url = g.url_playback(int(canal), momento, momento + timedelta(minutes=1))
        sessao = ic.sessao_do_gravador(host)
        if not sessao.acquire(timeout=40):
            raise HTTPException(status_code=503, detail="gravador ocupado, tente de novo")
        try:
            ok = arq.exists() or ic.tirar_quadro(url, arq, largura=640)
        finally:
            sessao.release()
        if not ok:
            raise HTTPException(status_code=404, detail="sem gravacao nesse instante")
    return FileResponse(arq, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


class TrechoRef(BaseModel):
    ini: str
    fim: str


class ClassificarRequest(BaseModel):
    host: str
    http_port: int = Field(default=80, ge=1, le=65535)
    canal: int = Field(ge=1, le=256)
    trechos: List[TrechoRef] = Field(default_factory=list)
    connector_id: str = ""
    job_id: str = ""


@router.post("/classificar")
def api_driver_classificar(req: ClassificarRequest) -> Dict[str, Any]:
    """Comeca a dizer, trecho a trecho, se o movimento foi pessoa, veiculo ou nada."""
    from app.services import investigation_classify as ic

    g = _abrir(req.host, req.http_port, req.connector_id)
    canal = int(req.canal)
    job_id = ic.iniciar(req.host, canal, [t.model_dump() for t in req.trechos],
                        lambda m: g.url_playback(canal, m, m + timedelta(minutes=1)))
    return {"job_id": job_id}


@router.post("/classificar/situacao")
def api_driver_classificar_situacao(req: ClassificarRequest) -> Dict[str, Any]:
    """Andamento do job e os rotulos que ja existem (cache inclusive de buscas antigas)."""
    from app.services import investigation_classify as ic

    job = None
    if req.job_id:
        try:
            job = ic.situacao(req.job_id)
        except KeyError:
            job = None
    return {"job": job, "resultados": ic.resultados(req.host, int(req.canal), [t.model_dump() for t in req.trechos])}


class TrechoRequest(BaseModel):
    host: str
    http_port: int = Field(default=80, ge=1, le=65535)
    canal: int = Field(ge=1, le=256)
    inicio: str
    fim: str
    connector_id: str = ""


@router.post("/trecho")
def api_driver_trecho(req: TrechoRequest) -> Dict[str, Any]:
    """Baixa o trecho em MP4 na resolucao original (ate 30 min).

    O download em si e o de recorder_media_service: loadfile.cgi e, se o
    gravador devolver lixo (iNVD 5132), o indice + RPC_Loadfile.
    """
    import secrets

    from app.services.recorder_media_service import (
        RecorderAuthError, RecordingNotFoundError, download_clip_mp4,
        download_clip_mp4_hikvision)

    inicio, fim = _data(req.inicio, "inicio"), _data(req.fim, "fim")
    if not (timedelta(0) < fim - inicio <= timedelta(minutes=30)):
        raise HTTPException(status_code=400, detail="trecho de ate 30 minutos")
    g = _abrir(req.host, req.http_port, req.connector_id)
    porta = int(g.base.rsplit(":", 1)[1]) if g.base.count(":") > 1 else 80
    try:
        if g.marca == "hikvision":
            # RTSP de playback -> MP4 (-c copy). O gravador entrega ~tempo real,
            # entao o timeout acompanha a duracao do trecho (ate 30 min).
            rtsp = g.url_playback(int(req.canal), inicio, fim)
            mp4 = download_clip_mp4_hikvision(
                rtsp_url=rtsp, host=g.alcance, channel=int(req.canal),
                start_dt=inicio, end_dt=fim,
                timeout_sec=int((fim - inicio).total_seconds()) + 120)
        elif g.marca == "intelbras":
            mp4 = download_clip_mp4(host=g.alcance, http_port=porta, user=g.user, password=g.password,
                                    channel=int(req.canal), start_dt=inicio, end_dt=fim, timeout_sec=600,
                                    scale="scale=trunc(iw/2)*2:trunc(ih/2)*2")
        else:
            raise HTTPException(status_code=501, detail=f"baixar trecho ainda nao esta disponivel para {g.marca}")
    except RecorderAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RecordingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # O nome padrao e previsivel (host+canal+horario) e a pasta de exportacao
    # e comum; o sufixo aleatorio impede adivinhar o arquivo de outro cliente.
    final = mp4.with_name(f"{mp4.stem}-{secrets.token_hex(6)}.mp4")
    mp4.replace(final)
    return {"url": f"/api/playback/files/{final.name}", "filename": final.name, "size": final.stat().st_size}


# ------------------------------------------------------------------- Casos
class CasoNovo(BaseModel):
    titulo: str
    site: str = ""
    autor: str = ""


class CasoItem(BaseModel):
    host: str
    http_port: int = 80
    canal: int
    camera: str = ""
    momento: str
    inicio: str = ""
    fim: str = ""
    nota: str = ""


class CasoNotas(BaseModel):
    notas: str | None = None
    item_id: str = ""
    nota_item: str | None = None


def _caso(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="caso nao encontrado") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/casos")
def api_casos_listar() -> Dict[str, Any]:
    from app.services import investigation_cases as ic
    return {"casos": ic.listar()}


@router.post("/casos")
def api_casos_criar(req: CasoNovo) -> Dict[str, Any]:
    from app.services import investigation_cases as ic
    return _caso(ic.criar, req.titulo, req.site, req.autor)


@router.post("/casos/{caso_id}/itens")
def api_casos_item(caso_id: str, req: CasoItem) -> Dict[str, Any]:
    from app.services import investigation_cases as ic
    return _caso(ic.adicionar_item, caso_id, req.model_dump())


@router.post("/casos/{caso_id}/itens/{item_id}/remover")
def api_casos_item_remover(caso_id: str, item_id: str) -> Dict[str, Any]:
    from app.services import investigation_cases as ic
    return _caso(ic.remover_item, caso_id, item_id)


@router.post("/casos/{caso_id}/notas")
def api_casos_notas(caso_id: str, req: CasoNotas) -> Dict[str, Any]:
    from app.services import investigation_cases as ic
    return _caso(ic.atualizar, caso_id, req.notas, req.item_id, req.nota_item)
