# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone agent-dump CLI."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


# PyInstaller executes spec files via exec(), so __file__ is not guaranteed.
SPEC_FILE = Path(globals().get("__file__", Path.cwd() / "packaging" / "pyinstaller.spec")).resolve()
PROJECT_ROOT = SPEC_FILE.parent.parent

hiddenimports = sorted(
    {
        *collect_submodules("prompt_toolkit"),
        *collect_submodules("questionary"),
    }
)
datas = copy_metadata("prompt_toolkit") + copy_metadata("questionary")


a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="agent-dump",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
