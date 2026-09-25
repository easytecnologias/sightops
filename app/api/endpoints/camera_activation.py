"""Implantacao > Ativacao de Cameras.

Camera Intelbras nova sai de fabrica **sem senha** e, ate ser inicializada,
ignora todo o resto do sistema: snapshot, CGI, ONVIF, cadastro no gravador --
tudo responde 401. Antes disto a unica saida era ir no site com o IP Utility.

O fluxo da tela e o mesmo do tecnico em campo, so que remoto:

1. `/activation/scan`  -- le o ARP/DHCP que o conector ja coletou do MikroTik,
   sonda esses IPs com o NetSDK e separa quem esta de fabrica de quem ja esta
   ativa (o SDK e a unica fonte que sabe dizer isso, ver intelbras_netsdk).
2. `/activation/run`   -- ativa 1 ou N cameras (a tela oferece as duas formas)
   e guarda a senha no cofre por MAC/site, pra camera nascer ja conhecida.

Tudo conversa por **IP virtual (vnat)**, como o resto do app -- o container nao
enxerga as interfaces `wgc<N>` do host.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from app.services import connector_routing_vnat as _vnat
from app.services import intelbras_netsdk as netsdk
from app.services.camera_credentials import save_camera_credential
from app.api.endpoints.deployments import _connector_inventory, _inventory_sources, _text

router = APIRouter(prefix="/api/deployments/activation", tags=["deployments"])

# O SDK aceita 256 IPs por chamada; a faixa de um site cabe folgado nisso.
MAX_ALVOS = netsdk.MAX_SEARCH_IPS


def _norm_mac(value: Any) -> str:
    return _text(value).lower().replace("-", ":")


def _ips_do_conector(connector_id: str) -> List[str]:
    """IPs que o MikroTik ja viu (ARP + leases DHCP).

    Usa o inventario que o conector reporta em vez de varrer a faixa inteira:
    e o mesmo caminho do "ir ate o MikroTik" que o tecnico faria na mao, e
    evita sondar 254 enderecos pra achar 20 cameras.
    """
    dados = _connector_inventory(connector_id)
    vistos: List[str] = []
    for item in _inventory_sources(dados["inventory"]):
        ip = _text(item.get("ip") or item.get("address"))
        if not ip or ip in vistos:
            continue
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue
        vistos.append(ip)
    return vistos


def _virtual(connector_id: str, ip: str) -> str:
    """IP pelo qual o container alcanca esse endereco. Conector sem mapa vnat
    devolve o proprio IP real -- mesmo comportamento do resto do app."""
    try:
        return _vnat.virtual_ip_for(connector_id, ip) or ip
    except Exception:
        return ip


@router.get("/status")
def api_activation_status() -> Dict[str, Any]:
    """A tela chama isto antes de tudo: sem a lib do NetSDK no container nao ha
    ativacao possivel, e e melhor dizer isso do que falhar no meio."""
    return netsdk.available()


@router.post("/scan")
def api_activation_scan(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload invalido")
    connector_id = _text(payload.get("connector_id"))
    if not connector_id:
        raise HTTPException(status_code=400, detail="conector obrigatorio")

    # A tela pode mandar uma faixa explicita; o normal e deixar vazio e usar o
    # que o MikroTik enxerga.
    alvos = [_text(ip) for ip in (payload.get("ips") or []) if _text(ip)]
    origem = "manual"
    if not alvos:
        alvos = _ips_do_conector(connector_id)
        origem = "conector"
    if not alvos:
        return {
            "ok": True, "source": origem, "scanned": 0, "devices": [],
            "detail": "O conector ainda nao reportou nenhum IP (ARP/DHCP vazio).",
        }
    alvos = alvos[:MAX_ALVOS]

    # real -> virtual pra sondar, e a volta pra reconhecer quem respondeu (o
    # SDK devolve sempre o IP real que a camera tem na LAN do cliente).
    por_virtual = {_virtual(connector_id, ip): ip for ip in alvos}
    resultado = netsdk.search_devices(list(por_virtual.keys()))
    if not resultado.get("ok") and not resultado.get("devices"):
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao sondar as cameras: {resultado.get('error') or 'sem detalhe'}",
        )

    dispositivos: List[Dict[str, Any]] = []
    for dev in resultado.get("devices") or []:
        real = _text(dev.get("ip"))
        item = dict(dev)
        item["connector_id"] = connector_id
        item["virtual_ip"] = _virtual(connector_id, real)
        dispositivos.append(item)

    pendentes = [d for d in dispositivos if d.get("needs_activation")]
    return {
        "ok": True,
        "source": origem,
        "scanned": resultado.get("scanned") or len(alvos),
        "devices": dispositivos,
        "pending": len(pendentes),
        "already_active": len(dispositivos) - len(pendentes),
    }


@router.post("/run")
def api_activation_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ativa as cameras escolhidas. Uma so ou o lote inteiro -- a diferenca e
    so o tamanho de `targets`, o caminho e identico.

    Sequencial de proposito: o NetSDK tem estado global no processo e o ganho
    de paralelizar nao paga o risco de embaralhar duas ativacoes.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload invalido")

    connector_id = _text(payload.get("connector_id"))
    senha = str(payload.get("senha") or payload.get("password") or "")
    usuario = _text(payload.get("usuario") or payload.get("username")) or "admin"
    email = _text(payload.get("email"))
    celular = _text(payload.get("celular") or payload.get("phone"))
    site = _text(payload.get("site"))
    salvar = bool(payload.get("salvar_credencial", True))
    alvos = payload.get("targets") or []

    if not connector_id:
        raise HTTPException(status_code=400, detail="conector obrigatorio")
    if not senha:
        raise HTTPException(status_code=400, detail="senha obrigatoria")
    if not isinstance(alvos, list) or not alvos:
        raise HTTPException(status_code=400, detail="selecione ao menos uma camera")

    resultados: List[Dict[str, Any]] = []
    ativadas = 0
    for alvo in alvos:
        if not isinstance(alvo, dict):
            continue
        ip_real = _text(alvo.get("ip"))
        mac = _norm_mac(alvo.get("mac"))
        if not ip_real or not mac:
            resultados.append({"ip": ip_real, "mac": mac, "ok": False,
                               "error": "ip e mac sao obrigatorios"})
            continue

        r = netsdk.init_device(
            device_ip=_virtual(connector_id, ip_real),
            mac=mac,
            password=senha,
            username=usuario,
            email=email,
            phone=celular,
            pwd_reset_way=int(alvo.get("pwd_reset_way") or 0),
        )
        item = {"ip": ip_real, "mac": mac, "model": _text(alvo.get("model")), "ok": bool(r.get("ok"))}
        if r.get("ok"):
            ativadas += 1
            if salvar:
                # Senha no cofre por MAC (e como padrao do site, se for a
                # primeira): a camera ja nasce conhecida pro snapshot e pro
                # resto do sistema, sem ninguem redigitar.
                try:
                    save_camera_credential(mac, site, usuario, senha)
                except Exception as exc:
                    item["warning"] = f"ativou, mas nao consegui guardar a senha: {exc}"
        else:
            item["error"] = r.get("error") or "falha desconhecida"
        resultados.append(item)

    return {
        "ok": ativadas > 0,
        "activated": ativadas,
        "failed": len(resultados) - ativadas,
        "results": resultados,
    }
