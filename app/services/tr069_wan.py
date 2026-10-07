"""Modo de operacao da ONT por TR-069: os servicos (WANs) e os cenarios prontos.

Um so mecanismo para editar, criar, remover e aplicar cenario: a tela manda a
lista de servicos DESEJADA (sem a gerencia) e `planejar` compara com o que a
ONT tem, devolvendo os passos -- editar o que da para reaproveitar, remover o
que sobrou, criar o que falta. Os cenarios prontos sao so formas de preencher
essa lista no frontend.

Regras que protegem o cliente:

- **A gerencia nunca entra no plano.** E a WAN por onde o servidor fala com a
  ONU (o IP do ConnectionRequestURL). Apagar ou trocar a VLAN dela tira a ONU
  do TR-069 e so se resolve em campo.
- **So fabricante com mapa.** VLAN e portas sao parametros de fabricante
  (X_<OUI>_...). Hoje: Intelbras (X_ITBS_, medido na 140PoE da SIERRA em
  07/10/2026). Fabricante sem mapa aparece so para leitura.
- **Execucao passo a passo, conferida.** Cada passo espera a ONU aplicar; o
  primeiro que falhar ou ficar na fila PARA o plano e diz exatamente o que ja
  foi feito.
"""
from __future__ import annotations

import contextvars
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

RAIZ_WAN = "InternetGatewayDevice.WANDevice.1.WANConnectionDevice"
FUNCOES = ("cameras", "internet", "iptv", "voip", "outro")
MODOS = ("bridge", "dhcp", "pppoe")

# Nome dos parametros por fabricante. Detectado pela PRESENCA dos campos na
# WAN (nao pelo OUI): o mesmo firmware Realtek aparece com OUIs diferentes.
PERFIS = {
    "intelbras": {
        "detecta": "X_ITBS_VlanMuxID",
        "vlan_on": "X_ITBS_VlanEnable", "vlan": "X_ITBS_VlanMuxID", "prioridade": "X_ITBS_VlanMux8021p",
        "portas": "X_ITBS_LanInterface", "mcast_vlan": "X_ITBS_MulticastVlan", "igmp": "X_ITBS_IGMPProxyEnable",
        # X_RTK_ServiceType: 2 na WAN de gerencia e 1 na bridge da 140PoE. So
        # gravamos 1 (dados) em servico novo; o existente fica como esta.
        "servico": "X_RTK_ServiceType", "servico_dados": 1,
    },
}

NOME_FUNCAO = {"cameras": "Câmeras", "internet": "Internet", "iptv": "IPTV", "voip": "VoIP", "outro": "Serviço"}


# Nome gravado NA ONU: sem acento (firmware de ONU costuma estragar UTF-8).
_ASCII = {"cameras": "Cameras", "internet": "Internet", "iptv": "IPTV", "voip": "VoIP", "outro": "Servico"}


class WanError(ValueError):
    pass


def _no(doc: Any, caminho: str) -> Any:
    cur = doc
    for parte in caminho.split("."):
        if not isinstance(cur, dict) or parte not in cur:
            return None
        cur = cur[parte]
    return cur


def _v(no: Any, chave: str) -> Any:
    alvo = _no(no, chave)
    return alvo.get("_value") if isinstance(alvo, dict) else None


def _inst(no: Any) -> List[Tuple[int, Dict[str, Any]]]:
    if not isinstance(no, dict):
        return []
    return sorted((int(k), v) for k, v in no.items() if k.isdigit() and isinstance(v, dict))


def _int(v: Any) -> Optional[int]:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def perfil_da_wan(no: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for nome, p in PERFIS.items():
        if isinstance(no, dict) and p["detecta"] in no:
            return {"nome": nome, **p}
    return None


def portas_lan(doc: Dict[str, Any]) -> List[str]:
    n = len(_inst(_no(doc, "InternetGatewayDevice.LANDevice.1.LANEthernetInterfaceConfig")))
    return [f"LAN{i}" for i in range(1, n + 1)]


def _host_de_gerencia(doc: Dict[str, Any]) -> str:
    url = str(_v(doc, "InternetGatewayDevice.ManagementServer.ConnectionRequestURL") or "")
    m = re.match(r"^\w+://\[?([^\]/:]+)", url)
    return m.group(1) if m else ""


def servicos(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """WANs da ONT (TR-098), com a de gerencia marcada e travada."""
    if "InternetGatewayDevice" not in doc:
        return []
    gerencia_ip = _host_de_gerencia(doc)
    out = []
    for c, cd in _inst(_no(doc, RAIZ_WAN)):
        for tipo, chave in (("ip", "WANIPConnection"), ("ppp", "WANPPPConnection")):
            for i, w in _inst(cd.get(chave)):
                perfil = perfil_da_wan(w)
                tipo_conexao = str(_v(w, "ConnectionType") or "")
                modo = "pppoe" if tipo == "ppp" else ("bridge" if tipo_conexao == "IP_Bridged" else "dhcp")
                ip = _v(w, "ExternalIPAddress")
                gerencia = bool(gerencia_ip) and ip == gerencia_ip
                portas = []
                if perfil:
                    portas = [p.strip().upper() for p in str(_v(w, perfil["portas"]) or "").split(",") if p.strip()]
                out.append({
                    "id": f"{RAIZ_WAN}.{c}.{chave}.{i}", "conexao": f"{RAIZ_WAN}.{c}",
                    "conexoes_no_grupo": len(_inst(cd.get("WANIPConnection"))) + len(_inst(cd.get("WANPPPConnection"))),
                    "tipo": tipo, "modo": modo, "nome": _v(w, "Name") or "",
                    "habilitada": bool(_v(w, "Enable")), "status": _v(w, "ConnectionStatus"), "ip": ip,
                    "vlan": _int(_v(w, perfil["vlan"])) if perfil else None,
                    "vlan_on": bool(_v(w, perfil["vlan_on"])) if perfil else False,
                    "prioridade": _int(_v(w, perfil["prioridade"])) if perfil else None,
                    "portas": portas, "nat": bool(_v(w, "NATEnabled")),
                    "usuario": _v(w, "Username") if tipo == "ppp" else None,
                    "mcast_vlan": _int(_v(w, perfil["mcast_vlan"])) if perfil else None,
                    "igmp": bool(_v(w, perfil["igmp"])) if perfil else False,
                    "gerencia": gerencia,
                    "funcao": "gerencia" if gerencia else _funcao(_v(w, "Name"), modo, portas),
                    "perfil": perfil["nome"] if perfil else None,
                    "editavel": bool(perfil) and not gerencia,
                    "motivo": ("e por este servico que o servidor fala com a ONU" if gerencia
                               else "" if perfil else "fabricante ainda sem mapa de VLAN e portas"),
                })
    return out


def _funcao(nome: Any, modo: str, portas: List[str]) -> str:
    texto = str(nome or "").lower()
    for chave, palavras in (("cameras", ("camera", "cftv")), ("iptv", ("iptv", "tv")),
                            ("voip", ("voip", "voz")), ("internet", ("internet", "pppoe"))):
        if any(p in texto for p in palavras):
            return chave
    if modo == "pppoe":
        return "internet"
    return "outro"


def cenario_atual(lista: List[Dict[str, Any]]) -> Dict[str, str]:
    dados = [s for s in lista if not s["gerencia"]]
    tem_gerencia = any(s["gerencia"] for s in lista)
    if not dados:
        return {"chave": "so_gerencia", "nome": "Só gerência", "texto": "A ONT só tem o serviço de gerência."}
    modos = {s["modo"] for s in dados}
    if len(dados) > 1 and len(modos) > 1:
        return {"chave": "multisservico", "nome": "Multisserviço",
                "texto": " + ".join(f"{s['modo']} VLAN {s['vlan'] or '?'}" for s in dados)}
    s = dados[0]
    if modos == {"bridge"}:
        nome = "Câmeras em bridge (VEIP)" if tem_gerencia else "Bridge total"
        vlans = ", ".join(str(x["vlan"]) for x in dados if x["vlan"])
        return {"chave": "cameras_bridge" if tem_gerencia else "bridge_total", "nome": nome,
                "texto": f"Bridge na VLAN {vlans or '?'} em {', '.join(s['portas']) or 'nenhuma porta'}."}
    if modos == {"pppoe"}:
        return {"chave": "internet_pppoe", "nome": "Internet do cliente (PPPoE)",
                "texto": f"PPPoE na VLAN {s['vlan'] or '?'}."}
    return {"chave": "roteador_ipoe", "nome": "Roteador IPoE", "texto": f"Roteador DHCP na VLAN {s['vlan'] or '?'}."}


# --------------------------------------------------------------------------- #
# Planejamento (puro: nao fala com ninguem)
# --------------------------------------------------------------------------- #

def _normalizar_desejado(d: Dict[str, Any], lans: List[str]) -> Dict[str, Any]:
    modo = str(d.get("modo") or "").lower()
    if modo not in MODOS:
        raise WanError("modo do servico precisa ser bridge, dhcp ou pppoe")
    funcao = str(d.get("funcao") or "outro").lower()
    if funcao not in FUNCOES:
        raise WanError("funcao desconhecida")
    vlan = _int(d.get("vlan"))
    if not vlan or vlan > 4094:
        raise WanError("VLAN precisa ser de 1 a 4094")
    prio = d.get("prioridade")
    prio = None if prio in (None, "", -1, "-1") else int(prio)
    if prio is not None and not 0 <= prio <= 7:
        raise WanError("prioridade 802.1p vai de 0 a 7")
    portas = [str(p).strip().upper() for p in (d.get("portas") or []) if str(p).strip()]
    fora = [p for p in portas if p not in lans]
    if fora:
        raise WanError(f"porta inexistente nesta ONT: {', '.join(fora)}")
    out = {
        "id": d.get("id") or None, "funcao": funcao, "modo": modo, "vlan": vlan, "prioridade": prio,
        "portas": portas, "nat": bool(d.get("nat", modo != "bridge")) and modo != "bridge",
        "mcast_vlan": _int(d.get("mcast_vlan")), "igmp": bool(d.get("igmp")),
        "nome": str(d.get("nome") or f"SightOps {_ASCII[funcao]}")[:32],
        "usuario": str(d.get("usuario") or "").strip(), "senha": str(d.get("senha") or ""),
    }
    if modo == "pppoe" and not out["usuario"]:
        raise WanError("PPPoE precisa de usuario")
    return out


def _valores(s: Dict[str, Any], perfil: Dict[str, Any], novo: bool, atual: Optional[Dict[str, Any]] = None) -> List[list]:
    base = s["id_destino"]
    v: List[list] = []

    def put(chave, valor, tipo):
        v.append([f"{base}.{chave}", valor, tipo])

    if s["modo"] != "pppoe":
        put("ConnectionType", "IP_Bridged" if s["modo"] == "bridge" else "IP_Routed", "xsd:string")
        if s["modo"] == "dhcp":
            put("AddressingType", "DHCP", "xsd:string")
    else:
        put("ConnectionType", "IP_Routed", "xsd:string")
        put("Username", s["usuario"], "xsd:string")
        if s["senha"]:
            put("Password", s["senha"], "xsd:string")
    put("NATEnabled", bool(s["nat"]), "xsd:boolean")
    put(perfil["vlan_on"], True, "xsd:boolean")
    put(perfil["vlan"], s["vlan"], "xsd:int")
    put(perfil["prioridade"], -1 if s["prioridade"] is None else s["prioridade"], "xsd:int")
    put(perfil["portas"], ",".join(s["portas"]), "xsd:string")
    put(perfil["mcast_vlan"], s["mcast_vlan"] or -1, "xsd:int")
    put(perfil["igmp"], bool(s["igmp"]), "xsd:boolean")
    if novo:
        put("Name", s["nome"], "xsd:string")
        put(perfil["servico"], perfil["servico_dados"], "xsd:int")
        put("Enable", True, "xsd:boolean")
    if atual is not None:
        # editar: so manda o que mudou
        antes = {
            "ConnectionType": {"bridge": "IP_Bridged", "dhcp": "IP_Routed", "pppoe": "IP_Routed"}[atual["modo"]],
            "NATEnabled": atual["nat"], perfil["vlan_on"]: atual["vlan_on"], perfil["vlan"]: atual["vlan"],
            perfil["prioridade"]: -1 if atual["prioridade"] is None else atual["prioridade"],
            perfil["portas"]: ",".join(atual["portas"]), perfil["mcast_vlan"]: atual["mcast_vlan"] or -1,
            perfil["igmp"]: atual["igmp"], "Username": atual.get("usuario"),
        }
        v = [x for x in v if x[0].rsplit(".", 1)[1] not in antes or antes[x[0].rsplit(".", 1)[1]] != x[1]]
    return v


def _descrever(s: Dict[str, Any]) -> str:
    modo = {"bridge": "bridge", "dhcp": "roteador DHCP", "pppoe": "PPPoE"}[s["modo"]]
    portas = ", ".join(s["portas"]) or "nenhuma porta"
    extra = f", prioridade {s['prioridade']}" if s.get("prioridade") is not None else ""
    return f"{NOME_FUNCAO.get(s['funcao'], 'Servico')} · {modo} VLAN {s['vlan']}{extra} · {portas}"


def planejar(doc: Dict[str, Any], desejados: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Passos para a ONT ficar com `desejados` (a gerencia fica de fora e intacta)."""
    atuais = servicos(doc)
    gerencia = [s for s in atuais if s["gerencia"]]
    if not gerencia:
        raise WanError("nao achei o servico de gerencia desta ONU; por seguranca nada sera alterado pela tela")
    dados = [s for s in atuais if not s["gerencia"]]
    if any(not s["editavel"] for s in dados):
        raise WanError("este fabricante ainda nao tem mapa de VLAN e portas: so leitura por enquanto")
    perfil = next((p for p in PERFIS.values() if p["detecta"] in (_no(doc, gerencia[0]["id"]) or {})), None)
    if not perfil:
        raise WanError("fabricante ainda sem mapa de VLAN e portas: so leitura por enquanto")
    lans = portas_lan(doc)
    alvo = [_normalizar_desejado(d, lans) for d in desejados]

    vlans_usadas = [s["vlan"] for s in alvo]
    if len(set(vlans_usadas)) != len(vlans_usadas):
        raise WanError("dois servicos com a mesma VLAN")
    if gerencia[0]["vlan"] in vlans_usadas:
        raise WanError(f"a VLAN {gerencia[0]['vlan']} e da gerencia: use outra")
    vistas: Dict[str, str] = {}
    for s in alvo:
        for p in s["portas"]:
            if p in vistas:
                raise WanError(f"a porta {p} esta em dois servicos ({vistas[p]} e VLAN {s['vlan']})")
            vistas[p] = f"VLAN {s['vlan']}"

    por_id = {s["id"]: s for s in dados}
    passos: List[Dict[str, Any]] = []
    mantidos = {s["id"] for s in alvo if s["id"] in por_id}
    for s in alvo:
        if s["id"] and s["id"] not in por_id:
            raise WanError("um dos servicos mudou na ONU desde a ultima leitura; leia de novo")

    # 1) remover o que nao fica (libera portas e VLAN para os novos)
    for s in dados:
        if s["id"] not in mantidos:
            alvo_obj = s["conexao"] if s["conexoes_no_grupo"] <= 1 else s["id"]
            passos.append({"op": "remover", "objeto": alvo_obj, "texto": "Remover " + _descrever(s)})
    # 2) editar / 3) criar
    for s in alvo:
        atual = por_id.get(s["id"]) if s["id"] else None
        if atual and (atual["tipo"] == "ppp") == (s["modo"] == "pppoe"):
            s["id_destino"] = atual["id"]
            valores = _valores(s, perfil, novo=False, atual=atual)
            if valores:
                passos.append({"op": "editar", "valores": valores,
                               "texto": f"Alterar {_descrever(atual)} → {_descrever(s)}"})
        else:
            if atual:
                passos.insert(0, {"op": "remover", "objeto": atual["conexao"] if atual["conexoes_no_grupo"] <= 1 else atual["id"],
                                  "texto": "Remover " + _descrever(atual) + " (troca de tipo)"})
            passos.append({"op": "criar", "tipo": "ppp" if s["modo"] == "pppoe" else "ip", "servico": s,
                           "texto": "Criar " + _descrever(s)})

    avisos = []
    portas_antes = {p for s in dados for p in s["portas"]}
    portas_depois = {p for s in alvo for p in s["portas"]}
    saem = sorted(portas_antes - portas_depois)
    if saem:
        avisos.append(f"{', '.join(saem)} deixa(m) de passar qualquer VLAN: o que estiver ligado ali fica sem rede.")
    if any(p["op"] == "remover" for p in passos) and any(p["op"] == "criar" for p in passos):
        avisos.append("Entre remover e criar, as portas envolvidas ficam sem rede por alguns segundos.")
    return {
        "mantida": f"Gerência TR-069 · VLAN {gerencia[0]['vlan'] or '?'} · mantida",
        "passos": [{k: v for k, v in p.items() if k in ("op", "texto")} for p in passos],
        "avisos": avisos, "_passos": passos,
    }


# --------------------------------------------------------------------------- #
# Execucao (fala com o GenieACS, passo a passo)
# --------------------------------------------------------------------------- #

_JOBS: Dict[Tuple[str, str], Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _instancias_em(doc: Dict[str, Any], caminho: str) -> set:
    return {k for k, _ in _inst(_no(doc, caminho))}


def executar_plano(tr, serial: str, desejados: List[Dict[str, Any]], autor: str) -> Dict[str, Any]:
    """Dispara em segundo plano; devolve o id para acompanhar."""
    from app.core.tenant_context import get_current_tenant_slug

    doc, onu = tr._documento_do_cliente(serial)
    plano = planejar(doc, desejados)
    if not plano["_passos"]:
        return {"ok": True, "job": None, "estado": "nada_a_fazer", "passos": []}
    if tr.estado(tr.resumo_do_dispositivo(doc)) != "gerenciada":
        raise WanError("a ONU esta sem contato: aplique quando ela voltar a falar com o servidor")
    tenant = get_current_tenant_slug()
    job_id = uuid.uuid4().hex[:12]
    job = {"id": job_id, "serial": tr.normalizar_serial(serial), "estado": "rodando", "feitos": [],
           "total": len(plano["_passos"]), "erro": "", "inicio": datetime.now(timezone.utc).isoformat()}
    with _JOBS_LOCK:
        _JOBS[(tenant, job_id)] = job
    ctx = contextvars.copy_context()  # leva o tenant para a thread
    threading.Thread(target=ctx.run, args=(_rodar, tr, serial, plano, onu, job, autor), daemon=True).start()
    return {"ok": True, "job": job_id, "estado": "rodando", "passos": plano["passos"]}


def ver_job(job_id: str) -> Optional[Dict[str, Any]]:
    from app.core.tenant_context import get_current_tenant_slug

    with _JOBS_LOCK:
        job = _JOBS.get((get_current_tenant_slug(), job_id))
        return dict(job) if job else None


def _rodar(tr, serial, plano, onu, job, autor) -> None:
    conector = str(onu.get("connector_id") or onu.get("remote_connector_id") or "")

    def tarefa(t: Dict[str, Any]) -> str:
        doc, _ = tr._documento_do_cliente(serial)
        device_id = doc["_id"]
        criada = tr._nbi("POST", tr._device_path(device_id) + "/tasks", body=t) or {}
        chamou, motivo = tr._chamar_onu(doc, conector)
        if not chamou:
            return "na_fila: " + motivo
        return tr._esperar_tarefa(str(criada.get("_id") or ""), device_id, limite_s=40.0)

    def recarregar(obj: str) -> Dict[str, Any]:
        res = tarefa({"name": "refreshObject", "objectName": obj})
        if res != "aplicada":
            raise WanError(f"nao consegui reler {obj} ({res})")
        return tr._documento_do_cliente(serial)[0]

    try:
        for passo in plano["_passos"]:
            if passo["op"] == "remover":
                res = tarefa({"name": "deleteObject", "objectName": passo["objeto"]})
            elif passo["op"] == "editar":
                res = tarefa({"name": "setParameterValues", "parameterValues": passo["valores"]})
            else:
                doc = recarregar(RAIZ_WAN)
                antes = _instancias_em(doc, RAIZ_WAN)
                res = tarefa({"name": "addObject", "objectName": RAIZ_WAN})
                if res == "aplicada":
                    doc = recarregar(RAIZ_WAN)
                    novos = _instancias_em(doc, RAIZ_WAN) - antes
                    if len(novos) != 1:
                        raise WanError("a ONU nao criou o grupo da WAN como esperado")
                    grupo = f"{RAIZ_WAN}.{novos.pop()}"
                    chave = "WANPPPConnection" if passo["tipo"] == "ppp" else "WANIPConnection"
                    res = tarefa({"name": "addObject", "objectName": f"{grupo}.{chave}"})
                    if res == "aplicada":
                        doc = recarregar(grupo)
                        inst = _instancias_em(doc, f"{grupo}.{chave}")
                        if not inst:
                            raise WanError("a ONU nao criou a conexao da WAN")
                        s = dict(passo["servico"], id_destino=f"{grupo}.{chave}.{max(inst)}")
                        perfil = PERFIS["intelbras"]
                        res = tarefa({"name": "setParameterValues", "parameterValues": _valores(s, perfil, novo=True)})
            if res != "aplicada":
                raise WanError(f"{passo['texto']}: {res}")
            job["feitos"].append(passo["texto"])
        job["estado"] = "concluido"
    except Exception as exc:  # para no primeiro erro e diz o que ja foi
        job["estado"] = "parou"
        job["erro"] = str(exc)
    finally:
        job["fim"] = datetime.now(timezone.utc).isoformat()
        tr._registrar({
            "em": job["fim"], "serial": job["serial"], "acao": "modo_operacao",
            "descricao": "Modo de operacao: " + "; ".join(p["texto"] for p in plano["passos"]),
            "autor": autor, "resultado": "aplicada" if job["estado"] == "concluido" else "falhou: " + job["erro"],
            "detalhe": f"{len(job['feitos'])} de {job['total']} passo(s) feitos",
        })
        try:
            recarregar(RAIZ_WAN)
        except Exception:
            pass
