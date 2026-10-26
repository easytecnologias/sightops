"""Permissao por modulo x nivel (fase 3 do console de Configuracoes).

Decisao nova, ao lado da antiga (perfil fixo viewer/operator/admin/owner):

  1. a rota pertence a um MODULO (pelo prefixo do caminho);
  2. o CLIENTE precisa ter esse modulo no plano (enabled_modules do tenant;
     antes isso so escondia o menu -- a API ficava aberta);
  3. o USUARIO precisa ter no modulo o NIVEL que a rota exige.

O nivel exigido sai das regras que ja existem em security._role_rules:
viewer -> ver, operator -> operar, admin -> administrar; GET sem regra -> ver;
escrita sem regra continua negada. Os 4 perfis antigos viram perfis padrao com
o mesmo nivel em todo modulo, entao a decisao nova e IGUAL a antiga para quem
nao tem perfil personalizado. E isso que o modo sombra prova antes de valer.

Perfis personalizados e ajustes por usuario ficam por cliente em json_state
(chave "perfis_acesso" do proprio tenant). O modo (sombra | valer) e da
plataforma (json_state tenant "_platform", chave "permissoes_modo").
"""

from __future__ import annotations

import collections
import contextvars
import copy
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("cam-snapshot")

NIVEIS = {"sem_acesso": 0, "ver": 1, "operar": 2, "administrar": 3}
NIVEL_NOME = {v: k for k, v in NIVEIS.items()}
_ROLE_NIVEL = {"viewer": 1, "operator": 2, "admin": 3, "owner": 3}

# `views` = chaves de MODULE_CATALOG (auth_store) que ligam o modulo no plano do
# cliente. Modulo sem views (Administracao) nunca e desligado pelo plano.
MODULOS: List[Dict[str, Any]] = [
    # Painel inicial: o plano do cliente nunca o desliga (nao esta no catalogo
    # do plano), so o perfil do usuario.
    {"key": "painel", "label": "Dashboard (painel inicial)", "views": ["dashboard"],
     "prefixos": ["/api/dashboard"], "sempre_no_plano": True},
    {"key": "cameras", "label": "Câmeras e snapshots",
     "views": ["inv-olt", "snap-cam", "mnt-cam", "deploy-new", "deploy-activation", "deploy-onvif"],
     "prefixos": ["/api/cameras", "/api/snapshot", "/api/inventory", "/api/inventory-last", "/api/maintenance",
                  "/api/geo", "/api/scan", "/api/rescan-single-ip", "/api/portscan", "/api/tools",
                  "/api/discovery", "/api/db/inventory"]},
    {"key": "gravadores", "label": "Gravadores",
     "views": ["inv-nvr", "snap-dvr", "mnt-nvr", "deploy-recorder"],
     "prefixos": ["/api/nvr", "/api/dvr"]},
    {"key": "optica", "label": "Rede óptica (OLT, ONU, TR-069)",
     "views": ["olt", "deploy-olt", "deploy-onu", "deploy-tr069"],
     "prefixos": ["/api/olt", "/api/tr069"]},
    {"key": "rede", "label": "Switches e rede",
     "views": ["switch", "switch-provedores", "net-operate"],
     "prefixos": ["/api/switch", "/api/network"]},
    {"key": "conectores", "label": "Conectores", "views": ["connectors"], "prefixos": ["/api/connectors"]},
    {"key": "mapa", "label": "Mapa", "views": ["kmz"], "prefixos": ["/api/kmz", "/api/mapa"]},
    # Projetos (Implantacao > Projetos) era parte de "Mapa e projetos": quem ja
    # tinha nivel em "mapa" e nada em "projetos" herda o de "mapa"
    # (niveis_do_usuario), para ninguem ganhar ou perder acesso na separacao.
    {"key": "projetos", "label": "Projetos", "views": ["planning"], "prefixos": ["/api/planning"]},
    {"key": "monitoramento", "label": "Monitoramento e Zabbix",
     "views": ["monitoring", "script-zabbix", "script-grafana"],
     "prefixos": ["/api/monitoring", "/api/scripts", "/api/telegram"]},
    {"key": "acesso", "label": "Controle de acesso",
     "views": ["access-live", "access-messenger", "access-control", "access-painel"],
     "prefixos": ["/api/access-control"]},
    {"key": "alerta", "label": "Alerta de pânico", "views": ["alert-live", "alert-members", "alert-reports"], "prefixos": ["/api/alert"]},
    {"key": "rotas", "label": "Controle de rotas (transporte escolar)",
     "views": ["rotas-vivo", "rotas-viagens", "rotas-cadastro", "rotas-frota", "rotas-pnate"],
     "prefixos": ["/api/rotas"]},
    {"key": "investigacao", "label": "Investigação e IA", "views": ["playback", "ia-nvr"],
     "prefixos": ["/api/playback", "/api/ia"]},
    {"key": "computadores", "label": "Computadores", "views": ["inv-windows"], "prefixos": ["/api/windows"]},
    {"key": "implantacao", "label": "Implantação",
     "views": ["deploy-new", "deploy-recorder", "deploy-activation", "deploy-onvif", "deploy-olt", "deploy-onu"],
     "prefixos": ["/api/deployments"]},
    {"key": "administracao", "label": "Administração (usuários e configurações)", "views": [],
     "prefixos": ["/api/auth/users", "/api/auth/audit", "/api/auth/access-profiles", "/api/settings",
                  "/api/backup", "/api/db", "/api/system/product", "/api/system/bootstrap"]},
]
_MODULO_KEYS = [m["key"] for m in MODULOS]
# prefixo mais longo primeiro: /api/db/inventory (cameras) antes de /api/db (administracao)
_PREFIXOS: List[Tuple[str, str]] = sorted(
    ((p, m["key"]) for m in MODULOS for p in m["prefixos"]), key=lambda x: -len(x[0])
)

PERFIS_PADRAO: Dict[str, Dict[str, Any]] = {
    "viewer": {"name": "Visualizador", "descricao": "Vê tudo, não altera nada."},
    "operator": {"name": "Operador", "descricao": "Opera equipamento no dia a dia."},
    "admin": {"name": "Administrador", "descricao": "Tudo do cliente, inclusive usuários."},
    "owner": {"name": "Dono da conta", "descricao": "Tudo do cliente. Não pode ser restringido."},
}


def modulo_da_rota(path: str) -> str:
    """Modulo do caminho pelo prefixo mais longo (casa o prefixo inteiro ou ate uma "/")."""
    for prefixo, key in _PREFIXOS:
        if path == prefixo or path.startswith(prefixo + "/"):
            return key
    return ""


def nivel_exigido(min_role: str, method: str) -> Optional[int]:
    """None = negado de qualquer jeito (escrita sem regra)."""
    if min_role:
        return _ROLE_NIVEL.get(str(min_role).lower(), 99)
    return NIVEIS["ver"] if method in ("GET", "HEAD") else None


# Excluir, limpar e remover: so administrador e dono (decisao do dono do
# produto em 21/10/2026). O operador faz todo o resto -- reiniciar camera,
# consultar, mapa, gravacao, cadastrar pessoa na controladora --, so nao
# destroi. Regra por FORMA da rota, nao por lista: rota nova de excluir nasce
# coberta. O proxy da pagina web do equipamento fica de fora: ali o DELETE e
# da propria camera/gravador, nao do SightOps.
_EXCLUSAO_NA_ROTA = re.compile(
    r"/(?:[a-z0-9]+-)*(?:delete|clear|excluir|remover|remove|revoke|limpar|apagar)(?:-[a-z0-9]+)*(?:/|$)"
)
_EXCLUSAO_FORA = ("/api/maintenance/web/",)
# Tem nome de exclusao mas e operacao do dia a dia: tirar item da lista do
# caso de investigacao que o proprio operador monta, e desligar o celular
# perdido/roubado de um membro do alerta (acao de seguranca, nao apaga dado).
_EXCLUSAO_LIBERADA = re.compile(
    r"^/api/nvr/driver/casos/[^/]+/itens/[^/]+/remover/?$|^/api/alert/members/[^/]+/revoke-devices/?$"
)
MSG_EXCLUIR = "Excluir e limpar são só para administrador ou dono da conta."


def pode_excluir(user: Optional[Dict[str, Any]] = None) -> bool:
    """Para a acao destrutiva que vem DENTRO de uma rota de uso normal (editar
    canal com acao=excluir, importar que substitui, esvaziar grupo...): a
    regra por forma de rota nao enxerga o corpo. Sem usuario (autenticacao
    desligada), nada muda. Operador com autorizacao de um administrador
    (senha digitada na hora, para ESTA requisicao) tambem pode."""
    if user is None:
        from app.core.tenant_context import get_current_user

        user = get_current_user()
    if not user:
        return True
    if str(user.get("role") or "").strip().lower() in ("admin", "owner"):
        return True
    return autorizacao_da_requisicao() is not None


# --------------------------------------------------------------------------- autorizacao do administrador
# O operador tenta excluir -> 403 com o cabecalho EXIGE_ADMIN -> a tela pede
# usuario e senha de um administrador -> /api/auth/autorizar-exclusao devolve
# um codigo de USO UNICO, preso ao operador, ao cliente e a esta acao exata
# (metodo + caminho), valido por 2 minutos -> a tela repete a requisicao com o
# codigo no cabecalho AUTORIZACAO. Em memoria: a API roda num processo so, e
# um codigo perdido num reinicio so obriga a digitar a senha de novo.
CABECALHO_EXIGE_ADMIN = "X-SightOps-Exige-Admin"
CABECALHO_AUTORIZACAO = "X-SightOps-Autorizacao"
_AUTORIZACAO_TTL = 120.0
_autorizacoes: Dict[str, Dict[str, Any]] = {}
_autorizacoes_lock = threading.Lock()
_AUTORIZACAO_ATUAL: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar(
    "sightops_autorizacao_admin", default=None)


def _tenant_de(user: Dict[str, Any]) -> str:
    return str(user.get("effective_tenant_slug") or user.get("tenant_slug") or "").strip().lower()


def hash_corpo(corpo: Any) -> str:
    import hashlib

    if isinstance(corpo, str):
        corpo = corpo.encode("utf-8")
    return hashlib.sha256(bytes(corpo or b"")).hexdigest()


def emitir_autorizacao(admin: Dict[str, Any], operador: Dict[str, Any], metodo: str, caminho: str,
                       corpo_hash: str = "") -> str:
    """corpo_hash: sha256 do corpo que a tela vai reenviar. O codigo so vale
    para ESSE conteudo -- sem isso o operador trocava o canal, o gravador ou o
    conector ao repetir o pedido."""
    import secrets

    agora = time.monotonic()
    codigo = secrets.token_urlsafe(24)
    with _autorizacoes_lock:
        for k in [k for k, v in _autorizacoes.items() if v["expira"] <= agora]:
            _autorizacoes.pop(k, None)
        if len(_autorizacoes) > 1000:
            _autorizacoes.clear()
        _autorizacoes[codigo] = {
            "expira": agora + _AUTORIZACAO_TTL, "tenant": _tenant_de(operador),
            "operador_id": int(operador.get("id") or 0), "metodo": str(metodo or "").upper(),
            "caminho": str(caminho or ""), "corpo": str(corpo_hash or hash_corpo(b"")),
            "admin_id": int(admin.get("id") or 0),
            "admin": str(admin.get("username") or ""),
        }
    return codigo


def consumir_autorizacao(codigo: str, operador: Dict[str, Any], metodo: str, caminho: str,
                         corpo: bytes = b"") -> Optional[Dict[str, Any]]:
    """Valida e gasta o codigo (uso unico). None se nao serve para isto."""
    codigo = str(codigo or "").strip()
    if not codigo or not operador:
        return None
    with _autorizacoes_lock:
        item = _autorizacoes.pop(codigo, None)
    if not item or item["expira"] <= time.monotonic():
        return None
    if (item["tenant"], item["operador_id"], item["metodo"], item["caminho"]) != (
            _tenant_de(operador), int(operador.get("id") or 0), str(metodo or "").upper(), str(caminho or "")):
        return None
    if item["corpo"] != hash_corpo(corpo):
        return None
    return item


def definir_autorizacao_da_requisicao(item: Optional[Dict[str, Any]]):
    return _AUTORIZACAO_ATUAL.set(item)


def limpar_autorizacao_da_requisicao(token) -> None:
    _AUTORIZACAO_ATUAL.reset(token)


def autorizacao_da_requisicao() -> Optional[Dict[str, Any]]:
    return _AUTORIZACAO_ATUAL.get()


def erro_exige_admin(detalhe: str = ""):
    """403 que a tela entende como "peca a senha de um administrador"."""
    from fastapi import HTTPException

    return HTTPException(status_code=403, detail=detalhe or MSG_EXCLUIR, headers={CABECALHO_EXIGE_ADMIN: "1"})


def e_exclusao(path: str, method: str) -> bool:
    path = str(path or "").lower()
    method = str(method or "").upper()
    if not path.startswith("/api/") or any(path.startswith(p) for p in _EXCLUSAO_FORA):
        return False
    if _EXCLUSAO_LIBERADA.match(path):
        return False
    if method == "DELETE":
        return True
    return method in ("POST", "PUT", "PATCH") and bool(_EXCLUSAO_NA_ROTA.search(path))


def modulo_no_plano(modulo: str, enabled_modules: Any) -> bool:
    if enabled_modules is None:
        return True
    mod = next((m for m in MODULOS if m["key"] == modulo), None)
    if not mod or not mod["views"] or mod.get("sempre_no_plano"):
        return True
    habilitados = set(enabled_modules or [])
    return any(v in habilitados for v in mod["views"])


# --------------------------------------------------------------------------- perfis do cliente

_CACHE_TTL = 30.0
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # chave = tenant_slug
_ultimo_bom: Dict[str, Dict[str, Any]] = {}  # ultima leitura que deu certo, por tenant
_cache_lock = threading.Lock()


class PerfisIndisponiveis(RuntimeError):
    """Nao deu para ler os perfis do cliente e nao ha leitura anterior boa."""


def _chave_perfis(tenant_slug: str) -> str:
    return f"perfis_acesso__tenant__{tenant_slug}"


def _ler_json_state(tenant_slug: str, k: str) -> Any:
    """Leitura direta, sem init_db(): este caminho roda no middleware de toda
    requisicao e init_db() passa pelo verificador de migrations (lock global no
    Postgres). Erro sobe: o middleware cai na regra antiga."""
    from app.services.db_store import _conn

    with _conn() as c:
        row = c.execute("SELECT v FROM json_state WHERE tenant_slug=? AND k=?", (tenant_slug, k)).fetchone()
    return json.loads(str(row["v"] or "null")) if row else None


def carregar_perfis(tenant_slug: str, usar_cache: bool = True) -> Dict[str, Any]:
    slug = str(tenant_slug or "").strip().lower()
    agora = time.monotonic()
    if usar_cache:
        with _cache_lock:
            hit = _cache.get(slug)
            if hit and agora - hit[0] < _CACHE_TTL:
                return hit[1]
    try:
        raw = _ler_json_state(slug, "perfis_acesso")
    except Exception as exc:
        # Banco falhou: usa a ultima leitura boa deste cliente. Sem nenhuma, nega
        # (com a regra valendo, cair na antiga apagaria as restricoes do perfil).
        with _cache_lock:
            velho = _ultimo_bom.get(slug)
        if velho is not None:
            logger.warning("permissoes: perfis de %s indisponiveis (%s); usando a ultima leitura boa", slug, exc)
            return velho
        raise PerfisIndisponiveis(str(exc)) from exc
    dados = raw if isinstance(raw, dict) else {}
    dados = {"profiles": dict(dados.get("profiles") or {}), "users": dict(dados.get("users") or {})}
    with _cache_lock:
        _cache[slug] = (agora, dados)
        _ultimo_bom[slug] = dados
    return dados


# Sobe a cada perfil/modo salvo: quem guarda "pode abrir" (ponte do acesso
# web, app/api/endpoints/ws.py) poe isto na chave e o que mudou vale na hora.
_versao_autorizacao = 0


def versao_autorizacao() -> int:
    return _versao_autorizacao


def _nova_versao_autorizacao() -> None:
    global _versao_autorizacao
    _versao_autorizacao += 1


def salvar_perfis(tenant_slug: str, dados: Dict[str, Any]) -> None:
    from app.services.db_store import set_json_state

    slug = str(tenant_slug or "").strip().lower()
    if not set_json_state(_chave_perfis(slug), dados).get("ok"):
        raise RuntimeError("nao foi possivel gravar os perfis de acesso")
    with _cache_lock:
        _cache.pop(slug, None)
    _nova_versao_autorizacao()


def _nivel_int(v: Any) -> int:
    if isinstance(v, str) and v in NIVEIS:
        return NIVEIS[v]
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError("nivel invalido")
    if n not in NIVEL_NOME:
        raise ValueError("nivel invalido")
    return n


def niveis_do_usuario(user: Dict[str, Any], dados: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Nivel efetivo por modulo: perfil (padrao = o perfil fixo) + ajustes do usuario.

    Administracao nunca passa do perfil fixo: varios handlers (criar usuario,
    redefinir senha...) conferem o perfil fixo por dentro."""
    role = str(user.get("role") or "").strip().lower()
    base_role = _ROLE_NIVEL.get(role, 0)
    niveis = {m: base_role for m in _MODULO_KEYS}
    if role == "owner":
        return niveis  # dono da conta nao e restringido (evita trancar o cliente para fora)
    slug = str(user.get("effective_tenant_slug") or user.get("tenant_slug") or "").strip().lower()
    dados = dados if dados is not None else carregar_perfis(slug)
    cfg = (dados.get("users") or {}).get(str(user.get("id"))) or {}
    perfil = (dados.get("profiles") or {}).get(str(cfg.get("profile") or ""))
    definidos: set = set()
    if perfil:
        for m, v in (perfil.get("levels") or {}).items():
            if m in niveis:
                niveis[m] = _nivel_int(v)
                definidos.add(m)
    for m, v in (cfg.get("overrides") or {}).items():
        if m in niveis:
            niveis[m] = _nivel_int(v)
            definidos.add(m)
    if "mapa" in definidos and "projetos" not in definidos:
        niveis["projetos"] = niveis["mapa"]  # antes era um modulo so
    # Telas desmarcadas no editor (arvore do menu): modulo com TODAS as telas
    # desmarcadas fica sem acesso tambem nas rotas, nao so some do menu.
    ocultas = set(cfg.get("telas_ocultas") or [])
    if ocultas:
        for m in MODULOS:
            if m["views"] and all(v in ocultas for v in m["views"]):
                niveis[m["key"]] = 0
    niveis["administracao"] = min(niveis["administracao"], base_role)
    return niveis


# Tipo de equipamento do monitoramento -> modulo que da acesso a ele.
MODULO_DO_TIPO = {
    "camera": "cameras", "nvr": "gravadores", "dvr": "gravadores", "onu": "optica", "olt": "optica",
    "switch": "rede", "access_point": "rede", "access_device": "acesso", "whatsapp": "acesso",
    "connector": "conectores", "windows": "computadores",
}


def modulos_ocultos_da_sessao() -> List[str]:
    """Modulos sem acesso (nem "ver") do usuario da requisicao, com a regra
    valendo. Vazio sem usuario, em sombra ou sem restricao: telas que juntam
    varios modulos (o painel inicial) escondem so o que ele nao ve."""
    if modo() != "valer":
        return []
    from app.core.tenant_context import get_current_user

    user = get_current_user()
    if not user:
        return []
    return sorted(m for m, n in niveis_do_usuario(user).items() if n <= 0)


def views_sem_acesso(user: Dict[str, Any]) -> List[str]:
    """Telas do menu que o usuario nao abre pela regra nova (so quando ela vale).

    Uma tela que aparece em mais de um modulo (ex.: implantar camera esta em
    Cameras e em Implantacao) so some se o usuario nao tiver nenhum deles."""
    if modo() != "valer":
        return []
    niveis = niveis_do_usuario(user)
    por_view: Dict[str, List[int]] = {}
    for m in MODULOS:
        for v in m["views"]:
            por_view.setdefault(v, []).append(niveis.get(m["key"], 0))
    sem = {v for v, ns in por_view.items() if max(ns) <= 0}
    if str(user.get("role") or "").strip().lower() != "owner":
        slug = str(user.get("effective_tenant_slug") or user.get("tenant_slug") or "").strip().lower()
        cfg = (carregar_perfis(slug).get("users") or {}).get(str(user.get("id"))) or {}
        sem |= set(cfg.get("telas_ocultas") or [])
    return sorted(sem)


# Rota de um modulo que outra tela tambem usa: o nivel no modulo alternativo
# tambem vale. A tela Projetos importa e desenha o KMZ do projeto pelas rotas
# do Mapa. So as rotas EXATAS que ela chama: o prefixo inteiro abria editar
# camada do Mapa e gravar coordenadas no inventario.
_MODULO_ALTERNATIVO: List[Tuple[str, str, str]] = [
    ("POST", "/api/kmz/import", "projetos"),
    ("GET", "/api/kmz/import/layers", "projetos"),
]


def decidir(user: Dict[str, Any], path: str, method: str, min_role: str) -> Tuple[bool, str]:
    """(permitido, motivo) pela regra nova."""
    role = str(user.get("role") or "").strip().lower()
    if str(min_role or "").lower() == "owner":
        return (role == "owner"), ("" if role == "owner" else "requer dono da conta")
    exigido = nivel_exigido(min_role, method)
    if exigido is None:
        return False, "escrita sem regra declarada"
    # Rotas que hoje exigem admin (backup com CPF e foto, trocar IP de gravador,
    # config do TR-069...) continuam exigindo o perfil fixo admin: perfil
    # personalizado nunca da mais que "operar" a quem nao e administrador.
    if exigido >= NIVEIS["administrar"] and _ROLE_NIVEL.get(role, 0) < NIVEIS["administrar"]:
        return False, "requer perfil fixo administrador"
    modulo = modulo_da_rota(path)
    if not modulo:
        # Rota fora dos modulos (login, painel, plataforma): so o perfil fixo, como antes.
        tem = _ROLE_NIVEL.get(str(user.get("role") or "").lower(), 0)
        return (tem >= exigido), ("" if tem >= exigido else f"requer {NIVEL_NOME.get(exigido, exigido)}")
    if not modulo_no_plano(modulo, user.get("effective_enabled_modules")):
        return False, f"modulo {modulo} fora do plano do cliente"
    niveis = niveis_do_usuario(user)
    tem = niveis.get(modulo, 0)
    for metodo, caminho, alternativo in _MODULO_ALTERNATIVO:
        if method == metodo and path.rstrip("/") == caminho and modulo_no_plano(alternativo, user.get("effective_enabled_modules")):
            tem = max(tem, niveis.get(alternativo, 0))
    if tem < exigido:
        return False, f"requer {NIVEL_NOME.get(exigido, exigido)} em {modulo} (tem {NIVEL_NOME.get(tem, tem)})"
    return True, ""


# --------------------------------------------------------------------------- modo e divergencias

_MODO_TTL = 30.0
_modo_cache: Tuple[float, str] = (0.0, "")
_modo_lock = threading.Lock()
_DIVERGENCIAS: "collections.deque[Dict[str, Any]]" = collections.deque(maxlen=500)
_CONTAGEM: Dict[Tuple[str, str, str, str], int] = collections.Counter()
_div_lock = threading.Lock()
_MAX_GRUPOS = 2000
_CHAVE_EXCESSO = ("*", "*", "(outras rotas: limite de grupos atingido)", "*")
_CHAVE_MODO = "permissoes_modo__tenant___platform"


def modo() -> str:
    """'sombra' (padrao: calcula e registra, vale a regra antiga) ou 'valer'."""
    global _modo_cache
    agora = time.monotonic()
    with _modo_lock:
        if agora - _modo_cache[0] < _MODO_TTL and _modo_cache[1]:
            return _modo_cache[1]
    try:
        raw = _ler_json_state("_platform", "permissoes_modo")
        valor = str((raw or {}).get("modo") or "sombra") if isinstance(raw, dict) else "sombra"
    except Exception:
        valor = "sombra"  # sem conseguir ler, fica no seguro: vale a regra antiga
    valor = valor if valor in ("sombra", "valer") else "sombra"
    with _modo_lock:
        _modo_cache = (agora, valor)
    return valor


def definir_modo(actor: Dict[str, Any], novo: str) -> str:
    global _modo_cache
    if not bool(actor.get("is_platform_admin")):
        raise PermissionError("somente admin da plataforma")
    if novo not in ("sombra", "valer"):
        raise ValueError("modo deve ser sombra ou valer")
    from app.services.db_store import set_json_state

    if not set_json_state(_CHAVE_MODO, {"modo": novo, "por": actor.get("username"),
                                        "em": datetime.now(timezone.utc).isoformat()}).get("ok"):
        raise RuntimeError("nao foi possivel gravar o modo")
    with _modo_lock:
        _modo_cache = (time.monotonic(), novo)
    _nova_versao_autorizacao()
    return novo


def _rota_agrupada(path: str) -> str:
    """/api/nvr/driver/10.0.0.5/canais -> /api/nvr/driver/:id/canais (agrupa por rota, nao por equipamento)."""
    out = []
    for parte in [p for p in path.split("/") if p][:6]:
        tem_digito = any(ch.isdigit() for ch in parte)
        out.append(":id" if tem_digito and (len(parte) > 3 or "." in parte) else parte)
    return "/" + "/".join(out)


def registrar_divergencia(user: Dict[str, Any], path: str, method: str, antiga: bool, nova: bool, motivo: str) -> None:
    tenant = str(user.get("effective_tenant_slug") or user.get("tenant_slug") or "")
    rota = _rota_agrupada(path)
    chave = (tenant, method, rota, f"{'permitia' if antiga else 'negava'}->{'permite' if nova else 'nega'}")
    with _div_lock:
        if chave not in _CONTAGEM and len(_CONTAGEM) >= _MAX_GRUPOS:
            _CONTAGEM[_CHAVE_EXCESSO] += 1  # teto: caminho inventado nao cresce a memoria
            return
        _CONTAGEM[chave] += 1
        primeira = _CONTAGEM[chave] == 1
        _DIVERGENCIAS.appendleft({
            "em": datetime.now(timezone.utc).isoformat(), "tenant": tenant, "usuario": user.get("username"),
            "role": user.get("role"), "metodo": method, "rota": rota, "antiga": antiga, "nova": nova, "motivo": motivo,
        })
    if primeira:
        logger.warning("permissoes(sombra): %s %s tenant=%s user=%s antiga=%s nova=%s %s",
                       method, rota, tenant, user.get("username"), antiga, nova, motivo)


def resumo_sombra() -> Dict[str, Any]:
    with _div_lock:
        grupos = [
            {"tenant": t, "metodo": m, "rota": r, "mudanca": mud, "vezes": n}
            for (t, m, r, mud), n in sorted(_CONTAGEM.items(), key=lambda kv: -kv[1])
        ]
        recentes = list(_DIVERGENCIAS)[:100]
    return {"modo": modo(), "grupos": grupos[:200], "recentes": recentes, "total": sum(g["vezes"] for g in grupos)}


# --------------------------------------------------------------------------- edicao pelo cliente

def _validar_niveis(niveis: Dict[str, Any]) -> Dict[str, int]:
    if niveis is not None and not isinstance(niveis, dict):
        raise ValueError("niveis devem ser um objeto modulo -> nivel")
    limpos: Dict[str, int] = {}
    for m, v in (niveis or {}).items():
        if m not in _MODULO_KEYS:
            raise ValueError(f"modulo desconhecido: {m}")
        limpos[m] = _nivel_int(v)
    return limpos


def salvar_perfil(tenant_slug: str, chave: str, nome: str, niveis: Dict[str, Any]) -> Dict[str, Any]:
    chave = "".join(ch for ch in str(chave or "").strip().lower() if ch.isalnum() or ch in "-_")[:40]
    if not chave or chave in PERFIS_PADRAO:
        raise ValueError("chave de perfil invalida (os perfis padrao nao podem ser alterados)")
    nome = str(nome or "").strip()[:60]
    if not nome:
        raise ValueError("nome do perfil obrigatorio")
    dados = copy.deepcopy(carregar_perfis(tenant_slug, usar_cache=False))  # nao mexe no cache antes de gravar
    dados["profiles"][chave] = {"name": nome, "levels": _validar_niveis(niveis)}
    salvar_perfis(tenant_slug, dados)
    return dados["profiles"][chave]


def excluir_perfil(tenant_slug: str, chave: str) -> None:
    dados = copy.deepcopy(carregar_perfis(tenant_slug, usar_cache=False))  # nao mexe no cache antes de gravar
    if chave not in dados["profiles"]:
        raise LookupError("perfil nao encontrado")
    em_uso = [uid for uid, cfg in dados["users"].items() if (cfg or {}).get("profile") == chave]
    if em_uso:
        raise ValueError(f"perfil em uso por {len(em_uso)} usuario(s)")
    dados["profiles"].pop(chave, None)
    salvar_perfis(tenant_slug, dados)


def sites_do_cliente(tenant_slug: str) -> List[Dict[str, Any]]:
    """Sites do cliente: os cadastrados e os que ja aparecem nos equipamentos
    monitorados, com quantos equipamentos cada um tem."""
    from app.services.db_store import _conn

    slug = str(tenant_slug or "").strip().lower()
    contagem: Dict[str, int] = {}
    with _conn() as c:
        for row in c.execute(
            "SELECT trim(COALESCE(name,'')) AS name FROM sites WHERE tenant_slug=? AND active=1", (slug,)
        ).fetchall():
            nome = str(row["name"] or "").strip()
            if nome and nome.upper() != "GERAL":
                contagem.setdefault(nome, 0)
        for row in c.execute(
            "SELECT trim(COALESCE(site,'')) AS site, COUNT(1) AS n FROM monitoring_entities"
            " WHERE tenant_slug=? AND monitoring_enabled=1 GROUP BY trim(COALESCE(site,''))", (slug,)
        ).fetchall():
            nome = str(row["site"] or "").strip()
            if nome and nome.upper() != "GERAL":
                contagem[nome] = contagem.get(nome, 0) + int(row["n"] or 0)
    return [{"name": n, "equipamentos": contagem[n]} for n in sorted(contagem, key=str.upper)]


def _validar_sites(tenant_slug: str, sites: Any) -> List[str]:
    if sites is None:
        return []
    if not isinstance(sites, list):
        raise ValueError("sites deve ser uma lista")
    validos = {s["name"].upper(): s["name"] for s in sites_do_cliente(tenant_slug)}
    limpos: List[str] = []
    for s in sites:
        nome = str(s or "").strip()
        if not nome:
            continue
        if nome.upper() not in validos:
            raise ValueError(f"site desconhecido: {nome}")
        if validos[nome.upper()] not in limpos:
            limpos.append(validos[nome.upper()])
    return limpos


def sites_do_usuario(user: Dict[str, Any], dados: Optional[Dict[str, Any]] = None) -> List[str]:
    """Sites que o usuario acessa. Lista vazia = todos (padrao; dono sempre todos)."""
    if str(user.get("role") or "").lower() == "owner":
        return []
    slug = str(user.get("effective_tenant_slug") or user.get("tenant_slug") or "").strip().lower()
    dados = dados if dados is not None else carregar_perfis(slug)
    cfg = (dados.get("users") or {}).get(str(user.get("id"))) or {}
    return list(cfg.get("sites") or [])


_TELA_VALIDA = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _validar_telas(telas: Any) -> List[str]:
    if not isinstance(telas, list):
        raise ValueError("telas_ocultas deve ser uma lista")
    limpas = sorted({str(t or "").strip().lower() for t in telas if str(t or "").strip()})
    if len(limpas) > 120 or any(not _TELA_VALIDA.match(t) for t in limpas):
        raise ValueError("tela invalida")
    return limpas


def definir_acesso_usuario(tenant_slug: str, alvo: Dict[str, Any], perfil: str, ajustes: Dict[str, Any],
                           sites: Any = None, telas_ocultas: Any = None) -> Dict[str, Any]:
    """`sites=None` mantem os sites atuais; lista vazia = todos os sites.
    `telas_ocultas=None` mantem as atuais; lista = telas do menu que a pessoa
    nao ve (desmarcadas na arvore do editor)."""
    if str(alvo.get("role") or "").lower() == "owner":
        raise ValueError("o dono da conta tem acesso total e nao pode ser restringido")
    dados = copy.deepcopy(carregar_perfis(tenant_slug, usar_cache=False))  # nao mexe no cache antes de gravar
    perfil = str(perfil or "").strip().lower()
    if perfil and perfil not in dados["profiles"]:
        raise ValueError("perfil nao encontrado")
    atual = (dados["users"].get(str(alvo.get("id"))) or {})
    lista_sites = list(atual.get("sites") or []) if sites is None else _validar_sites(tenant_slug, sites)
    telas = list(atual.get("telas_ocultas") or []) if telas_ocultas is None else _validar_telas(telas_ocultas)
    cfg = {"profile": perfil or None, "overrides": _validar_niveis(ajustes), "sites": lista_sites,
           "telas_ocultas": telas}
    cfg = {k: v for k, v in cfg.items() if v}
    uid = str(alvo.get("id"))
    if cfg:
        dados["users"][uid] = cfg
    else:
        dados["users"].pop(uid, None)
    salvar_perfis(tenant_slug, dados)
    return cfg


# --------------------------------------------------------------------------- para os outros caminhos
# Quem autoriza fora do middleware (ws/web-tunnel, proxy web, conector) usa estas
# duas. As duas respeitam o modo: em "sombra" respondem como a regra antiga (so o
# perfil fixo, todos os sites), entao ninguem perde acesso antes do "valer".

def pode(user: Dict[str, Any], modulo: str, nivel: str = "ver") -> bool:
    """O usuario tem `nivel` (ver | operar | administrar) no `modulo`?"""
    exigido = NIVEIS.get(str(nivel or "ver"), 1)
    role = str(user.get("role") or "").strip().lower()
    fixo = _ROLE_NIVEL.get(role, 0)
    if modo() != "valer":
        return fixo >= exigido
    if exigido >= NIVEIS["administrar"] and fixo < NIVEIS["administrar"]:
        return False
    if not modulo_no_plano(modulo, user.get("effective_enabled_modules")):
        return False
    return niveis_do_usuario(user).get(modulo, 0) >= exigido


def site_liberado(user: Dict[str, Any], site: Any) -> bool:
    """O usuario pode ver/operar equipamento deste site?

    Usuario sem restricao (lista vazia) ve todos. Com restricao, equipamento sem
    site definido fica de fora: na duvida, nao mostra."""
    if modo() != "valer":
        return True
    sites = sites_do_usuario(user)
    if not sites:
        return True
    nome = str(site or "").strip().upper()
    return bool(nome) and nome in {s.upper() for s in sites}


_CAMPOS_SITE = ("site", "site_name", "local", "LOCAL")


def sites_da_sessao() -> Optional[List[str]]:
    """Sites que a requisicao atual pode ver; None = sem filtro (sombra, laco de
    fundo, usuario sem restricao ou dono)."""
    from app.core.tenant_context import get_current_user

    user = get_current_user()
    if not user or modo() != "valer":
        return None
    sites = sites_do_usuario(user)
    return list(sites) if sites else None


def filtrar_por_site(linhas: Any, campos: Tuple[str, ...] = _CAMPOS_SITE) -> Any:
    """Tira das listas o que e de site que o usuario da sessao nao acessa.

    Linha sem site nenhum fica de fora para quem tem restricao (na duvida, nao
    mostra). Sem restricao, devolve a mesma lista intacta."""
    sites = sites_da_sessao()
    if sites is None or not isinstance(linhas, list):
        return linhas
    liberados = {s.strip().upper() for s in sites}
    saida = []
    for linha in linhas:
        if not isinstance(linha, dict):
            continue
        if site_da_linha(linha, campos).upper() in liberados:
            saida.append(linha)
    return saida


def site_da_linha(linha: Dict[str, Any], campos: Tuple[str, ...] = _CAMPOS_SITE) -> str:
    """Site do equipamento = o PRIMEIRO campo preenchido (site, site_name, local).

    Nao a uniao: com a uniao, quem edita o "local" de uma camera de outro site
    (o operador edita esse campo) passava a ve-la."""
    for c in campos:
        v = str(linha.get(c) or "").strip()
        if v:
            return v
    return ""


def catalogo() -> Dict[str, Any]:
    return {
        "modulos": [{"key": m["key"], "label": m["label"], "views": m["views"]} for m in MODULOS],
        "niveis": [{"key": k, "valor": v} for k, v in NIVEIS.items()],
        "perfis_padrao": [{"key": k, **v, "nivel": NIVEL_NOME[_ROLE_NIVEL[k]]} for k, v in PERFIS_PADRAO.items()],
    }


def _limpar_cache_para_testes() -> None:
    global _modo_cache
    with _cache_lock:
        _cache.clear()
        _ultimo_bom.clear()
    with _modo_lock:
        _modo_cache = (0.0, "")
    with _div_lock:
        _DIVERGENCIAS.clear()
        _CONTAGEM.clear()


__all__ = [
    "MODULOS", "NIVEIS", "PERFIS_PADRAO", "modulo_da_rota", "nivel_exigido", "modulo_no_plano",
    "niveis_do_usuario", "decidir", "modo", "definir_modo", "registrar_divergencia", "resumo_sombra",
    "carregar_perfis", "salvar_perfil", "excluir_perfil", "definir_acesso_usuario", "catalogo",
    "pode", "site_liberado", "sites_do_usuario", "sites_da_sessao", "filtrar_por_site", "site_da_linha",
]
