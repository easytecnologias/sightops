"""Acompanha no Zabbix a troca de IP de uma camera.

Trocar o IP de uma camera nao mexia em nada no Zabbix. O resultado era o pior
dos dois mundos: a camera no IP novo ficava SEM MONITORAMENTO NENHUM, e o host
do IP velho continuava sendo pingado e alarmando por um equipamento que nao
existe mais. A renumeracao do CANAPI em 29/09/2026 produziu 53 hosts fantasma e
deixou 21 cameras sem medicao -- 63 dos 132 alertas de severidade alta vinham
dai.

Aqui o host e RENOMEADO, nao apagado e recriado. Isso preserva o historico de
ping (mesmo hostid, mesmos itens), que e justamente o que alguem quer olhar
depois de mexer na rede de um site.

So o host de MEDICAO precisa disto. O de telemetria ("SIGHTOPS.<tenant>...")
se conserta sozinho: `sync_monitoring_to_zabbix` recria o que falta e poda o
que sobra a cada passagem.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _prefixos_possiveis(tenant: str) -> tuple[str, ...]:
    """Como o host desta camera pode se chamar hoje.

    O tenant `default` e a excecao historica: os hosts dele nasceram como
    "CAM-<ip>", sem prefixo de cliente (ZBX_LEGACY_DEFAULT_HOSTNAMES=1). Todo
    cliente novo usa "<TENANT>-CAM-<ip>".
    """
    if tenant.upper() == "DEFAULT":
        return (f"{tenant.upper()}-CAM-", "CAM-")
    return (f"{tenant.upper()}-CAM-",)


def renomear_host_de_medicao(ip_antigo: str, ip_novo: str) -> Dict[str, Any]:
    """Leva o host de medicao do IP antigo para o novo.

    Nunca derruba a troca de IP: a camera ja mudou quando chegamos aqui, e o
    Zabbix e consequencia. Qualquer falha volta no retorno para aparecer na
    tela, em vez de morrer em silencio como acontecia antes.
    """
    ip_antigo = (ip_antigo or "").strip()
    ip_novo = (ip_novo or "").strip()
    if not ip_antigo or not ip_novo or ip_antigo == ip_novo:
        return {"ok": True, "renamed": 0}

    try:
        from app.api.endpoints.maintenance import (
            _load_settings,
            _normalize_zabbix_url,
            _reach,
            _zabbix_api_call,
            _zabbix_effective_sync_config,
            _zabbix_host_belongs_to_tenant,
            _zabbix_login,
            _zabbix_tenant_slug,
        )
        from app.services.inventory_json import load_inventory_json
    except Exception as exc:
        return {"ok": False, "error": f"zabbix indisponivel: {exc}"}

    try:
        cfg = _zabbix_effective_sync_config((_load_settings() or {}).get("zabbix_ip_sync") or {})
        url = _normalize_zabbix_url(cfg.get("url"))
        if not url:
            return {"ok": True, "renamed": 0, "detail": "zabbix nao configurado"}
        auth = _zabbix_login(url, cfg.get("user"), cfg.get("pass") or cfg.get("password"))
        if not auth:
            return {"ok": False, "error": "login no zabbix falhou"}

        tenant = _zabbix_tenant_slug()
        prefixos = _prefixos_possiveis(tenant)
        nomes_antigos = [p + ip_antigo for p in prefixos]
        nomes_novos = [p + ip_novo for p in prefixos]

        achados = _zabbix_api_call(
            url, "host.get",
            {"output": ["hostid", "host", "name"],
             "selectInterfaces": ["interfaceid", "ip"],
             "filter": {"host": nomes_antigos + nomes_novos}},
            auth,
        ) or []

        antigo = novo = None
        for h in achados:
            if not _zabbix_host_belongs_to_tenant(h, tenant):
                continue          # host de OUTRO cliente com o mesmo IP privado
            nome = str(h.get("host") or "")
            if nome in nomes_antigos:
                antigo = h
            elif nome in nomes_novos:
                novo = h

        if antigo is None:
            # Sem host no IP velho nao ha o que renomear. Pode ser camera que
            # nunca foi sincronizada; o sync normal cria depois.
            return {"ok": True, "renamed": 0, "detail": f"nenhum host em {ip_antigo}"}
        if novo is not None:
            # Ja existe host no IP de destino. Renomear criaria nome duplicado e
            # o Zabbix recusaria; pior, apagar o de destino poderia derrubar uma
            # camera legitima. Melhor parar e avisar.
            return {"ok": False, "renamed": 0,
                    "error": f"ja existe host em {ip_novo}; resolva no Zabbix antes"}

        # O IP que o Zabbix PINGA e o virtual (vnat) quando o conector e
        # isolado. O inventario guarda o real, entao a traducao tem que ser
        # refeita para o IP novo -- reaproveitar a interface antiga apontaria
        # para o endereco velho.
        conector = ""
        try:
            for modo in ("olt", "basic", "switch"):
                for r in (load_inventory_json(mode=modo) or []):
                    if str(r.get("ip") or "").strip() in (ip_antigo, ip_novo):
                        conector = str(r.get("remote_connector_id") or r.get("connector_id") or "").strip()
                        break
                if conector:
                    break
        except Exception:
            conector = ""
        try:
            ip_para_pingar = str(_reach(ip_novo, conector) or "").strip() or ip_novo
        except Exception:
            ip_para_pingar = ip_novo

        nome_tecnico = str(antigo.get("host") or "")
        prefixo = nome_tecnico[: -len(ip_antigo)] if nome_tecnico.endswith(ip_antigo) else ""
        if not prefixo:
            return {"ok": False, "renamed": 0, "error": f"nome inesperado: {nome_tecnico}"}

        # O nome visivel carrega o IP entre parenteses -- "[RADS] 04 - MULTIRAO
        # (172.28.1.44)". Trocar so o tecnico deixaria a tela do Zabbix mentindo.
        visivel = str(antigo.get("name") or "")
        visivel_novo = re.sub(r"\b%s\b" % re.escape(ip_antigo), ip_novo, visivel) if visivel else ""

        params: Dict[str, Any] = {"hostid": str(antigo.get("hostid")), "host": prefixo + ip_novo}
        if visivel_novo and visivel_novo != visivel:
            params["name"] = visivel_novo
        _zabbix_api_call(url, "host.update", params, auth)

        ifaces = antigo.get("interfaces") or []
        if ifaces and str(ifaces[0].get("ip") or "") != ip_para_pingar:
            _zabbix_api_call(
                url, "hostinterface.update",
                {"interfaceid": str(ifaces[0].get("interfaceid")), "ip": ip_para_pingar},
                auth,
            )

        logger.warning("zabbix: host %s renomeado para %s (pinga %s)",
                       nome_tecnico, prefixo + ip_novo, ip_para_pingar)
        return {"ok": True, "renamed": 1, "de": nome_tecnico,
                "para": prefixo + ip_novo, "pinga": ip_para_pingar}
    except Exception as exc:
        logger.exception("falha ao renomear host do Zabbix na troca de IP")
        return {"ok": False, "renamed": 0, "error": str(exc)}
