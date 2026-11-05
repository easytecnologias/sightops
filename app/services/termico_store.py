"""Alerta Termico -- cameras vigiadas, regra de cada uma e os alertas.

Toda consulta filtra pelo cliente da sessao (`_tenant`): o id sozinho nunca
basta. A camera so entra pelo inventario do proprio cliente (`adicionar`
procura o IP la), nunca por IP digitado -- assim o vigia nao vira um jeito de
abrir conexao para a rede de outro cliente.

Fotos e matriz de cada alerta em data/tenants/<slug>/termico/<camera>/<alerta>/.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_path
from app.services import db_store
from app.services.termico_deteccao import Regra

FUSO = ZoneInfo("America/Sao_Paulo")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MODELO_TERMICO = re.compile(r"^(HM-T|DS-2TD|DS-2TP|DS-2TB)|THERMAL", re.I)
SITUACOES = ("novo", "visto", "falso")
MOTIVOS_FALSO = ("animal", "sol", "equipe", "mato", "veiculo", "outro")
FOTOS = {"termico": "termico.jpg", "visivel": "visivel.jpg"}

# Limites do que a tela pode mandar na regra (fora disso e erro de digitacao).
LIMITES = {
    "corpo_min": (-10.0, 60.0), "corpo_max": (-10.0, 80.0), "dif_min": (1.0, 40.0),
    "pontos_min": (2, 5000), "pontos_max": (10, 49152), "quadros_seguidos": (1, 10),
    "intervalo_alertas_s": (0, 3600), "aprendizado": (0.001, 0.5),
}


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tenant() -> str:
    slug = get_current_tenant_slug()
    if not slug:
        raise PermissionError("Cliente não identificado.")
    return slug


def _txt(v: Any) -> str:
    return str(v or "").strip()


def _json(raw: Any, padrao: Any) -> Any:
    try:
        return json.loads(raw) if raw else padrao
    except Exception:
        return padrao


def _ordem_natural(txt: str) -> List[Any]:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", txt or "")]


def _site_ok(site: Any) -> bool:
    """Usuario com acesso restrito a alguns sites so ve camera/alerta deles.
    Laco de fundo e usuario sem restricao: sites_da_sessao() = None."""
    from app.core.permissions import sites_da_sessao
    sites = sites_da_sessao()
    if sites is None:
        return True
    nome = _txt(site).upper()
    return bool(nome) and nome in {s.strip().upper() for s in sites}


def chave(ip: Any, connector_id: Any) -> str:
    """Camera = IP + conector: a mesma faixa privada se repete em usinas."""
    return f"{_txt(ip)}|{_txt(connector_id)}"


REMOVIDA = "removida"
LEITURA_VELHA_S = 180     # desarmada le a cada 60 s; mais que isso parado = sem leitura


# --------------------------------------------------------------------- regra

def regra_de(camera: Dict[str, Any]) -> Regra:
    dados = _json(camera.get("regra"), {})
    r = Regra()
    for campo in LIMITES:
        if campo in dados:
            setattr(r, campo, type(getattr(r, campo))(dados[campo]))
    r.areas = [[tuple(p) for p in pol] for pol in dados.get("areas") or []]
    r.ignorar = [[tuple(p) for p in pol] for pol in dados.get("ignorar") or []]
    return r


def _poligonos(valor: Any, campo: str) -> List[List[List[float]]]:
    if valor in (None, ""):
        return []
    if not isinstance(valor, list) or len(valor) > 20:
        raise ValueError(f"{campo}: lista de polígonos inválida.")
    saida = []
    for pol in valor:
        if not isinstance(pol, list) or not (3 <= len(pol) <= 40):
            raise ValueError(f"{campo}: cada polígono precisa de 3 a 40 pontos.")
        pts = []
        for p in pol:
            try:
                x, y = float(p[0]), float(p[1])
            except Exception:
                raise ValueError(f"{campo}: ponto inválido {p!r}.")
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError(f"{campo}: ponto fora da imagem {p!r} (use 0 a 1).")
            pts.append([round(x, 4), round(y, 4)])
        saida.append(pts)
    return saida


def _validar_regra(dados: Dict[str, Any], atual: Dict[str, Any]) -> Dict[str, Any]:
    regra = dict(atual)
    for campo, (lo, hi) in LIMITES.items():
        if campo not in dados:
            continue
        try:
            v = float(dados[campo])
        except Exception:
            raise ValueError(f"{campo}: número inválido.")
        if not (lo <= v <= hi):
            raise ValueError(f"{campo}: use de {lo} a {hi}.")
        regra[campo] = int(v) if isinstance(lo, int) else v
    for campo in ("areas", "ignorar"):
        if campo in dados:
            regra[campo] = _poligonos(dados[campo], campo)
    if float(regra.get("corpo_min", Regra.corpo_min)) >= float(regra.get("corpo_max", Regra.corpo_max)):
        raise ValueError("A temperatura mínima de corpo tem que ser menor que a máxima.")
    if int(regra.get("pontos_min", Regra.pontos_min)) >= int(regra.get("pontos_max", Regra.pontos_max)):
        raise ValueError("O tamanho mínimo tem que ser menor que o máximo.")
    return regra


def esta_armado(camera: Dict[str, Any], agora: Optional[datetime] = None) -> bool:
    """'' nos dois campos = 24 h. Horario que vira o dia (18:00 -> 06:00) vale."""
    if not int(camera.get("ativo") or 0):
        return False
    de, ate = _txt(camera.get("armado_de")), _txt(camera.get("armado_ate"))
    if not de or not ate:
        return True
    hora = (agora or datetime.now(FUSO)).astimezone(FUSO).time()
    h_de = dtime.fromisoformat(de)
    h_ate = dtime.fromisoformat(ate)
    if h_de <= h_ate:
        return h_de <= hora < h_ate
    return hora >= h_de or hora < h_ate


# ------------------------------------------------------------------- cameras

def _inventario_termico(tenant: str) -> List[Dict[str, Any]]:
    from app.services.inventory_json import load_inventory_json

    vistos: Dict[str, Dict[str, Any]] = {}
    for modo in ("switch", "olt"):
        try:
            linhas = load_inventory_json(mode=modo)
        except Exception:
            linhas = []
        for row in linhas or []:
            ip = _txt(row.get("ip"))
            modelo = _txt(row.get("modelo") or row.get("model"))
            k = chave(ip, row.get("remote_connector_id"))
            if not ip or k in vistos or not MODELO_TERMICO.search(modelo):
                continue
            vistos[k] = {
                "ip": ip, "mac": _txt(row.get("mac")).lower(), "modelo": modelo,
                "site": _txt(row.get("site") or row.get("local")),
                "nome": _txt(row.get("titulo") or row.get("title")) or ip,
                "connector_id": _txt(row.get("remote_connector_id")),
                "porta": int(row.get("http_port") or 80),
            }
    return list(vistos.values())


def _publica(c: Dict[str, Any]) -> Dict[str, Any]:
    regra = regra_de(c)
    return {
        "id": c["id"], "ip": c["ip"], "connector_id": c.get("connector_id") or "", "mac": c.get("mac") or "", "site": c.get("site") or "",
        "nome": c.get("nome") or "", "modelo": c.get("modelo") or "", "canal": int(c.get("canal") or 2),
        "ativo": bool(int(c.get("ativo") or 0)), "armado_de": c.get("armado_de") or "",
        "armado_ate": c.get("armado_ate") or "", "armado_agora": esta_armado(c),
        "leitura": c.get("leitura") or "", "leitura_erro": c.get("leitura_erro") or "",
        "leitura_at": c.get("leitura_at") or "", "fundo_c": c.get("fundo_c"),
        "regra": {**{k: getattr(regra, k) for k in LIMITES}, "areas": regra.areas, "ignorar": regra.ignorar},
    }


def listar_cameras() -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM termico_cameras WHERE tenant_slug=?", (tenant,)).fetchall()]
        pend = {dict(r)["camera_id"]: int(dict(r)["n"]) for r in c.execute(
            "SELECT camera_id, COUNT(*) AS n FROM termico_alertas WHERE tenant_slug=? AND situacao='novo' GROUP BY camera_id",
            (tenant,)).fetchall()}
    rows = [r for r in rows if r.get("leitura") != REMOVIDA and _site_ok(r.get("site"))]
    rows.sort(key=lambda r: (_ordem_natural(r.get("site") or ""), _ordem_natural(r.get("nome") or "")))
    cadastradas = {chave(r["ip"], r.get("connector_id")) for r in rows}
    novas = [x for x in _inventario_termico(tenant)
             if chave(x["ip"], x["connector_id"]) not in cadastradas and _site_ok(x["site"])]
    novas.sort(key=lambda r: (_ordem_natural(r["site"]), _ordem_natural(r["nome"])))
    return {
        "cameras": [{**_publica(r), "pendentes": pend.get(r["id"], 0)} for r in rows],
        "no_inventario": novas,
    }


def _camera(c: Any, tenant: str, camera_id: str) -> Dict[str, Any]:
    if not ID_RE.match(camera_id or ""):
        raise LookupError("Câmera não encontrada.")
    r = c.execute("SELECT * FROM termico_cameras WHERE tenant_slug=? AND id=?", (tenant, camera_id)).fetchone()
    if not r or dict(r).get("leitura") == REMOVIDA or not _site_ok(dict(r).get("site")):
        raise LookupError("Câmera não encontrada.")
    return dict(r)


def adicionar(ip: str, connector_id: str = "") -> Dict[str, Any]:
    tenant = _tenant()
    alvo = next((x for x in _inventario_termico(tenant)
                 if chave(x["ip"], x["connector_id"]) == chave(ip, connector_id)), None)
    if not alvo or not _site_ok(alvo["site"]):
        raise LookupError("Essa câmera térmica não está no inventário deste cliente.")
    agora = _agora()
    novo_id = uuid.uuid4().hex
    with db_store._conn() as c:
        antiga = c.execute("SELECT id, leitura FROM termico_cameras WHERE tenant_slug=? AND ip=? AND connector_id=?",
                           (tenant, alvo["ip"], alvo["connector_id"])).fetchone()
        if antiga and dict(antiga).get("leitura") != REMOVIDA:
            raise ValueError("Essa câmera já está no Alerta Térmico.")
        if antiga:      # tinha sido removida: volta com a regra antiga, desligada
            novo_id = dict(antiga)["id"]
            c.execute("UPDATE termico_cameras SET leitura='', leitura_erro='', ativo=0, site=?, nome=?, mac=?, modelo=?, "
                      "updated_at=? WHERE tenant_slug=? AND id=?",
                      (alvo["site"], alvo["nome"], alvo["mac"], alvo["modelo"], agora, tenant, novo_id))
            return _publica(_camera(c, tenant, novo_id))
        c.execute(
            "INSERT INTO termico_cameras(id, tenant_slug, site, ip, mac, connector_id, porta, canal, nome, modelo, "
            "ativo, regra, armado_de, armado_ate, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (novo_id, tenant, alvo["site"], alvo["ip"], alvo["mac"], alvo["connector_id"], alvo["porta"], 2,
             alvo["nome"], alvo["modelo"], 0, "{}", "", "", agora, agora))
        return _publica(_camera(c, tenant, novo_id))


def salvar_camera(camera_id: str, dados: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        atual = _camera(c, tenant, camera_id)
        regra = _validar_regra(dados.get("regra") or {}, _json(atual.get("regra"), {}))
        de = _txt(dados.get("armado_de", atual.get("armado_de")))
        ate = _txt(dados.get("armado_ate", atual.get("armado_ate")))
        for h in (de, ate):
            if h and not HORA_RE.match(h):
                raise ValueError(f"Horário inválido: {h} (use HH:MM).")
        if bool(de) != bool(ate):
            raise ValueError("Informe início e fim do horário armado, ou deixe os dois vazios para 24 h.")
        ativo = 1 if dados.get("ativo", bool(int(atual.get("ativo") or 0))) else 0
        c.execute(
            "UPDATE termico_cameras SET regra=?, armado_de=?, armado_ate=?, ativo=?, updated_at=? WHERE tenant_slug=? AND id=?",
            (json.dumps(regra, ensure_ascii=False), de, ate, ativo, _agora(), tenant, camera_id))
        return _publica(_camera(c, tenant, camera_id))


def remover_camera(camera_id: str) -> Dict[str, Any]:
    """Tira do Alerta Termico sem apagar a linha: o Zabbix precisa receber
    "desligada" (termico_leitura=2) para fechar o gatilho de sem medicao, e os
    alertas antigos continuam respondiveis (fecham o de pessoa pendente)."""
    tenant = _tenant()
    with db_store._conn() as c:
        _camera(c, tenant, camera_id)
        c.execute("UPDATE termico_cameras SET ativo=0, leitura=?, leitura_erro='', updated_at=? WHERE tenant_slug=? AND id=?",
                  (REMOVIDA, _agora(), tenant, camera_id))
    return {"ok": True}


# ------------------------------------------------------- usado pelo vigia --

def tenants_com_cameras_ativas() -> List[str]:
    with db_store._conn() as c:
        rows = c.execute("SELECT DISTINCT tenant_slug FROM termico_cameras WHERE ativo=1").fetchall()
        slugs = {_txt(dict(r)["tenant_slug"]) for r in rows}
        if not slugs:
            return []
        try:
            existentes = {_txt(dict(r)["slug"]) for r in c.execute("SELECT slug FROM tenants WHERE active=1").fetchall()}
        except Exception:
            existentes = slugs
    return sorted(s for s in slugs if s and s in existentes)


def cameras_ativas() -> List[Dict[str, Any]]:
    tenant = _tenant()
    with db_store._conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM termico_cameras WHERE tenant_slug=? AND ativo=1", (tenant,)).fetchall()]


def registrar_leitura(camera_id: str, ok: bool, erro: str = "", fundo_c: Optional[float] = None) -> None:
    tenant = _tenant()
    with db_store._conn() as c:
        # ativo=1: leitura atrasada de camera recem-removida nao a "ressuscita".
        c.execute(
            "UPDATE termico_cameras SET leitura=?, leitura_erro=?, leitura_at=?, fundo_c=? WHERE tenant_slug=? AND id=? AND ativo=1",
            ("ok" if ok else "erro", "" if ok else _txt(erro)[:300], _agora(),
             round(fundo_c, 1) if (ok and fundo_c is not None) else None, tenant, camera_id))


def registrar_alerta(camera: Dict[str, Any], mancha: Dict[str, Any], arquivos: Dict[str, bytes]) -> Dict[str, Any]:
    """Grava o alerta e os arquivos (termico.jpg, visivel.jpg, temps.bin)."""
    tenant = _tenant()
    if _txt(camera.get("tenant_slug")) != tenant:
        raise PermissionError("Câmera de outro cliente.")
    alerta_id = uuid.uuid4().hex
    pasta = tenant_scoped_path(f"termico/{camera['id']}/{alerta_id}", tenant)
    pasta.mkdir(parents=True, exist_ok=True)
    salvos = []
    for nome, dado in arquivos.items():
        if dado and nome in ("termico.jpg", "visivel.jpg", "temps.bin"):
            (pasta / nome).write_bytes(dado)
            salvos.append(nome)
    agora = _agora()
    with db_store._conn() as c:
        c.execute(
            "INSERT INTO termico_alertas(id, tenant_slug, camera_id, site, camera_nome, criado_at, situacao, temp_c, "
            "fundo_c, dif_c, mancha, fotos, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (alerta_id, tenant, camera["id"], camera.get("site") or "", camera.get("nome") or "", agora, "novo",
             mancha.get("temp_media"), mancha.get("fundo_medio"), mancha.get("dif"),
             json.dumps(mancha, ensure_ascii=False), json.dumps(salvos), agora))
    return {"id": alerta_id, "criado_at": agora, "fotos": salvos}


# ------------------------------------------------------------------- alertas

def _alerta_publico(r: Dict[str, Any]) -> Dict[str, Any]:
    fotos = _json(r.get("fotos"), [])
    return {
        "id": r["id"], "camera_id": r["camera_id"], "site": r.get("site") or "", "camera_nome": r.get("camera_nome") or "",
        "criado_at": r.get("criado_at") or "", "situacao": r.get("situacao") or "novo",
        "temp_c": r.get("temp_c"), "fundo_c": r.get("fundo_c"), "dif_c": r.get("dif_c"),
        "mancha": _json(r.get("mancha"), {}),
        "fotos": {k: (f"/api/termico/alertas/{r['id']}/foto/{k}" if v in fotos else "") for k, v in FOTOS.items()},
        "visto_por": r.get("visto_por") or "", "visto_at": r.get("visto_at") or "",
        "motivo_falso": r.get("motivo_falso") or "", "comentario": r.get("comentario") or "",
    }


def listar_alertas(site: str = "", situacao: str = "", camera_id: str = "", desde: str = "", limite: int = 200) -> Dict[str, Any]:
    tenant = _tenant()
    filtros, params = ["tenant_slug=?"], [tenant]
    if desde:
        filtros.append("criado_at>=?")
        params.append(_txt(desde))
    with db_store._conn() as c:
        base = [dict(r) for r in c.execute(
            f"SELECT * FROM termico_alertas WHERE {' AND '.join(filtros)} ORDER BY criado_at DESC LIMIT 2000",
            tuple(params)).fetchall()]
    base = [r for r in base if _site_ok(r.get("site"))]
    contagem_sit = {s: 0 for s in SITUACOES}
    contagem_site: Dict[str, int] = {}
    for r in base:
        contagem_sit[r.get("situacao") or "novo"] = contagem_sit.get(r.get("situacao") or "novo", 0) + 1
        contagem_site[r.get("site") or ""] = contagem_site.get(r.get("site") or "", 0) + 1
    sel = [r for r in base
           if (not site or r.get("site") == site)
           and (not situacao or r.get("situacao") == situacao)
           and (not camera_id or r.get("camera_id") == camera_id)]
    limite = max(1, min(int(limite or 200), 500))
    return {
        "alertas": [_alerta_publico(r) for r in sel[:limite]],
        "total": len(sel),
        "por_situacao": contagem_sit,
        "por_site": dict(sorted(contagem_site.items(), key=lambda kv: _ordem_natural(kv[0]))),
    }


def marcar(alerta_id: str, situacao: str, quem: str, motivo: str = "", comentario: str = "") -> Dict[str, Any]:
    tenant = _tenant()
    if situacao not in ("visto", "falso"):
        raise ValueError("Situação inválida.")
    if situacao == "falso" and motivo not in MOTIVOS_FALSO:
        raise ValueError("Diga o motivo do falso alarme.")
    if not ID_RE.match(alerta_id or ""):
        raise LookupError("Alerta não encontrado.")
    agora = _agora()
    with db_store._conn() as c:
        r = c.execute("SELECT * FROM termico_alertas WHERE tenant_slug=? AND id=?", (tenant, alerta_id)).fetchone()
        if not r or not _site_ok(dict(r).get("site")):
            raise LookupError("Alerta não encontrado.")
        c.execute(
            "UPDATE termico_alertas SET situacao=?, visto_por=?, visto_at=?, motivo_falso=?, comentario=?, updated_at=? "
            "WHERE tenant_slug=? AND id=?",
            (situacao, _txt(quem)[:120], agora, motivo if situacao == "falso" else "", _txt(comentario)[:500], agora,
             tenant, alerta_id))
        return _alerta_publico(dict(c.execute(
            "SELECT * FROM termico_alertas WHERE tenant_slug=? AND id=?", (tenant, alerta_id)).fetchone()))


_FOTOS_AGORA: Dict[Any, Any] = {}
FOTO_AGORA_VALE_S = 4.0


def foto_agora(camera_id: str, tipo: str) -> bytes:
    """Foto atual da camera para a ronda. Guarda 4 s por (cliente, camera, tipo):
    varios celulares abertos nao multiplicam o trafego no link da usina."""
    import time
    from app.services.camera_credentials import resolve_camera_credential
    from app.services.connector_routing_vnat import set_olt_reach_connector
    from app.services.termico_camera import base_da_camera, buscar_foto

    if tipo not in ("termica", "colorida"):
        raise LookupError("Foto não encontrada.")
    tenant = _tenant()
    with db_store._conn() as c:
        cam = _camera(c, tenant, camera_id)
    chave_foto = (tenant, camera_id, tipo)
    agora = time.time()
    guardada = _FOTOS_AGORA.get(chave_foto)
    if guardada and agora - guardada[0] < FOTO_AGORA_VALE_S:
        return guardada[1]
    cred = resolve_camera_credential(cam.get("mac") or "", cam.get("site") or "")
    if not cred:
        raise ValueError("Sem usuário e senha salvos para esta câmera.")
    set_olt_reach_connector("")
    base = base_da_camera(cam["ip"], cam.get("porta") or 80, cam.get("connector_id") or "")
    dado = buscar_foto(base, cred["username"], cred["password"], canal_video=2 if tipo == "termica" else 1)
    if len(_FOTOS_AGORA) > 200:
        _FOTOS_AGORA.clear()
    _FOTOS_AGORA[chave_foto] = (agora, dado)
    return dado


def camera_do_alerta(alerta_id: str) -> Dict[str, str]:
    """IP e conector da camera do alerta (para o envio imediato ao Zabbix)."""
    tenant = _tenant()
    with db_store._conn() as c:
        r = c.execute(
            "SELECT c.ip, c.connector_id FROM termico_alertas a JOIN termico_cameras c "
            "ON c.id=a.camera_id AND c.tenant_slug=a.tenant_slug WHERE a.tenant_slug=? AND a.id=?",
            (tenant, alerta_id)).fetchone()
    return {"tenant": tenant, "ip": dict(r)["ip"], "connector_id": dict(r)["connector_id"] or ""} if r else {}


def caminho_foto(alerta_id: str, tipo: str) -> Path:
    tenant = _tenant()
    if tipo not in FOTOS or not ID_RE.match(alerta_id or ""):
        raise LookupError("Foto não encontrada.")
    with db_store._conn() as c:
        r = c.execute("SELECT camera_id, site, fotos FROM termico_alertas WHERE tenant_slug=? AND id=?", (tenant, alerta_id)).fetchone()
    if not r or not _site_ok(dict(r).get("site")):
        raise LookupError("Foto não encontrada.")
    r = dict(r)
    if FOTOS[tipo] not in _json(r.get("fotos"), []):
        raise LookupError("Foto não encontrada.")
    caminho = tenant_scoped_path(f"termico/{r['camera_id']}/{alerta_id}", tenant) / FOTOS[tipo]
    if not caminho.is_file():
        raise LookupError("Foto não encontrada.")
    return caminho


# -------------------------------------------------------------------- zabbix

def _segundos_desde(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
    except Exception:
        return float("inf")


def resumo_para_zabbix(tenant: str) -> Dict[str, Dict[str, Any]]:
    """Por camera (chave IP|conector): alertas pendentes, fundo e a leitura.

    termico_leitura: 1 = lendo; 0 = sem leitura (erro OU leitura parada ha mais
    de LEITURA_VELHA_S -- laco morto ou thread presa nao pode parecer "ok");
    2 = desligada/removida do Alerta Termico (fecha o gatilho de sem medicao).
    Camera que nunca leu fica de fora: nao cria item nem manda 0 enganoso.
    Pendentes vale tambem para desligada/removida: responder o alerta fecha o
    gatilho de pessoa."""
    with db_store._conn() as c:
        cams = [dict(r) for r in c.execute(
            "SELECT id, ip, connector_id, ativo, leitura, leitura_at, fundo_c FROM termico_cameras WHERE tenant_slug=?",
            (tenant,)).fetchall()]
        pend = {dict(r)["camera_id"]: int(dict(r)["n"]) for r in c.execute(
            "SELECT camera_id, COUNT(*) AS n FROM termico_alertas WHERE tenant_slug=? AND situacao='novo' GROUP BY camera_id",
            (tenant,)).fetchall()}
    saida = {}
    for cam in cams:
        leitura = cam.get("leitura") or ""
        if not leitura:
            continue
        if not int(cam.get("ativo") or 0) or leitura == REMOVIDA:
            estado, fundo = 2, None
        elif leitura == "ok" and _segundos_desde(cam.get("leitura_at") or "") <= LEITURA_VELHA_S:
            estado, fundo = 1, cam.get("fundo_c")
        else:
            estado, fundo = 0, None
        saida[chave(cam["ip"], cam.get("connector_id"))] = {
            "termico_pendentes": pend.get(cam["id"], 0),
            "termico_leitura": estado,
            "termico_fundo_c": fundo,
        }
    return saida
