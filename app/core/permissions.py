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
import copy
import json
import logging
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
    {"key": "cameras", "label": "Câmeras e snapshots",
     "views": ["inv-olt", "snap-cam", "mnt-cam", "deploy-new", "deploy-activation"],
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
     "views": ["switch", "net-operate"],
     "prefixos": ["/api/switch", "/api/network"]},
    {"key": "conectores", "label": "Conectores", "views": ["connectors"], "prefixos": ["/api/connectors"]},
    {"key": "mapa", "label": "Mapa e projetos", "views": ["kmz", "planning"],
     "prefixos": ["/api/kmz", "/api/planning", "/api/mapa"]},
    {"key": "monitoramento", "label": "Monitoramento e Zabbix",
     "views": ["monitoring", "script-zabbix", "script-grafana"],
     "prefixos": ["/api/monitoring", "/api/scripts", "/api/telegram"]},
    {"key": "acesso", "label": "Controle de acesso",
     "views": ["access-live", "access-messenger", "access-control"],
     "prefixos": ["/api/access-control"]},
    {"key": "alerta", "label": "Alerta de pânico", "views": ["alert-live", "alert-members"], "prefixos": ["/api/alert"]},
    {"key": "investigacao", "label": "Investigação e IA", "views": ["playback", "ia-nvr"],
     "prefixos": ["/api/playback", "/api/ia"]},
    {"key": "computadores", "label": "Computadores", "views": ["inv-windows"], "prefixos": ["/api/windows"]},
    {"key": "implantacao", "label": "Implantação",
     "views": ["deploy-new", "deploy-recorder", "deploy-activation", "deploy-olt", "deploy-onu"],
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


def modulo_no_plano(modulo: str, enabled_modules: Any) -> bool:
    if enabled_modules is None:
        return True
    mod = next((m for m in MODULOS if m["key"] == modulo), None)
    if not mod or not mod["views"]:
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


def salvar_perfis(tenant_slug: str, dados: Dict[str, Any]) -> None:
    from app.services.db_store import set_json_state

    slug = str(tenant_slug or "").strip().lower()
    if not set_json_state(_chave_perfis(slug), dados).get("ok"):
        raise RuntimeError("nao foi possivel gravar os perfis de acesso")
    with _cache_lock:
        _cache.pop(slug, None)


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
    if perfil:
        for m, v in (perfil.get("levels") or {}).items():
            if m in niveis:
                niveis[m] = _nivel_int(v)
    for m, v in (cfg.get("overrides") or {}).items():
        if m in niveis:
            niveis[m] = _nivel_int(v)
    niveis["administracao"] = min(niveis["administracao"], base_role)
    return niveis


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
    return sorted(v for v, ns in por_view.items() if max(ns) <= 0)


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
    tem = niveis_do_usuario(user).get(modulo, 0)
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


def definir_acesso_usuario(tenant_slug: str, alvo: Dict[str, Any], perfil: str, ajustes: Dict[str, Any]) -> Dict[str, Any]:
    if str(alvo.get("role") or "").lower() == "owner":
        raise ValueError("o dono da conta tem acesso total e nao pode ser restringido")
    dados = copy.deepcopy(carregar_perfis(tenant_slug, usar_cache=False))  # nao mexe no cache antes de gravar
    perfil = str(perfil or "").strip().lower()
    if perfil and perfil not in dados["profiles"]:
        raise ValueError("perfil nao encontrado")
    cfg = {"profile": perfil or None, "overrides": _validar_niveis(ajustes)}
    cfg = {k: v for k, v in cfg.items() if v}
    uid = str(alvo.get("id"))
    if cfg:
        dados["users"][uid] = cfg
    else:
        dados["users"].pop(uid, None)
    salvar_perfis(tenant_slug, dados)
    return cfg


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
]
