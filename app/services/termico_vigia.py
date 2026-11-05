"""Vigia do Alerta Termico: le as cameras ativas e grava o alerta quando a
deteccao dispara. Chamado pelo laco `_termico_loop` (app/main.py) a cada 2 s.

Cada camera tem a sua leitura em andamento no maximo -- camera lenta (link
fraco da usina) nao atrasa as outras nem empilha pedidos. Fora do horario
armado a camera e lida uma vez por minuto so para a saude (leitura ok, fundo)
chegar ao Zabbix; alerta so sai armado.

Estado em memoria (fundo aprendido, manchas seguidas) por (cliente, camera):
reiniciar o container so custa reaprender o fundo no primeiro quadro.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug

logger = logging.getLogger(__name__)

INTERVALO_ARMADO_S = 2.0
INTERVALO_DESARMADO_S = 60.0
GRAVAR_SAUDE_S = 30.0
CREDENCIAL_VALE_S = 300.0
MAX_LEITURAS_JUNTAS = 8


class _Estado:
    def __init__(self, assinatura: str, vigia: Any):
        self.assinatura = assinatura
        self.vigia = vigia
        self.ultima_leitura = float("-inf")      # nunca leu
        self.ultima_saude = float("-inf")
        self.ultimo_ok: Optional[bool] = None
        self.cred: Optional[Dict[str, str]] = None
        self.cred_em = 0.0


class VigiaTermico:
    def __init__(self, avisar: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], None]] = None):
        self._estados: Dict[Tuple[str, str], _Estado] = {}
        self._ocupado: set = set()
        self._trava = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=MAX_LEITURAS_JUNTAS, thread_name_prefix="termico")
        self._avisar = avisar
        self.ultima_rodada: Dict[str, Any] = {}

    # ------------------------------------------------------------ rodada --
    def rodada(self, agora: Optional[float] = None) -> Dict[str, Any]:
        from app.services import termico_store

        agora = time.time() if agora is None else agora
        disparadas = 0
        vistas: set = set()
        for tenant in termico_store.tenants_com_cameras_ativas():
            token = set_current_tenant_slug(tenant)
            try:
                cams = termico_store.cameras_ativas()
            finally:
                reset_current_tenant_slug(token)
            for cam in cams:
                chave = (tenant, cam["id"])
                vistas.add(chave)
                est = self._estado(chave, cam)
                intervalo = INTERVALO_ARMADO_S if termico_store.esta_armado(cam) else INTERVALO_DESARMADO_S
                if agora - est.ultima_leitura < intervalo:
                    continue
                with self._trava:
                    if chave in self._ocupado:
                        continue
                    self._ocupado.add(chave)
                est.ultima_leitura = agora
                disparadas += 1
                self._pool.submit(self._ler_seguro, tenant, cam, est)
        # Camera desativada/removida: esquece o estado (libera memoria).
        for chave in list(self._estados):
            if chave not in vistas:
                self._estados.pop(chave, None)
        self.ultima_rodada = {"cameras": len(vistas), "leituras_disparadas": disparadas,
                              "em_andamento": len(self._ocupado)}
        return self.ultima_rodada

    def _estado(self, chave: Tuple[str, str], cam: Dict[str, Any]) -> _Estado:
        from app.services import termico_store
        from app.services.termico_deteccao import Vigia

        assinatura = f"{cam.get('updated_at')}|{cam.get('regra')}"
        est = self._estados.get(chave)
        if est is None or est.assinatura != assinatura:
            novo = _Estado(assinatura, Vigia(termico_store.regra_de(cam)))
            if est is not None:      # regra mudou: guarda o ritmo, reaprende o fundo
                novo.ultima_leitura, novo.ultima_saude, novo.ultimo_ok = est.ultima_leitura, est.ultima_saude, est.ultimo_ok
                novo.cred, novo.cred_em = est.cred, est.cred_em
            self._estados[chave] = novo
            est = novo
        return est

    # ----------------------------------------------------------- leitura --
    def _ler_seguro(self, tenant: str, cam: Dict[str, Any], est: _Estado) -> None:
        from app.services.connector_routing_vnat import set_olt_reach_connector

        # A thread do pool e reaproveitada: `_base` deixa o conector da leitura
        # anterior no contexto, e camera SEM conector seria traduzida pelo
        # conector da outra (IP errado ou bloqueado). Zera antes e depois.
        set_olt_reach_connector("")
        token = set_current_tenant_slug(tenant)
        try:
            self._ler(tenant, cam, est)
        except Exception:
            logger.exception("termico: falha inesperada na camera %s (%s)", cam.get("ip"), tenant)
        finally:
            reset_current_tenant_slug(token)
            set_olt_reach_connector("")
            with self._trava:
                self._ocupado.discard((tenant, cam["id"]))

    def _saude(self, cam: Dict[str, Any], est: _Estado, ok: bool, erro: str = "", fundo: Optional[float] = None) -> None:
        from app.services import termico_store

        agora = time.time()
        if est.ultimo_ok is ok and agora - est.ultima_saude < GRAVAR_SAUDE_S:
            return
        if est.ultimo_ok is not ok:
            (logger.info if ok else logger.warning)("termico: camera %s %s %s", cam.get("ip"), "lendo" if ok else "sem leitura:", erro)
        est.ultimo_ok, est.ultima_saude = ok, agora
        termico_store.registrar_leitura(cam["id"], ok, erro, fundo)

    def _ler(self, tenant: str, cam: Dict[str, Any], est: _Estado) -> None:
        from app.core.destino import destino_permitido
        from app.services import termico_store
        from app.services.camera_credentials import resolve_camera_credential
        from app.services.termico_camera import base_da_camera, buscar_quadro, buscar_foto

        pode, motivo = destino_permitido(tenant, cam["ip"], exigir_dono=False)
        if not pode:
            self._saude(cam, est, False, f"destino recusado: {motivo}")
            return
        agora = time.time()
        if est.cred is None or agora - est.cred_em > CREDENCIAL_VALE_S:
            est.cred = resolve_camera_credential(cam.get("mac") or "", cam.get("site") or "")
            est.cred_em = agora
        if not est.cred:
            self._saude(cam, est, False, "sem usuário e senha salvos para esta câmera")
            return
        base = base_da_camera(cam["ip"], cam.get("porta") or 80, cam.get("connector_id") or "")
        try:
            quadro = buscar_quadro(base, est.cred["username"], est.cred["password"], int(cam.get("canal") or 2))
        except Exception as exc:
            if "credencial" in str(exc):
                est.cred = None      # senha pode ter mudado: rele na proxima
            self._saude(cam, est, False, str(exc)[:300])
            return

        manchas, disparo = est.vigia.processar(quadro, time.time())
        fundo = est.vigia.fundo
        media_fundo = (sum(fundo.valores) / len(fundo.valores)) if fundo else None
        self._saude(cam, est, True, fundo=media_fundo)
        if not disparo or not termico_store.esta_armado(cam):
            return

        visivel = quadro.jpeg_visivel
        if not visivel:
            try:
                visivel = buscar_foto(base, est.cred["username"], est.cred["password"], canal_video=1)
            except Exception as exc:
                logger.warning("termico: alerta sem foto colorida (%s): %s", cam.get("ip"), exc)
                visivel = b""
        mancha = disparo.mancha.como_dict()
        mancha["quadros"] = disparo.quadros
        alerta = termico_store.registrar_alerta(cam, mancha, {
            "termico.jpg": quadro.jpeg_termico, "visivel.jpg": visivel, "temps.bin": quadro.temps.tobytes()})
        logger.warning("termico: PESSOA %s %s (%s) %.1f °C dif %+.1f -> alerta %s", tenant, cam.get("nome"),
                       cam.get("ip"), mancha["temp_media"], mancha["dif"], alerta["id"])
        if self._avisar:
            try:
                self._avisar(tenant, cam, alerta)
            except Exception:
                logger.exception("termico: falha ao avisar o alerta %s", alerta["id"])


def avisar_alerta(tenant: str, cam: Dict[str, Any], alerta: Dict[str, Any]) -> None:
    """O que acontece na hora do alerta. Hoje: Zabbix na hora (o sync completo
    leva minutos) e automacoes (speed, refletor, sirene) numa thread propria.
    Proximas fases: notificacao no app, WhatsApp, central (Segware)."""
    from app.services.automacao_acoes import disparar_em_thread
    from app.services.zabbix_monitoring_service import enviar_termico_agora

    disparar_em_thread(tenant, cam["id"], alerta["id"])
    enviar_termico_agora(tenant, cam.get("ip") or "", cam.get("connector_id") or "")


_vigia: Optional[VigiaTermico] = None


def vigia_global() -> VigiaTermico:
    global _vigia
    if _vigia is None:
        _vigia = VigiaTermico(avisar=avisar_alerta)
    return _vigia
