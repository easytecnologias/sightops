"""Ponto de venda: caixas, recebimento das linhas do coletor e consultas.

Isolamento: toda consulta e escrita filtra por tenant_slug. O coletor nao tem
usuario: o token do caixa identifica caixa E cliente (receber_lote nunca usa o
tenant do contexto). O estado do processamento em memoria tem chave
(tenant, caixa, dia) e se reconstroi das linhas gravadas se a API reiniciar.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.services import db_store
from app.services import pdv_leitor as L
from app.services.pdv_processador import ProcessadorDia

ARQUIVOS = ("Espiao", "Teclas")
MAX_LINHAS_LOTE = 5000
MAX_TAM_LINHA = 2000
_DIA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_lock = threading.RLock()
_estado: Dict[Tuple[str, str, str], ProcessadorDia] = {}
_MAX_ESTADOS = 200  # caixas x dias em memoria; o mais antigo sai primeiro


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _hash(token: str) -> str:
    return hashlib.sha256(("sightops-pdv:" + str(token or "")).encode("utf-8")).hexdigest()


def _rows(c: Any, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def _row(c: Any, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    r = c.execute(sql, params).fetchone()
    return dict(r) if r else None


def _texto(v: Any, limite: int = 255) -> str:
    return str(v or "").strip()[:limite]


# ====================================================================== caixas

_CAMPOS_CAIXA = ("id", "nome", "numero", "site", "connector_id", "gravador_host", "gravador_canal",
                 "token_prefixo", "ativo", "coletor_versao", "ultimo_contato", "ultimo_evento",
                 "relogio_pdv_offset_s", "relogio_dvr_offset_s", "relogio_dvr_medido_em")


def _publico(r: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: r.get(k) for k in _CAMPOS_CAIXA}
    # acesso SSH ao caixa (migration 024): nunca a senha, so se ha uma guardada
    out.update({"pdv_host": r.get("pdv_host") or "", "ssh_porta": int(r.get("ssh_porta") or 22),
                "ssh_usuario": r.get("ssh_usuario") or "", "tem_senha": bool(r.get("ssh_senha_enc")),
                "instalacao_estado": r.get("instalacao_estado") or "", "instalacao_em": r.get("instalacao_em") or ""})
    return out


def listar_caixas() -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        rows = _rows(c, "SELECT * FROM pdv_caixas WHERE tenant_slug=? ORDER BY numero, nome", (_tenant(),))
    return [_publico(r) for r in rows]


def salvar_caixa(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou edita. Na criacao devolve o token UMA vez (so o hash fica no banco)."""
    tenant = _tenant()
    nome = _texto(payload.get("nome"), 60)
    if not nome:
        raise ValueError("Informe o nome do caixa (ex.: PDV 01).")
    try:
        numero = int(payload.get("numero") or 0)
        canal = int(payload.get("gravador_canal") or 0)
    except (TypeError, ValueError):
        raise ValueError("Número do caixa e canal do gravador são números.")
    if not 1 <= numero <= 999:
        raise ValueError("Número do caixa de 1 a 999 (é o .NNN do arquivo do PDV).")
    if not 0 <= canal <= 256:
        raise ValueError("Canal do gravador de 0 a 256.")
    campos = {
        "nome": nome, "numero": numero, "site": _texto(payload.get("site"), 120),
        "connector_id": _texto(payload.get("connector_id"), 64),
        "gravador_host": _texto(payload.get("gravador_host"), 120), "gravador_canal": canal,
        "ativo": 0 if str(payload.get("ativo", 1)).lower() in ("0", "false", "nao", "não") else 1,
    }
    if campos["gravador_host"] and campos["gravador_host"] not in gravadores_do_cliente():
        # Sem isto, um IP qualquer viraria alvo da leitura de relogio/video pela
        # rede do servidor. So gravador ja cadastrado no inventario do cliente.
        raise ValueError("Esse gravador não está no inventário deste cliente. Cadastre-o em Gravadores primeiro.")
    if campos["connector_id"]:
        from app.services.connector_service import get_connector
        if not get_connector(campos["connector_id"], include_token=False, enforce_tenant=True):
            raise ValueError("Conector não encontrado neste cliente.")
    agora = _agora()
    caixa_id = _texto(payload.get("id"), 64)
    with db_store._conn() as c:
        dup = _row(c, "SELECT id FROM pdv_caixas WHERE tenant_slug=? AND nome=?", (tenant, nome))
        if dup and dup["id"] != caixa_id:
            raise ValueError("Já existe um caixa com esse nome.")
        if caixa_id:
            if not _row(c, "SELECT id FROM pdv_caixas WHERE tenant_slug=? AND id=?", (tenant, caixa_id)):
                raise ValueError("Caixa não encontrado.")
            antes = _row(c, "SELECT connector_id FROM pdv_caixas WHERE tenant_slug=? AND id=?", (tenant, caixa_id)) or {}
            if (antes.get("connector_id") or "") != campos["connector_id"]:
                # Outro conector = outra rede: o mesmo IP privado e outra maquina.
                # A senha do caixa nunca segue para la sem alguem digita-la de novo.
                c.execute("UPDATE pdv_caixas SET ssh_senha_enc='', ssh_hostkey='' WHERE tenant_slug=? AND id=?",
                          (tenant, caixa_id))
            sets = ", ".join("%s=?" % k for k in campos)
            c.execute("UPDATE pdv_caixas SET %s, updated_at=? WHERE tenant_slug=? AND id=?" % sets,
                      (*campos.values(), agora, tenant, caixa_id))
            token = None
        else:
            caixa_id = uuid.uuid4().hex[:16]
            token = "pdv_" + secrets.token_urlsafe(24)
            cols = ", ".join(campos)
            c.execute("INSERT INTO pdv_caixas(id, tenant_slug, %s, token_hash, token_prefixo, created_at, updated_at) "
                      "VALUES(?, ?, %s, ?, ?, ?, ?)" % (cols, ", ".join("?" * len(campos))),
                      (caixa_id, tenant, *campos.values(), _hash(token), token[:8], agora, agora))
        r = _row(c, "SELECT * FROM pdv_caixas WHERE tenant_slug=? AND id=?", (tenant, caixa_id))
    out = _publico(r)
    if token:
        out["token"] = token
    return out


def excluir_caixa(caixa_id: str) -> Dict[str, Any]:
    """Apaga o caixa e tudo que veio dele (linhas, eventos, itens, cupons).

    O coletor que estiver no caixa passa a receber 401 (token some com o caixa).
    A entidade de monitoramento sai na proxima passagem do refresh (poda por tipo).
    """
    tenant = _tenant()
    with _lock, db_store._conn() as c:
        cx = _caixa_do_cliente(c, tenant, caixa_id)
        apagados = {}
        for t in ("pdv_linhas", "pdv_eventos", "pdv_itens", "pdv_cupons"):
            cur = c.execute("DELETE FROM %s WHERE tenant_slug=? AND caixa_id=?" % t, (tenant, caixa_id))
            apagados[t] = getattr(cur, "rowcount", 0)
        c.execute("DELETE FROM pdv_caixas WHERE tenant_slug=? AND id=?", (tenant, caixa_id))
        for chave in [k for k in _estado if k[0] == tenant and k[1] == caixa_id]:
            _estado.pop(chave, None)
    return {"ok": True, "nome": cx["nome"], "apagados": apagados}


def gravadores_do_cliente() -> set:
    """IPs dos gravadores (NVR/DVR) no inventario do cliente da sessao."""
    from app.services.nvr_ai_service import _read_nvr_inventory
    return {str(r.get("host") or r.get("ip") or "").strip() for r in _read_nvr_inventory()} - {""}


def novo_token(caixa_id: str) -> Dict[str, Any]:
    """Troca o token (o antigo para de funcionar na hora)."""
    tenant = _tenant()
    token = "pdv_" + secrets.token_urlsafe(24)
    with db_store._conn() as c:
        cur = c.execute("UPDATE pdv_caixas SET token_hash=?, token_prefixo=?, updated_at=? WHERE tenant_slug=? AND id=?",
                        (_hash(token), token[:8], _agora(), tenant, caixa_id))
        if not getattr(cur, "rowcount", 1):
            raise ValueError("Caixa não encontrado.")
    return {"id": caixa_id, "token": token, "token_prefixo": token[:8]}


def autenticar(caixa_id: str, token: str) -> Optional[Dict[str, Any]]:
    """Caixa do token, ou None. Nao depende do tenant do contexto."""
    if not caixa_id or not token or len(token) > 200:
        return None
    with db_store._conn() as c:
        r = _row(c, "SELECT * FROM pdv_caixas WHERE id=? AND token_hash=? AND ativo=1", (caixa_id, _hash(token)))
    return r


# ====================================================================== coletor

def _dia(texto: Any) -> str:
    d = str(texto or "").strip()
    if not _DIA_RE.match(d):
        raise ValueError("dia invalido: use AAAA-MM-DD")
    datetime.strptime(d, "%Y-%m-%d")
    return d


def _processador(c: Any, tenant: str, caixa_id: str, dia: str) -> ProcessadorDia:
    chave = (tenant, caixa_id, dia)
    pr = _estado.get(chave)
    if pr is not None:
        return pr
    # Reconstroi do que ja foi gravado (API reiniciou ou primeiro lote do dia).
    pr = ProcessadorDia(dia)
    linhas = {a: [(int(r["seq"]), r["linha"]) for r in _rows(
        c, "SELECT seq, linha FROM pdv_linhas WHERE tenant_slug=? AND caixa_id=? AND arquivo=? AND dia=? ORDER BY seq",
        (tenant, caixa_id, a, dia))] for a in ARQUIVOS}
    if linhas["Espiao"] or linhas["Teclas"]:
        # Regrava o que sair (o banco ignora o que ja tinha): o que estava
        # esperando tecla quando a API caiu nao se perde. O resto volta a esperar.
        _gravar_saida(c, tenant, caixa_id, dia, pr.receber(linhas["Espiao"], linhas["Teclas"]))
    _estado[chave] = pr
    while len(_estado) > _MAX_ESTADOS:
        _estado.pop(next(iter(_estado)))
    return pr


def _gravar_saida(c: Any, tenant: str, caixa_id: str, dia: str, saida: Dict[str, list]) -> None:
    for e in saida["eventos"]:
        c.execute("INSERT INTO pdv_eventos(tenant_slug, caixa_id, dia, seq, ts, tipo, cupom, operador, codigo, descricao, "
                  "valor_centavos, campos_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(tenant_slug, caixa_id, dia, seq) DO NOTHING",
                  (tenant, caixa_id, dia, e["seq"], e["ts"], e["tipo"], e["cupom"], e["operador"], e["codigo"],
                   e["descricao"], e["valor_centavos"], e["campos_json"]))
    for i in saida["itens"]:
        c.execute("INSERT INTO pdv_itens(tenant_slug, caixa_id, dia, seq, ts, cupom, operador, codigo, desc2, descricao, "
                  "quant, valor_centavos, modo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(tenant_slug, caixa_id, dia, seq) DO UPDATE SET modo=excluded.modo",
                  (tenant, caixa_id, dia, i["seq"], i["ts"], i["cupom"], i["operador"], i["codigo"], i["desc2"],
                   i["descricao"], i["quant"], i["valor_centavos"], i["modo"]))
    for k in saida["cupons"]:
        c.execute("INSERT INTO pdv_cupons(tenant_slug, caixa_id, dia, cupom, operador, aberto_em, fechado_em, situacao, "
                  "itens, itens_cancelados, bipados, digitados, menu, total_centavos, pagamento) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tenant_slug, caixa_id, dia, cupom) DO UPDATE SET "
                  "operador=excluded.operador, aberto_em=excluded.aberto_em, fechado_em=excluded.fechado_em, "
                  "situacao=excluded.situacao, itens=excluded.itens, itens_cancelados=excluded.itens_cancelados, "
                  "bipados=excluded.bipados, digitados=excluded.digitados, menu=excluded.menu, "
                  "total_centavos=excluded.total_centavos, pagamento=excluded.pagamento",
                  (tenant, caixa_id, dia, k["cupom"], k["operador"], k["aberto_em"], k["fechado_em"], k["situacao"],
                   k["itens"], k["itens_cancelados"], k["bipados"], k["digitados"], k["menu"],
                   k["total_centavos"], k["pagamento"]))


def receber_lote(caixa: Dict[str, Any], payload: Dict[str, Any], agora: Optional[float] = None) -> Dict[str, Any]:
    """Lote do coletor: {versao, relogio, lotes:[{arquivo, dia, linhas:[[seq, texto], ...]}]}.

    Grava as linhas (reenvio nao duplica), processa e devolve ate onde cada
    arquivo foi aceito -- o coletor so avanca a posicao com essa resposta.
    """
    tenant, caixa_id = caixa["tenant_slug"], caixa["id"]
    lotes = payload.get("lotes") or []
    if not isinstance(lotes, list):
        raise ValueError("lotes deve ser lista")
    total = sum(len(l.get("linhas") or []) for l in lotes if isinstance(l, dict))
    if total > MAX_LINHAS_LOTE:
        raise ValueError("lote grande demais (max %d linhas)" % MAX_LINHAS_LOTE)

    por_dia: Dict[str, Dict[str, List[Tuple[int, str]]]] = {}
    for l in lotes:
        arq = str(l.get("arquivo") or "")
        if arq not in ARQUIVOS:
            raise ValueError("arquivo deve ser Espiao ou Teclas")
        dia = _dia(l.get("dia"))
        alvo = por_dia.setdefault(dia, {a: [] for a in ARQUIVOS})[arq]
        for item in l.get("linhas") or []:
            seq, texto = int(item[0]), str(item[1])[:MAX_TAM_LINHA]
            if seq < 1:
                raise ValueError("seq comeca em 1")
            alvo.append((seq, texto))

    agora_txt = _agora()
    aceito: Dict[str, int] = {}
    ultimo_ts = ""
    with _lock, db_store._conn() as c:
        for dia in sorted(por_dia):
            arqs = por_dia[dia]
            for arq in ARQUIVOS:
                arqs[arq].sort()
                for seq, texto in arqs[arq]:
                    c.execute("INSERT INTO pdv_linhas(tenant_slug, caixa_id, arquivo, dia, seq, linha, recebido_em) "
                              "VALUES(?,?,?,?,?,?,?) ON CONFLICT(tenant_slug, caixa_id, arquivo, dia, seq) DO NOTHING",
                              (tenant, caixa_id, arq, dia, seq, texto, agora_txt))
                if arqs[arq]:
                    aceito["%s/%s" % (arq, dia)] = arqs[arq][-1][0]
            pr = _processador(c, tenant, caixa_id, dia)
            saida = pr.receber(arqs["Espiao"], arqs["Teclas"], agora=agora)
            _gravar_saida(c, tenant, caixa_id, dia, saida)
            if saida["eventos"]:
                ultimo_ts = max(ultimo_ts, saida["eventos"][-1]["ts"])
        # dias que ficaram para tras soltam o que estava esperando tecla
        for (t, cx, dia), pr in list(_estado.items()):
            if t == tenant and cx == caixa_id and pr.pendentes and dia not in por_dia:
                _gravar_saida(c, tenant, caixa_id, dia, pr.receber(agora=agora))
        offset = _offset_relogio(payload.get("relogio"))
        sets, vals = ["ultimo_contato=?", "coletor_versao=?"], [agora_txt, _texto(payload.get("versao"), 40)]
        if ultimo_ts:
            sets.append("ultimo_evento=?")
            vals.append(ultimo_ts)
        if offset is not None:
            sets.append("relogio_pdv_offset_s=?")
            vals.append(offset)
        c.execute("UPDATE pdv_caixas SET %s WHERE tenant_slug=? AND id=?" % ", ".join(sets), (*vals, tenant, caixa_id))
    return {"ok": True, "aceito": aceito}


def _offset_relogio(relogio: Any) -> Optional[int]:
    """Relogio do PDV menos o do servidor, em s. As duas horas sao locais (o
    container roda em America/Sao_Paulo, a mesma base de Gravador.relogio)."""
    try:
        pdv = datetime.strptime(str(relogio), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return int(round((pdv - datetime.now()).total_seconds()))


def registrar_relogio_dvr(caixa_id: str, gravador_menos_servidor_s: int) -> Dict[str, Any]:
    """Guarda a diferenca gravador - caixa. Medida e guardada, NUNCA corrigida no gravador.

    gravador - caixa = (gravador - servidor) - (caixa - servidor); a segunda parte
    o coletor manda a cada envio.
    """
    tenant = _tenant()
    with db_store._conn() as c:
        cx = _caixa_do_cliente(c, tenant, caixa_id)
        dif = int(gravador_menos_servidor_s) - int(cx.get("relogio_pdv_offset_s") or 0)
        c.execute("UPDATE pdv_caixas SET relogio_dvr_offset_s=?, relogio_dvr_medido_em=? WHERE tenant_slug=? AND id=?",
                  (dif, _agora(), tenant, caixa_id))
    return {"ok": True, "gravador_menos_caixa_s": dif}


def janela_video(caixa_id: str, ts: str, antes: int = 20, depois: int = 20) -> Dict[str, Any]:
    """Gravador, canal e horario NO RELOGIO DO GRAVADOR para um momento do caixa.

    O download em si e o do driver de gravador (/api/nvr/driver/trecho/iniciar):
    credencial, IP virtual do conector e reserva por RTSP ja estao la.
    """
    try:
        momento = datetime.strptime(str(ts).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("Momento inválido: use AAAA-MM-DD HH:MM:SS.")
    antes, depois = max(0, min(int(antes), 600)), max(1, min(int(depois), 600))
    tenant = _tenant()
    with db_store._conn() as c:
        cx = _caixa_do_cliente(c, tenant, caixa_id)
    if not cx["gravador_host"] or not cx["gravador_canal"]:
        raise ValueError("Este caixa ainda não tem gravador e canal configurados.")
    dif = cx.get("relogio_dvr_offset_s")
    no_gravador = momento + timedelta(seconds=int(dif or 0))
    fmt = "%Y-%m-%d %H:%M:%S"
    return {"host": cx["gravador_host"], "canal": int(cx["gravador_canal"]), "connector_id": cx["connector_id"],
            "inicio": (no_gravador - timedelta(seconds=antes)).strftime(fmt),
            "fim": (no_gravador + timedelta(seconds=depois)).strftime(fmt),
            "momento_caixa": momento.strftime(fmt), "momento_gravador": no_gravador.strftime(fmt),
            "relogio_medido": dif is not None, "gravador_menos_caixa_s": int(dif or 0)}


# ====================================================================== consultas

def _caixa_do_cliente(c: Any, tenant: str, caixa_id: str) -> Dict[str, Any]:
    r = _row(c, "SELECT * FROM pdv_caixas WHERE tenant_slug=? AND id=?", (tenant, caixa_id))
    if not r:
        raise ValueError("Caixa não encontrado.")
    return r


def buscar_cupons(dia: str, caixa_id: str = "", operador: str = "", situacao: str = "", texto: str = "",
                  hora_de: str = "", hora_ate: str = "", limite: int = 200) -> List[Dict[str, Any]]:
    tenant = _tenant()
    dia = _dia(dia)
    sql = ("SELECT k.*, x.nome AS caixa FROM pdv_cupons k JOIN pdv_caixas x ON x.tenant_slug=k.tenant_slug AND x.id=k.caixa_id "
           "WHERE k.tenant_slug=? AND k.dia=?")
    p: list = [tenant, dia]
    if caixa_id:
        sql += " AND k.caixa_id=?"
        p.append(caixa_id)
    if operador:
        sql += " AND k.operador=?"
        p.append(operador)
    if situacao in ("aberto", "fechado", "cancelado"):
        sql += " AND k.situacao=?"
        p.append(situacao)
    elif situacao == "item_cancelado":
        sql += " AND k.itens_cancelados>0"
    if re.match(r"^\d{2}:\d{2}$", hora_de or ""):
        sql += " AND k.aberto_em>=?"
        p.append("%s %s:00" % (dia, hora_de))
    if re.match(r"^\d{2}:\d{2}$", hora_ate or ""):
        sql += " AND k.aberto_em<=?"
        p.append("%s %s:59" % (dia, hora_ate))
    t = _texto(texto, 60)
    if t:
        sql += (" AND (k.cupom=? OR EXISTS (SELECT 1 FROM pdv_itens i WHERE i.tenant_slug=k.tenant_slug AND "
                "i.caixa_id=k.caixa_id AND i.dia=k.dia AND i.cupom=k.cupom AND (i.codigo=? OR UPPER(i.descricao) LIKE ?)))")
        p += [t, t.lstrip("0"), "%" + t.upper() + "%"]
    sql += " ORDER BY k.aberto_em DESC LIMIT ?"
    p.append(max(1, min(int(limite or 200), 1000)))
    with db_store._conn() as c:
        return _rows(c, sql, tuple(p))


def detalhe_cupom(caixa_id: str, dia: str, cupom: str) -> Dict[str, Any]:
    """Cupom com itens e a linha do tempo do Espiao (do abrir ao fechar)."""
    tenant, dia = _tenant(), _dia(dia)
    with db_store._conn() as c:
        cx = _caixa_do_cliente(c, tenant, caixa_id)
        k = _row(c, "SELECT * FROM pdv_cupons WHERE tenant_slug=? AND caixa_id=? AND dia=? AND cupom=?",
                 (tenant, caixa_id, dia, cupom))
        if not k:
            raise ValueError("Cupom não encontrado.")
        itens = _rows(c, "SELECT * FROM pdv_itens WHERE tenant_slug=? AND caixa_id=? AND dia=? AND cupom=? ORDER BY seq",
                      (tenant, caixa_id, dia, cupom))
        fim = k["fechado_em"] or "%s 23:59:59" % dia
        linha = _rows(c, "SELECT seq, ts, tipo, cupom, operador, codigo, descricao, valor_centavos FROM pdv_eventos "
                         "WHERE tenant_slug=? AND caixa_id=? AND dia=? AND ts>=? AND ts<=? AND tipo NOT IN ('NUM','CDP') "
                         "ORDER BY seq LIMIT 500", (tenant, caixa_id, dia, k["aberto_em"], fim))
    return {"caixa": _publico(cx), "cupom": k, "itens": itens, "linha_do_tempo": linha}


def ao_vivo(caixa_id: str) -> Dict[str, Any]:
    """O cupom que esta passando agora (ou o ultimo) e os itens dele."""
    tenant = _tenant()
    with db_store._conn() as c:
        cx = _caixa_do_cliente(c, tenant, caixa_id)
        k = _row(c, "SELECT * FROM pdv_cupons WHERE tenant_slug=? AND caixa_id=? ORDER BY aberto_em DESC LIMIT 1",
                 (tenant, caixa_id))
        itens, cancelados = [], []
        if k:
            itens = _rows(c, "SELECT seq, ts, codigo, descricao, quant, valor_centavos, modo FROM pdv_itens "
                             "WHERE tenant_slug=? AND caixa_id=? AND dia=? AND cupom=? ORDER BY seq DESC LIMIT 60",
                          (tenant, caixa_id, k["dia"], k["cupom"]))
            cancelados = _rows(c, "SELECT seq, ts, codigo, descricao, valor_centavos FROM pdv_eventos "
                                  "WHERE tenant_slug=? AND caixa_id=? AND dia=? AND cupom=? AND tipo='CIT' ORDER BY seq DESC",
                               (tenant, caixa_id, k["dia"], k["cupom"]))
    # O que chegou e ainda espera tecla (ate 15 s): aparece JA, como provisorio.
    # Sem isto a lista ficava ~10 s atras da imagem (medido no PDV 02, 27/10/2026).
    with _lock:
        pr = max(((d, p) for (t, cxid, d), p in _estado.items() if t == tenant and cxid == caixa_id),
                 default=(None, None))[1]
        previa = pr.previa() if pr is not None else None
    if previa and previa["cupom"]:
        if not k or previa["cupom"] != k["cupom"]:
            k = {"cupom": previa["cupom"], "operador": previa["operador"], "aberto_em": previa["aberto_em"],
                 "dia": pr.dia, "situacao": "aberto", "itens": 0, "itens_cancelados": 0, "total_centavos": 0,
                 "pagamento": "", "fechado_em": ""}
            itens = []
        k = dict(k)
        if previa["itens"]:
            itens = list(reversed(previa["itens"])) + itens
            k["itens"] = int(k.get("itens") or 0) + len(previa["itens"])
            k["total_centavos"] = int(k.get("total_centavos") or 0) + sum(i["valor_centavos"] for i in previa["itens"])
    return {"caixa": _publico(cx), "cupom": k, "itens": itens[:60], "cancelados": cancelados}


def resumo_dia(dia: str, caixa_id: str = "") -> Dict[str, Any]:
    """Numeros da Visao geral: cupons, itens por modo, valor, cancelamentos."""
    tenant, dia = _tenant(), _dia(dia)
    filtro, p = "tenant_slug=? AND dia=?", [tenant, dia]
    if caixa_id:
        filtro += " AND caixa_id=?"
        p.append(caixa_id)
    with db_store._conn() as c:
        modos = {r["modo"]: {"n": int(r["n"]), "centavos": int(r["v"] or 0)} for r in _rows(
            c, "SELECT modo, COUNT(1) AS n, SUM(valor_centavos) AS v FROM pdv_itens WHERE %s GROUP BY modo" % filtro, tuple(p))}
        cup = {r["situacao"]: int(r["n"]) for r in _rows(
            c, "SELECT situacao, COUNT(1) AS n FROM pdv_cupons WHERE %s GROUP BY situacao" % filtro, tuple(p))}
        vendido = _row(c, "SELECT SUM(total_centavos) AS v FROM pdv_cupons WHERE %s AND situacao='fechado'" % filtro, tuple(p))
        ev = {r["tipo"]: int(r["n"]) for r in _rows(
            c, "SELECT tipo, COUNT(1) AS n FROM pdv_eventos WHERE %s AND tipo IN ('CIT','CCV','CCG','DIT','ITEMSEMCAD','SGR','GAV') "
               "GROUP BY tipo" % filtro, tuple(p))}
    itens = sum(m["n"] for m in modos.values())
    return {"dia": dia, "itens": itens, "modos": modos, "cupons": cup,
            "vendido_centavos": int((vendido or {}).get("v") or 0), "eventos": ev}


def reprocessar_dia(caixa_id: str, dia: str) -> Dict[str, Any]:
    """Refaz eventos, itens e cupons do dia a partir das linhas cruas gravadas."""
    tenant, dia = _tenant(), _dia(dia)
    with _lock, db_store._conn() as c:
        _caixa_do_cliente(c, tenant, caixa_id)
        for t in ("pdv_eventos", "pdv_itens", "pdv_cupons"):
            c.execute("DELETE FROM %s WHERE tenant_slug=? AND caixa_id=? AND dia=?" % t, (tenant, caixa_id, dia))
        _estado.pop((tenant, caixa_id, dia), None)
        pr = ProcessadorDia(dia)
        linhas = {a: [(int(r["seq"]), r["linha"]) for r in _rows(
            c, "SELECT seq, linha FROM pdv_linhas WHERE tenant_slug=? AND caixa_id=? AND arquivo=? AND dia=? ORDER BY seq",
            (tenant, caixa_id, a, dia))] for a in ARQUIVOS}
        saida = pr.receber(linhas["Espiao"], linhas["Teclas"], final=True)
        _gravar_saida(c, tenant, caixa_id, dia, saida)
        _estado[(tenant, caixa_id, dia)] = pr
    return {"ok": True, "eventos": len(saida["eventos"]), "itens": len(saida["itens"]), "cupons": len(saida["cupons"])}


# ====================================================================== monitoramento

OFFLINE_APOS_S = 180  # coletor manda sinal de vida a cada 30 s


def _segundos_desde(quando: str, agora: datetime, offset_caixa_s: int = 0) -> Optional[int]:
    """Idade em s de 'YYYY-MM-DDTHH:MM:SSZ' (UTC) ou 'YYYY-MM-DD HH:MM:SS' (hora local do caixa)."""
    if not quando:
        return None
    try:
        if quando.endswith("Z"):
            t = datetime.strptime(quando, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return max(0, int((agora - t).total_seconds()))
        t = datetime.strptime(quando, "%Y-%m-%d %H:%M:%S")
        # hora do caixa: o offset entra antes do max, senao a idade sai inflada
        return max(0, int((agora.astimezone().replace(tzinfo=None) - t).total_seconds()) + offset_caixa_s)
    except ValueError:
        return None


def entidades_monitoramento(agora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Cada caixa como entidade 'pdv' do monitoramento (e host no Zabbix)."""
    agora = agora or datetime.now(timezone.utc)
    out = []
    with db_store._conn() as c:
        rows = _rows(c, "SELECT * FROM pdv_caixas WHERE tenant_slug=?", (_tenant(),))
    for r in rows:
        contato = _segundos_desde(r.get("ultimo_contato") or "", agora)
        if not r.get("ativo"):
            status = "maintenance"
        elif contato is None:
            status = "unknown"  # coletor ainda nao instalado
        else:
            status = "online" if contato <= OFFLINE_APOS_S else "offline"
        evento = _segundos_desde(r.get("ultimo_evento") or "", agora, int(r.get("relogio_pdv_offset_s") or 0))
        out.append({
            "entity_key": "pdv:%s" % r["id"], "entity_type": "pdv", "entity_id": r["id"],
            "site": r.get("site"), "connector_id": r.get("connector_id"), "display_name": r.get("nome"),
            "status": status,
            "detail": {"contato_s": contato, "evento_s": evento, "coletor_versao": r.get("coletor_versao"),
                       "gravador": r.get("gravador_host"), "canal": r.get("gravador_canal"),
                       "relogio_pdv_offset_s": r.get("relogio_pdv_offset_s"),
                       "relogio_dvr_offset_s": r.get("relogio_dvr_offset_s")},
        })
    return out
