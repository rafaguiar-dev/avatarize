"""Constantes e caminhos do app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Avatarize"
APP_VERSION = "1.0.0"

# Único servidor com quem o app conversa (além dos links de upload/download que ele mesmo devolve).
SERVER_URL = "https://mcp.heygen.com/mcp/v1/"

# Retorno do login OAuth: servidor local de uso único, só em 127.0.0.1.
CALLBACK_PORT = 41799
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

ASSETS = Path(__file__).resolve().parent / "assets"


def data_dir() -> Path:
    """Pasta da sessão de login (separada de qualquer outro app HeyGen)."""
    override = os.environ.get("AVATARIZE_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Avatarize"
    else:
        base = Path.home() / ".avatarize"
    base.mkdir(parents=True, exist_ok=True)
    return base


def default_output_dir() -> Path:
    return Path.home() / "Videos" / "Avatarize"
