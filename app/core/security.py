from __future__ import annotations

import ipaddress
import logging
import time
from typing import Any, Dict, Iterable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core import permissions
from app.services import historico_service
from app.core.settings import AppSettings, get_settings
from app.core.tenant_context import (
    reset_current_tenant_slug,
    reset_current_user,
    set_current_tenant_slug,
    set_current_user,
)
from app.services.auth_store import get_user_by_token

AUTH_COOKIE_NAME = "sightops_session"

logger = logging.getLogger("cam-snapshot")

ROLE_RANK = {
    "viewer": 10,
    "operator": 20,
    "admin": 30,
    "owner": 40,
}


def _ip_valido(valor: Any) -> str:
    texto = str(valor or "").strip()
    try:
        ipaddress.ip_address(texto)
    except ValueError:
        return ""
    return texto


def _proxy_confiavel(par: str) -> bool:
    """Quem entrega a requisicao e proxy nosso? Rede interna (nginx/cloudflared
    no Docker) ou TRUSTED_PROXIES. A lista sozinha nao basta: o padrao do compose
    e 127.0.0.1 e o nginx chega por IP do Docker."""
    if not _ip_valido(par):
        return False
    ip = ipaddress.ip_address(par)
    if ip.is_private or ip.is_loopback:
        return True
    lista = str(get_settings().trusted_proxies or "").replace(",", " ").split()
    return par in lista


def ip_do_cliente(request: Any) -> str:
    """IP de quem chamou, para limite de tentativas.

    Nunca o primeiro valor de X-Forwarded-For: quem chama escreve o que quiser
    ali, e cada valor novo zerava o limite. CF-Connecting-IP o Cloudflare
    sobrescreve; X-Real-IP o nginx sobrescreve com quem conectou nele. Os dois
    so valem vindos de proxy nosso; sem isso, vale quem conectou."""
    par = str(getattr(getattr(request, "client", None), "host", "") or "")
    if _proxy_confiavel(par):
        for cabecalho in ("cf-connecting-ip", "x-real-ip"):
            ip = _ip_valido(request.headers.get(cabecalho))
            if ip:
                return ip
    return par or "desconhecido"


class ApiAuthMiddleware(BaseHTTPMiddleware):
    _WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

    def __init__(self, app, settings: AppSettings) -> None:
        super().__init__(app)
        self.settings = settings
        self._public_paths = {
            "/api/auth/status",
            "/api/auth/login",
            "/api/auth/bootstrap-admin",
            # auth_request do video: confere sessao OU bilhete curto dentro da
            # propria rota (app instalado nao tem cookie). Ver video_ticket.
            "/api/auth/video-ok",
            "/api/system/health/live",
            "/api/system/health/ready",
            "/api/windows/agent/report",
        }
        self._query_token_paths = (
            "/api/connectors/",
            "/api/inventory/export",
            "/api/inventory/report",
            "/api/dvr/report",
            "/api/nvr/report",
            "/api/kmz/",
            "/api/playback/files/",
        )
        self._role_rules = [
            (("GET",), "/api/auth/users", "admin"),
            (("GET",), "/api/mapa/resolver-link", "viewer"),
            (("GET",), "/api/auth/audit", "admin"),
            (("GET",), "/api/auth/tenants", "admin"),
            (("POST",), "/api/auth/users", "admin"),
            (("DELETE",), "/api/auth/users", "admin"),
            (("POST",), "/api/auth/tenants", "admin"),
            (("POST",), "/api/auth/tenants/", "admin"),
            (("PUT",), "/api/auth/tenants/", "admin"),
            (("POST",), "/api/auth/act-as", "admin"),
            # Administrador autoriza, com a senha dele, UMA exclusao pedida por
            # um operador (o handler confere usuario, senha e papel).
            (("POST",), "/api/auth/autorizar-exclusao", "operator"),
            # Historico de acoes do cliente: so administrador.
            (("GET",), "/api/auth/historico", "admin"),
            # Licencas: o handler ainda exige is_platform_admin; o perfil aqui so
            # tira a rota do 403 padrao de escrita.
            (("GET",), "/api/auth/licensing", "admin"),
            (("PUT",), "/api/auth/licensing/", "admin"),
            (("GET",), "/api/auth/my-plan", "admin"),
            # Perfis de acesso do cliente (fase 3). Modo/sombra: o handler exige
            # is_platform_admin.
            (("GET", "PUT", "DELETE"), "/api/auth/access-profiles", "admin"),
            (("PUT",), "/api/auth/users/", "admin"),
            (("GET", "PUT"), "/api/auth/permissions/", "admin"),
            (("POST",), "/api/system/product", "admin"),
            (("POST",), "/api/db/init", "admin"),
            (("POST",), "/api/db/migrate", "admin"),
            (("POST",), "/api/db/storage/migrate", "admin"),
            (("POST",), "/api/db/sites", "admin"),
            (("POST",), "/api/db/assign-site", "admin"),
            (("POST",), "/api/settings/imgbb", "admin"),
            (("POST",), "/api/settings/imgbb/test", "admin"),
            (("POST",), "/api/scripts/", "admin"),
            (("POST",), "/api/backup/import", "admin"),
            (("POST",), "/api/inventory/report/settings", "admin"),
            (("POST",), "/api/inventory/report/logo", "admin"),
            (("POST",), "/api/dvr/report/settings", "admin"),
            (("POST",), "/api/dvr/report/logo", "admin"),
            (("POST",), "/api/nvr/report/settings", "admin"),
            (("POST",), "/api/nvr/report/logo", "admin"),
            (("POST",), "/api/inventory/import", "operator"),
            (("POST",), "/api/inventory/clear", "operator"),
            (("POST",), "/api/inventory/imgbb/upload", "operator"),
            (("POST",), "/api/kmz/", "operator"),
            (("POST",), "/api/scan", "operator"),
            (("POST",), "/api/inventory/delete", "operator"),
            (("POST",), "/api/rescan-single-ip", "operator"),
            (("POST",), "/api/olt/", "operator"),
            (("GET",), "/api/olt/", "viewer"),
            (("GET",), "/api/tr069/config", "admin"),
            (("POST",), "/api/tr069/config", "admin"),
            (("POST",), "/api/tr069/", "operator"),
            (("GET",), "/api/tr069/", "viewer"),
            (("POST",), "/api/switch/", "operator"),
            # Instalador e script do agente levam a chave do cliente: so quem
            # instala (operador), nao o perfil so-leitura.
            (("GET",), "/api/windows/agent-", "operator"),
            (("POST",), "/api/windows/", "operator"),
            (("GET",), "/api/connectors", "operator"),
            (("POST",), "/api/connectors", "operator"),
            (("PUT",), "/api/connectors", "operator"),
            (("DELETE",), "/api/connectors", "operator"),
            (("GET", "POST"), "/api/deployments", "operator"),
            (("POST",), "/api/tools/scan-ip", "operator"),
            (("POST",), "/api/discovery/run", "operator"),
            (("POST",), "/api/portscan/apply", "operator"),
            (("POST",), "/api/cameras/save", "operator"),
            (("POST",), "/api/cameras/ocorrencia", "operator"),
            (("POST",), "/api/cameras/ping_many", "operator"),
            (("POST",), "/api/snapshot/save", "operator"),
            (("POST",), "/api/cameras/ptz_move", "operator"),
            (("POST",), "/api/cameras/reboot", "operator"),
            (("POST",), "/api/cameras/rename", "operator"),
            # Proxy web do equipamento: GET na camera/gravador tambem reinicia,
            # abre porta e troca config (CGI por GET). Operador em QUALQUER
            # metodo, antes da regra geral de /api/maintenance/.
            (("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"), "/api/maintenance/web/", "operator"),
            # O proxy web repassa o metodo do dispositivo (PUT/PATCH/DELETE
            # inclusive), nao so POST -- com o default virando NEGAR, cobrir
            # so POST quebraria o acesso web a camera/gravador.
            (("POST", "PUT", "PATCH", "DELETE"), "/api/maintenance/", "operator"),
            (("POST",), "/api/dvr/", "operator"),
            # Trocar IP/porta e reiniciar gravador: a mudanca sem volta pelo
            # SightOps (ver recorder_rede.py). Antes da regra geral de /api/nvr/.
            (("POST",), "/api/nvr/driver/rede/aplicar", "admin"),
            (("POST",), "/api/nvr/driver/reiniciar", "admin"),
            (("POST",), "/api/nvr/", "operator"),
            (("POST",), "/api/ia/", "operator"),
            (("POST", "DELETE"), "/api/alert/members", "operator"),
            (("POST",), "/api/alert/incidents", "operator"),
            # Passos do atendimento por site: regra da central, nao do plantao.
            (("PUT",), "/api/alert/protocols", "admin"),
            # Controle de Rotas: cadastro da frota. DELETE sobe para admin
            # sozinho (permissions.e_exclusao).
            (("POST", "DELETE"), "/api/rotas/", "operator"),
            # Maquete 3D: enviar planta e salvar o que foi montado. DELETE sobe
            # para admin sozinho (permissions.e_exclusao).
            # Gerar o PDF so le o projeto (POST porque leva as imagens da tela).
            (("POST",), "/api/maquete/pdf/", "viewer"),
            (("POST", "PUT", "DELETE"), "/api/maquete/", "operator"),
            # Alerta Termico: incluir camera, ajustar a regra, dar Ciente ou
            # Falso alarme. Remover camera (DELETE) sobe para admin sozinho
            # (permissions.e_exclusao).
            # Celular registrar para receber alerta nao altera nada do cliente.
            (("POST",), "/api/termico/aparelhos", "viewer"),
            (("POST", "PUT", "DELETE"), "/api/termico/", "operator"),
            # Automacoes acionam sirene, refletor e speed no cliente: so admin.
            (("POST", "PUT", "DELETE"), "/api/automacoes", "admin"),
            # Ponto de venda: caixa, token do coletor e reprocessar o dia
            # mexem na configuracao do cliente -- so administrador.
            (("POST",), "/api/pdv/caixas", "admin"),
            # Excluir caixa apaga tambem as vendas recebidas dele: so admin
            # (e a regra central de exclusao pede a senha do administrador).
            (("DELETE",), "/api/pdv/caixas/", "admin"),
            # Medir o relogio so LE a hora do gravador e guarda a diferenca.
            (("POST",), "/api/pdv/relogio/", "operator"),
            # Switch Provedores: cadastrar/testar operador; DELETE vira admin
            # pela regra central de exclusao. (POST cai em /api/switch/ abaixo.)
            (("DELETE",), "/api/switch/provedores/", "operator"),

            # --- Fase 1 da correcao de autorizacao (2026-09-20) ---------------
            # Estas rotas de ESCRITA caiam no default "basta estar logado", que
            # dava a um viewer poder de abrir porta, cadastrar pessoa com
            # acesso, extrair gravacao e trocar o destino dos alertas.
            # A ORDEM IMPORTA: _match_role_rule devolve a PRIMEIRA regra que
            # casa, entao o que exige admin vem antes do prefixo generico.

            # -- consequencia alta: exige admin --
            (("DELETE",), "/api/access-control/devices", "admin"),
            # Reiniciar controladora deixa a porta sem leitor por ~1 minuto.
            (("POST",), "/api/access-control/painel/reiniciar-controladora", "admin"),
            # Backup leva CPF e foto de todo mundo; excluir local apaga o local inteiro.
            (("GET", "POST"), "/api/access-control/painel/dados", "admin"),
            (("POST", "PUT", "DELETE"), "/api/access-control/whatsapp", "admin"),
            # Canal de e-mail (senha do SMTP) e teste de envio: so administrador.
            (("POST", "PUT", "DELETE"), "/api/access-control/email", "admin"),
            # Foto da gravacao (camera da porta): imagem e privacidade, como /api/playback/.
            (("GET",), "/api/access-control/painel/cameras/", "operator"),
            (("POST",), "/api/system/bootstrap", "admin"),
            (("DELETE", "PATCH"), "/api/auth/tenants/", "admin"),
            (("POST",), "/api/auth/storage/migrate", "admin"),
            # Notificacoes por site (grupos do Telegram): so administrador.
            (("GET", "POST", "PUT", "DELETE"), "/api/monitoring/notificacoes", "admin"),
            (("PUT",), "/api/monitoring/telegram", "admin"),
            (("PUT",), "/api/monitoring/profiles/", "admin"),
            (("POST",), "/api/monitoring/telegram/test", "admin"),

            # -- operacao do dia a dia: exige operator --
            # Controle de acesso: abrir porta, pessoas, grupos, regras, sync.
            (("POST", "PUT", "PATCH", "DELETE"), "/api/access-control/", "operator"),
            # Extrair gravacao e imagem e questao de privacidade.
            (("POST",), "/api/playback/", "operator"),
            (("POST", "PUT", "PATCH", "DELETE"), "/api/planning/", "operator"),
            (("POST",), "/api/monitoring/", "operator"),
            (("POST",), "/api/network/tools/", "operator"),
            (("POST",), "/api/telegram/", "operator"),
            (("POST",), "/api/cameras/", "operator"),
            (("POST",), "/api/inventory/report/job", "operator"),
            (("PATCH", "DELETE"), "/api/kmz/", "operator"),
            (("PATCH",), "/api/windows/", "operator"),
            (("DELETE",), "/api/olt/", "operator"),

            # Sair e a unica escrita que qualquer logado faz. Declarada aqui
            # de proposito: com o default virando NEGAR (Fase 2), rota sem
            # regra passa a ser recusada, entao esta precisa existir.
            (("POST",), "/api/auth/logout", "viewer"),
        ]
        # Rotas que alcancam TODOS os clientes de uma vez (backup leva o data/
        # inteiro, chaves WireGuard inclusive): so o admin da plataforma. Admin
        # e owner de cliente tomam 403. Conferido no dispatch, por cima do
        # perfil e nos dois modos de permissao.
        self._platform_admin_rules = [
            (("GET", "HEAD"), "/api/backup/export"),
            (("POST",), "/api/backup/import"),
            # Init/migracao do banco e do armazenamento (com force, apaga o de
            # todos os clientes).
            (("POST",), "/api/db/init"),
            (("POST",), "/api/db/migrate"),
            (("POST",), "/api/db/storage/migrate"),
            (("POST",), "/api/auth/storage/migrate"),
            (("POST",), "/api/system/bootstrap"),
        ]

    def _is_public_path(self, path: str) -> bool:
        if path in self._public_paths:
            return True
        if path.startswith("/api/connectors/agent/"):
            return True
        # App do botao de panico: autentica pelo token do aparelho dentro do
        # proprio endpoint (app/api/endpoints/alert.py), nao por usuario.
        if path.startswith("/api/alert/app/"):
            return True
        if path.startswith("/api/access-control/whatsapp/inbound/") and path != "/api/access-control/whatsapp/inbound/simulate":
            return True
        # Coletor do caixa (PDV): autentica pelo token do caixa dentro do
        # proprio endpoint (app/api/endpoints/pdv.py), nao por usuario.
        if path.startswith("/api/pdv/coletor/"):
            return True
        # Webhook da Cloud API: a Meta chama sem credencial nossa. A protecao e o
        # token de verificacao conferido dentro do proprio endpoint.
        if path.startswith("/api/access-control/whatsapp/meta/"):
            return True
        # Foto do aviso por e-mail: o responsavel abre do e-mail, sem login. A
        # protecao e o token aleatorio que vence em 24 h (access_control_email).
        if path.startswith("/api/access-control/foto/"):
            return True
        return False

    def _regra_declarada(self, path: str, method: str) -> str:
        """A regra da lista, sem a trava de exclusao por cima."""
        for methods, prefix, min_role in self._role_rules:
            if method in methods and (path == prefix or path.startswith(prefix)):
                return min_role
        return ""

    def autorizavel(self, path: str, method: str) -> bool:
        """A senha do administrador so tira a trava de EXCLUSAO de rota que o
        operador ja usa: rota que ja era de administrador (excluir
        controladora, WhatsApp, usuarios...) continua so de administrador."""
        return ROLE_RANK.get(self._regra_declarada(path, method), 0) < ROLE_RANK["admin"] and not path.startswith("/api/auth/")

    def _match_role_rule(self, path: str, method: str) -> str:
        for methods, prefix, min_role in self._role_rules:
            if method not in methods:
                continue
            if path == prefix or path.startswith(prefix):
                # Excluir/limpar/remover: so administrador e dono, nos dois
                # modos de permissao (permissions.e_exclusao). Rota sem regra
                # continua negada por padrao.
                if permissions.e_exclusao(path, method) and ROLE_RANK.get(min_role, 0) < ROLE_RANK["admin"]:
                    return "admin"
                return min_role
        return ""

    def _so_plataforma(self, path: str, method: str) -> bool:
        return any(method in methods and (path == prefix or path.startswith(prefix))
                   for methods, prefix in self._platform_admin_rules)

    def _query_token_allowed(self, path: str, method: str) -> bool:
        if method.upper() not in ("GET", "HEAD"):
            return False
        return any(path == prefix or path.startswith(prefix) for prefix in self._query_token_paths)

    def _require_auth(self, path: str, method: str) -> bool:
        if not self.settings.auth_enabled:
            return False
        if not path.startswith("/api/"):
            return False
        if self._is_public_path(path):
            return False
        if method.upper() == "OPTIONS" and not path.startswith("/api/maintenance/web/"):
            return False
        if self._match_role_rule(path, method) or self._so_plataforma(path, method.upper()):
            return True
        if self.settings.auth_required:
            return True
        if not self.settings.auth_legacy_open and method.upper() not in ("GET", "HEAD"):
            return True
        return False

    @staticmethod
    def _modelo_da_rota(request: Request, path: str) -> str:
        """Caminho com {parametros} (o que da nome a acao no historico)."""
        rota = request.scope.get("route")
        if getattr(rota, "path", None):
            return str(rota.path)
        try:
            from starlette.routing import Match

            for r in request.scope["app"].router.routes:
                if r.matches(request.scope)[0] == Match.FULL:
                    return str(getattr(r, "path", "") or path)
        except Exception:
            pass
        return path

    def _historico(self, request: Request, user: Dict[str, Any], method: str, path: str, status: int,
                   corpo: Any, duracao_ms: int, autorizado_por: str = "") -> None:
        if not historico_service.registravel(method, path):
            return
        ip = (request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip")
              or (request.client.host if request.client else "") or "")
        historico_service.registrar(
            user, method, path, self._modelo_da_rota(request, path), status,
            path_params=dict(request.scope.get("path_params") or {}), corpo=corpo or b"", ip=ip,
            autorizado_por=autorizado_por, duracao_ms=duracao_ms)

    def _operaria(self, user: Dict[str, Any], path: str, method: str) -> bool:
        """A autorizacao do administrador so tira a trava de EXCLUSAO: quem a
        recebe precisa operar este modulo (viewer, ou modulo restrito no
        perfil com a regra valendo, continua barrado)."""
        if not self._role_allows(str(user.get("role") or ""), "operator"):
            return False
        try:
            if permissions.modo() == "valer":
                return permissions.decidir(user, path, method, "operator")[0]
        except Exception:
            return False
        return True

    @staticmethod
    def _role_allows(user_role: str, required_role: str) -> bool:
        have = ROLE_RANK.get(str(user_role or "").strip().lower(), 0)
        need = ROLE_RANK.get(str(required_role or "").strip().lower(), 10**9)
        return have >= need

    def _extract_bearer_token(self, headers: Iterable[tuple[str, str]] | dict | Request) -> str:
        if isinstance(headers, Request):
            raw = str(headers.headers.get("authorization") or "").strip()
            if not raw:
                cookie_token = str(headers.cookies.get(AUTH_COOKIE_NAME) or "").strip()
                if cookie_token:
                    return cookie_token
            if not raw and self._query_token_allowed(headers.url.path, headers.method):
                query_token = str(
                    headers.query_params.get("auth_token")
                    or headers.query_params.get("access_token")
                    or headers.query_params.get("token")
                    or ""
                ).strip()
                if query_token:
                    return query_token
        elif isinstance(headers, dict):
            raw = str(headers.get("authorization") or "").strip()
        else:
            raw = ""
            for key, value in headers:
                if str(key).lower() == "authorization":
                    raw = str(value or "").strip()
                    break
        scheme, _, token = raw.partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return token.strip()

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method.upper()
        ctx_token = set_current_tenant_slug("")
        if not self._require_auth(path, method):
            try:
                return await call_next(request)
            finally:
                reset_current_tenant_slug(ctx_token)

        token = self._extract_bearer_token(request)
        if not token:
            try:
                return JSONResponse(status_code=401, content={"detail": "autenticacao obrigatoria"})
            finally:
                reset_current_tenant_slug(ctx_token)

        user = get_user_by_token(token)
        if not user:
            try:
                return JSONResponse(status_code=401, content={"detail": "token invalido ou expirado"})
            finally:
                reset_current_tenant_slug(ctx_token)

        if self._so_plataforma(path, method) and not bool(user.get("is_platform_admin")):
            logger.warning("rota so da plataforma negada: %s %s por %s (tenant %s)",
                           method, path, user.get("username"), user.get("tenant_slug"))
            self._historico(request, user, method, path, 403, None, 0)
            try:
                return JSONResponse(status_code=403, content={"detail": "somente admin da plataforma"})
            finally:
                reset_current_tenant_slug(ctx_token)

        required_role = self._match_role_rule(path, method)
        # FASE 2 -- default DENY para escrita. Antes, rota de escrita fora da
        # lista de prefixos caia em "basta estar logado": nascia no nivel mais
        # permissivo e ninguem percebia (eram 62 assim em 20/09/2026, entre
        # elas abrir porta). Agora o silencio custa 403, nao acesso.
        # Leitura segue no comportamento antigo de proposito: negar GET nao
        # declarado quebraria tela sem ganho de seguranca equivalente.
        if not required_role and method in self._WRITE_METHODS:
            antiga_ok, antiga_msg = False, "rota sem perfil declarado: acesso negado por padrao"
        elif required_role and not self._role_allows(str(user.get("role") or ""), required_role):
            antiga_ok, antiga_msg = False, f"permissao insuficiente: requer perfil {required_role}"
        else:
            antiga_ok, antiga_msg = True, ""

        # FASE 3 -- modulo x nivel (app/core/permissions.py). Em "sombra" vale a
        # regra antiga e a nova so e registrada quando diverge; em "valer" vale a
        # nova. Erro na regra nova nunca derruba a requisicao: cai na antiga.
        permitido, motivo = antiga_ok, antiga_msg
        try:
            nova_ok, nova_msg = permissions.decidir(user, path, method, required_role)
            if nova_ok != antiga_ok:
                permissions.registrar_divergencia(user, path, method, antiga_ok, nova_ok, nova_msg)
            if permissions.modo() == "valer":
                permitido, motivo = nova_ok, (f"permissao insuficiente: {nova_msg}" if not nova_ok else "")
        except permissions.PerfisIndisponiveis:
            if permissions.modo() == "valer":
                # Sem os perfis do cliente nao da para saber o que ele restringiu:
                # negar e mais seguro que liberar pelo perfil fixo.
                logger.exception("permissoes: perfis indisponiveis em %s %s; requisicao negada", method, path)
                try:
                    return JSONResponse(status_code=503, content={"detail": "permissoes temporariamente indisponiveis, tente de novo"})
                finally:
                    reset_current_tenant_slug(ctx_token)
            logger.exception("permissoes(sombra): perfis indisponiveis em %s %s", method, path)
        except Exception:
            logger.exception("permissoes: regra nova falhou em %s %s; valeu a antiga", method, path)

        # Exclusao autorizada por um administrador (senha digitada na hora):
        # o codigo vale uma vez, para este operador e esta acao exata.
        autorizacao = None
        codigo = str(request.headers.get(permissions.CABECALHO_AUTORIZACAO) or "").strip()
        if codigo and method in self._WRITE_METHODS and self.autorizavel(path, method):
            corpo = await request.body()
            autorizacao = permissions.consumir_autorizacao(codigo, user, method, path, corpo)
            if autorizacao:
                logger.warning("exclusao autorizada: %s %s por %s (operador %s), autorizada por %s",
                               method, path, user.get("username"), user.get("id"), autorizacao.get("admin"))
        exclusao_barrada = (required_role == "admin" and permissions.e_exclusao(path, method)
                            and not self._role_allows(str(user.get("role") or ""), "admin"))
        if not permitido and exclusao_barrada and autorizacao and self._operaria(user, path, method):
            permitido, motivo = True, ""

        if not permitido:
            headers = {}
            if exclusao_barrada:
                motivo = permissions.MSG_EXCLUIR
                # So oferece a senha do administrador a quem ela adiantaria.
                if self.autorizavel(path, method) and self._operaria(user, path, method):
                    headers[permissions.CABECALHO_EXIGE_ADMIN] = "1"
            self._historico(request, user, method, path, 403, None, 0)
            try:
                return JSONResponse(status_code=403, content={"detail": motivo}, headers=headers)
            finally:
                reset_current_tenant_slug(ctx_token)

        request.state.current_user = user
        # Usa o tenant EFETIVO (considera "operar como" outro cliente via
        # act-as), nao o tenant_slug fixo do usuario -- ver get_user_by_token
        # em app/services/auth_store.py.
        request.state.current_tenant_slug = str(user.get("effective_tenant_slug") or user.get("tenant_slug") or "").strip().lower()
        reset_current_tenant_slug(ctx_token)
        ctx_token = set_current_tenant_slug(request.state.current_tenant_slug)
        user_token = set_current_user(user)
        aut_token = permissions.definir_autorizacao_da_requisicao(autorizacao)
        # Historico: le o corpo JSON ANTES (o handler o consome depois; o
        # Starlette guarda a copia) para tirar o alvo da acao (IP, canal...).
        corpo = b""
        if historico_service.registravel(method, path) and "json" in str(request.headers.get("content-type") or ""):
            try:
                corpo = await request.body()
            except Exception:
                corpo = b""
        inicio = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            self._historico(request, user, method, path, status, corpo, int((time.monotonic() - inicio) * 1000),
                            (autorizacao or {}).get("admin", ""))
            permissions.limpar_autorizacao_da_requisicao(aut_token)
            reset_current_user(user_token)
            reset_current_tenant_slug(ctx_token)
