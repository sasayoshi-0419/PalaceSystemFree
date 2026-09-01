from __future__ import annotations

import sys
from pathlib import Path

import pytest

from palworld_discord_bot.config import ProcessConfig, RestartSchedule, ServerConfig
from palworld_discord_bot.operations import OperationError, ServerOperator
from palworld_discord_bot.process import pid_is_alive
from palworld_discord_bot.settings_ini import load_settings_file, write_settings_file, set_setting
from palworld_discord_bot.steamcmd import save_stored_path
from palworld_discord_bot.user_stop import marker_path


class FakeClient:
    def __init__(self, online: bool = False, auth_error: bool = False) -> None:
        self.online = online
        self.auth_error = auth_error
        self.saved = False
        self.shutdowns: list[tuple[int, str]] = []

    async def probe(self) -> str:
        if self.auth_error:
            return "auth"
        return "online" if self.online else "offline"

    async def is_online(self) -> bool:
        return await self.probe() == "online"

    async def save(self) -> None:
        self.saved = True

    async def shutdown(self, wait_seconds: int, message: str) -> None:
        self.shutdowns.append((wait_seconds, message))
        self.online = False

    async def stop(self) -> None:
        self.online = False

    async def aclose(self) -> None:
        return None


def _server(tmp_path: Path, start_command: tuple[str, ...] | None = None) -> ServerConfig:
    settings = tmp_path / "PalWorldSettings.ini"
    write_settings_file(
        settings,
        set_setting({"ExpRate": "1.000000", "ServerName": "Old"}, "DeathPenalty", "Item"),
    )
    return ServerConfig(
        id="main",
        name="本鯖",
        rest_url="http://127.0.0.1:8212",
        admin_password="secret",
        process=ProcessConfig(
            working_directory=tmp_path,
            start_command=start_command
            or (sys.executable, "-c", "import time; time.sleep(60)"),
            settings_file=settings,
            log_file=tmp_path / "server.log",
            start_timeout_seconds=8,
            stop_timeout_seconds=8,
            world_option_sav=tmp_path / "WorldOption.sav",
        ),
        restart_schedule=RestartSchedule("05:00", "Asia/Tokyo", 30, "restart"),
    )


@pytest.mark.asyncio
async def test_start_when_already_online_is_ok(tmp_path: Path) -> None:
    server = _server(tmp_path)
    client = FakeClient(online=True)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]
    message = await operator.start()
    assert "すでに起動" in message
    assert operator.process is not None
    assert operator.process.read_pid() is None


@pytest.mark.asyncio
async def test_start_rejects_rest_auth_failure(tmp_path: Path) -> None:
    server = _server(tmp_path)
    client = FakeClient(auth_error=True)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]
    with pytest.raises(OperationError, match="認証"):
        await operator.start()


@pytest.mark.asyncio
async def test_start_reports_immediate_process_exit(tmp_path: Path) -> None:
    server = _server(tmp_path, (sys.executable, "-c", "raise SystemExit(7)"))
    client = FakeClient(online=False)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]
    with pytest.raises(OperationError, match="すぐ終了"):
        await operator.start()


@pytest.mark.asyncio
async def test_start_spawns_process_then_stop(tmp_path: Path) -> None:
    server = _server(tmp_path)
    client = FakeClient(online=False)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]

    async def wait_until(online: bool, timeout: int) -> None:
        client.online = online

    operator.wait_until = wait_until  # type: ignore[method-assign]
    await operator.start()
    pid = operator.process.read_pid() if operator.process else None
    assert pid is not None
    assert pid_is_alive(pid)
    client.online = True
    await operator.stop(wait_seconds=0)
    assert client.saved
    assert client.shutdowns
    assert operator.process is not None
    assert operator.process.read_pid() is None


@pytest.mark.asyncio
async def test_apply_settings_writes_multiple_keys_once(tmp_path: Path) -> None:
    server = _server(tmp_path)
    client = FakeClient(online=False)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]
    updated = operator.apply_settings(
        {"ExpRate": "2.000000", "DeathPenalty": "None", "bIsPvP": "True"},
    )
    assert len(updated) == 3
    values = load_settings_file(server.process.settings_file)
    assert values["ExpRate"] == "2.000000"
    assert values["DeathPenalty"] == "None"
    assert values["bIsPvP"] == "True"


@pytest.mark.asyncio
async def test_apply_setting_after_stop_and_backup_world_option(tmp_path: Path) -> None:
    server = _server(tmp_path)
    sav = tmp_path / "WorldOption.sav"
    sav.write_bytes(b"sav")
    client = FakeClient(online=True)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]

    async def wait_until(online: bool, timeout: int) -> None:
        client.online = online

    operator.wait_until = wait_until  # type: ignore[method-assign]
    old, new = await operator.apply_setting_and_restart("ExpRate", "3.000000", wait_seconds=0)
    assert old == "1.000000"
    assert new == "3.000000"
    values = load_settings_file(server.process.settings_file)
    assert values["ExpRate"] == "3.000000"
    assert sav.with_suffix(".sav.bak").is_file()
    assert not sav.exists()
    if operator.process and operator.process.read_pid():
        operator.process.terminate()


@pytest.mark.asyncio
async def test_update_with_steamcmd_stops_backs_up_and_restarts(tmp_path: Path) -> None:
    server = _server(tmp_path)
    saved = tmp_path / "Pal" / "Saved"
    saved.mkdir(parents=True)
    (saved / "Save.sav").write_bytes(b"world")
    steam = tmp_path / "steamcmd"
    steam.write_bytes(b"x")
    save_stored_path(tmp_path, steam)
    client = FakeClient(online=True)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]

    async def wait_until(online: bool, timeout: int) -> None:
        client.online = online

    operator.wait_until = wait_until  # type: ignore[method-assign]
    calls: list[tuple[Path, Path]] = []

    async def updater(executable: Path, install_dir: Path, progress=None) -> None:
        calls.append((executable, install_dir))
        if progress:
            await progress("fake update")

    message = await operator.update_with_steamcmd(wait_seconds=0, updater=updater)
    assert client.saved
    assert calls
    assert calls[0][0] == steam
    backups = list((tmp_path / "backups").iterdir())
    assert backups
    assert (backups[0] / "Save.sav").read_bytes() == b"world"
    assert "更新して起動" in message
    if operator.process and operator.process.read_pid():
        operator.process.terminate()


@pytest.mark.asyncio
async def test_update_with_steamcmd_requires_steamcmd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("palworld_discord_bot.operations.find_steamcmd", lambda *a, **k: None)
    server = _server(tmp_path)
    operator = ServerOperator(server, FakeClient(), tmp_path)  # type: ignore[arg-type]
    with pytest.raises(OperationError, match="SteamCMD"):
        await operator.update_with_steamcmd(restart_after=False)


@pytest.mark.asyncio
async def test_update_with_steamcmd_can_skip_restart(tmp_path: Path) -> None:
    server = _server(tmp_path)
    steam = tmp_path / "steamcmd"
    steam.write_bytes(b"x")
    save_stored_path(tmp_path, steam)
    client = FakeClient(online=False)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]
    called = {"n": 0}

    async def updater(executable: Path, install_dir: Path, progress=None) -> None:
        called["n"] += 1

    message = await operator.update_with_steamcmd(
        restart_after=False,
        backup=False,
        updater=updater,
    )
    assert called["n"] == 1
    assert "起動はしていません" in message
    assert not (tmp_path / "backups").exists()
    assert not marker_path(tmp_path, "main").exists()


def _operator_with_fast_wait(tmp_path: Path, *, online: bool) -> tuple[ServerOperator, FakeClient]:
    server = _server(tmp_path)
    client = FakeClient(online=online)
    operator = ServerOperator(server, client, tmp_path)  # type: ignore[arg-type]

    async def wait_until(online_flag: bool, timeout: int) -> None:
        client.online = online_flag

    operator.wait_until = wait_until  # type: ignore[method-assign]
    return operator, client


def _cleanup_operator(operator: ServerOperator) -> None:
    if operator.process and operator.process.read_pid():
        operator.process.terminate()


@pytest.mark.asyncio
async def test_stop_writes_user_stopped_marker(tmp_path: Path) -> None:
    operator, client = _operator_with_fast_wait(tmp_path, online=True)
    marker = marker_path(tmp_path, "main")
    await operator.stop(wait_seconds=0)
    assert marker.is_file()
    assert client.saved
    _cleanup_operator(operator)


@pytest.mark.asyncio
async def test_start_clears_user_stopped_marker(tmp_path: Path) -> None:
    operator, client = _operator_with_fast_wait(tmp_path, online=False)
    marker = marker_path(tmp_path, "main")
    marker.write_text("stale", encoding="utf-8")
    await operator.start()
    assert not marker.exists()
    assert operator.process is not None
    assert operator.process.read_pid() is not None
    _cleanup_operator(operator)


@pytest.mark.asyncio
async def test_start_when_already_online_clears_user_stopped_marker(tmp_path: Path) -> None:
    operator, _client = _operator_with_fast_wait(tmp_path, online=True)
    marker = marker_path(tmp_path, "main")
    marker.write_text("stale", encoding="utf-8")
    message = await operator.start()
    assert "すでに起動" in message
    assert not marker.exists()
    _cleanup_operator(operator)


@pytest.mark.asyncio
async def test_restart_does_not_leave_user_stopped_marker(tmp_path: Path) -> None:
    operator, client = _operator_with_fast_wait(tmp_path, online=True)
    marker = marker_path(tmp_path, "main")
    await operator.restart(wait_seconds=0)
    assert not marker.exists()
    assert client.saved
    _cleanup_operator(operator)


@pytest.mark.asyncio
async def test_failed_stop_does_not_write_user_stopped_marker(tmp_path: Path) -> None:
    operator, _client = _operator_with_fast_wait(tmp_path, online=True)
    marker = marker_path(tmp_path, "main")

    async def wait_until(online: bool, timeout: int) -> None:
        raise OperationError("timeout")

    operator.wait_until = wait_until  # type: ignore[method-assign]
    with pytest.raises(OperationError, match="timeout"):
        await operator.stop(wait_seconds=0)
    assert not marker.exists()
    _cleanup_operator(operator)


@pytest.mark.asyncio
async def test_steamcmd_update_does_not_write_user_stopped_marker(tmp_path: Path) -> None:
    operator, _client = _operator_with_fast_wait(tmp_path, online=True)
    steam = tmp_path / "steamcmd"
    steam.write_bytes(b"x")
    save_stored_path(tmp_path, steam)

    async def updater(executable: Path, install_dir: Path, progress=None) -> None:
        return None

    await operator.update_with_steamcmd(wait_seconds=0, backup=False, updater=updater)
    assert not marker_path(tmp_path, "main").exists()
    _cleanup_operator(operator)
