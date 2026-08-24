from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from pathlib import Path

from palworld_discord_bot.config import ServerConfig
from palworld_discord_bot.palworld import PalworldAPIError, PalworldClient
from palworld_discord_bot.process import ProcessController, ProcessError
from palworld_discord_bot.steamcmd import (
    SteamCmdError,
    find_steamcmd,
    looks_like_steam_client_install,
    palserver_install_dir,
    update_palworld_server,
)
from palworld_discord_bot.settings_ini import (
    SettingsError,
    load_settings_file,
    set_setting,
    set_settings,
    write_settings_file,
)

Progress = Callable[[str], Awaitable[None]]


class OperationError(RuntimeError):
    """Raised when a start/stop/restart/settings operation fails."""


async def _noop_progress(_message: str) -> None:
    return None


class ServerOperator:
    def __init__(
        self,
        server: ServerConfig,
        client: PalworldClient,
        data_dir: Path,
    ) -> None:
        self.server = server
        self.client = client
        self.data_dir = data_dir
        self.lock = asyncio.Lock()
        self.process = None
        if server.process is not None:
            self.process = ProcessController(server.process, data_dir / f"{server.id}.pid")

    def _require_process(self) -> ProcessController:
        if self.process is None or self.server.process is None:
            raise OperationError(
                f"{self.server.name} には process 設定がありません。"
                "config.yaml に working_directory と start_command を書いてください。"
            )
        return self.process

    async def probe(self) -> str:
        return await self.client.probe()

    async def is_online(self) -> bool:
        return await self.client.is_online()

    async def wait_until(self, online: bool, timeout: int) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if await self.is_online() is online:
                return
            await asyncio.sleep(2)
        if online:
            raise OperationError(
                f"{self.server.name} が {timeout} 秒以内にオンラインになりませんでした。"
                "PalWorldSettings.ini の RESTAPIEnabled=True、RESTAPIPort と config.yaml の rest_url、"
                ".env のパスワードと AdminPassword が一致しているか確認してください。"
            )
        raise OperationError(f"{self.server.name} が {timeout} 秒以内にオフラインになりませんでした")

    def _raise_if_auth_failed(self, state: str) -> None:
        if state == "auth":
            raise OperationError(
                f"{self.server.name} の REST API 認証に失敗しました。"
                ".env のパスワードと PalWorldSettings.ini の AdminPassword を一致させてください。"
                "ゲームサーバー自体は起動済みの可能性があります。"
            )

    async def start(self, progress: Progress | None = None) -> str:
        report = progress or _noop_progress
        self._require_process()
        async with self.lock:
            return await self._start_unlocked(report)

    async def _start_unlocked(self, report: Progress) -> str:
        controller = self._require_process()
        state = await self.probe()
        if state == "online":
            await report("すでに起動しています")
            return f"{self.server.name} はすでに起動しています"
        self._raise_if_auth_failed(state)
        await report("プロセスを起動しています…")
        try:
            controller.start()
        except ProcessError as exc:
            raise OperationError(str(exc)) from exc
        await asyncio.sleep(1)
        exit_code = controller.child_exit_code()
        if exit_code is not None:
            tail = controller.log_tail()
            extra = f" ログ: {tail}" if tail else ""
            raise OperationError(
                f"{self.server.name} のプロセスがすぐ終了しました (exit={exit_code})。"
                "working_directory と start_command（Windows なら PalServer.exe）を確認してください。"
                f"{extra}"
            )
        await report("REST API の応答を待っています…")
        await self.wait_until(True, controller.process.start_timeout_seconds)
        return f"{self.server.name} を起動しました"

    async def stop(self, wait_seconds: int = 30, message: str = "サーバーを停止します", progress: Progress | None = None) -> None:
        report = progress or _noop_progress
        async with self.lock:
            await self._stop_unlocked(wait_seconds, message, report)

    async def _stop_unlocked(self, wait_seconds: int, message: str, report: Progress) -> None:
        timeout = self.server.process.stop_timeout_seconds if self.server.process else 90
        if await self.is_online():
            await report("ワールドを保存しています…")
            try:
                await self.client.save()
            except PalworldAPIError as exc:
                await report(f"保存に失敗しましたが停止を続けます: {exc}")
            await report(f"{wait_seconds} 秒後にシャットダウンします…")
            try:
                await self.client.shutdown(wait_seconds, message)
            except PalworldAPIError:
                try:
                    await self.client.stop()
                except PalworldAPIError as exc:
                    raise OperationError(f"停止に失敗しました: {exc}") from exc
            await asyncio.sleep(min(wait_seconds, 5))
            await self.wait_until(False, timeout + wait_seconds)
        if self.process is not None:
            if self.process.is_running():
                await report("残っているプロセスを終了しています…")
                self.process.terminate()
                await asyncio.sleep(1)
                if self.process.is_running():
                    self.process.terminate()
            self.process.clear_pid()

    async def restart(
        self,
        wait_seconds: int = 60,
        message: str = "サーバーを再起動します",
        progress: Progress | None = None,
        after_stop: Callable[[], None] | None = None,
    ) -> None:
        report = progress or _noop_progress
        self._require_process()
        async with self.lock:
            state = await self.probe()
            self._raise_if_auth_failed(state)
            if state == "online":
                await self._stop_unlocked(wait_seconds, message, report)
            if after_stop is not None:
                after_stop()
            await self._start_unlocked(report)

    def read_settings(self) -> dict[str, str]:
        if self.server.process is None:
            raise OperationError("process.settings_file が設定されていません")
        try:
            return load_settings_file(self.server.process.settings_file)
        except SettingsError as exc:
            raise OperationError(str(exc)) from exc

    def _write_settings(self, updated: dict[str, str]) -> None:
        process = self.server.process
        if process is None:
            raise OperationError("process.settings_file が設定されていません")
        write_settings_file(process.settings_file, updated)
        if process.world_option_sav and process.world_option_sav.is_file():
            sav = process.world_option_sav
            shutil.copy2(sav, sav.with_suffix(sav.suffix + ".bak"))
            sav.unlink()

    def apply_setting(self, key: str, value: str) -> tuple[str | None, str]:
        updated_map = self.apply_settings({key: value})
        old, new = updated_map[key]
        return old, new

    def apply_settings(self, changes: dict[str, str]) -> dict[str, tuple[str | None, str]]:
        if not changes:
            return {}
        process = self.server.process
        if process is None:
            raise OperationError("process.settings_file が設定されていません")
        values = self.read_settings()
        updated_info: dict[str, tuple[str | None, str]] = {}
        try:
            updated = set_settings(values, changes)
        except SettingsError as exc:
            raise OperationError(str(exc)) from exc
        for key, value in changes.items():
            updated_info[key] = (values.get(key), value)
        self._write_settings(updated)
        return updated_info

    async def apply_setting_and_restart(
        self,
        key: str,
        value: str,
        wait_seconds: int = 60,
        progress: Progress | None = None,
    ) -> tuple[str | None, str]:
        updated = await self.apply_settings_and_restart(
            {key: value},
            wait_seconds=wait_seconds,
            progress=progress,
        )
        old, new = updated[key]
        return old, new

    async def apply_settings_and_restart(
        self,
        changes: dict[str, str],
        wait_seconds: int = 60,
        progress: Progress | None = None,
    ) -> dict[str, tuple[str | None, str]]:
        result: dict[str, tuple[str | None, str]] = {}

        def write_after_stop() -> None:
            result.update(self.apply_settings(changes))

        if await self.is_online():
            await self.restart(
                wait_seconds=wait_seconds,
                message="設定変更のため再起動します",
                progress=progress,
                after_stop=write_after_stop,
            )
        else:
            result.update(self.apply_settings(changes))
        return result

    def backup_saved_world(self) -> Path | None:
        process = self.server.process
        if process is None:
            return None
        saved = process.working_directory / "Pal" / "Saved"
        if not saved.is_dir():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = self.data_dir / "backups" / f"{self.server.id}-{stamp}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(saved, dest)
        return dest

    async def update_with_steamcmd(
        self,
        *,
        restart_after: bool = True,
        backup: bool = True,
        wait_seconds: int = 30,
        progress: Progress | None = None,
        updater=update_palworld_server,
    ) -> str:
        report = progress or _noop_progress
        process = self.server.process
        if process is None:
            raise OperationError(
                f"{self.server.name} には process 設定がありません。"
                "先に初回セットアップで PalServer フォルダを指定してください。"
            )
        executable = find_steamcmd(process.working_directory, data_dir=self.data_dir)
        if executable is None:
            raise OperationError(
                "SteamCMD が見つかりません。管理画面の「SteamCMD を入れる」を先に実行してください。"
            )
        if looks_like_steam_client_install(process.working_directory):
            await report(
                "Steam クライアントで入れた PalServer に見えます。SteamCMD での更新は、専用サーバー用のフォルダ向けです。"
            )
        install_dir = palserver_install_dir(process.working_directory)
        async with self.lock:
            state = await self.probe()
            self._raise_if_auth_failed(state)
            if state == "online":
                await self._stop_unlocked(
                    wait_seconds,
                    "SteamCMD で更新するため停止します",
                    report,
                )
            if backup:
                saved = self.backup_saved_world()
                if saved is not None:
                    await report(f"セーブデータをバックアップしました: {saved}")
                else:
                    await report("セーブフォルダがまだないので、バックアップはスキップします")
            else:
                await report("セーブのバックアップはスキップします")
            await report("SteamCMD で専用サーバーを更新しています…")
            try:
                await updater(executable, install_dir, progress=report)
            except SteamCmdError as exc:
                raise OperationError(str(exc)) from exc
            if restart_after:
                await self._start_unlocked(report)
                return f"{self.server.name} を更新して起動しました"
            return f"{self.server.name} のファイルを更新しました。起動はしていません。"


class ScheduleStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items()}

    def last_run_date(self, server_id: str) -> date | None:
        text = self.load().get(server_id)
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    def mark_run(self, server_id: str, day: date) -> None:
        data = self.load()
        data[server_id] = day.isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def local_today(tz_name: str) -> date:
    from zoneinfo import ZoneInfo

    return datetime.now(timezone.utc).astimezone(ZoneInfo(tz_name)).date()
