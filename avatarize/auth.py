"""Login OAuth no servidor MCP oficial do HeyGen.

O app nunca vê sua senha: o login acontece no site do HeyGen, no seu navegador.
O HeyGen devolve um código para http://localhost:<porta>/callback, que o SDK troca
por um token (com PKCE e verificação de `state`). O token fica criptografado em
%LOCALAPPDATA%\\Avatarize\\session.bin.
"""
from __future__ import annotations

import asyncio
import html
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

from . import config
from .secure_store import SecureFile

StatusFn = Callable[[str], None]

LOGIN_TIMEOUT_S = 300


class NotConnectedError(RuntimeError):
    pass


def _session() -> SecureFile:
    return SecureFile(config.data_dir() / "session.bin")


def is_connected() -> bool:
    return bool(_session().load().get("tokens"))


def logout() -> None:
    _session().delete()


class SessionStorage(TokenStorage):
    """Onde o SDK MCP guarda token e registro do cliente OAuth."""

    def __init__(self) -> None:
        self._file = _session()

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._file.load().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._file.set("tokens", tokens.model_dump(mode="json"))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._file.load().get("client_info")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._file.set("client_info", client_info.model_dump(mode="json"))


_PAGE_HEAD = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Avatarize</title></head>"
    "<body style='font-family:Segoe UI,sans-serif;text-align:center;margin-top:90px;"
    "background:#0d0f12;color:#e8eaed'>"
)


class LoopbackReceiver:
    """Servidor HTTP de uso único em 127.0.0.1 que recebe o retorno do login."""

    def __init__(self) -> None:
        self.params: dict[str, str] = {}
        self._done = threading.Event()
        self._server: HTTPServer | None = None

    def start(self) -> None:
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:
                url = urlparse(self.path)
                if url.path != "/callback" or receiver._done.is_set():
                    self.send_response(404)
                    self.end_headers()
                    return
                params = {k: v[0] for k, v in parse_qs(url.query).items() if v}
                if params.get("code"):
                    msg = ("<h2 style='color:#3ecf8e'>HeyGen conectado</h2>"
                           "<p>Pode fechar esta aba e voltar ao app.</p>")
                else:
                    reason = params.get("error_description") or params.get("error") or "nenhum código recebido"
                    msg = f"<h2 style='color:#ff6b6b'>Login não concluído</h2><p>{html.escape(reason)}</p>"
                body = (_PAGE_HEAD + msg + "</body></html>").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                receiver.params = params
                receiver._done.set()

        try:
            self._server = HTTPServer(("127.0.0.1", config.CALLBACK_PORT), Handler)
        except OSError as e:
            raise RuntimeError(
                f"A porta {config.CALLBACK_PORT} está ocupada (outro login aberto?). Feche-o e tente de novo."
            ) from e
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def wait(self, timeout: float = LOGIN_TIMEOUT_S) -> dict[str, str]:
        try:
            if not self._done.wait(timeout):
                raise RuntimeError("Tempo esgotado esperando o login no navegador.")
            return self.params
        finally:
            self.close()

    def cancel(self) -> None:
        if not self._done.is_set():
            self.params = {"error": "cancelado"}
            self._done.set()

    def close(self) -> None:
        server, self._server = self._server, None
        if server:
            server.shutdown()
            server.server_close()


_active: LoopbackReceiver | None = None


def cancel_login() -> None:
    """Desiste do login em andamento (a pessoa fechou a aba ou clicou em Cancelar)."""
    if _active is not None:
        _active.cancel()


def build_auth(on_status: StatusFn | None, *, interactive: bool) -> tuple[OAuthClientProvider, LoopbackReceiver]:
    """Provider OAuth do SDK MCP. Com interactive=False nunca abre o navegador."""
    say = on_status or (lambda _m: None)
    receiver = LoopbackReceiver()

    async def redirect_handler(auth_url: str) -> None:
        global _active
        if not interactive:
            raise NotConnectedError("Sessão expirada. Clique em 'Conectar HeyGen' para entrar de novo.")
        say("Abrindo o navegador para login no HeyGen...")
        receiver.start()
        _active = receiver
        if not webbrowser.open(auth_url):
            say(f"Abra este link no navegador para entrar: {auth_url}")

    async def callback_handler() -> AuthorizationCodeResult:
        say("Aguardando autorização no navegador...")
        params = await asyncio.to_thread(receiver.wait)
        if not params.get("code"):
            reason = params.get("error_description") or params.get("error") or "cancelado"
            raise RuntimeError(f"Login não concluído: {reason}")
        say("Autorizado. Conectando...")
        return AuthorizationCodeResult(code=params["code"], state=params.get("state"), iss=params.get("iss"))

    metadata = OAuthClientMetadata(
        client_name=config.APP_NAME,
        redirect_uris=[config.REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )
    provider = OAuthClientProvider(
        server_url=config.SERVER_URL,
        client_metadata=metadata,
        storage=SessionStorage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    return provider, receiver
