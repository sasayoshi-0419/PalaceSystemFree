from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from palworld_admin.runtime import AdminRuntime
from palworld_admin.scheduler import run_scheduled_restarts, run_update_watch
from palworld_admin.web import create_app
from palworld_discord_bot.bot import application_id_from_token, bot_invite_url
from palworld_discord_bot.config import AppConfig, load_config
from palworld_discord_bot.paths import resolve_user_path
from palworld_discord_bot.setup import apply_discord_from_mapping, apply_server_ops_from_mapping

logger = logging.getLogger(__name__)


class AdminService:
    def __init__(self, config: AppConfig, *, config_path: str | None = None) -> None:
        self.config = config
        self.config_path = (
            resolve_user_path(config_path) if config_path else resolve_user_path("config.yaml")
        )
        self.stop_event = asyncio.Event()
        self.ready = asyncio.Event()
        self.runtime: AdminRuntime | None = None
        self.url = f"http://{config.admin.bind}:{config.admin.port}/"
        self.bot: Any = None
        self.bot_error: str | None = None
        self.finished = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bot_task: asyncio.Task[None] | None = None
        self._discord_lock = asyncio.Lock()
        self._ops_lock = asyncio.Lock()

    def request_stop(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self.stop_event.set)
        else:
            self.stop_event.set()

    async def run(self, *, with_bot: bool) -> None:
        self._loop = asyncio.get_running_loop()
        runtime = AdminRuntime(self.config, config_path=self.config_path)
        self.runtime = runtime
        app = create_app(runtime, service=self)

        async def on_startup(_app: web.Application) -> None:
            _app["scheduler"] = asyncio.create_task(run_scheduled_restarts(runtime))
            _app["update_watch"] = asyncio.create_task(run_update_watch(runtime))

        async def on_cleanup(_app: web.Application) -> None:
            for key in ("scheduler", "update_watch"):
                task = _app.get(key)
                if task:
                    task.cancel()
            if self._bot_task is not None:
                self._bot_task.cancel()
                try:
                    await self._bot_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self.bot is not None:
                try:
                    await self.bot.close()
                except Exception:
                    logger.exception("Discord ボットの終了に失敗しました")
            await runtime.close()

        app.on_startup.append(on_startup)
        app.on_cleanup.append(on_cleanup)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, self.config.admin.bind, self.config.admin.port)
            await site.start()
            logger.info("管理パネル: %s", self.url)
            logger.info("このウィンドウを開いている間、定時再起動も実行されます。")
            self.ready.set()
            if with_bot:
                await self._start_bot()
            await self.stop_event.wait()
            logger.info("終了します")
        except asyncio.CancelledError:
            logger.info("キャンセルされました")
            raise
        finally:
            await runner.cleanup()
            self.finished = True

    async def _stop_bot(self) -> None:
        self.bot_error = None
        if self._bot_task is not None:
            self._bot_task.cancel()
            try:
                await self._bot_task
            except (asyncio.CancelledError, Exception):
                pass
            self._bot_task = None
        if self.bot is not None:
            try:
                await self.bot.close()
            except Exception:
                logger.exception("Discord ボットの終了に失敗しました")
            self.bot = None

    async def _restart_bot(self) -> None:
        await self._stop_bot()
        await self._start_bot()

    def discord_status(self) -> dict[str, Any]:
        config = self.config
        discord = config.discord
        configured = discord is not None
        has_token = bool(config.discord_token)
        bot_running = self._bot_task is not None and not self._bot_task.done()
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
            "bot_error": self.bot_error,
            "guild_id": guild_id,
            "status_channel_id": status_channel_id,
            "notify_channel_id": notify_channel_id,
            "owner_user_id": owner_user_id,
            "invite_url": invite_url,
        }

    async def apply_discord(self, data: dict[str, Any]) -> dict[str, Any]:
        async with self._discord_lock:
            assert self.config_path is not None
            root = self.config_path.parent
            note = apply_discord_from_mapping(root, self.config_path, data)
            new = load_config(
                self.config_path,
                dotenv_path=root / ".env",
                require_discord_token=False,
            )
            self.config = new
            if self.runtime is not None:
                self.runtime.config = new
            await self._restart_bot()
            payload = self.discord_status()
            payload["message"] = f"{note}。ボットを起動しています。"
            return payload

    async def apply_server_ops(self, server_id: str, data: dict[str, Any]) -> dict[str, Any]:
        async with self._ops_lock:
            assert self.config_path is not None
            note = apply_server_ops_from_mapping(self.config_path, server_id, data)
            new = load_config(
                self.config_path,
                dotenv_path=self.config_path.parent / ".env",
                require_discord_token=False,
            )
            self.config = new
            if self.runtime is not None:
                self.runtime.config = new
            if self.bot is not None:
                self.bot.config = new
            server = next((item for item in new.servers if item.id == server_id), None)
            schedule_payload = {
                "enabled": False,
                "time": "05:00",
                "timezone": "Asia/Tokyo",
                "warn_seconds": 120,
            }
            join_info = ""
            if server is not None:
                join_info = server.join_info
                if server.restart_schedule is not None:
                    schedule_payload = {
                        "enabled": True,
                        "time": server.restart_schedule.time,
                        "timezone": server.restart_schedule.timezone,
                        "warn_seconds": server.restart_schedule.warn_seconds,
                    }
            return {
                "ok": True,
                "join_info": join_info,
                "schedule": schedule_payload,
                "message": note,
            }

    async def _start_bot(self) -> None:
        if not self.config.discord or not self.config.discord_token:
            logger.info("Discord 設定がないのでボットは起動しません")
            return
        from palworld_discord_bot.bot import PalworldBot

        self.bot = PalworldBot(self.config)

        async def run_bot() -> None:
            try:
                await self.bot.start(self.config.discord_token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.bot_error = str(exc)
                logger.exception("Discord ボットを起動できませんでした")

        self._bot_task = asyncio.create_task(run_bot())
        logger.info("Discord ボットを起動しています")
