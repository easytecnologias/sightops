"""Horarios da aba Acesso indo para o leitor Intelbras: comparar e enviar.

O que o leitor guarda (lido em 22/10/2026 nos 6 leitores em producao: SS 3532,
SS 3540 e SS 3542, HTTP API V3.59):
- AccessTimeSchedule[0..127]: 7 dias (domingo = 0) x 4 faixas,
  "1 HH:MM:SS-HH:MM:SS"; faixa vazia = "1 00:00:00-00:00:00". O indice 0 e o
  "geral" 24 h que todo usuario usa hoje (TimeSections [0]).
- Cada usuario aponta para um indice: AccessUser TimeSections (um por porta,
  paralelo a Doors).

O que o teste controlado mostrou (ENTRADA - ESCOLA PRESIDENTE DUTRA,
usuario de teste 999999, tudo desfeito):
- setConfig com as 29 chaves de uma vez volta HTTP 501 (URL longa demais);
  ate 12 chaves passa. Aqui vai um dia por vez (4 faixas).
- O Name do horario nao e gravavel nesse firmware: qual indice e de qual
  horario fica no SightOps (leitor_indices em acesso-horarios.json).
- AccessUser updateMulti so com UserID + TimeSections troca o horario e nao
  mexe em nome, validade, senha nem foto.
- Espaco tem de ir como %20: com "+" (urlencode padrao) o leitor grava o "+".
- Feriado por data (SpecialDayGroup.Days) nao e aceito no SS 3532/3542, entao
  feriado ainda nao vai ao leitor; a tela avisa.

Indices do SightOps sao alocados de 127 para baixo, so em indice com o padrao
de fabrica (desligado, 24 h todo dia), para nao cair em horario feito na
pagina web do leitor (que comeca do 1).

Equipamento de cliente e vivo: comparar so le; enviar so roda no clique, um
leitor por vez, le de volta o que gravou e registra no log com o usuario.
"""
from __future__ import annotations

import logging
import re
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException

from app.services import access_control_horarios as H

logger = logging.getLogger("cam-snapshot")

INDICES = 128
FAIXAS_LEITOR = 4
VAZIA = "1 00:00:00-00:00:00"
LOTE_USUARIOS = 20
DIA_TODO = [["00:00", "24:00"]]


def _t(v: Any) -> str:
    return str(v or "").strip()


# ---------------------------------------------------------------- formato do leitor

def _faixa_leitor(ini: str, fim: str) -> str:
    return f"1 {ini}:00-{'23:59:59' if fim in ('24:00', '23:59') else fim + ':00'}"


def _faixa_sightops(txt: str) -> Optional[List[str]]:
    m = re.match(r"^\d+\s+(\d\d):(\d\d):\d\d-(\d\d):(\d\d):(\d\d)$", _t(txt))
    if not m:
        return None
    ini, fim = f"{m.group(1)}:{m.group(2)}", f"{m.group(3)}:{m.group(4)}"
    if ini == "00:00" and fim == "00:00":
        return None
    return [ini, "24:00" if fim == "23:59" else fim]


def _dias_iguais(a: Dict[str, List[List[str]]], b: Dict[str, List[List[str]]]) -> bool:
    return all([list(x) for x in a.get(str(d)) or []] == [list(x) for x in b.get(str(d)) or []] for d in range(7))


def _semana_24h() -> Dict[str, List[List[str]]]:
    return {str(d): [list(x) for x in DIA_TODO] for d in range(7)}


def ler_horarios(device: Dict[str, Any], get: Callable) -> Dict[int, Dict[str, Any]]:
    from app.services.access_control_controladora import _ler
    kv = _ler(device, "/cgi-bin/configManager.cgi", {"action": "getConfig", "name": "AccessTimeSchedule"}, get)
    saida: Dict[int, Dict[str, Any]] = {}
    for chave, valor in kv.items():
        m = re.match(r"^AccessTimeSchedule\[(\d+)\]\.(Enable|TimeSchedule\[(\d)\]\[(\d)\])$", chave)
        if not m:
            continue
        h = saida.setdefault(int(m.group(1)), {"ativo": False, "dias": {str(d): [] for d in range(7)}})
        if m.group(2) == "Enable":
            h["ativo"] = valor.strip().lower() == "true"
        else:
            f = _faixa_sightops(valor)
            if f and m.group(3) in h["dias"]:
                h["dias"][m.group(3)].append(f)
    for h in saida.values():
        for d in h["dias"].values():
            d.sort()
    return saida


def ler_usuarios(device: Dict[str, Any], get: Callable) -> Dict[str, Dict[str, Any]]:
    from app.services.access_control_device import _check_device_response, _parse_record_table
    texto = _check_device_response(
        get(device, "/cgi-bin/recordFinder.cgi", {"action": "find", "name": "AccessControlCard", "count": 5000}),
        "a leitura dos usuarios")
    usuarios: Dict[str, Dict[str, Any]] = {}
    for row in _parse_record_table(texto):
        uid = "".join(c for c in _t(row.get("UserID")) if c.isdigit())
        if not uid:
            continue
        def lista(campo: str) -> List[str]:
            achados = [(int(m.group(1)), v) for k, v in row.items() if (m := re.match(rf"^{campo}\[(\d+)\]$", k))]
            return [v for _, v in sorted(achados)]
        usuarios[uid] = {"nome": _t(row.get("CardName") or row.get("UserName")),
                         "portas": lista("Doors") or ["0"], "horarios": [int(x) for x in lista("TimeSections") if x.isdigit()]}
    return usuarios


def _set_config(device: Dict[str, Any], pares: Dict[str, str], get: Callable, rotulo: str) -> None:
    from app.services.access_control_device import _check_device_response
    q = "&".join(f"{quote(k, safe='[]._')}={quote(v, safe=':-')}" for k, v in pares.items())
    _check_device_response(get(device, "/cgi-bin/configManager.cgi?action=setConfig&" + q, None), rotulo)


def gravar_horario(device: Dict[str, Any], indice: int, dias: Dict[str, List[List[str]]], get: Callable,
                   ativo: bool = True) -> None:
    for d in range(7):
        faixas = [_faixa_leitor(a, b) for a, b in dias.get(str(d)) or []]
        if len(faixas) > FAIXAS_LEITOR:
            raise HTTPException(status_code=400, detail=f"Mais de {FAIXAS_LEITOR} faixas num dia: o leitor nao guarda.")
        faixas += [VAZIA] * (FAIXAS_LEITOR - len(faixas))
        _set_config(device, {f"AccessTimeSchedule[{indice}].TimeSchedule[{d}][{s}]": f for s, f in enumerate(faixas)},
                    get, f"o horario {indice}")
    _set_config(device, {f"AccessTimeSchedule[{indice}].Enable": "true" if ativo else "false"}, get, f"o horario {indice}")


# ---------------------------------------------------------------- o que deveria estar no leitor

def _uniao(dias_lista: List[Dict[str, List[List[str]]]]) -> Dict[str, List[List[str]]]:
    """Pessoa em dois grupos com horarios diferentes na mesma porta: o leitor so
    guarda um horario por pessoa, entao vale a soma das faixas."""
    saida: Dict[str, List[List[str]]] = {}
    for d in range(7):
        todas = [f for dias in dias_lista for f in dias.get(str(d)) or []]
        saida[str(d)] = H._limpar_faixas(todas, H.NOMES_DIAS[str(d)]) if todas else []
    return saida


def _desejado(device: Dict[str, Any]) -> Dict[str, Any]:
    """Para cada pessoa que tem este leitor em algum grupo: qual horario (chave)
    ela deveria ter. Chave "" = 24 horas (indice 0)."""
    from app.services.access_control_store import list_groups, list_people, list_rules
    did = _t(device.get("id"))
    d = H._ler()
    regras = list_rules()
    grupos = {_t(g.get("id")): g for g in list_groups() if g.get("active", True)}
    deste = {gid for gid in grupos if did in H._portas_do_grupo(gid, regras)}
    funcao = _t(device.get("access_direction")).lower() or "entrada"
    pessoas = {_t(p.get("id")): p for p in list_people() if p.get("active") is not False}
    grupos_da: Dict[str, List[str]] = {}
    for r in H._rows("SELECT group_id, person_id FROM access_group_members WHERE tenant_slug=?", (H._tenant(),)):
        if _t(r.get("group_id")) in deste and _t(r.get("person_id")) in pessoas:
            grupos_da.setdefault(_t(r.get("person_id")), []).append(_t(r.get("group_id")))
    avisos: List[str] = []
    chaves: Dict[str, Dict[str, List[List[str]]]] = {"": _semana_24h()}
    por_pessoa: Dict[str, Dict[str, Any]] = {}
    erros: List[str] = []
    for pid, gs in grupos_da.items():
        horarios = []
        livre = False
        for gid in gs:
            hid = d["grupo_horario"].get(gid)
            if not hid or hid not in d["horarios"]:
                livre = True                                     # grupo sem horario = 24 h
            elif funcao == "saida" and d["saida_livre"].get(gid, True):
                livre = True                                     # leitor de saida + saida livre
            else:
                horarios.append(hid)
                if funcao == "entrada_saida" and d["saida_livre"].get(gid, True):
                    aviso = (f"{_t(device.get('name'))} e de entrada e saida: o leitor nao separa, entao "
                             "a saida livre nao vale nele (vale o horario).")
                    if aviso not in avisos:
                        avisos.append(aviso)
        chave = "" if livre or not horarios else "+".join(sorted(set(horarios)))
        if chave and chave not in chaves:
            try:
                chaves[chave] = _uniao([d["horarios"][h]["dias"] for h in sorted(set(horarios))])
            except ValueError as exc:
                erros.append(f"{_t(pessoas[pid].get('full_name'))}: os horarios dos grupos dela somam faixas demais ({exc})")
                continue
        por_pessoa[pid] = {"chave": chave, "pessoa": pessoas[pid]}
    nomes = {k: " + ".join(d["horarios"][h]["nome"] for h in k.split("+")) if k else "24 horas" for k in chaves}
    feriados = (d["feriados"].get(_t(device.get("site")).upper()) or {})
    if feriados.get("datas") and (feriados.get("regra") or {}).get("modo", "fechado") != "normal" and len(chaves) > 1:
        avisos.append("Feriado ainda nao vai ao leitor (este modelo nao aceita feriado por data): "
                      "no feriado o leitor segue o horario do dia da semana.")
    return {"chaves": chaves, "nomes": nomes, "por_pessoa": por_pessoa, "avisos": avisos, "erros": erros,
            "indices": dict((d.get("leitor_indices") or {}).get(did) or {})}


def _padrao_de_fabrica(h: Dict[str, Any]) -> bool:
    return not h["ativo"] and _dias_iguais(h["dias"], _semana_24h())


def _plano_leitor(device: Dict[str, Any], get: Callable) -> Dict[str, Any]:
    des = _desejado(device)
    no_leitor = ler_horarios(device, get)
    usuarios = ler_usuarios(device, get)
    plano: Dict[str, Any] = {"id": _t(device.get("id")), "nome": _t(device.get("name")), "site": _t(device.get("site")),
                             "avisos": list(des["avisos"]), "erros": list(des["erros"]), "horarios": [],
                             "pessoas_mudam": [], "pessoas_iguais": 0, "fora_do_leitor": [], "sem_id": [], "liberar": []}
    zero = no_leitor.get(0)
    if not zero or not _dias_iguais(zero["dias"], _semana_24h()):
        plano["erros"].append("O horario 0 do leitor nao e 24 horas todos os dias. Confira na pagina do leitor antes de enviar.")
    # indice de cada chave: o que ja e nosso, senao o livre mais alto
    indices = {k: i for k, i in des["indices"].items() if isinstance(i, int) and 0 < i < INDICES}
    usados = set(indices.values())
    livres = [i for i in range(INDICES - 1, 0, -1) if i in no_leitor and _padrao_de_fabrica(no_leitor[i]) and i not in usados]
    for chave in sorted(k for k in des["chaves"] if k):
        if chave not in indices:
            if not livres:
                plano["erros"].append("O leitor nao tem horario livre (128 ocupados).")
                break
            indices[chave] = livres.pop(0)
        i = indices[chave]
        atual = no_leitor.get(i)
        igual = bool(atual and atual["ativo"] and _dias_iguais(atual["dias"], des["chaves"][chave]))
        plano["horarios"].append({"indice": i, "chave": chave, "nome": des["nomes"][chave],
                                  "estado": "igual" if igual else ("novo" if chave not in des["indices"] else "gravar")})
    indice_de = {"": 0, **{k: v for k, v in indices.items() if k in des["chaves"]}}
    for pid, info in des["por_pessoa"].items():
        p = info["pessoa"]
        uid = "".join(c for c in _t(p.get("controller_user_id")) if c.isdigit())
        if not uid:
            plano["sem_id"].append(_t(p.get("full_name")))
            continue
        u = usuarios.get(uid)
        if not u:
            plano["fora_do_leitor"].append(_t(p.get("full_name")))
            continue
        alvo = indice_de.get(info["chave"])
        if alvo is None:
            continue
        if u["horarios"] and all(x == alvo for x in u["horarios"]):
            plano["pessoas_iguais"] += 1
        else:
            plano["pessoas_mudam"].append({"uid": uid, "nome": _t(p.get("full_name")), "portas": len(u["portas"]),
                                           "de": u["horarios"], "para": alvo, "para_nome": des["nomes"][info["chave"]]})
    # indices nossos que ninguem mais usa (depois do envio) voltam ao padrao
    em_uso = {x for u in usuarios.values() for x in u["horarios"]}
    vao_mudar = {m["uid"] for m in plano["pessoas_mudam"]}
    em_uso_depois = {x for uid, u in usuarios.items() if uid not in vao_mudar for x in u["horarios"]} | {
        m["para"] for m in plano["pessoas_mudam"]}
    for chave, i in des["indices"].items():
        if chave not in des["chaves"] and i not in em_uso_depois and i in no_leitor and not _padrao_de_fabrica(no_leitor[i]):
            plano["liberar"].append(i)
    plano["indices_novos"] = {k: v for k, v in indices.items() if k in des["chaves"]}
    plano["_chaves"] = des["chaves"]
    plano["_em_uso"] = sorted(em_uso)
    plano["mudancas"] = (len([h for h in plano["horarios"] if h["estado"] != "igual"]) + len(plano["pessoas_mudam"])
                         + len(plano["liberar"]))
    return plano


def _publico(plano: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in plano.items() if not k.startswith("_")}


def _leitores_do_local(site: str) -> List[Dict[str, Any]]:
    from app.services.access_control_device import _is_intelbras_device
    from app.services.access_control_store import get_device_with_password, list_devices
    saida = []
    for x in list_devices():
        if site and _t(x.get("site")).upper() != _t(site).upper():
            continue
        if not x.get("active", True):
            continue
        d = get_device_with_password(_t(x.get("id")))
        if d and _is_intelbras_device(d):
            saida.append(d)
    return sorted(saida, key=lambda d: (_t(d.get("site")).upper(), _t(d.get("name")).upper()))


def comparar(site: str = "", device_ids: Optional[List[str]] = None, get: Optional[Callable] = None) -> Dict[str, Any]:
    """So le: o que o SightOps manda x o que esta em cada leitor."""
    from app.services.access_control_device import _get
    get = get or _get
    leitores = []
    for d in _leitores_do_local(site):
        if device_ids is not None and _t(d.get("id")) not in device_ids:
            continue
        try:
            leitores.append(_publico(_plano_leitor(d, get)))
        except HTTPException as exc:
            leitores.append({"id": _t(d.get("id")), "nome": _t(d.get("name")), "site": _t(d.get("site")),
                             "erro": _t(exc.detail), "mudancas": 0})
    return {"ok": True, "site": site, "leitores": leitores}


# ---------------------------------------------------------------- enviar

def enviar(device_id: str, usuario: str = "", get: Optional[Callable] = None, post: Optional[Callable] = None,
           progresso: Optional[Callable[[str, int, int], None]] = None) -> Dict[str, Any]:
    """Um leitor: grava os horarios que faltam, troca o horario de quem muda,
    devolve ao padrao os indices nossos que ninguem usa, e le de volta."""
    from app.services.access_control_device import _get, _post_json
    from app.services.access_control_store import get_device_with_password
    get = get or _get
    post = post or _post_json
    andar = progresso or (lambda *_: None)
    device = get_device_with_password(_t(device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Leitor nao encontrado neste cliente.")
    plano = _plano_leitor(device, get)
    if plano["erros"]:
        raise HTTPException(status_code=400, detail=" ".join(plano["erros"]))
    nome = plano["nome"]
    feito: Dict[str, Any] = {"leitor": nome, "horarios_gravados": [], "pessoas_trocadas": 0, "falhas": [], "liberados": []}

    # 1) horarios (antes das pessoas: ninguem aponta para indice vazio)
    a_gravar = [h for h in plano["horarios"] if h["estado"] != "igual"]
    for n, h in enumerate(a_gravar, 1):
        andar(f"gravando o horario {h['nome']}", n, len(a_gravar))
        gravar_horario(device, h["indice"], plano["_chaves"][h["chave"]], get)
        feito["horarios_gravados"].append({"indice": h["indice"], "nome": h["nome"]})
    # guarda o indice ja aqui: se cair no meio, o proximo envio reconhece o que e nosso
    d = H._ler()
    d.setdefault("leitor_indices", {})[plano["id"]] = {
        **((d.get("leitor_indices") or {}).get(plano["id"]) or {}), **plano["indices_novos"]}
    H._gravar(d)
    if a_gravar:
        lido = ler_horarios(device, get)
        for h in a_gravar:
            if not _dias_iguais(lido.get(h["indice"], {}).get("dias", {}), plano["_chaves"][h["chave"]]):
                raise HTTPException(status_code=502, detail=f"O leitor nao guardou o horario {h['nome']} como enviado. "
                                                            "Ninguem foi trocado de horario.")

    # 2) pessoas, em lotes
    mudam = plano["pessoas_mudam"]
    for n in range(0, len(mudam), LOTE_USUARIOS):
        lote = mudam[n:n + LOTE_USUARIOS]
        andar("trocando o horario das pessoas", n, len(mudam))
        corpo = {"UserList": [{"UserID": m["uid"], "TimeSections": [m["para"]] * max(1, m["portas"])} for m in lote]}
        try:
            post(device, "/cgi-bin/AccessUser.cgi?action=updateMulti", corpo, "a troca de horario")
        except HTTPException as exc:
            feito["falhas"] += [{"nome": m["nome"], "erro": _t(exc.detail)} for m in lote]
    lidos = ler_usuarios(device, get) if mudam else {}
    for m in mudam:
        if any(f["nome"] == m["nome"] for f in feito["falhas"]):
            continue
        u = lidos.get(m["uid"])
        if u and u["horarios"] and all(x == m["para"] for x in u["horarios"]):
            feito["pessoas_trocadas"] += 1
        else:
            feito["falhas"].append({"nome": m["nome"], "erro": "o leitor nao mostrou o horario novo"})

    # 3) indices nossos sem uso voltam ao padrao de fabrica (so se ninguem aponta)
    if plano["liberar"]:
        em_uso = {x for u in (lidos or ler_usuarios(device, get)).values() for x in u["horarios"]}
        d = H._ler()
        meus = (d.get("leitor_indices") or {}).get(plano["id"]) or {}
        for i in plano["liberar"]:
            if i in em_uso:
                continue
            gravar_horario(device, i, _semana_24h(), get, ativo=False)
            meus = {k: v for k, v in meus.items() if v != i}
            feito["liberados"].append(i)
        d.setdefault("leitor_indices", {})[plano["id"]] = meus
        H._gravar(d)

    feito["ok"] = not feito["falhas"]
    logger.info("horarios enviados ao leitor %s (%s) por %s: horarios %s, pessoas %s trocadas, %s falhas, liberados %s",
                plano["id"], nome, usuario, [h["indice"] for h in feito["horarios_gravados"]],
                feito["pessoas_trocadas"], len(feito["falhas"]), feito["liberados"])
    return feito


# ---------------------------------------------------------------- em segundo plano
# Mesmo motivo do excluir local (access_control_dados): leitor pelo conector
# leva segundos por pedido e o Cloudflare corta em 100 s.

_TAREFAS: Dict[str, Dict[str, Any]] = {}
_TRAVA = threading.Lock()


def _tarefa_publica(t: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in t.items() if k != "cliente"}


def iniciar_envio(device_id: str, usuario: str = "") -> Dict[str, Any]:
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services.access_control_store import get_device_with_password
    device = get_device_with_password(_t(device_id))
    if not device:
        raise HTTPException(status_code=404, detail="Leitor nao encontrado neste cliente.")
    tenant = H._tenant()
    with _TRAVA:
        for t in _TAREFAS.values():
            if t["cliente"] == tenant and t["leitor_id"] == _t(device_id) and t["estado"] == "rodando":
                return _tarefa_publica(t)
        tid = uuid.uuid4().hex
        tarefa = {"id": tid, "cliente": tenant, "leitor_id": _t(device_id), "leitor": _t(device.get("name")),
                  "estado": "rodando", "etapa": "lendo o leitor", "feitas": 0, "total": 0, "resultado": None, "erro": ""}
        _TAREFAS[tid] = tarefa

    def andar(etapa: str, feitas: int, total: int) -> None:
        tarefa.update(etapa=etapa, feitas=feitas, total=total)

    def rodar() -> None:
        token = set_current_tenant_slug(tenant)
        try:
            tarefa["resultado"] = enviar(device_id, usuario, progresso=andar)
            tarefa["estado"] = "pronto"
        except HTTPException as exc:
            tarefa.update(estado="erro", erro=_t(exc.detail))
        except Exception as exc:
            logger.exception("envio de horarios %s/%s falhou", tenant, device_id)
            tarefa.update(estado="erro", erro=_t(exc) or exc.__class__.__name__)
        finally:
            reset_current_tenant_slug(token)

    threading.Thread(target=rodar, name=f"horarios-{tid[:8]}", daemon=True).start()
    return _tarefa_publica(tarefa)


def ver_envio(tid: str) -> Dict[str, Any]:
    t = _TAREFAS.get(_t(tid))
    if not t or t["cliente"] != H._tenant():
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada (o servidor pode ter reiniciado).")
    return _tarefa_publica(t)
