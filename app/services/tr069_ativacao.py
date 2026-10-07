"""Ativar TR-069 numa ONU: pela OLT (quando o driver sabe) ou pelo DHCP do conector.

O endereco do servidor que a ONU usa e o IP do SERVIDOR dentro do tunel isolado
do conector dela: 10.201.0.(2 x iso_index) -- a mesma conta do iso_provisioner.
Na SIERRA (iso_index 13) da 10.201.0.26, o endereco com que as 140PoE estao
conversando desde 06/10/2026.

Dois caminhos:

- **OLT** (FiberHome AN5516): `set remote_manage_cfg ... tr069 enable acs_url ...`
  -- o comando que funcionou na SIERRA --, conferido em `show rmt_manage` e salvo.
- **DHCP do conector** (qualquer fabricante, inclusive EPON): o MikroTik entrega
  o endereco na opcao 43 e faz NAT da porta 7547 para o tunel. Gera o script; o
  tecnico cola no roteador do cliente (escrever no roteador do cliente sozinho
  nao e papel da tela).

Nos dois casos a ONU precisa ter IP de gerencia (uma WAN com DHCP numa VLAN que
chegue ao MikroTik, como a VLAN 7 da SIERRA). Sem isso ela nunca faz contato, e
a tela diz isso em vez de esperar para sempre.
"""
from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("cam-snapshot")

PORTA_CWMP = 7547


class AtivacaoError(ValueError):
    pass


def url_do_servidor(connector_id: str) -> str:
    """http://10.201.0.(2N):7547 do conector isolado da ONU."""
    from app.services.connector_service import get_connector

    conector = get_connector(str(connector_id or ""), enforce_tenant=True) if connector_id else None
    if not conector:
        raise AtivacaoError("a ONU nao tem conector deste cliente; sem ele o servidor nao alcanca a ONU")
    try:
        n = int(conector.get("iso_index") or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        raise AtivacaoError(f"o conector {conector.get('name') or connector_id} nao tem tunel isolado; "
                            "migre o conector antes de ativar TR-069")
    return f"http://10.201.0.{2 * n}:{PORTA_CWMP}"


def opcao_43_hex(url: str) -> str:
    """Opcao 43 no formato que a 140PoE leu na SIERRA: sub-opcao 1 = URL do ACS."""
    dado = url.encode("ascii")
    if len(dado) > 255:
        raise AtivacaoError("endereco do servidor longo demais para a opcao 43")
    return "0x01" + format(len(dado), "02x") + dado.hex()


def script_mikrotik(url: str, rede_gerencia: str) -> str:
    """Comandos RouterOS: opcao 43 na rede de gerencia + NAT da 7547 para o tunel."""
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}/\d{1,2}", rede_gerencia or ""):
        raise AtivacaoError("informe a rede de gerencia das ONUs no formato 172.18.1.0/24")
    servidor = re.match(r"http://([\d.]+):", url).group(1)
    return "\n".join([
        "# SightOps - TR-069 das ONUs (cole no terminal do MikroTik do cliente)",
        f"# Rede de gerencia das ONUs: {rede_gerencia}  |  Servidor: {url}",
        f'/ip dhcp-server option remove [find name="sightops-acs"]',
        f'/ip dhcp-server option add name="sightops-acs" code=43 value={opcao_43_hex(url)} comment="SightOps TR-069"',
        f':local rede [/ip dhcp-server network find address="{rede_gerencia}"]',
        ':if ([:len $rede] = 0) do={ :error "rede de gerencia nao existe em /ip dhcp-server network" }',
        ':local opcoes [/ip dhcp-server network get $rede dhcp-option]',
        ':if ([:typeof [:find $opcoes "sightops-acs"]] = "nil") do={ /ip dhcp-server network set $rede dhcp-option=($opcoes, "sightops-acs") }',
        f'/ip firewall nat remove [find comment="SightOps TR-069"]',
        f'/ip firewall nat add chain=srcnat src-address={rede_gerencia} dst-address={servidor} protocol=tcp '
        f'dst-port={PORTA_CWMP} action=masquerade comment="SightOps TR-069" place-before=0',
    ])


def _olt_da_onu(onu: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.olt_registry import list_olts

    olt = next((o for o in list_olts(True) if str(o.get("host")) == str(onu.get("olt_ip"))), None)
    if not olt:
        raise AtivacaoError("a OLT desta ONU nao esta cadastrada neste cliente")
    return olt


def _driver(olt: Dict[str, Any]) -> str:
    from app.services.olt_capabilities import normalize_olt_driver

    return normalize_olt_driver(olt.get("vendor"), olt.get("model"))


def _vlan_gerencia(tr) -> Optional[int]:
    v = tr.get_config_publica().get("vlan_gerencia")
    return int(v) if v else None


def metodo_sugerido(olt: Dict[str, Any], tr=None) -> str:
    """FiberHome: a OLT manda o endereco do servidor. 8820i: a OLT poe na ONU o
    servico da VLAN de gerencia do cliente e o DHCP com opcao 43 faz o resto
    (padrao da Easy, VLAN 7, provado na ONU 3/17 da PERUCABA em 07/10/2026)."""
    driver = _driver(olt)
    if driver == "fiberhome_an5516":
        return "olt"
    if driver == "intelbras_8820i" and tr is not None and _vlan_gerencia(tr):
        return "olt"
    return "dhcp"


def plano(tr, serial: str) -> Dict[str, Any]:
    """O que a tela mostra antes de ativar: metodo, endereco e a linha da OLT."""
    s = tr.normalizar_serial(serial)
    onu = tr.onus_do_cliente().get(s)
    if not onu:
        raise AtivacaoError("ONU nao encontrada neste cliente")
    olt = _olt_da_onu(onu)
    url = url_do_servidor(str(onu.get("connector_id") or onu.get("remote_connector_id") or ""))
    usuario, _ = tr.credencial()
    slot, pon, n = onu.get("olt_slot"), onu.get("pon"), onu.get("onu_id")
    linha = None
    metodo = metodo_sugerido(olt, tr)
    if metodo == "olt" and _driver(olt) == "fiberhome_an5516":
        linha = (f"set remote_manage_cfg slot {slot} link {pon} onu {n} tr069 enable acs_url {url} "
                 f"acl_user {usuario} acl_pswd •••••••• inform enable interval {tr.INFORM_PADRAO_S} "
                 f"port {PORTA_CWMP} user {usuario} pswd ••••••••")
    elif metodo == "olt":
        linha = f"bridge add gpon {pon} onu {n} tls vlan {_vlan_gerencia(tr)} tagged router"
    return {
        "ok": True, "serial": s, "olt": olt.get("name"), "pon": onu.get("pon_label") or f"{slot}/{pon}",
        "onu_id": n, "status_onu": onu.get("oper_status"), "modelo": onu.get("onu_model"),
        "metodo_sugerido": metodo, "pela_olt_disponivel": metodo == "olt",
        "servidor": url, "comando_olt": linha,
        "vlan_gerencia": _vlan_gerencia(tr) if _driver(olt) == "intelbras_8820i" else None,
    }


def _marcar_aguardando(tr, serial: str, metodo: str, autor: str) -> None:
    from app.services.db_store import get_json_state, set_json_state

    cfg = tr.garantir_credencial()
    aguardando = dict(cfg.get("aguardando") or {})
    aguardando[tr.normalizar_serial(serial)] = {"em": datetime.now(timezone.utc).isoformat(), "metodo": metodo, "autor": autor}
    cfg["aguardando"] = aguardando
    set_json_state(tr.CONFIG_KEY, cfg)


def ativar(tr, serial: str, metodo: str, autor: str, rede_gerencia: str = "") -> Dict[str, Any]:
    p = plano(tr, serial)
    if metodo == "dhcp":
        script = script_mikrotik(p["servidor"], rede_gerencia)
        _marcar_aguardando(tr, serial, "dhcp", autor)
        tr._registrar({"em": datetime.now(timezone.utc).isoformat(), "serial": p["serial"], "acao": "ativar",
                       "descricao": "Ativar TR-069 pelo DHCP do conector", "autor": autor,
                       "resultado": "na_fila", "detalhe": "script gerado; vale quando colado no MikroTik"})
        return {"ok": True, "metodo": "dhcp", "script": script, **p}
    if metodo != "olt" or not p["pela_olt_disponivel"]:
        raise AtivacaoError("esta OLT ainda nao ativa TR-069 pela propria OLT; use o DHCP do conector")
    resultado = _ativar_pela_olt(tr, serial)
    _marcar_aguardando(tr, serial, "olt", autor)
    tr._registrar({"em": datetime.now(timezone.utc).isoformat(), "serial": p["serial"], "acao": "ativar",
                   "descricao": "Ativar TR-069 pela OLT", "autor": autor,
                   "resultado": "aplicada" if resultado["ok"] else "falhou: " + resultado.get("error", ""),
                   "detalhe": "OLT configurada; esperando a ONU fazer o 1o contato" if resultado["ok"] else ""})
    return {**p, **resultado, "metodo": "olt"}


def _ativar_pela_olt(tr, serial: str) -> Dict[str, Any]:
    from app.cli.tools.olt_fiberhome import ativar_tr069_fiberhome
    from app.services import connector_routing_vnat as vnat
    from app.services.olt_registry import resolve_credentials

    onus = tr.onus_do_cliente()
    onu = onus[tr.serial_do_inventario(serial, onus)]
    olt = _olt_da_onu(onu)
    cred = resolve_credentials(int(olt["id"]))
    vnat.set_olt_reach_connector(cred.get("connector_id") or "")
    if _driver(olt) == "intelbras_8820i":
        return _ativar_8820i(tr, cred, onu)
    host = vnat.reach_olt_ip(cred["host"]) or cred["host"]
    usuario, senha = tr.credencial()
    url = url_do_servidor(str(onu.get("connector_id") or onu.get("remote_connector_id") or ""))
    return ativar_tr069_fiberhome(
        host, cred["username"], cred["password"], pon=f"{onu.get('olt_slot')}/{onu.get('pon')}",
        onu=int(onu.get("onu_id")), acs_url=url, usuario=usuario, senha=senha, intervalo=tr.INFORM_PADRAO_S,
    )


def _servicos_8820i(chan, pon: int, onu: int) -> list:
    """VLANs ja entregues a ONU: 'tagged 3000 router' da saida de bridge show."""
    from app.cli.tools.olt_8820i_add_onu import cli_run

    out = cli_run(chan, f"bridge show gpon {pon} onu {onu}", timeout=20)
    return [int(v) for v in re.findall(r"tagged\s+(\d+)\s+router", out or "")]


def _ativar_8820i(tr, cred: Dict[str, Any], onu: Dict[str, Any]) -> Dict[str, Any]:
    """Poe na ONU o servico router da VLAN de gerencia; o DHCP (opcao 43) faz o resto.
    Se a ONU ja tem a VLAN, nao mexe. Confere em bridge show depois."""
    from app.cli.tools.olt_8820i_add_onu import _connect, add_bridge_only, open_shell

    vlan = _vlan_gerencia(tr)
    if not vlan:
        return {"ok": False, "error": "configure a VLAN de gerencia TR-069 deste cliente antes"}
    pon, n = int(onu.get("pon")), int(onu.get("onu_id"))
    client = _connect(cred["host"], cred["username"], cred["password"], 15)
    try:
        antes = _servicos_8820i(open_shell(client), pon, n)
    finally:
        client.close()
    if vlan in antes:
        return {"ok": True, "ja_tinha": True, "vlans": antes}
    feito = add_bridge_only(cred["host"], cred["username"], cred["password"], pon, n,
                            service="tls", vlan=vlan, terminal="ont", timeout=15.0)
    client = _connect(cred["host"], cred["username"], cred["password"], 15)
    try:
        depois = _servicos_8820i(open_shell(client), pon, n)
    finally:
        client.close()
    if vlan not in depois:
        return {"ok": False, "error": f"a OLT aceitou, mas a VLAN {vlan} nao aparece na ONU", "comandos": feito.get("commands_run")}
    return {"ok": True, "vlans": depois, "comandos": feito.get("commands_run")}


def ativar_apos_autorizar(olt_ip: str, slot: Any, pon: Any, onu: Any, serial: str) -> None:
    """Chamado depois de autorizar ONU pela tela: ativa em segundo plano se o
    cliente ligou a ativacao automatica. Nunca derruba a autorizacao."""
    from app.services import tr069_service as tr

    try:
        if not tr.get_config_publica().get("auto_ativar"):
            return
    except Exception:
        return

    def _rodar():
        # A OLT FiberHome so aceita UMA sessao admin: espera a da autorizacao fechar.
        time.sleep(5)
        for tentativa in range(3):
            try:
                if tr.normalizar_serial(serial) not in tr.onus_do_cliente():
                    time.sleep(60)  # o inventario ainda nao tem a ONU nova
                    continue
                ativar(tr, serial, "olt", "ativacao automatica")
                return
            except Exception as exc:
                logger.warning("TR-069 automatico falhou para %s (tentativa %s): %s", serial, tentativa + 1, exc)
                time.sleep(30)

    threading.Thread(target=contextvars.copy_context().run, args=(_rodar,), daemon=True).start()
