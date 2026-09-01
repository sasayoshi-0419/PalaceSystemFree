from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from palworld_discord_bot.applog import recent_logs
from palworld_discord_bot.bot import application_id_from_token, bot_invite_url
from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.operations import OperationError
from palworld_discord_bot.setup import apply_discord_from_mapping, apply_server_ops_from_mapping
from palworld_discord_bot.settings_ini import COMMON_KEYS, PROTECTED_KEYS
from palworld_discord_bot.settings_catalog import merge_settings_view
from palworld_discord_bot.steamcmd import (
    SteamCmdError,
    default_install_directory,
    describe_steamcmd,
    install_steamcmd,
)
from palworld_discord_bot.updates import inspect_update
from palworld_admin.runtime import AdminRuntime
from palworld_admin.worldmap import fetch_map_data

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _schedule_payload(server) -> dict[str, Any]:
    if server.restart_schedule is not None:
        return {
            "enabled": True,
            "time": server.restart_schedule.time,
            "timezone": server.restart_schedule.timezone,
            "warn_seconds": server.restart_schedule.warn_seconds,
        }
    return {
        "enabled": False,
        "time": "05:00",
        "timezone": "Asia/Tokyo",
        "warn_seconds": 120,
    }


def _json_error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


async def handle_index(_request: web.Request) -> web.Response:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_favicon(_request: web.Request) -> web.Response:
    return web.FileResponse(STATIC_DIR / "favicon.svg")


async def handle_css(_request: web.Request) -> web.Response:
    return web.Response(
        body=(STATIC_DIR / "app.css").read_bytes(),
        content_type="text/css",
        charset="utf-8",
    )


async def handle_servers(request: web.Request) -> web.Response:
    runtime: AdminRuntime = request.app["runtime"]
    payload = []
    for server in runtime.config.servers:
        operator = runtime.operator(server.id)
        state = await operator.probe()
        process = server.process
        process_path_ok = process is not None and process.working_directory.is_dir()
        settings_ok = process is not None and process.settings_file.is_file()
        hints: list[str] = []
        if process is None:
            hints.append("process 設定がありません。初回セットアップで PalServer フォルダを指定してください。")
        elif not process_path_ok:
            hints.append(f"PalServer フォルダが見つかりません: {process.working_directory}")
        elif not settings_ok:
            hints.append(
                f"PalWorldSettings.ini がまだありません: {process.settings_file}。"
                "サーバーを一度起動するか、初回セットアップで REST API を有効にしてください。"
            )
        if state == "auth":
            hints.append("REST API のパスワードが違います。.env と AdminPassword を揃えてください。")
        running_version = None
        if state == "online":
            try:
                info = await operator.client.info()
                running_version = info.version or None
            except Exception:
                running_version = None
        working = process.working_directory if process is not None else None
        update = await inspect_update(working, running_version=running_version)
        if update.update_available and update.hint:
            hints.append(update.hint)
        schedule = _schedule_payload(server)
        payload.append(
            {
                "id": server.id,
                "name": server.name,
                "join_info": server.join_info,
                "online": state == "online",
                "status": state,
                "has_process": server.process is not None,
                "process_path_ok": process_path_ok,
                "settings_ok": settings_ok,
                "hints": hints,
                "schedule": schedule,
                "working_directory": working.as_posix() if working is not None else "",
                "update": update.as_dict(),
            }
        )
    return web.json_response({"ok": True, "servers": payload})


def _operator(request: web.Request, server_id: str):
    runtime: AdminRuntime = request.app["runtime"]
    try:
        return runtime.operator(server_id)
    except KeyError as exc:
        raise web.HTTPNotFound(text=str(exc)) from exc


async def handle_start(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    try:
        message = await operator.start()
    except OperationError as exc:
        return _json_error(str(exc), 409)
    return web.json_response({"ok": True, "message": message})


async def handle_stop(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    body = await _read_json(request)
    wait_seconds = int(body.get("wait_seconds", 30))
    try:
        await operator.stop(wait_seconds=max(0, min(wait_seconds, 300)))
    except OperationError as exc:
        return _json_error(str(exc), 409)
    return web.json_response({"ok": True, "message": f"{operator.server.name} を停止しました"})


async def handle_restart(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    body = await _read_json(request)
    wait_seconds = int(body.get("wait_seconds", 60))
    try:
        await operator.restart(wait_seconds=max(0, min(wait_seconds, 300)))
    except OperationError as exc:
        return _json_error(str(exc), 409)
    return web.json_response({"ok": True, "message": f"{operator.server.name} を再起動しました"})


async def handle_map(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    status = await operator.probe()
    payload = await fetch_map_data(operator, status)
    return web.json_response(payload)


async def handle_settings_get(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    try:
        values = operator.read_settings()
    except OperationError as exc:
        return _json_error(str(exc), 409)
    common = {
        key: values[key]
        for key in COMMON_KEYS
        if key in values and key not in PROTECTED_KEYS
    }
    public_values = dict(values)
    if "AdminPassword" in public_values:
        public_values["AdminPassword"] = "********"
    fields = merge_settings_view(values)
    return web.json_response({"ok": True, "common": common, "all": public_values, "fields": fields})


async def handle_settings_set(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    body = await _read_json(request)
    restart = bool(body.get("restart", True))
    changes_raw = body.get("changes")
    if isinstance(changes_raw, dict) and changes_raw:
        changes = {str(key): str(value) for key, value in changes_raw.items()}
        blocked = sorted(key for key in changes if key in PROTECTED_KEYS)
        if blocked:
            return _json_error(
                f"{' / '.join(blocked)} は管理画面からは変更できません。初回セットアップのみ変更できます。",
                409,
            )
        if not changes:
            return _json_error("変更がありません")
        try:
            if restart:
                updated = await operator.apply_settings_and_restart(changes)
                restarted = True
            else:
                updated = operator.apply_settings(changes)
                restarted = False
        except OperationError as exc:
            return _json_error(str(exc), 409)
        response_updated = {
            key: {"old": old, "new": new}
            for key, (old, new) in updated.items()
        }
        return web.json_response(
            {
                "ok": True,
                "updated": response_updated,
                "restarted": restarted,
                "message": f"{len(updated)} 件を保存しました",
            }
        )

    key = str(body.get("key") or "").strip()
    value = str(body.get("value") or "").strip()
    if not key:
        return _json_error("設定キーが空です")
    if key in PROTECTED_KEYS:
        return _json_error(
            f"{key} は管理画面からは変更できません。初回セットアップのみ変更できます。",
            409,
        )
    try:
        if restart:
            old, new = await operator.apply_setting_and_restart(key, value)
            restarted = True
        else:
            old, new = operator.apply_setting(key, value)
            restarted = False
    except OperationError as exc:
        return _json_error(str(exc), 409)
    return web.json_response({"ok": True, "key": key, "old": old, "new": new, "restarted": restarted})


async def _steam_progress(message: str) -> None:
    logger.info("%s", message)


async def handle_steamcmd_status(request: web.Request) -> web.Response:
    runtime: AdminRuntime = request.app["runtime"]
    hints: list[Path | None] = []
    for server in runtime.config.servers:
        if server.process is not None:
            hints.append(server.process.working_directory)
    payload = describe_steamcmd(runtime.config.data_dir, *hints)
    return web.json_response({"ok": True, **payload})


async def handle_steamcmd_install(request: web.Request) -> web.Response:
    runtime: AdminRuntime = request.app["runtime"]
    body = await _read_json(request)
    raw = str(body.get("directory") or "").strip()
    directory = Path(raw).expanduser() if raw else default_install_directory()
    installer = request.app.get("steamcmd_installer") or install_steamcmd
    try:
        path = await installer(
            directory,
            data_dir=runtime.config.data_dir,
            progress=_steam_progress,
        )
    except SteamCmdError as exc:
        return _json_error(str(exc), 409)
    return web.json_response(
        {
            "ok": True,
            "path": Path(path).as_posix(),
            "message": f"SteamCMD を入れました: {Path(path)}",
        }
    )


async def handle_steam_update(request: web.Request) -> web.Response:
    operator = _operator(request, request.match_info["server_id"])
    body = await _read_json(request)
    wait_seconds = int(body.get("wait_seconds", 30))
    restart = bool(body.get("restart", True))
    backup = bool(body.get("backup", True))
    try:
        message = await operator.update_with_steamcmd(
            restart_after=restart,
            backup=backup,
            wait_seconds=max(0, min(wait_seconds, 300)),
            progress=_steam_progress,
        )
    except OperationError as exc:
        return _json_error(str(exc), 409)
    return web.json_response({"ok": True, "message": message})


async def handle_logs(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "lines": recent_logs(300)})


def _discord_payload(runtime: AdminRuntime, service: Any | None = None) -> dict[str, Any]:
    config = runtime.config
    discord = config.discord
    configured = discord is not None
    has_token = bool(config.discord_token)
    bot_running = False
    bot_error = None
    if service is not None:
        bot_error = service.bot_error
        bot_running = service._bot_task is not None and not service._bot_task.done()
    guild_id = str(discord.guild_id) if discord else ""
    status_channel_id = str(discord.status_channel_id) if discord else ""
    notify_channel_id = str(discord.notify_channel_id) if discord else ""
    owner_user_id = ""
    if discord and discord.owner_user_ids:
        owner_user_id = str(sorted(discord.owner_user_ids)[0])
    invite_url = ""
    if has_token:
        app_id = application_id_from_token(config.discord_token)
        if app_id is not None:
            invite_url = bot_invite_url(app_id)
    return {
        "ok": True,
        "configured": configured,
        "has_token": has_token,
        "bot_running": bot_running,
        "bot_error": bot_error,
        "guild_id": guild_id,
        "status_channel_id": status_channel_id,
        "notify_channel_id": notify_channel_id,
        "owner_user_id": owner_user_id,
        "invite_url": invite_url,
    }


async def handle_discord_get(request: web.Request) -> web.Response:
    runtime: AdminRuntime = request.app["runtime"]
    service = request.app.get("service")
    if service is not None and hasattr(service, "discord_status"):
        return web.json_response(service.discord_status())
    return web.json_response(_discord_payload(runtime, service))


async def handle_discord_post(request: web.Request) -> web.Response:
    runtime: AdminRuntime = request.app["runtime"]
    service = request.app.get("service")
    body = await _read_json(request)
    try:
        if service is not None:
            payload = await service.apply_discord(body)
            return web.json_response(payload)
        assert runtime.config_path is not None
        root = runtime.config_path.parent
        note = apply_discord_from_mapping(root, runtime.config_path, body)
        new = load_config(
            runtime.config_path,
            dotenv_path=root / ".env",
            require_discord_token=False,
        )
        runtime.config = new
        payload = _discord_payload(runtime, service)
        payload["message"] = note
        return web.json_response(payload)
    except ConfigError as exc:
        return _json_error(str(exc), 400)


async def handle_server_ops(request: web.Request) -> web.Response:
    runtime: AdminRuntime = request.app["runtime"]
    service = request.app.get("service")
    server_id = request.match_info["server_id"]
    body = await _read_json(request)
    try:
        if service is not None and hasattr(service, "apply_server_ops"):
            payload = await service.apply_server_ops(server_id, body)
            return web.json_response(payload)
        assert runtime.config_path is not None
        note = apply_server_ops_from_mapping(runtime.config_path, server_id, body)
        new = load_config(
            runtime.config_path,
            dotenv_path=runtime.config_path.parent / ".env",
            require_discord_token=False,
        )
        runtime.config = new
        server = next((item for item in new.servers if item.id == server_id), None)
        if server is None:
            return _json_error(f"サーバー {server_id} がありません", 400)
        payload = {
            "ok": True,
            "join_info": server.join_info,
            "schedule": _schedule_payload(server),
            "message": note,
        }
        return web.json_response(payload)
    except ConfigError as exc:
        return _json_error(str(exc), 400)


async def handle_shutdown(request: web.Request) -> web.Response:
    service = request.app.get("service")
    if service is None:
        return _json_error("この起動方法では、画面の終了ボタンは使えません", 409)

    async def stop_after_response() -> None:
        await asyncio.sleep(0.15)
        service.request_stop()

    asyncio.create_task(stop_after_response())
    return web.json_response({"ok": True, "message": "管理ツールを終了します"})


async def _read_json(request: web.Request) -> dict:
    if not request.can_read_body:
        return {}
    if request.content_type and "json" not in request.content_type:
        return {}
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def create_app(runtime: AdminRuntime, service=None, steamcmd_installer=None) -> web.Application:
    app = web.Application()
    app["runtime"] = runtime
    if service is not None:
        app["service"] = service
    if steamcmd_installer is not None:
        app["steamcmd_installer"] = steamcmd_installer
    app.router.add_get("/", handle_index)
    app.router.add_get("/app.css", handle_css)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/favicon.svg", handle_favicon)
    app.router.add_get("/api/servers", handle_servers)
    app.router.add_get("/api/steamcmd", handle_steamcmd_status)
    app.router.add_post("/api/steamcmd/install", handle_steamcmd_install)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/api/discord", handle_discord_get)
    app.router.add_post("/api/discord", handle_discord_post)
    app.router.add_post("/api/shutdown", handle_shutdown)
    app.router.add_post("/api/servers/{server_id}/start", handle_start)
    app.router.add_post("/api/servers/{server_id}/stop", handle_stop)
    app.router.add_post("/api/servers/{server_id}/restart", handle_restart)
    app.router.add_post("/api/servers/{server_id}/steam-update", handle_steam_update)
    app.router.add_get("/api/servers/{server_id}/map", handle_map)
    app.router.add_get("/api/servers/{server_id}/settings", handle_settings_get)
    app.router.add_post("/api/servers/{server_id}/settings", handle_settings_set)
    app.router.add_post("/api/servers/{server_id}/ops", handle_server_ops)
    return app
