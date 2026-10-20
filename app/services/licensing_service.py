"""Planos e licencas por equipamento.

O SightOps e vendido por quantidade de equipamento monitorado. A contagem sai
de `monitoring_entities` (o que vira host no Zabbix), com peso por tipo: uma
OLT vale mais que uma camera, e dez ONUs valem uma licenca.

Planos, pesos, politica de limite e o plano de cada cliente sao dados da
PLATAFORMA, nao de um cliente: ficam numa linha unica de `json_state` com
tenant_slug `_platform`. So o admin da plataforma escreve; o cliente le apenas
o resumo do proprio plano (`tenant_summary`).

Limite estourado nunca desliga monitoramento. Nesta versao o sistema so mede,
avisa e marca a tolerancia; bloquear cadastro novo vem depois.
"""

from __future__ import annotations

import copy
import json
import math
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.db_store import _conn as _main_conn, init_db, set_json_state

# set_json_state entende "<chave>__tenant__<slug>": grava em tenant_slug=_platform.
_STATE_TENANT, _STATE_K = "_platform", "licensing"
_STATE_KEY = f"{_STATE_K}__tenant__{_STATE_TENANT}"
# "Acima do limite desde" fica em outra linha: e escrito a partir de leituras
# do proprio cliente e nao pode regravar planos/pesos que so a plataforma edita.
_OVER_K = "licensing_over"
_OVER_KEY = f"{_OVER_K}__tenant__{_STATE_TENANT}"
_LOCK = threading.Lock()

# Tipos de `monitoring_entities.entity_type`. Rotulo = como aparece na tela.
ENTITY_TYPES: List[Dict[str, Any]] = [
    {"type": "camera", "label": "Câmera IP", "weight": 1},
    {"type": "nvr", "label": "Gravador NVR/DVR", "weight": 1},
    {"type": "dvr", "label": "DVR", "weight": 1},
    {"type": "switch", "label": "Switch", "weight": 1},
    {"type": "access_point", "label": "Access point", "weight": 1},
    {"type": "access_device", "label": "Controladora de acesso", "weight": 1},
    {"type": "olt", "label": "OLT", "weight": 5},
    {"type": "onu", "label": "ONU", "weight": 0.1},
    {"type": "windows", "label": "Computador com agente", "weight": 0.5},
    {"type": "connector", "label": "Conector", "weight": 0},
    {"type": "whatsapp", "label": "Canal WhatsApp", "weight": 0},
]
_TYPE_LABEL = {t["type"]: t["label"] for t in ENTITY_TYPES}

DEFAULT_PLANS: List[Dict[str, Any]] = [
    {"key": "teste", "name": "Teste", "license_limit": 25, "user_limit": 2, "price": 0,
     "trial_days": 14, "features": ["CFTV e gravadores", "Snapshots", "Monitoramento e Zabbix"]},
    {"key": "essencial", "name": "Essencial", "license_limit": 100, "user_limit": 3, "price": 9.90,
     "trial_days": 0, "features": ["CFTV e gravadores", "Snapshots e relatórios", "Monitoramento e Zabbix", "WhatsApp 300/mês"]},
    {"key": "profissional", "name": "Profissional", "license_limit": 250, "user_limit": 10, "price": 8.50,
     "trial_days": 0, "features": ["Tudo do Essencial", "OLT, ONU e TR-069", "Controle de acesso", "Alerta de pânico", "Mapa e projetos"]},
    {"key": "empresarial", "name": "Empresarial", "license_limit": None, "user_limit": None, "price": None,
     "trial_days": 0, "features": ["Tudo do Profissional", "IA em gravação", "API sem limite", "Suporte dedicado"]},
    {"key": "interno", "name": "Interno", "license_limit": None, "user_limit": None, "price": None,
     "trial_days": 0, "features": ["Uso da própria Easy, sem limite"]},
]

DEFAULT_POLICY: Dict[str, Any] = {
    "warn_pct": 90,          # avisa a partir de X% do limite
    "tolerance_pct": 10,     # pode passar ate X% do limite...
    "tolerance_days": 15,    # ...por N dias
    "after": "block",        # block | charge | warn  (o que fazer depois da tolerancia)
    "overage_price": 11.00,  # R$ por equipamento excedente, se after=charge
}

_AFTER_CHOICES = {"block", "charge", "warn"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_state() -> Dict[str, Any]:
    return {
        "weights": {t["type"]: t["weight"] for t in ENTITY_TYPES},
        "policy": dict(DEFAULT_POLICY),
        "plans": copy.deepcopy(DEFAULT_PLANS),
        "tenants": {"default": {"plan": "interno"}},
    }


def _read_row(k: str) -> Any:
    init_db()
    with _main_conn() as c:
        row = c.execute("SELECT v FROM json_state WHERE tenant_slug=? AND k=?", (_STATE_TENANT, k)).fetchone()
    return json.loads(str(row["v"] or "null")) if row else None


def _load_over() -> Dict[str, str]:
    raw = _read_row(_OVER_K)
    return {str(k): str(v) for k, v in raw.items() if v} if isinstance(raw, dict) else {}


def _save_over(over: Dict[str, str]) -> None:
    if not set_json_state(_OVER_KEY, over).get("ok"):
        raise RuntimeError("nao foi possivel gravar o estado de excesso")


def _load() -> Dict[str, Any]:
    # Le direto em vez de get_json_state(): aquele devolve o padrao quando o
    # banco falha, e a gravacao seguinte apagaria os planos reais com o padrao.
    raw = _read_row(_STATE_K)
    state = _default_state()
    if isinstance(raw, dict):
        if isinstance(raw.get("weights"), dict):
            state["weights"].update({str(k): raw["weights"][k] for k in raw["weights"]})
        if isinstance(raw.get("policy"), dict):
            state["policy"].update(raw["policy"])
        if isinstance(raw.get("plans"), list) and raw["plans"]:
            state["plans"] = raw["plans"]
        if isinstance(raw.get("tenants"), dict):
            state["tenants"] = raw["tenants"]
    return state


def _save(state: Dict[str, Any]) -> None:
    result = set_json_state(_STATE_KEY, state)
    if not result.get("ok"):
        raise RuntimeError("nao foi possivel gravar a configuracao de licencas")


# --------------------------------------------------------------------------- contagem

def count_entities(tenant_slug: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """{tenant_slug: {entity_type: quantidade}} do que esta cadastrado no monitoramento."""
    sql = "SELECT tenant_slug, entity_type, COUNT(*) AS n FROM monitoring_entities"
    params: tuple = ()
    if tenant_slug:
        sql += " WHERE tenant_slug=?"
        params = (str(tenant_slug).strip().lower(),)
    sql += " GROUP BY tenant_slug, entity_type"
    out: Dict[str, Dict[str, int]] = {}
    init_db()
    with _main_conn() as c:
        for row in c.execute(sql, params).fetchall():
            slug = str(row["tenant_slug"] or "").strip().lower()
            out.setdefault(slug, {})[str(row["entity_type"] or "")] = int(row["n"] or 0)
    return out


def _weight(weights: Dict[str, Any], entity_type: str) -> float:
    try:
        return max(0.0, float(weights.get(entity_type, 1)))
    except (TypeError, ValueError):
        return 1.0


def _breakdown(counts: Dict[str, int], weights: Dict[str, Any]) -> tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    total = 0.0
    known = [t["type"] for t in ENTITY_TYPES]
    for et in known + sorted(k for k in counts if k not in known):
        n = int(counts.get(et, 0))
        if not n:
            continue
        w = _weight(weights, et)
        lic = n * w
        total += lic
        rows.append({"type": et, "label": _TYPE_LABEL.get(et, et), "count": n, "weight": w, "licenses": round(lic, 1)})
    # Fracao conta como licenca inteira: 151 ONUs a 0,1 = 15,1 -> 16.
    return rows, int(math.ceil(round(total, 6)))


# --------------------------------------------------------------------------- resumo

def _plan_by_key(state: Dict[str, Any], key: Optional[str]) -> Optional[Dict[str, Any]]:
    for p in state["plans"]:
        if str(p.get("key")) == str(key or ""):
            return p
    return None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _days_since(iso: Any) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except ValueError:
        return None


def _summarize(slug: str, counts: Dict[str, int], state: Dict[str, Any], users: Optional[int] = None,
               over: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    cfg = dict(state["tenants"].get(slug) or {})
    plan = _plan_by_key(state, cfg.get("plan"))
    rows, used = _breakdown(counts, state["weights"])
    override = _int_or_none(cfg.get("license_limit"))
    limit = override if override is not None else (_int_or_none(plan.get("license_limit")) if plan else None)
    user_override = _int_or_none(cfg.get("user_limit"))
    user_limit = user_override if user_override is not None else (_int_or_none(plan.get("user_limit")) if plan else None)
    pol = state["policy"]
    tol_pct = _int_or_none(cfg.get("tolerance_pct"))
    tol_pct = tol_pct if tol_pct is not None else int(pol.get("tolerance_pct") or 0)
    tol_days = _int_or_none(cfg.get("tolerance_days"))
    tol_days = tol_days if tol_days is not None else int(pol.get("tolerance_days") or 0)

    status, over_since, tolerance_until = "sem_plano", None, None
    if plan and limit is None:
        status = "sem_limite"
    elif limit is not None:
        over_since = (over or {}).get(slug) if used > limit else None
        if used <= limit:
            status = "aviso" if limit and used * 100 >= limit * int(pol.get("warn_pct") or 90) else "ok"
        else:
            days = _days_since(over_since)
            within_pct = used <= limit * (1 + tol_pct / 100.0)
            within_days = days is None or days <= tol_days
            status = "tolerancia" if (within_pct and within_days) else "excedido"
            if over_since:
                try:
                    start = datetime.fromisoformat(str(over_since))
                    tolerance_until = (start.timestamp() + tol_days * 86400)
                    tolerance_until = datetime.fromtimestamp(tolerance_until, timezone.utc).date().isoformat()
                except ValueError:
                    tolerance_until = None
    return {
        "tenant_slug": slug,
        "plan": ({"key": plan.get("key"), "name": plan.get("name"), "price": plan.get("price"),
                  "features": plan.get("features") or []} if plan else None),
        "license_limit": limit,
        "license_limit_override": override is not None,
        "licenses_used": used,
        "user_limit": user_limit,
        "users": users,
        "breakdown": rows,
        "status": status,
        "over_since": over_since,
        "tolerance_pct": tol_pct,
        "tolerance_days": tol_days,
        "tolerance_until": tolerance_until,
        "after": pol.get("after") or "block",
        "renewal": cfg.get("renewal") or "",
        "note": cfg.get("note") or "",
    }


def _track_over_since(over: Dict[str, str], summaries: List[Dict[str, Any]]) -> None:
    """Grava/limpa o inicio do excesso, para a tolerancia ter prazo real."""
    changed = False
    for s in summaries:
        slug = s["tenant_slug"]
        is_over = s["license_limit"] is not None and s["licenses_used"] > s["license_limit"]
        if is_over and not over.get(slug):
            over[slug] = _now()
            s["over_since"] = over[slug]
            changed = True
        elif not is_over and slug in over:
            over.pop(slug, None)
            changed = True
    if changed:
        _save_over(over)


def tenant_summary(tenant_slug: str, users: Optional[int] = None) -> Dict[str, Any]:
    slug = str(tenant_slug or "").strip().lower()
    with _LOCK:
        state, over = _load(), _load_over()
        counts = count_entities(slug).get(slug, {})
        summary = _summarize(slug, counts, state, users, over)
        _track_over_since(over, [summary])
    return summary


def platform_overview(tenants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tudo que o Painel do Dono precisa: planos, pesos, politica e uso de cada cliente."""
    with _LOCK:
        state, over = _load(), _load_over()
        counts = count_entities()
        summaries = []
        for t in tenants:
            slug = str(t.get("slug") or "").strip().lower()
            s = _summarize(slug, counts.get(slug, {}), state, int(t.get("users") or 0), over)
            s.update({"tenant_id": t.get("id"), "tenant_name": t.get("name") or slug,
                      "active": t.get("active"), "created_at": t.get("created_at")})
            summaries.append(s)
        _track_over_since(over, summaries)
    for p in state["plans"]:
        p["tenants"] = sum(1 for s in summaries if (s["plan"] or {}).get("key") == p.get("key"))
    return {
        "plans": state["plans"],
        "weights": state["weights"],
        "entity_types": ENTITY_TYPES,
        "policy": state["policy"],
        "tenants": summaries,
    }


# --------------------------------------------------------------------------- escrita (so plataforma)

def _require_platform(actor: Dict[str, Any]) -> None:
    if not bool(actor.get("is_platform_admin")):
        raise PermissionError("somente admin da plataforma")


def _clean_plan(raw: Dict[str, Any], existing: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    name = str(raw.get("name") or (existing or {}).get("name") or "").strip()
    if not name:
        raise ValueError("nome do plano obrigatorio")
    price = raw.get("price")
    try:
        price = None if price in (None, "") else round(float(str(price).replace(",", ".")), 2)
    except ValueError:
        raise ValueError("preco invalido")
    features = raw.get("features")
    if isinstance(features, str):
        features = [f.strip() for f in features.split("\n") if f.strip()]
    return {
        "key": str((existing or {}).get("key") or raw.get("key") or "").strip().lower(),
        "name": name,
        "license_limit": _int_or_none(raw.get("license_limit")),
        "user_limit": _int_or_none(raw.get("user_limit")),
        "price": price,
        "trial_days": _int_or_none(raw.get("trial_days")) or 0,
        "features": [str(f)[:80] for f in (features or [])][:12],
    }


def save_plan(actor: Dict[str, Any], key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_platform(actor)
    key = "".join(ch for ch in str(key or "").strip().lower() if ch.isalnum() or ch in "-_")
    if not key:
        raise ValueError("chave do plano invalida")
    with _LOCK:
        state = _load()
        existing = _plan_by_key(state, key)
        plan = _clean_plan({**payload, "key": key}, existing)
        if existing:
            state["plans"] = [plan if p.get("key") == key else p for p in state["plans"]]
        else:
            state["plans"].append(plan)
        _save(state)
    _audit(actor, "licensing.plan", key, {"plan": plan})
    return plan


def save_weights(actor: Dict[str, Any], weights: Dict[str, Any]) -> Dict[str, Any]:
    _require_platform(actor)
    clean: Dict[str, float] = {}
    for k, v in (weights or {}).items():
        try:
            f = float(str(v).replace(",", "."))
        except ValueError:
            raise ValueError(f"peso invalido para {k}")
        if f < 0 or f > 100:
            raise ValueError(f"peso fora da faixa para {k}")
        clean[str(k)] = round(f, 2)
    with _LOCK:
        state = _load()
        before = dict(state["weights"])
        state["weights"].update(clean)
        _save(state)
    _audit(actor, "licensing.weights", "weights", {"before": before, "after": state["weights"]})
    return state["weights"]


def save_policy(actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_platform(actor)
    with _LOCK:
        state = _load()
        pol = state["policy"]
        before = dict(pol)
        for k in ("warn_pct", "tolerance_pct", "tolerance_days"):
            if k in payload:
                v = _int_or_none(payload.get(k))
                if v is None or v > 365:
                    raise ValueError(f"valor invalido para {k}")
                pol[k] = v
        if "after" in payload:
            after = str(payload.get("after") or "").strip()
            if after not in _AFTER_CHOICES:
                raise ValueError("acao depois da tolerancia invalida")
            pol["after"] = after
        if "overage_price" in payload:
            try:
                pol["overage_price"] = round(float(str(payload.get("overage_price")).replace(",", ".")), 2)
            except ValueError:
                raise ValueError("preco do excedente invalido")
        _save(state)
    _audit(actor, "licensing.policy", "policy", {"before": before, "after": pol})
    return pol


def set_tenant_plan(actor: Dict[str, Any], tenant_slug: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _require_platform(actor)
    slug = str(tenant_slug or "").strip().lower()
    if not slug:
        raise ValueError("cliente invalido")
    with _LOCK:
        state = _load()
        plan_key = str(payload.get("plan") or "").strip().lower()
        if plan_key and not _plan_by_key(state, plan_key):
            raise ValueError("plano nao encontrado")
        cfg = dict(state["tenants"].get(slug) or {})
        before = dict(cfg)
        cfg["plan"] = plan_key or None
        for k in ("license_limit", "user_limit", "tolerance_pct", "tolerance_days"):
            if k in payload:
                cfg[k] = _int_or_none(payload.get(k))
        for k in ("renewal", "note"):
            if k in payload:
                cfg[k] = str(payload.get(k) or "").strip()[:120]
        cfg = {k: v for k, v in cfg.items() if v not in (None, "")}
        if cfg:
            state["tenants"][slug] = cfg
        else:
            state["tenants"].pop(slug, None)
        _save(state)
    _audit(actor, "licensing.tenant_plan", slug, {"before": before, "after": cfg})
    return tenant_summary(slug)


def _sem_nota(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sem_nota(v) for k, v in obj.items() if k != "note"}
    return obj


def _audit(actor: Dict[str, Any], action: str, resource_id: str, detail: Dict[str, Any]) -> None:
    try:
        from app.services.auth_store import _audit as _auth_audit, _conn as _auth_conn

        with _auth_conn() as c:
            _auth_audit(
                c,
                action=action,
                # Evento de plataforma (tenant NULL): aparece so na auditoria do
                # Dono. Com o tenant do ator, um admin comum da Easy leria notas
                # e precos de todos os clientes pelo /api/auth/audit.
                tenant_id=None,
                user_id=int(actor["id"]),
                resource_type="licensing",
                resource_id=str(resource_id),
                detail_json=json.dumps(_sem_nota(detail), ensure_ascii=False, default=str)[:4000],
            )
    except Exception:  # auditoria nao pode derrubar a gravacao
        import logging

        logging.getLogger("cam-snapshot").exception("falha ao auditar %s", action)
