"""Classificacao em segundo plano dos trechos com movimento da Investigacao.

Para cada trecho: tira 1 quadro do gravador (2 se o trecho passa de 1 min),
roda o detector (motion_classifier) e guarda o resultado em cache por tenant.
A foto tirada aqui e a MESMA que o cartao mostra (mesmo arquivo do /quadro),
entao o retangulo desenhado na tela cai em cima do que foi detectado.

O gargalo e o gravador, nao a CPU: cada quadro e uma sessao RTSP de playback
(~2 s) e o Intelbras trava calado quando passa do numero de sessoes. Por isso
cada gravador tem no maximo 2 quadros sendo tirados ao mesmo tempo, somando o
que vier do /quadro da tela.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.core.tenant_context import (get_current_tenant_slug, reset_current_tenant_slug,
                                     set_current_tenant_slug, tenant_scoped_path)
from app.services import motion_classifier as mc

FMT = "%Y-%m-%d %H:%M:%S"
PRE_GRAVACAO_S = 10        # a etiqueta do indice comeca 10 s antes do disparo
SEGUNDO_QUADRO_S = 60      # trecho com 1 min ou mais ganha um segundo quadro
MAX_TRECHOS = 400

_SESSOES: Dict[str, threading.BoundedSemaphore] = {}
_SESSOES_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}
_EXEC = ThreadPoolExecutor(max_workers=2, thread_name_prefix="classifica")
_CACHE_LOCK = threading.Lock()
# Cache em memoria por (tenant, gravador, canal), espelhado em disco: a tela
# le os rotulos enquanto o job ainda roda.
_CACHES: Dict[tuple, Dict[str, Any]] = {}


def sessao_do_gravador(host: str) -> threading.BoundedSemaphore:
    """No maximo 2 quadros por gravador ao mesmo tempo (compartilhado com /quadro)."""
    with _SESSOES_LOCK:
        if host not in _SESSOES:
            _SESSOES[host] = threading.BoundedSemaphore(2)
        return _SESSOES[host]


def pasta_quadros() -> Path:
    p = tenant_scoped_path("investigacao_quadros")
    p.mkdir(parents=True, exist_ok=True)
    return p


def arquivo_quadro(host: str, canal: int, momento: datetime) -> Path:
    return pasta_quadros() / f"{host.replace('.', '_').replace(':', '_')}_{int(canal)}_{momento:%Y%m%d%H%M%S}.jpg"


def _arquivo_cache(host: str, canal: int) -> Path:
    p = tenant_scoped_path("investigacao_classes")
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{host.replace('.', '_').replace(':', '_')}_{int(canal)}.json"


def ler_cache(host: str, canal: int) -> Dict[str, Any]:
    """O dicionario VIVO do cache (chamar com _CACHE_LOCK)."""
    chave = (get_current_tenant_slug(), host, int(canal))
    if chave not in _CACHES:
        arq = _arquivo_cache(host, canal)
        dados: Dict[str, Any] = {}
        if arq.exists():
            try:
                dados = json.loads(arq.read_text(encoding="utf-8") or "{}")
            except Exception:
                dados = {}
        _CACHES[chave] = dados
    return _CACHES[chave]


def _gravar_cache(host: str, canal: int, dados: Dict[str, Any]) -> None:
    arq = _arquivo_cache(host, canal)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    tmp.replace(arq)


def instantes_do_trecho(ini: datetime, fim: datetime) -> List[datetime]:
    """Onde tirar quadro: no disparo (10 s depois do inicio da etiqueta) e, se
    o trecho for longo, mais um 1 min depois."""
    primeiro = min(ini + timedelta(seconds=PRE_GRAVACAO_S), fim)
    saida = [primeiro]
    if (fim - ini).total_seconds() >= SEGUNDO_QUADRO_S:
        saida.append(min(ini + timedelta(seconds=SEGUNDO_QUADRO_S), fim))
    return saida


def tirar_quadro(url_rtsp: str, destino: Path, largura: int = 0, timeout: int = 30) -> bool:
    """Um quadro do playback RTSP em JPG. largura=0 mantem o tamanho original."""
    filtro = ["-vf", f"scale={largura}:-2"] if largura else []
    try:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
                            "-timeout", "10000000", "-i", url_rtsp, "-frames:v", "1", *filtro,
                            "-q:v", "4", "-y", str(destino)], capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        destino.unlink(missing_ok=True)
        return False
    if p.returncode != 0 or not destino.exists() or destino.stat().st_size < 1000:
        destino.unlink(missing_ok=True)
        return False
    return True


def classificar_quadro(host: str, canal: int, momento: datetime, url_rtsp: str) -> Optional[List[mc.Deteccao]]:
    """Tira (ou reaproveita) o quadro e detecta. None = gravador nao entregou imagem."""
    import cv2

    arq = arquivo_quadro(host, canal, momento)
    with sessao_do_gravador(host):
        img = cv2.imread(str(arq)) if arq.exists() else None
        # Miniatura antiga de 320 px nao serve para detectar: tira de novo.
        if img is None or img.shape[1] < 600:
            # Resolucao original para detectar (pessoa ao fundo tem poucos pixels)...
            bruto = arq.with_suffix(".full.jpg")
            if not tirar_quadro(url_rtsp, bruto):
                return None
            img = cv2.imread(str(bruto))
            bruto.unlink(missing_ok=True)
            if img is None:
                return None
            # ...e 640 px para o cartao (o mesmo arquivo do /quadro).
            h, w = img.shape[:2]
            cv2.imwrite(str(arq), cv2.resize(img, (640, max(2, int(640 * h / w)))), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return mc.detector().detectar(img)


def _consolidar(cache: Dict[str, Any]) -> None:
    """Refaz o filtro de objeto fixo com TODOS os quadros ja vistos da camera."""
    por, instantes = {}, {}
    for chave, item in cache.items():
        por[chave] = [mc.Deteccao(**{**d, "fixo": False}) for d in item.get("dets", [])]
        try:
            instantes[chave] = datetime.strptime(chave, FMT).timestamp()
        except ValueError:
            instantes[chave] = 0
    mc.marcar_fixos(por, instantes)
    for chave, dets in por.items():
        cache[chave]["dets"] = mc.como_dict(dets)
        cache[chave]["rotulo"] = mc.rotulo(dets)


def resultado_do_trecho(cache: Dict[str, Any], ini: datetime, fim: datetime) -> Optional[Dict[str, Any]]:
    """Junta os quadros de um trecho: pessoa em qualquer quadro vence."""
    itens = [cache.get(m.strftime(FMT)) for m in instantes_do_trecho(ini, fim)]
    if any(i is None for i in itens):
        return None
    vistos = [i for i in itens if not i.get("sem_imagem")]
    if not vistos:
        return {"rotulo": "sem_imagem", "dets": [], "foto": itens[0].get("momento")}
    ordem = {"pessoa": 0, "veiculo": 1, "movimento": 2}
    melhor = sorted(vistos, key=lambda i: ordem.get(i.get("rotulo"), 3))[0]
    return {"rotulo": melhor.get("rotulo"), "dets": melhor.get("dets", []), "foto": melhor.get("momento")}


def iniciar(host: str, canal: int, trechos: List[Dict[str, str]], url_playback: Callable[[datetime], str]) -> str:
    """Cria o job e devolve o id. `url_playback(momento)` monta o RTSP do instante."""
    tenant = get_current_tenant_slug()
    lista = []
    for t in trechos[:MAX_TRECHOS]:
        try:
            lista.append((datetime.strptime(t["ini"][:19], FMT), datetime.strptime(t["fim"][:19], FMT)))
        except (KeyError, ValueError):
            continue
    job_id = uuid.uuid4().hex[:16]
    _JOBS[job_id] = {"tenant": tenant, "host": host, "canal": int(canal), "status": "fila",
                     "feito": 0, "total": len(lista), "criado": time.time(), "erro": ""}
    _EXEC.submit(_rodar, job_id, tenant, host, int(canal), lista, url_playback)
    return job_id


def _rodar(job_id: str, tenant: str, host: str, canal: int, lista, url_playback) -> None:
    token = set_current_tenant_slug(tenant)
    job = _JOBS[job_id]
    job["status"] = "rodando"
    try:
        mc.detector()  # falha cedo e claro se o modelo nao esta instalado
        with _CACHE_LOCK:
            cache = ler_cache(host, canal)
        faltam = []
        for ini, fim in lista:
            for m in instantes_do_trecho(ini, fim):
                ja = cache.get(m.strftime(FMT))
                # "sem imagem" e falha do gravador naquela hora: tenta de novo.
                if (ja is None or ja.get("sem_imagem")) and m not in faltam:
                    faltam.append(m)
        job["total"] = len(lista)
        job["quadros"] = len(faltam)
        # Os trechos ja classificados contam como feitos desde o inicio.
        job["feito"] = sum(1 for ini, fim in lista if resultado_do_trecho(cache, ini, fim) is not None)

        def um(m: datetime) -> None:
            # Thread nova NAO herda o tenant (contextvar): sem isto as fotos iam
            # para DATA_DIR/investigacao_quadros, pasta comum a todos os clientes
            # (visto na prova real de 09/10/2026).
            tk = set_current_tenant_slug(tenant)
            try:
                dets = classificar_quadro(host, canal, m, url_playback(m))
            finally:
                reset_current_tenant_slug(tk)
            item = {"momento": m.strftime(FMT)}
            if dets is None:
                item["sem_imagem"] = True
                item["dets"], item["rotulo"] = [], "sem_imagem"
            else:
                item["dets"], item["rotulo"] = mc.como_dict(dets), mc.rotulo(dets)
            with _CACHE_LOCK:
                cache[m.strftime(FMT)] = item
                job["feito"] = sum(1 for ini, fim in lista if resultado_do_trecho(cache, ini, fim) is not None)
                job["_gravar"] = job.get("_gravar", 0) + 1
                if job["_gravar"] % 20 == 0:
                    _gravar_cache(host, canal, cache)

        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(um, faltam))
        with _CACHE_LOCK:
            _consolidar(cache)
            _gravar_cache(host, canal, cache)
        job["status"] = "pronto"
    except FileNotFoundError as exc:
        job["status"], job["erro"] = "erro", f"detector nao instalado no servidor ({exc})"
    except Exception as exc:  # o job nunca pode morrer calado
        job["status"], job["erro"] = "erro", str(exc)[:200]
        try:
            with _CACHE_LOCK:
                _gravar_cache(host, canal, cache)
        except Exception:
            pass
    finally:
        reset_current_tenant_slug(token)


def situacao(job_id: str, trechos: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    job = _JOBS.get(job_id)
    if not job or job["tenant"] != get_current_tenant_slug():
        raise KeyError("job nao encontrado")
    return {k: v for k, v in job.items() if not k.startswith("_") and k != "tenant"}


def resultados(host: str, canal: int, trechos: List[Dict[str, str]]) -> Dict[str, Any]:
    """Rotulo de cada trecho que ja tem quadro classificado (chave = ini do trecho)."""
    saida = {}
    with _CACHE_LOCK:
        cache = ler_cache(host, canal)
        for t in trechos[:MAX_TRECHOS]:
            try:
                ini = datetime.strptime(t["ini"][:19], FMT)
                fim = datetime.strptime(t["fim"][:19], FMT)
            except (KeyError, ValueError):
                continue
            r = resultado_do_trecho(cache, ini, fim)
            if r:
                saida[t["ini"][:19]] = r
    return saida
