"""Historico de acoes: tudo que um usuario MUDA no sistema (POST/PUT/PATCH/DELETE).

Quem, quando, o que (em portugues), em que, se deu certo e quem autorizou --
gravado na mesma tabela de auditoria dos logins (audit_log), no cliente
efetivo. Leitura (abrir tela, ver video, ping) nao entra: vira ruido e
esconde o que importa.

O middleware (app/core/security.py) chama registrar() DEPOIS da resposta; a
gravacao e numa thread de fundo para nao atrasar a requisicao. A API roda num
processo so, entao uma fila em memoria basta. Senha nunca e gravada: do corpo
so saem os campos da lista _CAMPOS_ALVO.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("cam-snapshot")

RETENCAO_DIAS = 365
try:
    from zoneinfo import ZoneInfo

    _FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem base de fusos: Brasilia e UTC-3 o ano todo desde 2019
    _FUSO = timezone(timedelta(hours=-3))

# Rotas que so leem ou abrem algo (nao mudam nada): fora do historico.
_RUIDO = re.compile(
    r"^/api/(cameras/(ping_many|ptz_capability|snapshot/capture)"
    r"|maintenance/(web/|stream_(un)?register/|batch/(test|time_check)$)"
    r"|deployments/(recorder-(live-stream|live-stop|login|channels|xray|buscar-cameras)|camera-xray|buscar-gravadores|activation/(locate|scan))$"
    r"|olt/(find-onu|onu-signal)$|olt/registry/[^/]+/(test|telemetry)$"
    r"|switch/(hikvision|intelbras)/inspect$|network/tools/run$|tools/scan-ip$"
    r"|nvr/driver/(classificar(/situacao)?|trecho(/iniciar)?|playback|rede/conferir)$"
    r"|scripts/zabbix/preview$|connectors/agent/|alert/app/|windows/agent/report$|auth/)"
)

# Nome da acao pelo MODELO da rota (o caminho com {parametros}).
ROTULOS: Dict[str, str] = {
    "POST /api/cameras/reboot": "Reiniciou câmera",
    "POST /api/cameras/rename": "Renomeou câmera",
    "POST /api/cameras/save": "Salvou câmera",
    "POST /api/cameras/ptz_move": "Moveu câmera (PTZ)",
    "POST /api/cameras/ocorrencia": "Registrou ocorrência",
    "POST /api/snapshot/save": "Salvou foto da câmera",
    "POST /api/scan": "Rodou inventário de câmeras",
    "POST /api/rescan-single-ip": "Reverificou um IP",
    "POST /api/discovery/run": "Rodou descoberta de equipamentos",
    "POST /api/portscan/apply": "Aplicou varredura de portas",
    "POST /api/inventory/import": "Importou inventário",
    "POST /api/inventory/delete": "Excluiu câmeras do inventário",
    "POST /api/inventory/clear": "Limpou o inventário de câmeras",
    "POST /api/inventory/report/job": "Gerou relatório de câmeras",
    "POST /api/inventory/report/settings": "Alterou o relatório de câmeras",
    "POST /api/inventory/report/logo": "Trocou o logo do relatório",
    "POST /api/maintenance/change_ip": "Trocou IP de câmera",
    "POST /api/maintenance/change_ip/confirmar": "Confirmou troca de IP",
    "POST /api/maintenance/batch/reboot": "Reiniciou câmeras em lote",
    "POST /api/maintenance/batch/rename": "Renomeou câmeras em lote",
    "POST /api/maintenance/batch/password": "Trocou senha de câmeras em lote",
    "POST /api/maintenance/batch/ntp": "Ajustou horário (NTP) em lote",
    "POST /api/maintenance/batch/ip": "Trocou IP em lote",
    "POST /api/maintenance/batch/change_ips": "Trocou IPs em lote",
    "POST /api/maintenance/batch/shift_ips": "Deslocou IPs em lote",
    "POST /api/maintenance/batch/network_config": "Mudou rede de câmeras em lote",
    "POST /api/maintenance/batch/video_quality": "Mudou qualidade de vídeo em lote",
    "POST /api/maintenance/batch/day_night": "Mudou dia/noite em lote",
    "POST /api/maintenance/batch/mirror": "Espelhou imagem em lote",
    "POST /api/maintenance/batch/snapshot_force": "Atualizou fotos em lote",
    "POST /api/maintenance/camera_senha/ensinar": "Salvou senha de câmera",
    "POST /api/deployments": "Registrou implantação",
    "POST /api/deployments/apply-camera-ip": "Aplicou IP na câmera",
    "POST /api/deployments/commit-camera": "Concluiu ativação de câmera",
    "POST /api/deployments/save-camera-title": "Renomeou câmera",
    "POST /api/deployments/activation/run": "Ativou câmera",
    "POST /api/deployments/activation/reboot": "Reiniciou câmera (ativação)",
    "POST /api/deployments/recorder-add-camera": "Adicionou câmera no gravador",
    "POST /api/deployments/recorder-remove-camera": "Excluiu canal do gravador",
    "POST /api/deployments/recorder-edit": "Alterou canal do gravador",
    "POST /api/deployments/recorder-canal-desfazer": "Desfez mudança de canal",
    "POST /api/dvr/save": "Salvou DVR", "POST /api/nvr/save": "Salvou NVR",
    "POST /api/dvr/scan": "Rodou inventário de DVR", "POST /api/nvr/scan": "Rodou inventário de NVR",
    "POST /api/dvr/delete": "Excluiu DVR do inventário", "POST /api/nvr/delete": "Excluiu NVR do inventário",
    "POST /api/dvr/clear": "Limpou o inventário de DVR", "POST /api/nvr/clear": "Limpou o inventário de NVR",
    "POST /api/dvr/reboot": "Reiniciou DVR", "POST /api/nvr/reboot": "Reiniciou NVR",
    "POST /api/dvr/change_ip": "Trocou IP do DVR", "POST /api/nvr/change_ip": "Trocou IP do NVR",
    "POST /api/dvr/network": "Mudou rede do DVR", "POST /api/nvr/network": "Mudou rede do NVR",
    "POST /api/dvr/ntp": "Ajustou horário do DVR", "POST /api/nvr/ntp": "Ajustou horário do NVR",
    "POST /api/dvr/channel/rename": "Renomeou canal do DVR", "POST /api/nvr/channel/rename": "Renomeou canal do NVR",
    "POST /api/nvr/channel/change_ip": "Trocou IP de canal do NVR",
    "POST /api/nvr/driver/corrigir": "Corrigiu canais do gravador",
    "POST /api/nvr/driver/desfazer": "Desfez correção no gravador",
    "POST /api/nvr/driver/padronizar": "Padronizou nomes no gravador",
    "POST /api/nvr/driver/rede/aplicar": "Mudou rede do gravador",
    "POST /api/nvr/driver/reiniciar": "Reiniciou gravador",
    "POST /api/nvr/driver/casos": "Criou caso de investigação",
    "POST /api/nvr/driver/casos/{caso_id}/itens": "Adicionou gravação ao caso",
    "POST /api/nvr/driver/casos/{caso_id}/itens/{item_id}/remover": "Tirou gravação do caso",
    "POST /api/nvr/driver/casos/{caso_id}/notas": "Anotou no caso",
    "POST /api/playback/clip": "Exportou trecho de gravação",
    "POST /api/playback/snapshot": "Extraiu imagem de gravação",
    "POST /api/playback/frames": "Extraiu quadros de gravação",
    "POST /api/ia/nvr/search/jobs": "Buscou em gravações (IA)",
    "POST /api/ia/nvr/recordings": "Consultou gravações (IA)",
    "POST /api/olt/add-onu": "Autorizou ONU", "POST /api/olt/add-onu-bridge": "Autorizou ONU (bridge)",
    "POST /api/olt/delete-onu": "Excluiu ONU da OLT", "POST /api/olt/reboot-onu": "Reiniciou ONU",
    "POST /api/olt/discover-onus": "Procurou ONUs novas", "POST /api/olt/collect-macs": "Coletou MACs da OLT",
    "POST /api/olt/clear": "Limpou dados da OLT",
    "POST /api/olt/registry": "Cadastrou OLT", "DELETE /api/olt/registry/{olt_id}": "Excluiu OLT",
    "POST /api/olt/registry/{olt_id}/sync": "Sincronizou OLT",
    "POST /api/tr069/devices/{serial}/action": "Ação na ONU (TR-069)",
    "POST /api/tr069/devices/{serial}/servicos": "Mudou serviços da ONU",
    "POST /api/tr069/devices/{serial}/servicos/plano": "Mudou plano da ONU",
    "POST /api/tr069/ativar": "Ativou TR-069 na ONU",
    "POST /api/tr069/config": "Alterou configuração do TR-069",
    "POST /api/switch/port/enabled": "Ligou/desligou porta do switch",
    "POST /api/switch/port/poe": "Ligou/desligou PoE",
    "POST /api/switch/collect-macs": "Coletou MACs do switch", "POST /api/switch/clear": "Limpou dados de switch",
    "POST /api/connectors": "Criou conector", "PUT /api/connectors/{connector_id}": "Alterou conector",
    "DELETE /api/connectors/{connector_id}": "Excluiu conector",
    "PUT /api/connectors/{connector_id}/ports": "Alterou portas do conector",
    "POST /api/connectors/{connector_id}/wireguard": "Configurou WireGuard do conector",
    "POST /api/connectors/{connector_id}/ruijie/vpn": "Configurou VPN do Ruijie",
    "POST /api/connectors/{connector_id}/ruijie/lan-inventory": "Inventário da rede do conector",
    "POST /api/connectors/jobs": "Mandou tarefa ao conector",
    "POST /api/access-control/people": "Salvou pessoa", "POST /api/access-control/people/import": "Importou pessoas",
    "DELETE /api/access-control/people/{person_id}": "Excluiu pessoa",
    "POST /api/access-control/painel/pessoas/{person_id}/excluir": "Excluiu pessoa",
    "PUT /api/access-control/painel/pessoas/{person_id}/grupos": "Mudou grupos da pessoa",
    "POST /api/access-control/people/{person_id}/face-photo": "Trocou foto da pessoa",
    "POST /api/access-control/people/{person_id}/sync": "Reenviou pessoa às controladoras",
    "POST /api/access-control/devices": "Salvou controladora",
    "DELETE /api/access-control/devices/{device_id}": "Excluiu controladora",
    "POST /api/access-control/devices/{device_id}/open-door": "Abriu porta remotamente",
    "POST /api/access-control/painel/controladora/{device_id}/fechar": "Fechou porta remotamente",
    "POST /api/access-control/devices/{device_id}/test": "Testou controladora",
    "POST /api/access-control/devices/{device_id}/import-people": "Importou pessoas da controladora",
    "POST /api/access-control/painel/controladora/{device_id}/hora": "Acertou hora da controladora",
    "POST /api/access-control/painel/controladora/{device_id}/ntp": "Configurou NTP da controladora",
    "POST /api/access-control/painel/reiniciar-controladora/{device_id}": "Reiniciou controladora",
    "POST /api/access-control/groups": "Salvou grupo de pessoas", "DELETE /api/access-control/groups/{group_id}": "Excluiu grupo de pessoas",
    "POST /api/access-control/door-groups": "Salvou grupo de portas", "DELETE /api/access-control/door-groups/{door_group_id}": "Excluiu grupo de portas",
    "POST /api/access-control/rules": "Salvou regra de acesso", "DELETE /api/access-control/rules/{rule_id}": "Excluiu regra de acesso",
    "PUT /api/access-control/painel/acesso/grupos": "Salvou grupo de acesso",
    "DELETE /api/access-control/painel/acesso/grupos/{group_id}": "Excluiu grupo de acesso",
    "PUT /api/access-control/painel/acesso/horarios": "Salvou horário de acesso",
    "DELETE /api/access-control/painel/acesso/horarios/{horario_id}": "Excluiu horário de acesso",
    "PUT /api/access-control/painel/acesso/feriados": "Salvou feriados",
    "POST /api/access-control/reports/manual-exit": "Registrou saída manual",
    "POST /api/access-control/painel/dados/backup": "Gerou backup do controle de acesso",
    "POST /api/access-control/painel/dados/excluir-local": "Excluiu dados de um local",
    "PUT /api/access-control/whatsapp": "Alterou WhatsApp", "POST /api/access-control/whatsapp/disconnect": "Desconectou WhatsApp",
    "POST /api/alert/members": "Salvou membro do alerta", "DELETE /api/alert/members/{member_id}": "Excluiu membro do alerta",
    "POST /api/alert/members/{member_id}/activation-code": "Gerou código de ativação do alerta",
    "POST /api/alert/members/{member_id}/revoke-devices": "Desligou celular do membro do alerta",
    "POST /api/alert/incidents/{incident_id}/{action}": "Atendeu alerta de pânico",
    "POST /api/kmz/import": "Importou KMZ", "POST /api/kmz/generate": "Gerou KMZ",
    "PATCH /api/kmz/import/layers/{layer_id}": "Alterou camada do mapa",
    "PATCH /api/kmz/generated/layers/{layer_id}": "Alterou camada do mapa",
    "DELETE /api/kmz/import/layers/{layer_id}": "Excluiu camada do mapa",
    "DELETE /api/kmz/generated/layers/{layer_id}": "Excluiu camada do mapa",
    "POST /api/kmz/import/locations/apply": "Aplicou localizações do KMZ",
    "POST /api/planning/projects": "Criou projeto", "PUT /api/planning/projects/{project_id}": "Alterou projeto",
    "DELETE /api/planning/projects/{project_id}": "Excluiu projeto",
    "POST /api/windows/clear": "Limpou inventário de computadores",
    "POST /api/windows/inventory/delete": "Excluiu computadores do inventário",
    "PATCH /api/windows/inventory/manual": "Alterou computador",
    "PUT /api/monitoring/telegram": "Alterou avisos do Telegram",
    "PUT /api/monitoring/profiles/{profile_key}": "Alterou alarmes",
    "POST /api/monitoring/refresh": "Atualizou o monitoramento",
    "POST /api/monitoring/zabbix-sync": "Sincronizou com o Zabbix",
    "POST /api/backup/import": "Importou backup",
    "POST /api/db/sites": "Salvou site", "POST /api/db/assign-site": "Mudou site de equipamentos",
}

_VERBO = {"POST": "Alterou", "PUT": "Alterou", "PATCH": "Alterou", "DELETE": "Excluiu"}

# Do corpo, so estes campos (nunca senha). Listas viram contagem.
_CAMPOS_ALVO = ("ip", "host", "recorder_host", "olt_ip", "serial", "name", "nome", "title", "username",
                "canal", "channel", "site", "acao", "action", "type", "new_ip", "ip_novo", "pon", "onu")
_CAMPOS_LISTA = ("ips", "items", "cameras", "keys", "hosts", "rows")
_CAMPOS_CAMINHO_FORA = {"action"}


def registravel(method: str, path: str) -> bool:
    return str(method or "").upper() in ("POST", "PUT", "PATCH", "DELETE") and not _RUIDO.match(str(path or ""))


def _corpo_dict(corpo: bytes) -> Dict[str, Any]:
    if not corpo or len(corpo) > 256_000:
        return {}
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except Exception:
        return {}
    return dados if isinstance(dados, dict) else {}


def _alvo(path_params: Dict[str, Any], corpo: Dict[str, Any]) -> str:
    partes: List[str] = []
    for k, v in (path_params or {}).items():
        if k not in _CAMPOS_CAMINHO_FORA and str(v or "").strip():
            partes.append(str(v).strip())
    for k in _CAMPOS_ALVO:
        v = corpo.get(k)
        if isinstance(v, (str, int, float)) and str(v).strip() and str(v).strip() not in partes:
            rotulo = {"canal": "canal ", "channel": "canal ", "new_ip": "→ ", "ip_novo": "→ ", "acao": "", "action": ""}.get(k, "")
            partes.append(f"{rotulo}{str(v).strip()}"[:80])
    for k in _CAMPOS_LISTA:
        v = corpo.get(k)
        if isinstance(v, list) and v:
            partes.append(f"{len(v)} item(ns)")
            break
    return " · ".join(partes)[:200]


def descrever(method: str, modelo: str, path: str) -> str:
    """Nome em portugues da acao (pelo modelo da rota)."""
    chave = f"{str(method or '').upper()} {modelo or path}"
    if chave in ROTULOS:
        return ROTULOS[chave]
    from app.core import permissions

    modulo = permissions.modulo_da_rota(path)
    nome = next((m["label"] for m in permissions.MODULOS if m["key"] == modulo), "") if modulo else ""
    verbo = _VERBO.get(str(method or "").upper(), "Alterou")
    return f"{verbo} em {nome}" if nome else f"{verbo} ({modelo or path})"


# --------------------------------------------------------------------------- gravacao em fundo

_fila: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=5000)
_thread: Optional[threading.Thread] = None
_thread_lock = threading.Lock()
_ultima_limpeza: Optional[float] = None  # None: limpa no primeiro lote


def registrar(user: Dict[str, Any], method: str, path: str, modelo: str, status: int,
              path_params: Optional[Dict[str, Any]] = None, corpo: bytes = b"", ip: str = "",
              autorizado_por: str = "", duracao_ms: int = 0) -> None:
    """Enfileira (nunca levanta: historico nao derruba a requisicao)."""
    try:
        if not user or not registravel(method, path):
            return
        from app.core import permissions
        from app.services.auth_store import _actor_tenant_id

        status = int(status or 0)
        if status == 403:
            acao = "acao.negada"
        elif permissions.e_exclusao(path, method) or ROTULOS.get(f"{method} {modelo}", "").startswith(("Excluiu", "Limpou")):
            acao = "acao.exclusao"
        else:
            acao = "acao"
        detalhe = {
            "r": descrever(method, modelo, path), "m": str(method).upper(), "rota": path, "s": status,
            "ok": 200 <= status < 400, "ms": int(duracao_ms or 0),
        }
        if user.get("acting_as"):
            # Suporte da Easy operando a conta: o cliente ve "suporte Easy",
            # nao o login, o papel nem o IP do funcionario (outro cliente).
            detalhe["suporte"] = True
        else:
            detalhe["ip"] = str(ip or "")[:64]
            detalhe["papel"] = str(user.get("role") or "")
        if autorizado_por:
            detalhe["autorizado_por"] = autorizado_por
        item = {
            "tenant_id": _actor_tenant_id(user), "user_id": int(user.get("id") or 0) or None, "action": acao,
            "resource_type": permissions.modulo_da_rota(path) or "", "resource_id": _alvo(path_params or {}, _corpo_dict(corpo)),
            "detail_json": json.dumps(detalhe, ensure_ascii=False)[:4000],
        }
        _garantir_thread()
        _fila.put_nowait(item)
    except queue.Full:
        logger.warning("historico: fila cheia, acao descartada (%s %s)", method, path)
    except Exception:
        logger.exception("historico: falha ao registrar %s %s", method, path)


def _garantir_thread() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    with _thread_lock:
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(target=_gravador, name="historico-acoes", daemon=True)
        _thread.start()


def _gravador() -> None:
    while True:
        lote = [_fila.get()]
        while len(lote) < 200:
            try:
                lote.append(_fila.get_nowait())
            except queue.Empty:
                break
        try:
            gravar_lote(lote)
        except Exception:
            logger.exception("historico: falha ao gravar %d acao(oes)", len(lote))
            time.sleep(2)


def gravar_lote(lote: List[Dict[str, Any]]) -> None:
    global _ultima_limpeza
    from app.services.auth_store import _audit, _conn, _ensure_schema, _execute

    _ensure_schema()
    with _conn() as c:
        for it in lote:
            _audit(c, action=it["action"], tenant_id=it["tenant_id"], user_id=it["user_id"],
                   resource_type=it["resource_type"], resource_id=it["resource_id"], detail_json=it["detail_json"])
        if _ultima_limpeza is None or time.monotonic() - _ultima_limpeza > 86400:
            _ultima_limpeza = time.monotonic()
            limite = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=RETENCAO_DIAS)
            # Padrao LIKE como parametro: % literal no SQL quebra no psycopg.
            _execute(c, "DELETE FROM audit_log WHERE action LIKE ? AND created_at < ?", ("acao%", limite))


# --------------------------------------------------------------------------- consulta

TIPOS = {
    "acesso": ("auth.%",),
    "usuarios": ("user.%", "access.%", "tenant.%", "licensing.%", "exclusao_autorizada"),
    "exclusoes": ("acao.exclusao", "exclusao_autorizada"),
    "negadas": ("acao.negada",),
}


def consultar(actor: Dict[str, Any], usuario_id: Optional[int] = None, de: str = "", ate: str = "",
              tipo: str = "", q: str = "", antes_id: Optional[int] = None, limite: int = 100) -> Dict[str, Any]:
    """Historico do cliente EFETIVO de quem pergunta (nunca de outro)."""
    from app.core import permissions
    from app.services.auth_store import _actor_tenant_id, _conn, _ensure_schema, _fetchall

    _ensure_schema()
    lim = max(1, min(int(limite or 100), 200))
    where = ["a.tenant_id = ?"]
    params: List[Any] = [_actor_tenant_id(actor)]
    if usuario_id:
        where.append("a.user_id = ?")
        params.append(int(usuario_id))
    for valor, op, extra in ((de, ">=", 0), (ate, "<", 1)):
        if valor:
            try:
                dia = datetime.strptime(str(valor)[:10], "%Y-%m-%d") + timedelta(days=extra)
            except ValueError:
                raise ValueError("data invalida (use AAAA-MM-DD)")
            # O dia escolhido na tela e de Brasilia; created_at e UTC.
            dia = dia.replace(tzinfo=_FUSO).astimezone(timezone.utc).replace(tzinfo=None)
            where.append(f"a.created_at {op} ?")
            params.append(dia)
    tipo = str(tipo or "").strip().lower()
    if tipo in TIPOS:
        conds = []
        for padrao in TIPOS[tipo]:
            conds.append("a.action LIKE ?" if "%" in padrao else "a.action = ?")
            params.append(padrao)
        where.append("(" + " OR ".join(conds) + ")")
    elif tipo and any(m["key"] == tipo for m in permissions.MODULOS):
        where.append("a.action LIKE ? AND a.resource_type = ?")
        params += ["acao%", tipo]
    texto = str(q or "").strip().lower()[:80]
    if texto:
        where.append("(LOWER(a.resource_id) LIKE ? OR LOWER(a.detail_json) LIKE ? OR LOWER(COALESCE(u.username,'')) LIKE ?)")
        params += [f"%{texto}%"] * 3
    if antes_id:
        where.append("a.id < ?")
        params.append(int(antes_id))
    sql = (
        "SELECT a.id, a.action, a.resource_type, a.resource_id, a.detail_json, a.created_at, a.user_id, "
        "u.username, u.full_name FROM audit_log a "
        # So usuario do proprio cliente: o suporte da Easy (act-as) grava com o
        # id dele, de outro cliente -- o nome nao pode aparecer aqui.
        "LEFT JOIN users u ON u.id = a.user_id AND u.tenant_id = a.tenant_id "
        f"WHERE {' AND '.join(where)} ORDER BY a.id DESC LIMIT ?"
    )
    params.append(lim + 1)
    with _conn() as c:
        linhas = _fetchall(c, sql, tuple(params))
    mais = len(linhas) > lim
    linhas = linhas[:lim]
    return {"ok": True, "eventos": linhas, "mais": mais, "proximo": linhas[-1]["id"] if mais and linhas else None}
