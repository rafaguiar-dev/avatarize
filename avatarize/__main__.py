"""Uso: python -m avatarize            (abre o app)
       python -m avatarize --list-tools (lista as tools do MCP do HeyGen)"""
from __future__ import annotations

import sys


def main() -> None:
    if "--list-tools" in sys.argv[1:]:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        from avatarize.service import dump_tools

        dump_tools()
        return
    from avatarize.ui import run

    run()


if __name__ == "__main__":
    main()
