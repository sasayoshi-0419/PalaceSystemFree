from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory that holds config.yaml / .env (next to the EXE when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def resolve_user_path(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return app_root() / candidate


def prepare_frozen_cwd() -> None:
    if is_frozen():
        os.chdir(app_root())


def _is_windows() -> bool:
    return os.name == "nt"


def webview_storage_path() -> Path:
    """WebView2 user data folder. On Windows, lives outside dist (LocalAppData)."""
    if _is_windows():
        local = os.environ.get("LOCALAPPDATA")
        if local:
            base = Path(local)
        else:
            base = Path.home() / "AppData" / "Local"
        path = base / "HomeServerAdmin" / "WebView2"
    else:
        path = app_root() / ".data" / "webview"
    path.mkdir(parents=True, exist_ok=True)
    return path
