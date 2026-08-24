from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from palworld_admin.web import STATIC_DIR, _json_error, _read_json
from palworld_discord_bot.config import ConfigError, _load_yaml_mapping
from palworld_discord_bot.detect import list_palserver_candidates
from palworld_discord_bot.setup import apply_setup_from_mapping, retarget_palserver


def _current_working_directory(config_path: Path) -> str | None:
    if not config_path.is_file():
        return None
    try:
        raw = _load_yaml_mapping(config_path)
        servers = raw.get("servers") or []
        if not servers or not isinstance(servers[0], dict):
            return None
        process = servers[0].get("process") or {}
        value = str(process.get("working_directory") or "").strip()
        return value or None
    except Exception:
        return None


def create_setup_app(
    root: Path,
    config_path: Path,
    state: dict,
    *,
    mode: str = "setup",
) -> web.Application:
    app = web.Application()
    app["setup_root"] = root
    app["setup_config_path"] = config_path
    app["setup_state"] = state
    app["setup_mode"] = mode if mode in {"setup", "choose"} else "setup"

    async def handle_setup(_request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "setup.html")

    async def handle_css(_request: web.Request) -> web.Response:
        return web.Response(
            body=(STATIC_DIR / "app.css").read_bytes(),
            content_type="text/css",
            charset="utf-8",
        )

    async def handle_favicon(_request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "favicon.svg")

    async def handle_detect(_request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        candidates = await loop.run_in_executor(None, list_palserver_candidates)
        return web.json_response(
            {
                "ok": True,
                "mode": app["setup_mode"],
                "current": _current_working_directory(config_path),
                "must_choose": len(candidates) > 1,
                "palservers": [item["path"] for item in candidates],
                "candidates": candidates,
            }
        )

    async def handle_save(request: web.Request) -> web.Response:
        body: dict[str, Any] = await _read_json(request)
        try:
            if request.app["setup_mode"] == "choose":
                note = retarget_palserver(
                    request.app["setup_config_path"],
                    Path(str(body.get("palserver") or "").strip()),
                )
            else:
                note = apply_setup_from_mapping(
                    request.app["setup_root"],
                    request.app["setup_config_path"],
                    body,
                )
        except (ConfigError, ValueError) as exc:
            return _json_error(str(exc), 400)
        request.app["setup_state"]["code"] = 0
        request.app["setup_state"]["note"] = note
        return web.json_response({"ok": True, "message": note})

    app.router.add_get("/", handle_setup)
    app.router.add_get("/setup.html", handle_setup)
    app.router.add_get("/app.css", handle_css)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/favicon.svg", handle_favicon)
    app.router.add_get("/api/setup/detect", handle_detect)
    app.router.add_post("/api/setup", handle_save)
    return app
