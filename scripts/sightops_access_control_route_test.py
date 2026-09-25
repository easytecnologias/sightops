from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.security import ApiAuthMiddleware
from app.core.settings import get_settings
from app.main import app


def test_access_control_requires_operator_role() -> None:
    """Sem regra de papel, o perfil autenticado mais baixo (viewer) podia abrir
    uma porta fisica, cadastrar/excluir pessoas e excluir dispositivos. O projeto
    ja exige 'operator' para todo endpoint de efeito fisico (reboot de camera,
    PTZ, comandos de OLT/switch/DVR/NVR) -- controle de acesso segue o mesmo."""
    middleware = ApiAuthMiddleware(app=None, settings=get_settings())
    checks = [
        ("/api/access-control/devices/abc/open-door", "POST"),
        ("/api/access-control/people", "POST"),
        ("/api/access-control/people/abc", "DELETE"),
        ("/api/access-control/people", "GET"),
        ("/api/access-control/devices/abc", "DELETE"),
        ("/api/access-control/groups", "POST"),
        ("/api/access-control/rules", "POST"),
        ("/api/access-control/events", "GET"),
        ("/api/access-control/summary", "GET"),
    ]
    for path, method in checks:
        required = middleware._match_role_rule(path, method)
        assert required == "operator", f"{method} {path} exige '{required or 'nenhum papel'}', esperado 'operator'"
    assert not middleware._role_allows("viewer", "operator")
    assert middleware._role_allows("operator", "operator")
    assert middleware._role_allows("admin", "operator")


def test_access_control_routes_are_registered() -> None:
    paths = {str(route.path) for route in app.routes if hasattr(route, "path")}
    for included in [route for route in app.routes if hasattr(route, "original_router")]:
        for route in getattr(included.original_router, "routes", []):
            if hasattr(route, "path"):
                paths.add(str(route.path))
    assert "/api/access-control/summary" in paths
    assert "/api/access-control/people" in paths
    assert "/api/access-control/people/{person_id}" in paths


if __name__ == "__main__":
    test_access_control_routes_are_registered()
    test_access_control_requires_operator_role()
    print("OK access control routes + papel minimo operator")
