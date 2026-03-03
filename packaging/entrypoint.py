"""Thin native entrypoint used by PyInstaller builds."""

from __future__ import annotations

import sys

from agent_dump.cli import main

if __name__ == "__main__":
    sys.exit(main())
