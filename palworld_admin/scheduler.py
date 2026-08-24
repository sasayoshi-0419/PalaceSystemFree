from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from palworld_discord_bot.operations import ScheduleStore
from palworld_discord_bot.schedule import resolve_timezone, schedule_is_due

from palworld_admin.runtime import AdminRuntime

logger = logging.getLogger(__name__)


async def run_scheduled_restarts(runtime: AdminRuntime) -> None:
    store = ScheduleStore(runtime.config.data_dir / "scheduled_restarts.json")
    while True:
        now = datetime.now(timezone.utc)
        for server in runtime.config.servers:
            schedule = server.restart_schedule
            if schedule is None:
                continue
            last = store.last_run_date(server.id)
            try:
                due = schedule_is_due(schedule, now=now, last_run_date=last)
            except ValueError as exc:
                logger.error("%s の定時再起動をスキップします: %s", server.id, exc)
                continue
            if not due:
                continue
            local = now.astimezone(resolve_timezone(schedule.timezone))
            store.mark_run(server.id, local.date())
            logger.info("定時再起動を開始します: %s", server.id)
            try:
                await runtime.operator(server.id).restart(
                    wait_seconds=schedule.warn_seconds,
                    message=schedule.message,
                )
                logger.info("定時再起動が完了しました: %s", server.id)
            except Exception:
                logger.exception("%s の定時再起動に失敗しました", server.id)
        await asyncio.sleep(15)


async def run_update_watch(runtime: AdminRuntime) -> None:
    from palworld_discord_bot.updates import UpdateNoticeStore, inspect_update

    store = UpdateNoticeStore(runtime.config.data_dir / "game_updates.json")
    while True:
        for server in runtime.config.servers:
            running = None
            try:
                if await runtime.operator(server.id).is_online():
                    info = await runtime.operator(server.id).client.info()
                    running = info.version or None
            except Exception:
                running = None
            working = server.process.working_directory if server.process else None
            try:
                status = await inspect_update(working, running_version=running)
            except Exception:
                logger.exception("%s の更新確認に失敗しました", server.id)
                continue
            previous_version = store.last_running_version(server.id)
            if running and previous_version and running != previous_version:
                logger.info(
                    "%s の稼働バージョンが変わりました: %s → %s",
                    server.name,
                    previous_version,
                    running,
                )
            token = status.latest_buildid or status.target_buildid or status.installed_buildid
            if status.update_available and token and store.should_notify(server.id, token):
                logger.warning("%s: %s", server.name, status.summary)
                if status.hint:
                    logger.warning("%s", status.hint)
                store.mark(server.id, notified=token, running_version=running)
            elif running:
                store.mark(server.id, notified=None, running_version=running)
        await asyncio.sleep(1800)
