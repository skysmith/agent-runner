# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path.cwd().resolve()
icon_path = root / "build" / "macos" / "Alcove.app" / "Contents" / "Resources" / "Alcove.icns"
icon = str(icon_path) if icon_path.exists() else None

a = Analysis(
    [str(root / "src" / "agent_runner" / "packaged_entry.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Alcove",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Alcove",
)

app = BUNDLE(
    coll,
    name="Alcove.app",
    icon=icon,
    bundle_identifier="local.alcove.packaged",
    version="1.0.0",
)
