"""Rede do gravador: ler, conferir, trocar IP/mascara/gateway/DNS/portas e
reiniciar -- sem perder o gravador.

Trocar o endereco de um gravador em producao e a unica mudanca sem volta pelo
SightOps: se ele nao responder no endereco novo, nao ha mais por onde falar com
ele para desfazer. Por isso:
  1. `conferir` barra o que certamente quebra: IP fora das redes que o conector
     leva (o IP virtual nao existiria), IP ja em uso na tabela ARP do conector,
     gateway fora da mascara, portas repetidas;
  2. `aplicar` guarda a configuracao de antes, grava UMA tabela (Network), e
     procura o gravador no endereco novo pelo mesmo conector;
  3. achou: atualiza inventario (NVR e DVR), porta e credencial juntos -- antes
     so o `host` do inventario de DVR mudava e o ao vivo, a Investigacao e a
     senha salva ficavam presos no endereco velho.

A aplicacao roda em segundo plano (job), porque a procura leva ate 2 min e o
Cloudflare corta pedido com mais de 100 s.

Intelbras (configManager Network). Hikvision: ErroDriver, nao foi provado.
"""
from __future__ import annotations

import contextvars
import ipaddress
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from app.services.recorder_driver import ErroDriver, Gravador, _pares

# chave do configManager -> nome do campo na tela
CAMPOS = {
    "ip": "Network.eth0.IPAddress",
    "mascara": "Network.eth0.SubnetMask",
    "gateway": "Network.eth0.DefaultGateway",
    "dns1": "Network.eth0.DnsServers[0]",
    "dns2": "Network.eth0.DnsServers[1]",
    # Portas NAO ficam na tabela Network: cada servico tem a sua (conferido no
    # NVD 7132: Web.Port=8081, RTSP.Port=554, DVRIP.TCPPort=30000, Https.Port=443).
    "http": "Web.Port",
    "tcp": "DVRIP.TCPPort",
    "https": "Https.Port",
    "rtsp": "RTSP.Port",
}
TABELAS = ("Network", "Web", "RTSP", "DVRIP", "Https")
NOMES = {"ip": "IP", "mascara": "Máscara", "gateway": "Gateway", "dns1": "DNS 1", "dns2": "DNS 2",
         "http": "Porta web (HTTP)", "tcp": "Porta SDK (TCP)", "https": "Porta HTTPS", "rtsp": "Porta de vídeo (RTSP)"}
PORTAS = ("http", "tcp", "https", "rtsp")
ESPERA_S = 120


def _so_intelbras(g: Gravador) -> None:
    if g.marca != "intelbras":
        raise ErroDriver(f"mudar a rede ainda nao esta disponivel para {g.marca}")


def ler_rede(g: Gravador) -> Dict[str, str]:
    """IP, mascara, gateway, DNS, MAC, DHCP e portas, como o gravador diz."""
    _so_intelbras(g)
    p: Dict[str, str] = {}
    for tabela in TABELAS:
        try:
            p.update(_pares(g._get(f"/cgi-bin/configManager.cgi?action=getConfig&name={tabela}")))
        except ErroDriver:
            if tabela == "Network":
                raise
    if not p.get("Network.eth0.IPAddress"):
        raise ErroDriver("o gravador nao devolveu a configuracao de rede")
    out = {k: str(p.get(chave, "")).strip() for k, chave in CAMPOS.items()}
    out["mac"] = str(p.get("Network.eth0.PhysicalAddress", "")).strip()
    out["dhcp"] = str(p.get("Network.eth0.DhcpEnable", "")).strip().lower() == "true"
    out["mtu"] = str(p.get("Network.eth0.MTU", "")).strip()
    return out


def _ip(v: str) -> Optional[ipaddress.IPv4Address]:
    try:
        return ipaddress.IPv4Address(str(v or "").strip())
    except ValueError:
        return None


def _redes_do_conector(conector: str) -> list:
    from app.services.connector_routing_vnat import _load_map
    try:
        return [real for real, _virt in (_load_map().get(str(conector or ""), []) or [])]
    except Exception:
        return []


def conferir(atual: Dict[str, str], novo: Dict[str, str], conector: str = "",
             arp: Optional[List[tuple]] = None, redes: Optional[list] = None) -> List[Dict[str, Any]]:
    """Lista de conferencias. `grave` = o botao fica travado."""
    out: List[Dict[str, Any]] = []

    def item(ok: bool, titulo: str, texto: str, grave: bool = True):
        out.append({"ok": ok, "grave": (not ok) and grave, "titulo": titulo, "texto": texto})

    ip, masc, gw = _ip(novo.get("ip")), _ip(novo.get("mascara")), _ip(novo.get("gateway"))
    item(bool(ip), "IP válido", f"{novo.get('ip')} é um endereço IPv4." if ip else f"“{novo.get('ip')}” não é um IP.")
    rede = None
    if ip and masc:
        try:
            rede = ipaddress.IPv4Network(f"{ip}/{masc}", strict=False)
        except ValueError:
            rede = None
    item(bool(rede), "Máscara válida", f"rede {rede}." if rede else f"“{novo.get('mascara')}” não é uma máscara.")
    if rede and gw:
        item(gw in rede and gw != ip, "Gateway na mesma rede",
             "O gateway fica dentro da rede da máscara." if gw in rede and gw != ip
             else f"{gw} fica fora de {rede} (ou é o próprio IP): o gravador perde a saída.")
    elif novo.get("gateway"):
        item(False, "Gateway válido", f"“{novo.get('gateway')}” não é um IP.")

    for k in ("dns1", "dns2"):
        v = str(novo.get(k) or "").strip()
        if v and not _ip(v):
            item(False, NOMES[k], f"“{v}” não é um IP.")

    portas = {}
    for k in PORTAS:
        v = str(novo.get(k) or "").strip()
        if not v:
            continue
        if not v.isdigit() or not (0 < int(v) < 65536):
            item(False, NOMES[k], f"“{v}” não é uma porta (1 a 65535).")
            continue
        portas.setdefault(int(v), []).append(NOMES[k])
    repetidas = [f"{p}: {', '.join(n)}" for p, n in portas.items() if len(n) > 1]
    item(not repetidas, "Portas sem conflito", "Cada serviço numa porta diferente." if not repetidas
         else "Mesma porta em dois serviços — " + "; ".join(repetidas))

    mudou_ip = ip and str(ip) != str(atual.get("ip") or "")
    mudou_web = str(novo.get("http") or "").strip() not in ("", str(atual.get("http") or ""))
    if mudou_ip and mudou_web:
        # Cada tabela e um pedido: depois do primeiro o SightOps ja nao alcanca
        # o gravador para mandar o segundo.
        item(False, "IP e porta web em vezes separadas",
             "Trocar o IP e a porta web juntos deixaria o gravador pela metade. Troque um, confira, depois o outro.")
    if conector and ip:
        redes = _redes_do_conector(conector) if redes is None else redes
        if redes:
            dentro = any(ip in r for r in redes)
            item(dentro, "Alcançável pelo conector",
                 f"{ip} está dentro das redes que o conector leva ({', '.join(str(r) for r in redes)})." if dentro
                 else f"{ip} está FORA das redes do conector ({', '.join(str(r) for r in redes)}): o SightOps perderia o gravador. Ajuste o conector antes.")
    if mudou_ip and arp is not None:
        dono = next((mac for a, mac in arp if a == str(ip)), None)
        meu = str(atual.get("mac") or "").lower().replace("-", ":")
        livre = dono is None or (meu and dono.lower().replace("-", ":") == meu)
        item(livre, "IP livre", "Ninguém respondeu nesse IP na tabela ARP do conector." if livre
             else f"{ip} já está em uso na rede (MAC {dono}): daria IP duplicado.")
    elif mudou_ip:
        item(False, "IP livre", "Sem a tabela ARP do conector não dá para saber se o IP está livre — confira no local.", grave=False)

    if str(atual.get("ip") or "") and str(novo.get("ip") or "") == str(atual.get("ip")) and not any(
            str(novo.get(k) or "") != str(atual.get(k) or "") for k in CAMPOS):
        item(False, "Há algo para mudar", "Nada foi alterado.", grave=True)
    return out


def mudancas(atual: Dict[str, str], novo: Dict[str, str]) -> List[Dict[str, str]]:
    out = []
    for k, chave in CAMPOS.items():
        de, para = str(atual.get(k) or ""), str(novo.get(k) or "").strip()
        # Vazio = "nao mexer", menos no DNS (que pode ser apagado de proposito).
        if not para and not k.startswith("dns"):
            continue
        if k in novo and para != de and not (k.startswith("dns") and not para and not de):
            out.append({"campo": k, "o": NOMES[k], "chave": chave, "de": de, "para": para})
    return out


# ------------------------------------------------------------------ jobs
_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def _passo(job: Dict[str, Any], texto: str, detalhe: str = "") -> None:
    with _LOCK:
        job["passos"].append({"t": texto, "s": detalhe, "em": datetime.now().isoformat(timespec="seconds")})


def situacao(job_id: str, tenant: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job or job.get("tenant") != tenant:
            return None   # tarefa de outro cliente nao existe para este
        return {k: v for k, v in job.items() if not k.startswith("_")}


def _novo_job(tenant: str, tipo: str, host: str) -> Dict[str, Any]:
    job = {"id": uuid.uuid4().hex[:12], "tenant": tenant, "tipo": tipo, "host": host,
           "estado": "rodando", "passos": [], "inicio": time.time()}
    with _LOCK:
        for k in [k for k, j in _JOBS.items() if time.time() - j.get("inicio", 0) > 3600]:
            _JOBS.pop(k, None)
        _JOBS[job["id"]] = job
    return job


def _procurar(abrir: Callable[[], Gravador], espera_s: float, intervalo_s: float = 5.0,
              dormir: Callable[[float], None] = time.sleep, relogio: Callable[[], float] = time.monotonic) -> Optional[Gravador]:
    """Tenta abrir o gravador ate `espera_s`; devolve o Gravador ou None."""
    limite = relogio() + espera_s
    while True:
        try:
            g = abrir()
            g.relogio()
            return g
        except Exception:
            pass
        if relogio() >= limite:
            return None
        dormir(intervalo_s)


def atualizar_inventario(host_antigo: str, porta_antiga: int, host_novo: str, porta_nova: int,
                         user: str, senha: str, conector: str = "") -> Dict[str, int]:
    """Endereco novo em tudo que guarda o gravador: inventario NVR e DVR
    (host, ip, nvr_ip, http_port) e a senha salva (que e chaveada por host+porta)."""
    from app.api.endpoints import dvr as _dvr
    from app.api.endpoints import nvr as _nvr
    from app.services.recorder_credentials import esquecer_recorder_credential, save_recorder_credential

    contas = {}
    sobrou = False   # outra linha (outro site) ainda usa o endereco antigo
    for nome, mod in (("nvr", _nvr), ("dvr", _dvr)):
        rows = mod._read_rows()
        n = 0
        for r in rows:
            if str(r.get("host") or r.get("ip") or "").strip() != host_antigo:
                continue
            # O mesmo IP existe em sites diferentes do mesmo cliente, atras de
            # outro conector: so a linha DESTE gravador muda.
            if str(mod._rec_row_connector(r) or "") != str(conector or ""):
                sobrou = True
                continue
            for campo in ("host", "ip", "nvr_ip"):
                if str(r.get(campo) or "").strip() == host_antigo:
                    r[campo] = host_novo
            if porta_nova and int(r.get("http_port") or 80) == int(porta_antiga or 80):
                r["http_port"] = int(porta_nova)
            n += 1
        if n:
            mod._write_rows(rows)
        contas[nome] = n
    save_recorder_credential(host_novo, porta_nova, user, senha)
    # A senha salva e por host+porta, sem conector: so esquece a antiga se
    # nenhum outro gravador do cliente usa aquele endereco.
    if not sobrou and (host_novo, int(porta_nova)) != (host_antigo, int(porta_antiga or 80)):
        esquecer_recorder_credential(host_antigo, porta_antiga)
    return contas


def iniciar_aplicacao(g: Gravador, novo: Dict[str, str], conector: str, base_registros: Path,
                      tenant: str, por: str, porta_atual: int, abrir_novo: Callable[[str, int], Gravador],
                      registrar: Callable[[Dict[str, Any]], None], espera_s: float = ESPERA_S) -> Dict[str, Any]:
    """Confere de novo (o valor vem da tela, mas a decisao e daqui), grava e
    procura em segundo plano. Devolve o job."""
    from app.services.recorder_xray import _arp_do_conector

    _so_intelbras(g)
    atual = ler_rede(g)
    checks = conferir(atual, novo, conector, arp=_arp_do_conector(conector) if conector else None)
    if any(c["grave"] for c in checks):
        raise ErroDriver("; ".join(c["texto"] for c in checks if c["grave"]))
    mud = mudancas(atual, novo)
    if not mud:
        raise ErroDriver("nada para mudar")

    job = _novo_job(tenant, "rede", g.host)
    base_registros.mkdir(parents=True, exist_ok=True)
    backup = base_registros / f"rede-{g.host.replace(':', '_')}-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    _passo(job, "Configuração de rede atual guardada", backup.name)

    host_novo = str(novo.get("ip") or atual["ip"]).strip()
    porta_nova = int(novo.get("http") or atual.get("http") or porta_atual or 80)
    ctx = contextvars.copy_context()

    # A Intelbras aplica so a PRIMEIRA tabela de cada setConfig: um pedido por
    # tabela. O que corta o acesso do SightOps (IP na Network, porta na Web) vai
    # por ultimo -- depois dele nao ha mais por onde mandar o resto.
    def corta(tabela: str) -> bool:
        return any(m["campo"] in ("ip", "mascara", "http") for m in mud if m["chave"].split(".", 1)[0] == tabela)
    tabelas = sorted({m["chave"].split(".", 1)[0] for m in mud}, key=lambda t: (corta(t), TABELAS.index(t)))

    def trabalho():
        try:
            for tabela in tabelas:
                grupo = [m for m in mud if m["chave"].split(".", 1)[0] == tabela]
                qs = "&".join(f"{quote(m['chave'], safe='[]._')}={quote(m['para'], safe='')}" for m in grupo)
                try:
                    txt = g._get(f"/cgi-bin/configManager.cgi?action=setConfig&{qs}")
                    if txt.strip() and not txt.strip().upper().startswith("OK"):
                        raise ErroDriver(f"o gravador recusou {tabela}: {txt.strip()[:120]}")
                    _passo(job, "Gravado: " + ", ".join(m["o"] for m in grupo), "OK")
                except ErroDriver as exc:
                    # Trocar IP/porta corta a resposta no meio: nao e prova de falha.
                    if "recusou" in str(exc) or not corta(tabela):
                        raise
                    _passo(job, "Gravador parou de responder logo depois de gravar", "esperado ao trocar endereço")
            achou = _procurar(lambda: abrir_novo(host_novo, porta_nova), espera_s)
            if not achou and (host_novo, porta_nova) != (atual["ip"], int(porta_atual)):
                # Nao apareceu no novo: se ainda responde no antigo, a mudanca
                # nao pegou -- e muito diferente de "perdido, ir ao local".
                velho = _procurar(lambda: abrir_novo(atual["ip"], int(porta_atual)), 10)
                if velho:
                    with _LOCK:
                        job.update(estado="nao_aplicou", erro=(
                            f"O gravador continua em {atual['ip']}:{porta_atual}: a mudança não pegou."))
                    registrar({"titulo": f"Rede: mudança não pegou ({atual['ip']})", "ok": False,
                               "mudancas": mud, "backup": backup.name})
                    return
            if not achou:
                with _LOCK:
                    job.update(estado="perdido", erro=(
                        f"O gravador não respondeu em {host_novo}:{porta_nova} em {int(espera_s)} s. "
                        f"Endereço antigo: {atual['ip']}:{porta_atual}. É preciso ir ao local."))
                registrar({"titulo": f"Rede: {atual['ip']} → {host_novo} (sem resposta)", "ok": False,
                           "mudancas": mud, "backup": backup.name})
                return
            depois = ler_rede(achou)
            nao = [m["o"] for m in mud if str(depois.get(m["campo"]) or "") != m["para"]]
            _passo(job, "Achado no endereço novo pelo conector", f"{host_novo}:{porta_nova}")
            contas = atualizar_inventario(atual["ip"], porta_atual, host_novo, porta_nova, g.user, g.password, conector)
            _passo(job, "Inventário, porta e senha salva atualizados",
                   f"NVR {contas.get('nvr', 0)} · DVR {contas.get('dvr', 0)} linha(s)")
            resumo = ", ".join("%s %s → %s" % (m["o"], m["de"] or "(vazio)", m["para"]) for m in mud)
            registrar({"titulo": f"Rede: {resumo}", "ok": not nao, "mudancas": mud, "backup": backup.name})
            with _LOCK:
                job.update(estado="pronto" if not nao else "parcial", nao_pegaram=nao,
                           host=host_novo, http_port=porta_nova)
        except Exception as exc:
            with _LOCK:
                job.update(estado="erro", erro=str(exc))

    threading.Thread(target=lambda: ctx.run(trabalho), daemon=True).start()
    return {k: v for k, v in job.items() if not k.startswith("_")}


def iniciar_reinicio(g: Gravador, tenant: str, abrir: Callable[[], Gravador],
                     registrar: Callable[[Dict[str, Any]], None], espera_s: float = 240) -> Dict[str, Any]:
    if g.marca != "intelbras":
        raise ErroDriver(f"reiniciar ainda nao esta disponivel para {g.marca}")
    caminho = "/cgi-bin/magicBox.cgi?action=reboot"
    job = _novo_job(tenant, "reinicio", g.host)
    ctx = contextvars.copy_context()

    def trabalho():
        try:
            try:
                g._get(caminho)
                _passo(job, "Pedido de reinício aceito", "")
            except ErroDriver as exc:
                if "recusou usuario" in str(exc):
                    raise
                _passo(job, "O gravador caiu logo após o pedido", "esperado")
            time.sleep(20)   # nao achar o gravador ainda de pe antes de cair
            volta = _procurar(abrir, espera_s, intervalo_s=8)
            registrar({"titulo": "Gravador reiniciado" if volta else "Gravador reiniciado e não voltou", "ok": bool(volta)})
            with _LOCK:
                if volta:
                    _passo(job, "Gravador de volta", "")
                    job.update(estado="pronto")
                else:
                    job.update(estado="perdido", erro=f"O gravador não voltou em {int(espera_s)} s.")
        except Exception as exc:
            with _LOCK:
                job.update(estado="erro", erro=str(exc))

    threading.Thread(target=lambda: ctx.run(trabalho), daemon=True).start()
    return {k: v for k, v in job.items() if not k.startswith("_")}
