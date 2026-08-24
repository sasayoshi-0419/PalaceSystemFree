# -*- mode: python ; coding: utf-8 -*-
"""Windows 無料版 EXE。PalServer / SteamCMD は同梱しない。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

# PyInstaller はエントリスクリプトを spec と同じフォルダ基準で探す。
# リポジトリ相対パスを書くと、そのフォルダが二重になる。
try:
    spec_dir = Path(SPECPATH).resolve()
except NameError:
    spec_dir = Path(__file__).resolve().parent
entry_script = spec_dir / "run_admin.py"

datas = collect_data_files("palworld_admin")
binaries = []
hiddenimports = [
    "palworld_admin.gui",
    "palworld_admin.desktop",
    "palworld_admin.splash",
    "palworld_admin.setup_app",
    "palworld_admin.setup_gui",
    "palworld_admin.service",
    "palworld_discord_bot.cogs.status",
    "palworld_discord_bot.steamcmd",
    "webview",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "zoneinfo",
    "tzdata",
]
for package in ("tzdata", "discord", "aiohttp", "httpx", "certifi", "webview"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(entry_script)],
    pathex=[str(spec_dir.parent)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "respx"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HomeServerAdmin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="HomeServerAdmin",
)
