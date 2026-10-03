"""Sessão MCP com o HeyGen e leitura das respostas das tools."""
from __future__ import annotations

import contextlib
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from mcp.client.client import Client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from . import auth, config
from .auth import NotConnectedError, StatusFn


class HeyGenError(RuntimeError):
    pass


@contextlib.asynccontextmanager
async def open_session(on_status: StatusFn | None = None, *, interactive: bool = False) -> AsyncIterator[Client]:
    """Abre uma sessão MCP autenticada. Só abre o navegador se interactive=True."""
    if not interactive and not auth.is_connected():
        raise NotConnectedError("Conecte sua conta HeyGen primeiro (botão 'Conectar HeyGen').")
    provider, receiver = auth.build_auth(on_status, interactive=interactive)
    http_client = create_mcp_http_client(auth=provider)
    try:
        async with Client(streamable_http_client(config.SERVER_URL, http_client=http_client)) as client:
            yield client
    finally:
        receiver.close()
        with contextlib.suppress(Exception):
            await http_client.aclose()


async def call(client: Client, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return payload(await client.call_tool(tool, arguments))


def _first_text(result: Any) -> str | None:
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    return None


def payload(result: Any) -> dict[str, Any]:
    """CallToolResult -> dict. Levanta HeyGenError se o servidor indicar erro."""
    if getattr(result, "isError", False):
        raise HeyGenError(_first_text(result) or "erro desconhecido do HeyGen")
    data: Any = getattr(result, "structuredContent", None)
    if not (isinstance(data, dict) and data):
        text = _first_text(result)
        if text is None:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"_text": text}
    if isinstance(data, list):
        return {"items": data}
    if not isinstance(data, dict):
        return {}
    if data.get("error") is True or data.get("error_code"):
        raise HeyGenError(str(data.get("message") or data.get("error_code") or "erro da API HeyGen"))
    for key in ("data", "result", "response"):
        if isinstance(data.get(key), dict):
            return data[key]
    return data


def _norm(key: str) -> str:
    return key.lower().replace("_", "")


def find(obj: Any, *names: str) -> Any:
    """Primeiro valor não vazio de uma das chaves (snake/camel), buscando em largura."""
    wanted = [_norm(n) for n in names]
    queue: deque[Any] = deque([obj])
    while queue:
        cur = queue.popleft()
        if isinstance(cur, dict):
            keys = {_norm(k): v for k, v in cur.items() if isinstance(k, str)}
            for w in wanted:
                if keys.get(w) not in (None, "", [], {}):
                    return keys[w]
            queue.extend(cur.values())
        elif isinstance(cur, list):
            queue.extend(cur)
    return None
