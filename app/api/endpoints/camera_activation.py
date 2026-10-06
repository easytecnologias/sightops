"""Implantacao > Ativacao de Cameras.

Camera Intelbras nova sai de fabrica **sem senha** e, ate ser inicializada,
ignora todo o resto do sistema: snapshot, CGI, ONVIF, cadastro no gravador --
tudo responde 401. Antes disto a unica saida era ir no site com o IP Utility.

O fluxo da tela e o mesmo do tecnico em campo, so que remoto:

1. `/activation/scan`  -- le o ARP/DHCP que o conector ja coletou do MikroTik,
   sonda esses IPs com o NetSDK e separa quem esta de fabrica de quem ja esta
   ativa (o SDK e a unica fonte que sabe dizer isso, ver intelbras_netsdk).
   A Hikvision nao fala esse SDK e a tela ficava cega para ela; os enderecos
   que o SDK nao reconheceu sao perguntados de novo por ISAPI, ver
   hikvision_activation.
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
from app.services import hikvision_activation as hikvision
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


def _dados_pelos_gravadores(connector_id: str) -> Dict[str, Dict[str, str]]:
    """Modelo, firmware e serial de cada camera, perguntando aos GRAVADORES.

    Uma camera ja ativada nao conta nada disso sem a senha dela, e a tela ficava
    com MODELO e FIRMWARE vazios. Mas o gravador ja sabe: cada canal do
    `InputProxy/channels` traz `<model>`, `<firmwareVersion>` e `<serialNumber>`
    da camera ligada nele. Usa a credencial do gravador, que o SightOps guarda
    -- nenhuma senha de camera e necessaria.

    Cameras que nao estao em canal nenhum continuam sem esses dados, o que e
    honesto: ninguem no site sabe.
    """
    import re as _re

    from app.services.recorder_credentials import resolve_recorder_credential
    from app.services import recorder_xray as _rx

    achados: Dict[str, Dict[str, str]] = {}
    hosts = set()
    for fonte in ("nvr", "dvr"):
        try:
            from app.api.endpoints.deployments import _read_recorder_rows
            linhas = _read_recorder_rows(fonte)
        except Exception:
            continue
        for linha in linhas:
            if _text(linha.get("remote_connector_id") or linha.get("connector_id")) != _text(connector_id):
                continue
            host = _text(linha.get("host"))
            if host:
                hosts.add((host, linha.get("http_port")))

    for host, porta in hosts:
        cred = resolve_recorder_credential(host, porta)
        if not cred or not cred.get("password"):
            continue
        try:
            base = _rx._base(host, porta, connector_id)
            if _rx.detectar_marca(base, cred["username"], cred["password"]) != "hikvision":
                continue
            _, corpo = _rx._pedir(f"{base}/ISAPI/ContentMgmt/InputProxy/channels",
                                  cred["username"], cred["password"], 25.0)
        except Exception:
            continue
        # Cada canal comeca em <id>; separar por ali evita casar campo de um
        # canal com o IP de outro.
        for bloco in _re.split(r"(?=<id>)", corpo or ""):
            ip = _re.search(r"<ipAddress>([^<]*)</ipAddress>", bloco)
            if not ip:
                continue
            def campo(nome: str) -> str:
                m = _re.search(rf"<{nome}>([^<]*)</{nome}>", bloco)
                return (m.group(1).strip() if m else "")
            achados[ip.group(1).strip()] = {
                "model": campo("model"),
                "firmware": campo("firmwareVersion"),
                "serial": campo("serialNumber"),
            }
    return achados


def _ordem_ip(ip: Any) -> tuple:
    """Ordena IP por octeto, nao por texto.

    Em ordem alfabetica 10.50.11.7 cai depois de 10.50.11.42, e a lista fica
    embaralhada justamente onde o tecnico precisa achar um endereco especifico.
    """
    partes = str(ip or "").split(".")
    try:
        return tuple(int(p) for p in partes) if len(partes) == 4 else (999, 999, 999, 999)
    except ValueError:
        return (999, 999, 999, 999)


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

    # Marca escolhida na tela. Sondar as duas pilhas custa caro: o NetSDK varre
    # por unicast e o ISAPI bate endereco por endereco. Quem sabe que o site e
    # de uma marca so poupa metade do tempo -- e nao encosta no equipamento da
    # outra marca a toa.
    marca_busca = _text(payload.get("marca") or payload.get("marca_busca")).lower() or "todas"

    # real -> virtual pra sondar, e a volta pra reconhecer quem respondeu (o
    # SDK devolve sempre o IP real que a camera tem na LAN do cliente).
    por_virtual = {_virtual(connector_id, ip): ip for ip in alvos}
    if marca_busca in ("todas", "intelbras"):
        # Isolado: um segfault do SDK mata so o subprocesso, nao a API.
        resultado = netsdk.search_devices_isolado(list(por_virtual.keys()))
    else:
        resultado = {"ok": True, "devices": []}

    dispositivos: List[Dict[str, Any]] = []
    for dev in resultado.get("devices") or []:
        real = _text(dev.get("ip"))
        item = dict(dev)
        item.setdefault("vendor", "Intelbras")
        item["connector_id"] = connector_id
        item["virtual_ip"] = _virtual(connector_id, real)
        dispositivos.append(item)

    # A Hikvision nao aparece no SDK da Intelbras -- nem ativada, nem de
    # fabrica. Mesmos enderecos, outra pergunta, so para quem o SDK nao
    # reconheceu. So leitura e sem mandar senha: ver hikvision_activation.
    erro_hik = ""
    ja_vistos = {_text(d.get("ip")) for d in dispositivos}
    restantes = ({v: r for v, r in por_virtual.items() if r not in ja_vistos}
                 if marca_busca in ("todas", "hikvision") else {})
    macs_da_rede = {_text(i.get("ip") or i.get("address")): _text(i.get("mac"))
                    for i in _inventory_sources(_connector_inventory(connector_id)["inventory"])
                    if _text(i.get("mac"))}
    try:
        for dev in hikvision.procurar(restantes, macs_da_rede):
            dev["connector_id"] = connector_id
            dev["virtual_ip"] = _virtual(connector_id, _text(dev.get("ip")))
            dispositivos.append(dev)
    except Exception as exc:
        erro_hik = str(exc)

    # So e falha quando NENHUMA das duas fontes achou nada: o SDK pode estar
    # fora do ar e o site ser todo Hikvision, e vice-versa.
    if not dispositivos and not resultado.get("ok"):
        raise HTTPException(
            status_code=502,
            detail=f"Falha ao sondar as cameras: {resultado.get('error') or erro_hik or 'sem detalhe'}",
        )

    # Modelo e firmware que a camera nao entrega sem senha, mas o gravador sabe.
    try:
        pelo_gravador = _dados_pelos_gravadores(connector_id)
    except Exception:
        pelo_gravador = {}
    for dev in dispositivos:
        extra = pelo_gravador.get(_text(dev.get("ip"))) or {}
        for chave in ("model", "firmware", "serial"):
            if extra.get(chave) and not _text(dev.get(chave)):
                dev[chave] = extra[chave]

    dispositivos.sort(key=lambda d: _ordem_ip(d.get("ip")))
    pendentes = [d for d in dispositivos if d.get("needs_activation")]
    return {
        "ok": True,
        "source": origem,
        "scanned": resultado.get("scanned") or len(alvos),
        "devices": dispositivos,
        "pending": len(pendentes),
        "already_active": len(dispositivos) - len(pendentes),
        "marca": marca_busca,
    }


def _pos_ativacao_hikvision(connector_id: str, ip: str, senha: str,
                            perguntas, pedir_dhcp: bool) -> Dict[str, Any]:
    """Perguntas de recuperacao e DHCP, logo depois de ativar.

    Sao por ISAPI (ver hikvision_activation) e dependem da senha que acabou de
    ser criada. Falhar aqui NAO desfaz a ativacao -- a camera ja tem senha e o
    tecnico precisa saber disso, entao cada passo volta com seu proprio estado.
    """
    base = f"http://{_virtual(connector_id, ip)}"
    saida: Dict[str, Any] = {}
    if perguntas:
        saida["perguntas"] = hikvision.definir_perguntas(base, senha, perguntas)
    if pedir_dhcp:
        saida["dhcp"] = hikvision.definir_dhcp(base, senha)
        # O DHCP so vale no boot. Reiniciar aqui, e nao "depois", tambem solta
        # o 192.168.1.64 de fabrica para a proxima camera do lote: com 2 de
        # fabrica no mesmo IP, so uma responde enquanto a outra nao sair dele.
        if saida["dhcp"].get("ok"):
            saida["reinicio"] = hikvision.reiniciar(base, senha)
    return saida


@router.post("/reboot")
def api_activation_reboot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Reinicia cameras recem-ativadas (botao do resultado da ativacao).

    Vai pelo IP virtual DESTE conector: 192.168.1.64 de fabrica existe em
    todo cliente, e a rota generica de reboot resolve o IP sem saber de qual
    site ele e.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload invalido")
    connector_id = _text(payload.get("connector_id"))
    senha = str(payload.get("senha") or payload.get("password") or "")
    alvos = payload.get("targets") or []
    if not connector_id:
        raise HTTPException(status_code=400, detail="conector obrigatorio")
    if not senha:
        raise HTTPException(status_code=400, detail="senha obrigatoria")
    if not isinstance(alvos, list) or not alvos:
        raise HTTPException(status_code=400, detail="selecione ao menos uma camera")

    resultados: List[Dict[str, Any]] = []
    for alvo in alvos:
        ip_real = _text((alvo or {}).get("ip")) if isinstance(alvo, dict) else ""
        if not ip_real:
            continue
        if _text(alvo.get("vendor")).lower() != "hikvision":
            resultados.append({"ip": ip_real, "ok": False,
                               "error": "reiniciar pela ativacao e so para Hikvision"})
            continue
        r = hikvision.reiniciar(f"http://{_virtual(connector_id, ip_real)}", senha)
        resultados.append({"ip": ip_real, "ok": bool(r.get("ok")), "error": r.get("error")})
    ok = sum(1 for r in resultados if r["ok"])
    return {"ok": ok > 0, "rebooted": ok, "failed": len(resultados) - ok, "results": resultados}


@router.post("/locate")
def api_activation_locate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Que IP cada MAC assumiu depois do reinicio com DHCP.

    Le o ARP/DHCP que o conector reporta (o mesmo do /scan). O IP antigo e
    ignorado: o ARP ainda guarda o 192.168.1.64 por um tempo com o mesmo MAC.
    DHCP vem antes de ARP por ser a fonte que realmente entregou o endereco.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload invalido")
    connector_id = _text(payload.get("connector_id"))
    if not connector_id:
        raise HTTPException(status_code=400, detail="conector obrigatorio")
    pedidos = {
        _norm_mac(a.get("mac")): _text(a.get("old_ip"))
        for a in (payload.get("targets") or [])
        if isinstance(a, dict) and _norm_mac(a.get("mac"))
    }
    ordem = {"dhcp": 0, "arp": 1, "neighbor": 2}
    achados: Dict[str, Dict[str, Any]] = {}
    for item in sorted(_inventory_sources(_connector_inventory(connector_id)["inventory"]),
                       key=lambda i: ordem.get(i.get("source"), 9)):
        mac = _norm_mac(item.get("mac") or item.get("mac_address"))
        ip = _text(item.get("ip") or item.get("address"))
        if mac in pedidos and ip and ip != pedidos[mac] and mac not in achados:
            achados[mac] = {"ip": ip, "source": item.get("source")}
    return {"ok": True, "found": achados}


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
    # Hikvision: a tela pode mandar as 3 perguntas de recuperacao e pedir DHCP.
    # Sao passos DEPOIS da ativacao, com a senha recem-criada.
    perguntas = [
        (int(q.get("id")), str(q.get("resposta") or q.get("answer") or ""))
        for q in (payload.get("perguntas") or [])
        if isinstance(q, dict) and str(q.get("id") or "").isdigit()
        and (q.get("resposta") or q.get("answer"))
    ]
    pedir_dhcp = bool(payload.get("dhcp"))

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
        eh_hikvision = _text(alvo.get("vendor")).lower() == "hikvision"
        # O MAC e obrigatorio no caminho Intelbras (o SDK ativa POR MAC); no
        # ISAPI da Hikvision quem identifica e o IP, e exigir MAC so impediria
        # ativar uma camera que respondeu sem ele.
        if not ip_real or (not mac and not eh_hikvision):
            resultados.append({"ip": ip_real, "mac": mac, "ok": False,
                               "error": "ip e mac sao obrigatorios"})
            continue

        if eh_hikvision:
            # A Hikvision cria sempre a conta `admin` na ativacao -- nao da para
            # escolher o usuario, entao o campo da tela nao vale aqui.
            r = hikvision.ativar(f"http://{_virtual(connector_id, ip_real)}", senha)
            usuario_criado = "admin"
        else:
            r = netsdk.init_device_isolado(
                device_ip=_virtual(connector_id, ip_real),
                mac=mac,
                password=senha,
                username=usuario,
                email=email,
                phone=celular,
                pwd_reset_way=int(alvo.get("pwd_reset_way") or 0),
            )
            usuario_criado = usuario
        item = {"ip": ip_real, "mac": mac, "model": _text(alvo.get("model")), "ok": bool(r.get("ok"))}
        if r.get("ok") and eh_hikvision:
            # A ativacao devolve MAC/modelo que so existiam depois dela.
            mac = _norm_mac(r.get("mac")) or mac
            item["mac"] = mac
            item["model"] = _text(r.get("model")) or item["model"]
            item["pos_ativacao"] = _pos_ativacao_hikvision(
                connector_id, ip_real, senha, perguntas, pedir_dhcp)
        if r.get("ok"):
            ativadas += 1
            if salvar:
                # Senha no cofre por MAC (e como padrao do site, se for a
                # primeira): a camera ja nasce conhecida pro snapshot e pro
                # resto do sistema, sem ninguem redigitar.
                try:
                    if mac:
                        save_camera_credential(mac, site, usuario_criado, senha)
                    else:
                        item["warning"] = ("ativou, mas a camera nao informou o MAC -- "
                                           "a senha nao foi para o cofre")
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
