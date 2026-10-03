"""Upload/download HTTP fora do MCP (URLs assinadas que o próprio HeyGen devolve). Só HTTPS."""
from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import truststore

_ssl = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class InsecureURLError(RuntimeError):
    pass


def _require_https(url: str) -> None:
    if urlparse(url).scheme != "https":
        raise InsecureURLError(f"o servidor devolveu um link que não é HTTPS: {url[:80]}")


class _HttpsOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ssl), _HttpsOnlyRedirects())


def put_file(url: str, path: Path, headers: dict[str, str]) -> int:
    """PUT do arquivo inteiro. Devolve o status HTTP."""
    _require_https(url)
    data = path.read_bytes()
    req = urllib.request.Request(url, data=data, method="PUT")
    for key, value in headers.items():
        req.add_header(key, str(value))
    req.add_header("Content-Length", str(len(data)))
    try:
        with _opener.open(req, timeout=300) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def download(url: str, dest: Path) -> Path:
    """Baixa para dest (via .part, então nunca sobra arquivo pela metade com o nome final)."""
    _require_https(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with _opener.open(url, timeout=600) as resp, open(part, "wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
        os.replace(part, dest)
    finally:
        part.unlink(missing_ok=True)
    return dest
