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
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_path
from app.services import db_store
from app.services.termico_deteccao import Regra

FUSO = ZoneInfo("America/Sao_Paulo")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
TENANT_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MODELO_TERMICO = re.compile(r"^(HM-T|DS-2TD|DS-2TP|DS-2TB)|THERMAL", re.I)
SITUACOES = ("novo", "visto", "falso")
MOTIVOS_FALSO = ("animal", "sol", "equipe", "mato", "veiculo", "outro")
FOTOS = {"termico": "termico.jpg", "visivel": "visivel.jpg"}
VIDEOS = {"termico": "termico.mp4", "visivel": "visivel.mp4"}
VIDEO_S = 15                # 12 s no fluxo leve deram 85 KB na CAM P 03
VIDEO_MAX_BYTES = 30_000_000

# Limites do que a tela pode mandar na regra (fora disso e erro de digitacao).
LIMITES = {
    "corpo_min": (-10.0, 60.0), "corpo_max": (-10.0, 80.0), "dif_min": (1.0, 40.0),
    "contraste_min": (0.0, 40.0),
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
FALHAS_JANELA_H = 24     # aviso ou automacao que falhou fica no Zabbix por este tempo
ESCALA_PADRAO = {"escalar_min": 10, "escalar_vezes": 2}
ESCALA_JANELA_H = 6
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
        "videos": {k: (f"/api/termico/alertas/{r['id']}/video/{k}" if v in fotos else "") for k, v in VIDEOS.items()},
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


def _video_liberado(eq: Dict[str, Any]) -> bool:
    """Esta rota vale para quem so tem o modulo termico: nao pode virar porta
    para todo o CFTV do cliente. Abre termica e a speed de uma automacao."""
    if MODELO_TERMICO.search(eq.get("modelo") or ""):
        return True
    tenant = _tenant()
    with db_store._conn() as c:
        rows = c.execute("SELECT acoes FROM automacoes WHERE tenant_slug=?", (tenant,)).fetchall()
    for r in rows:
        for a in _json(dict(r).get("acoes"), []):
            if a.get("tipo") == "speed_preset" and a.get("ip") == eq["ip"] and (a.get("connector_id") or "") == eq["connector_id"]:
                return True
    return False


def abrir_vivo(ip: str, connector_id: str, tipo: str, alta: bool = False) -> Dict[str, Any]:
    """Abre o video de uma camera do inventario do cliente e devolve o stream
    para o player. Termica: canal 2; colorida (e speed): canal 1. Parede usa o
    fluxo leve; `alta` so ao abrir a camera grande."""
    from app.services.automacao_store import equipamento_do_inventario
    from app.services.camera_credentials import resolve_camera_credential
    from app.services.connector_routing_vnat import set_olt_reach_connector
    from app.services.live_stream_service import register_camera_canal_stream
    from app.services.termico_camera import base_da_camera

    _tenant()
    if tipo not in ("termica", "colorida"):
        raise LookupError("Vídeo não encontrado.")
    eq = equipamento_do_inventario(ip, connector_id)
    if not eq or not _site_ok(eq["site"]) or not _video_liberado(eq):
        raise LookupError("Câmera não encontrada.")
    cred = resolve_camera_credential(eq["mac"], eq["site"])
    if not cred:
        raise ValueError("Sem usuário e senha salvos para esta câmera.")
    set_olt_reach_connector("")
    host = base_da_camera(eq["ip"], eq["porta"], eq["connector_id"]).split("//", 1)[1].split(":", 1)[0]
    canal = (2 if tipo == "termica" else 1) * 100 + (1 if alta else 2)
    return {"stream_name": register_camera_canal_stream(host=host, user=cred["username"], password=cred["password"], canal=canal)}


def preparar_camera(camera_id: str) -> Dict[str, Any]:
    """Botao Vigiar: deixa a camera medindo. Escreve na camera."""
    from app.services.camera_credentials import resolve_camera_credential
    from app.services.connector_routing_vnat import set_olt_reach_connector
    from app.services.termico_camera import base_da_camera, preparar_medicao

    tenant = _tenant()
    with db_store._conn() as c:
        cam = _camera(c, tenant, camera_id)
    cred = resolve_camera_credential(cam.get("mac") or "", cam.get("site") or "")
    if not cred:
        raise ValueError("Sem usuário e senha salvos para esta câmera.")
    set_olt_reach_connector("")
    base = base_da_camera(cam["ip"], cam.get("porta") or 80, cam.get("connector_id") or "")
    return preparar_medicao(base, cred["username"], cred["password"], int(cam.get("canal") or 2))


def alarme_de_teste(camera_id: str) -> Dict[str, Any]:
    """Alarme marcado TESTE com a imagem de agora da camera: passa pelo caminho
    inteiro (alerta, celular, Zabbix e automacoes), para ver funcionar sem
    ninguem andando na usina. Automacao Valendo aciona de verdade so para admin
    sem restricao de site, a mesma regra de testar a automacao; para os demais
    ela simula: "Todas as termicas" alcanca sites que o usuario nao ve."""
    from app.core.permissions import sites_da_sessao
    from app.core.security import ROLE_RANK
    from app.core.tenant_context import get_current_user
    from app.services.camera_credentials import resolve_camera_credential
    from app.services.connector_routing_vnat import set_olt_reach_connector
    from app.services.termico_camera import base_da_camera, buscar_foto
    from app.services.termico_vigia import avisar_alerta

    tenant = _tenant()
    with db_store._conn() as c:
        cam = _camera(c, tenant, camera_id)
    cred = resolve_camera_credential(cam.get("mac") or "", cam.get("site") or "")
    if not cred:
        raise ValueError("Sem usuário e senha salvos para esta câmera.")
    set_olt_reach_connector("")
    base = base_da_camera(cam["ip"], cam.get("porta") or 80, cam.get("connector_id") or "")
    u, s = cred["username"], cred["password"]
    mancha = {"teste": True, "fundo_medio": cam.get("fundo_c")}
    alerta = registrar_alerta(cam, mancha, {"termico.jpg": buscar_foto(base, u, s, canal_video=2),
                                            "visivel.jpg": buscar_foto(base, u, s, canal_video=1)})
    alerta["mancha"] = mancha
    papel = str((get_current_user() or {}).get("role") or "").strip().lower()
    alerta["so_simular"] = ROLE_RANK.get(papel, 0) < ROLE_RANK["admin"] or sites_da_sessao() is not None
    avisar_alerta(tenant, cam, alerta)
    return {"id": alerta["id"]}


def manchas_agora(camera_id: str) -> Dict[str, Any]:
    """O que a deteccao esta vendo nesta camera, para o Testar agora."""
    from app.services.termico_vigia import vigia_global

    tenant = _tenant()
    with db_store._conn() as c:
        cam = _camera(c, tenant, camera_id)
    return vigia_global().manchas_de(tenant, cam["id"])


def simular_pessoa(camera_id: str) -> Dict[str, Any]:
    from app.services.termico_vigia import vigia_global

    tenant = _tenant()
    with db_store._conn() as c:
        cam = _camera(c, tenant, camera_id)
    res = vigia_global().simular_pessoa(tenant, cam["id"])
    if res is None:
        raise ValueError("A câmera ainda não mandou nenhuma leitura. Tente em 1 minuto.")
    return res


def camera_do_alerta(alerta_id: str) -> Dict[str, str]:
    """IP e conector da camera do alerta (para o envio imediato ao Zabbix)."""
    tenant = _tenant()
    with db_store._conn() as c:
        r = c.execute(
            "SELECT c.ip, c.connector_id FROM termico_alertas a JOIN termico_cameras c "
            "ON c.id=a.camera_id AND c.tenant_slug=a.tenant_slug WHERE a.tenant_slug=? AND a.id=?",
            (tenant, alerta_id)).fetchone()
    return {"tenant": tenant, "ip": dict(r)["ip"], "connector_id": dict(r)["connector_id"] or ""} if r else {}


def foto_do_aviso(tenant: str, alerta_id: str, expira: int, assinatura: str) -> Path:
    """Foto termica do link assinado da notificacao (sem sessao: rota publica)."""
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services.termico_avisos import foto_valida

    if not TENANT_RE.match(tenant or "") or not ID_RE.match(alerta_id or "") or not foto_valida(tenant, alerta_id, expira, assinatura):
        raise LookupError("Foto não encontrada.")
    token = set_current_tenant_slug(tenant)
    try:
        with db_store._conn() as c:
            r = c.execute("SELECT camera_id FROM termico_alertas WHERE tenant_slug=? AND id=?", (tenant, alerta_id)).fetchone()
        if not r:
            raise LookupError("Foto não encontrada.")
        arq = tenant_scoped_path(f"termico/{dict(r)['camera_id']}/{alerta_id}", tenant) / FOTOS["termico"]
    finally:
        reset_current_tenant_slug(token)
    if not arq.is_file():
        raise LookupError("Foto não encontrada.")
    return arq


def caminho_foto(alerta_id: str, tipo: str) -> Path:
    return _arquivo_do_alerta(alerta_id, tipo, FOTOS)


def caminho_video(alerta_id: str, tipo: str) -> Path:
    return _arquivo_do_alerta(alerta_id, tipo, VIDEOS)


def _gravar_um_video(camera: Dict[str, Any], tipo: str, destino: Path) -> bool:
    """Grava o que a camera ve agora pelo go2rtc, no fluxo leve. So le a camera."""
    import requests
    from app.services.live_stream_service import GO2RTC_BASE_URL

    nome = abrir_vivo(camera["ip"], camera.get("connector_id") or "", tipo)["stream_name"]
    parcial = destino.with_suffix(".parte")
    total = 0
    with requests.get(f"{GO2RTC_BASE_URL}/api/stream.mp4", params={"src": nome, "mp4": "all", "duration": str(VIDEO_S)},
                      stream=True, timeout=VIDEO_S + 30) as r, parcial.open("wb") as arq:
        r.raise_for_status()
        for bloco in r.iter_content(65536):
            total += len(bloco)
            if total > VIDEO_MAX_BYTES:
                break
            arq.write(bloco)
    if not total:
        parcial.unlink(missing_ok=True)
        return False
    parcial.replace(destino)
    return True


def gravar_videos(tenant: str, camera: Dict[str, Any], alerta_id: str) -> List[str]:
    """Os segundos seguintes ao alarme, termica e colorida. Roda em thread
    propria: alarme nunca espera video, e falha aqui nao derruba nada."""
    import logging
    import threading
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug

    log = logging.getLogger(__name__)
    pasta = tenant_scoped_path(f"termico/{camera['id']}/{alerta_id}", tenant)
    salvos: List[str] = []

    def gravar(tipo: str, arquivo: str) -> None:
        token = set_current_tenant_slug(tenant)
        try:
            if _gravar_um_video(camera, tipo, pasta / arquivo):
                salvos.append(arquivo)
        except Exception as exc:
            log.warning("termico: video %s do alerta %s nao gravou: %s", tipo, alerta_id, exc)
        finally:
            reset_current_tenant_slug(token)

    linhas = [threading.Thread(target=gravar, args=a, daemon=True, name="termico-video")
              for a in (("termica", VIDEOS["termico"]), ("colorida", VIDEOS["visivel"]))]
    for t in linhas:
        t.start()
    for t in linhas:
        t.join()
    if salvos:
        with db_store._conn() as c:
            r = c.execute("SELECT fotos FROM termico_alertas WHERE tenant_slug=? AND id=?", (tenant, alerta_id)).fetchone()
            if r:
                atuais = _json(dict(r).get("fotos"), [])
                c.execute("UPDATE termico_alertas SET fotos=? WHERE tenant_slug=? AND id=?",
                          (json.dumps(atuais + [v for v in salvos if v not in atuais]), tenant, alerta_id))
    return salvos


def _arquivo_do_alerta(alerta_id: str, tipo: str, nomes: Dict[str, str]) -> Path:
    tenant = _tenant()
    if tipo not in nomes or not ID_RE.match(alerta_id or ""):
        raise LookupError("Foto não encontrada.")
    with db_store._conn() as c:
        r = c.execute("SELECT camera_id, site, fotos FROM termico_alertas WHERE tenant_slug=? AND id=?", (tenant, alerta_id)).fetchone()
    if not r or not _site_ok(dict(r).get("site")):
        raise LookupError("Foto não encontrada.")
    r = dict(r)
    if nomes[tipo] not in _json(r.get("fotos"), []):
        raise LookupError("Foto não encontrada.")
    caminho = tenant_scoped_path(f"termico/{r['camera_id']}/{alerta_id}", tenant) / nomes[tipo]
    if not caminho.is_file():
        raise LookupError("Foto não encontrada.")
    return caminho


# -------------------------------------------------------------------- zabbix

def _segundos_desde(iso: str) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
    except Exception:
        return float("inf")


# ------------------------------------------------------------- visao geral

def _segundos_entre(de: str, ate: str) -> Optional[float]:
    try:
        f = "%Y-%m-%dT%H:%M:%SZ"
        return (datetime.strptime(ate, f) - datetime.strptime(de, f)).total_seconds()
    except (TypeError, ValueError):
        return None


def visao_geral(dias: int = 30) -> Dict[str, Any]:
    """Cada usina numa linha: quem esta vigiando, o que esta sem leitura e como
    os alarmes foram respondidos. Alarme de teste nao entra na conta."""
    tenant = _tenant()
    dias = max(1, min(int(dias or 30), 366))
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db_store._conn() as c:
        cams = [dict(r) for r in c.execute("SELECT site, ativo, leitura, leitura_at FROM termico_cameras WHERE tenant_slug=?", (tenant,)).fetchall()]
        alertas = [dict(r) for r in c.execute(
            "SELECT site, situacao, criado_at, visto_at, mancha FROM termico_alertas WHERE tenant_slug=? AND criado_at>=?",
            (tenant, desde)).fetchall()]
    usinas: Dict[str, Dict[str, Any]] = {}

    def usina(site: str) -> Dict[str, Any]:
        return usinas.setdefault(site, {"site": site, "cameras": 0, "lendo": 0, "sem_leitura": 0, "pendentes": 0,
                                        "alarmes": 0, "falsos": 0, "cientes": 0, "_tempos": []})

    for cam in cams:
        if cam.get("leitura") == REMOVIDA or not int(cam.get("ativo") or 0) or not _site_ok(cam.get("site")):
            continue
        u = usina(cam.get("site") or "")
        u["cameras"] += 1
        if cam.get("leitura") == "ok" and _segundos_desde(cam.get("leitura_at") or "") <= LEITURA_VELHA_S:
            u["lendo"] += 1
        else:
            u["sem_leitura"] += 1
    for a in alertas:
        if not _site_ok(a.get("site")) or _json(a.get("mancha"), {}).get("teste"):
            continue
        u = usina(a.get("site") or "")
        u["alarmes"] += 1
        if a.get("situacao") == "novo":
            u["pendentes"] += 1
        else:
            u["falsos" if a.get("situacao") == "falso" else "cientes"] += 1
            t = _segundos_entre(a.get("criado_at"), a.get("visto_at"))
            if t is not None and t >= 0:
                u["_tempos"].append(t)
    saida = []
    for u in usinas.values():
        tempos = sorted(u.pop("_tempos"))
        u["resposta_s"] = tempos[len(tempos) // 2] if tempos else None
        saida.append(u)
    return {"dias": dias, "usinas": sorted(saida, key=lambda u: u["site"]), "config": config()}


def config() -> Dict[str, int]:
    tenant = _tenant()
    with db_store._conn() as c:
        r = c.execute("SELECT escalar_min, escalar_vezes FROM termico_config WHERE tenant_slug=?", (tenant,)).fetchone()
    return ({"escalar_min": int(dict(r)["escalar_min"]), "escalar_vezes": int(dict(r)["escalar_vezes"])}
            if r else dict(ESCALA_PADRAO))


def salvar_config(dados: Dict[str, Any]) -> Dict[str, int]:
    tenant = _tenant()
    try:
        minutos, vezes = int(dados.get("escalar_min")), int(dados.get("escalar_vezes"))
    except (TypeError, ValueError):
        raise ValueError("Informe minutos e vezes.")
    if not (0 <= minutos <= 240 and 0 <= vezes <= 5):
        raise ValueError("Use de 0 a 240 minutos e de 0 a 5 vezes.")
    with db_store._conn() as c:
        c.execute("DELETE FROM termico_config WHERE tenant_slug=?", (tenant,))
        c.execute("INSERT INTO termico_config(tenant_slug, escalar_min, escalar_vezes, updated_at) VALUES(?,?,?,?)",
                  (tenant, minutos, vezes, _agora()))
    return config()


def a_escalar(agora: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Alarmes sem resposta que devem avisar de novo. Ja marca: reiniciar o
    servidor nao repete o aviso. Alarme com mais de ESCALA_JANELA_H fica so no
    Zabbix: ninguem quer sirene de madrugada por um alarme de ontem."""
    tenant = _tenant()
    cfg = config()
    if cfg["escalar_min"] <= 0 or cfg["escalar_vezes"] <= 0:
        return []
    momento = agora or datetime.now(timezone.utc)
    f = "%Y-%m-%dT%H:%M:%SZ"
    desde = (momento - timedelta(hours=ESCALA_JANELA_H)).strftime(f)
    limite = (momento - timedelta(minutes=cfg["escalar_min"])).strftime(f)
    saida = []
    with db_store._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT id, camera_id, site, camera_nome, criado_at, escalado_n, escalado_at FROM termico_alertas "
            "WHERE tenant_slug=? AND situacao='novo' AND criado_at>=? AND escalado_n<?",
            (tenant, desde, cfg["escalar_vezes"])).fetchall()]
        for r in rows:
            if (r.get("escalado_at") or r.get("criado_at") or "") > limite:
                continue
            c.execute("UPDATE termico_alertas SET escalado_n=escalado_n+1, escalado_at=? WHERE tenant_slug=? AND id=?",
                      (momento.strftime(f), tenant, r["id"]))
            saida.append(r)
    return saida


def anotar_falha_aviso(tenant: str, alerta_id: str, falhas: int) -> None:
    """Sem sessao: roda na thread do envio, o cliente vem explicito."""
    with db_store._conn() as c:
        c.execute("UPDATE termico_alertas SET aviso_falhas=? WHERE tenant_slug=? AND id=?",
                  (int(falhas), tenant, alerta_id))


def _falhas_por_camera(c: Any, tenant: str) -> Dict[str, int]:
    """Avisos e automacoes que nao sairam nas ultimas FALHAS_JANELA_H horas."""
    desde = (datetime.now(timezone.utc) - timedelta(hours=FALHAS_JANELA_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    falhas: Dict[str, int] = {}
    for r in c.execute("SELECT camera_id, SUM(aviso_falhas) AS n FROM termico_alertas "
                       "WHERE tenant_slug=? AND criado_at>=? GROUP BY camera_id", (tenant, desde)).fetchall():
        falhas[dict(r)["camera_id"]] = int(dict(r)["n"] or 0)
    for r in c.execute("SELECT a.camera_id, COUNT(*) AS n FROM automacao_execucoes e "
                       "JOIN termico_alertas a ON a.id=e.alerta_id AND a.tenant_slug=e.tenant_slug "
                       "WHERE e.tenant_slug=? AND e.ok=0 AND e.criado_at>=? GROUP BY a.camera_id",
                       (tenant, desde)).fetchall():
        cam = dict(r)["camera_id"]
        falhas[cam] = falhas.get(cam, 0) + int(dict(r)["n"] or 0)
    return falhas


def resumo_para_zabbix(tenant: str) -> Dict[str, Dict[str, Any]]:
    """Por camera (chave IP|conector): alertas pendentes, fundo e a leitura.

    termico_leitura: 1 = lendo; 0 = sem leitura (erro OU leitura parada ha mais
    de LEITURA_VELHA_S -- laco morto ou thread presa nao pode parecer "ok");
    2 = desligada/removida do Alerta Termico (fecha o gatilho de sem medicao).
    Camera que nunca leu fica de fora: nao cria item nem manda 0 enganoso. A que
    ja leu continua mesmo readicionada e parada, senao o gatilho nunca fecha.
    Pendentes vale tambem para desligada/removida: responder o alerta fecha o
    gatilho de pessoa."""
    with db_store._conn() as c:
        cams = [dict(r) for r in c.execute(
            "SELECT id, ip, connector_id, ativo, leitura, leitura_at, fundo_c FROM termico_cameras WHERE tenant_slug=?",
            (tenant,)).fetchall()]
        pend = {dict(r)["camera_id"]: int(dict(r)["n"]) for r in c.execute(
            "SELECT camera_id, COUNT(*) AS n FROM termico_alertas WHERE tenant_slug=? AND situacao='novo' GROUP BY camera_id",
            (tenant,)).fetchall()}
        falhas = _falhas_por_camera(c, tenant)
    saida = {}
    for cam in cams:
        leitura = cam.get("leitura") or ""
        if not leitura and not cam.get("leitura_at"):
            continue
        if not leitura or not int(cam.get("ativo") or 0) or leitura == REMOVIDA:
            estado, fundo = 2, None
        elif leitura == "ok" and _segundos_desde(cam.get("leitura_at") or "") <= LEITURA_VELHA_S:
            estado, fundo = 1, cam.get("fundo_c")
        else:
            estado, fundo = 0, None
        saida[chave(cam["ip"], cam.get("connector_id"))] = {
            "termico_pendentes": pend.get(cam["id"], 0),
            "termico_leitura": estado,
            "termico_fundo_c": fundo,
            "termico_falhas": falhas.get(cam["id"], 0),
        }
    return saida
