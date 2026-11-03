"""Escuta ao vivo dos leitores Intelbras: a passagem aparece em ~1 s.

Antes so havia a busca periodica (access_control_sync_loop, a cada ~20 s): a
pessoa passava e a foto demorava 10-30 s para aparecer no Ao vivo. Aqui cada
leitor alcancavel pelo tunel fica com uma conexao aberta em
`eventManager.cgi?action=attach&codes=[AccessControl]` (HTTP API Intelbras,
so leitura). Quando o leitor avisa uma passagem, chamamos o MESMO
poll_device_events da busca periodica -- liga a pessoa, grava e nao duplica
(cursor + record_event). A busca periodica continua como reserva: leitor so
pelo conector (sem tunel) ou escuta caida.

Uma thread por leitor (requests e bloqueante); o laco em app/main.py chama
reconciliar() a cada minuto para abrir/fechar conforme os leitores ativos.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Iterable, List, Tuple

log = logging.getLogger("cam-snapshot")

HEARTBEAT_S = 10                 # o leitor manda "Heartbeat" nesse intervalo
ESPERAS_BUSCA = (0.3, 1.0, 2.5)  # o aviso pode chegar antes de o registro estar gravado no leitor

_escutas: Dict[Tuple[str, str], "Escuta"] = {}
_trava = threading.Lock()


def _alcance_direto(device: Dict[str, Any]) -> bool:
    """Mesmo criterio do _get: sem conector fala direto; com conector, so se o
    IP e comprovadamente daquele conector (IP virtual quando isolado)."""
    from app.services.access_control_device import (
        _connector_id, _has_vnat_mapping, _host_no_inventario_do_conector, _is_intelbras_device)
    if not _is_intelbras_device(device):
        return False
    if not _connector_id(device):
        return True
    return bool(_host_no_inventario_do_conector(device) or _has_vnat_mapping(device))


# Codigos que indicam passagem. Medido nos SS 3542 MF W (03/11/2026): o rosto
# reconhecido chega como _DoorFace_ (com UserID) e a porta aberta (rosto ou
# botao) como DoorStatus; AccessControl nao vem nesse modelo, mas fica para
# os que mandam. VideoMotion, ScreenSaver etc. sao ignorados.
CODIGOS_PASSAGEM = (b"AccessControl", b"_DoorFace_", b"DoorStatus")


def e_aviso_de_passagem(linha: bytes) -> bool:
    """Linha "Code=<codigo>;action=..." de um evento de passagem."""
    linha = linha.strip()
    if not linha.startswith(b"Code="):
        return False
    return linha[5:].split(b";", 1)[0] in CODIGOS_PASSAGEM


class Escuta(threading.Thread):
    def __init__(self, tenant: str, device_id: str) -> None:
        super().__init__(daemon=True, name=f"escuta-acesso-{tenant}-{device_id[:8]}")
        self.tenant, self.device_id = tenant, device_id
        self.parar = threading.Event()
        self.ligada = False
        self.avisos = 0
        self.ultimo_aviso = 0.0

    def run(self) -> None:
        from app.core.tenant_context import set_current_tenant_slug
        set_current_tenant_slug(self.tenant)   # contexto proprio desta thread
        espera = 5.0
        while not self.parar.is_set():
            try:
                if self._uma_conexao():
                    espera = 5.0
            except Exception as exc:   # rede, leitor reiniciando: tenta de novo
                log.info("escuta do leitor %s caiu: %s", self.device_id, exc)
            self.ligada = False
            self.parar.wait(espera)
            espera = min(espera * 2, 120.0)

    def _uma_conexao(self) -> bool:
        import requests
        from app.services.access_control_device import _auth, _base_url_direct
        from app.services.access_control_store import get_device_with_password

        d = get_device_with_password(self.device_id)
        if not d or not d.get("active") or not _alcance_direto(d):
            self.parar.wait(300)   # sem tunel: fica so a busca periodica
            return False
        url = (f"{_base_url_direct(d)}/cgi-bin/eventManager.cgi"
               f"?action=attach&codes=[All]&heartbeat={HEARTBEAT_S}")
        with requests.get(url, auth=_auth(d), stream=True, timeout=(5, HEARTBEAT_S * 3)) as r:
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            if not self.ligada:
                log.info("escuta ao vivo ligada no leitor %s (%s)", d.get("name"), self.device_id)
            self.ligada = True
            for linha in r.iter_lines(chunk_size=1):
                if self.parar.is_set():
                    return True
                if e_aviso_de_passagem(linha):
                    self.avisos += 1
                    self.ultimo_aviso = time.time()
                    self._buscar()
        return True

    def _buscar(self) -> None:
        from app.services.access_control_sync import poll_device_events
        for atraso in ESPERAS_BUSCA:
            time.sleep(atraso)
            try:
                if poll_device_events(self.device_id):
                    return
            except Exception:
                log.exception("busca imediata do leitor %s falhou", self.device_id)
                return


def reconciliar(alvo: Dict[str, Iterable[str]], fabrica=Escuta) -> Dict[str, Any]:
    """`alvo` = {tenant: [ids de leitores ativos]}. Abre escuta para quem
    falta, fecha a de quem saiu e refaz a que morreu."""
    quero = {(t, did) for t, ids in alvo.items() for did in ids if did}
    with _trava:
        for chave in list(_escutas):
            e = _escutas[chave]
            if chave not in quero or not e.is_alive():
                e.parar.set()
                del _escutas[chave]
        for chave in sorted(quero - set(_escutas)):
            e = fabrica(*chave)
            _escutas[chave] = e
            e.start()
        lista: List[Dict[str, Any]] = [
            {"tenant": t, "device_id": d, "ligada": e.ligada, "avisos": e.avisos}
            for (t, d), e in sorted(_escutas.items())]
    return {"leitores": len(lista), "ligadas": sum(1 for x in lista if x["ligada"]), "lista": lista}


def parar_todas() -> None:
    with _trava:
        for e in _escutas.values():
            e.parar.set()
        _escutas.clear()
