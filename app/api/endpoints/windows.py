from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.services.windows_inventory_service import (
    clear_windows_inventory,
    accept_windows_agent_report,
    build_windows_agent_exe,
    build_windows_agent_script,
    load_windows_inventory,
    save_windows_inventory,
    validate_windows_agent_token,
)
from app.services.windows_pdf_report import build_windows_inventory_pdf

router = APIRouter(prefix="/api/windows", tags=["windows"])


@router.get("/inventory")
def api_windows_inventory() -> Dict[str, Any]:
    rows = load_windows_inventory()
    return {"ok": True, "count": len(rows), "inventory": rows}


def _windows_row_key(row: Dict[str, Any]) -> str:
    for key in ("ip", "hostname", "serial"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


@router.patch("/inventory/manual")
def api_windows_inventory_manual(payload: Dict[str, Any]) -> Dict[str, Any]:
    target = str(payload.get("key") or payload.get("ip") or "").strip()
    manual = payload.get("physical") if isinstance(payload.get("physical"), dict) else {}
    allowed = {
        "switch_name",
        "switch_port",
        "patch_panel",
        "patch_port",
        "outlet",
        "rack",
        "cable_id",
        "asset_tag",
        "notes",
    }
    cleaned = {k: str(manual.get(k) or "").strip() for k in allowed}
    rows = load_windows_inventory()
    updated = False
    for row in rows:
        if target and target in {_windows_row_key(row), str(row.get("ip") or "").strip(), str(row.get("hostname") or "").strip(), str(row.get("serial") or "").strip()}:
            current = row.get("physical") if isinstance(row.get("physical"), dict) else {}
            row["physical"] = {**current, **cleaned}
            updated = True
            break
    if not updated:
        raise HTTPException(status_code=404, detail="computador nao encontrado")
    save_windows_inventory(rows)
    return {"ok": True, "updated": True}


@router.post("/inventory/delete")
def api_windows_inventory_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    keys = payload.get("keys")
    if not isinstance(keys, list):
        keys = []
    targets = {str(item or "").strip() for item in keys if str(item or "").strip()}
    if not targets:
        raise HTTPException(status_code=400, detail="nenhum computador selecionado")
    rows = load_windows_inventory()
    kept = [
        row for row in rows
        if _windows_row_key(row) not in targets
        and str(row.get("ip") or "").strip() not in targets
        and str(row.get("hostname") or "").strip() not in targets
        and str(row.get("serial") or "").strip() not in targets
    ]
    removed = len(rows) - len(kept)
    save_windows_inventory(kept)
    return {"ok": True, "removed": removed, "count": len(kept)}


@router.post("/clear")
def api_windows_clear() -> Dict[str, Any]:
    return clear_windows_inventory()


@router.get("/report.pdf")
def api_windows_report_pdf(request: Request) -> Response:
    """Relatorio em texto (ReportLab), montado em memoria: nada vai para a
    pasta comum output/reports, como no gerador antigo."""
    import re

    from app.core.tenant_context import get_current_tenant_slug, tenant_report_logo_path

    usuario = getattr(request.state, "current_user", None) or {}
    cliente = str(usuario.get("effective_tenant_name") or usuario.get("tenant_name") or "").strip()
    logo = None
    if get_current_tenant_slug():
        for tipo in ("inventory", "nvr", "dvr"):
            candidato = tenant_report_logo_path(tipo)
            if candidato.exists():
                logo = candidato
                break
    conteudo = build_windows_inventory_pdf(load_windows_inventory(), company_name=cliente, logo_path=logo)
    sufixo = re.sub(r"[^A-Za-z0-9]+", "-", cliente).strip("-")[:40]
    nome = f"computadores{'-' + sufixo if sufixo else ''}.pdf"
    return Response(content=conteudo, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _base_do_agente(request: Request, base: str) -> str:
    """Endereco que o agente usa para reportar.

    `request.base_url` aqui dentro e "http://<dominio>/": a v3 e servida sob
    /v3-api/ e o nginx corta esse prefixo. O agente ia postar em
    <dominio>/api/..., que e a API de PRODUCAO v2 -- o computador nunca
    apareceria na v3. A tela manda a base que ela mesma usa (API_BASE); so
    vale se for do mesmo dominio deste pedido, para o script nao embutir
    endereco de terceiro.
    """
    from urllib.parse import urlparse

    host_pedido = (request.headers.get("host") or "").split(":")[0].lower()
    alvo = urlparse(str(base or "").strip())
    import re

    # O valor vai para dentro de uma string do PowerShell: so letras, numeros e
    # / _ . - no caminho, nada de aspas ou $.
    if alvo.scheme in ("http", "https") and alvo.hostname and alvo.hostname.lower() == host_pedido \
            and not alvo.query and not alvo.fragment and "@" not in alvo.netloc \
            and re.fullmatch(r"[A-Za-z0-9.:-]+", alvo.netloc) and re.fullmatch(r"[A-Za-z0-9/_.-]*", alvo.path):
        return f"{alvo.scheme}://{alvo.netloc}{alvo.path}".rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("/agent-script")
def api_windows_agent_script(request: Request, base: str = "") -> Response:
    base_url = _base_do_agente(request, base)
    script = build_windows_agent_script(base_url=base_url)
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sightops-agente-windows.ps1"'},
    )


@router.get("/agent-exe")
def api_windows_agent_exe(request: Request, base: str = "") -> Response:
    """Instalador com janela: pede admin sozinho, site/setor e cria a tarefa.

    Leva a chave do agente do cliente, como o /agent-script.
    """
    import re

    usuario = getattr(request.state, "current_user", None) or {}
    cliente = str(usuario.get("effective_tenant_name") or usuario.get("tenant_name") or "").strip()
    base_url = _base_do_agente(request, base)
    try:
        conteudo = build_windows_agent_exe(base_url=base_url, cliente=cliente)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="instalador base ausente no servidor")
    sufixo = re.sub(r"[^A-Za-z0-9]+", "-", cliente).strip("-")[:40]
    nome = f"SightOps-Agente{'-' + sufixo if sufixo else ''}.exe"
    return Response(
        content=conteudo,
        media_type="application/vnd.microsoft.portable-executable",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.post("/agent/report")
async def api_windows_agent_report(request: Request) -> Dict[str, Any]:
    token = str(request.headers.get("x-sightops-agent-token") or "").strip()
    tenant_slug = validate_windows_agent_token(token)
    if not tenant_slug:
        raise HTTPException(status_code=401, detail="token do agente invalido")
    try:
        payload = await request.json()
        remote_ip = request.client.host if request.client else ""
        return accept_windows_agent_report(
            payload if isinstance(payload, dict) else {}, remote_ip=remote_ip, tenant_slug=tenant_slug
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
