import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from palworld_admin.runtime import AdminRuntime
from palworld_admin.web import STATIC_DIR, create_app
from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.operations import OperationError
from palworld_discord_bot.settings_ini import write_settings_file


def _admin_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    settings = tmp_path / "PalWorldSettings.ini"
    write_settings_file(settings, {"ExpRate": "1.000000", "ServerName": "Old"})
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
admin:
  bind: 127.0.0.1
  port: 8787
servers:
  - id: main
    name: 本鯖
    rest_url: http://127.0.0.1:8212
    admin_password_env: PAL_MAIN_ADMIN_PASSWORD
    process:
      working_directory: {tmp_path}
      start_command: "python3 -c pass"
      settings_file: {settings}
    restart_schedule:
      time: "05:00"
      timezone: Asia/Tokyo
      warn_seconds: 60
      message: restart
""",
        encoding="utf-8",
    )
    return path


def test_admin_config_does_not_need_discord(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    assert config.discord is None
    assert config.admin.bind == "127.0.0.1"
    assert config.servers[0].restart_schedule is not None


def test_lan_bind_requires_allow_lan(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "x")
    path = tmp_path / "config.yaml"
    path.write_text(
        """
admin:
  bind: 0.0.0.0
  port: 8787
servers:
  - id: main
    name: 本鯖
    rest_url: http://127.0.0.1:8212
    admin_password_env: PAL_MAIN_ADMIN_PASSWORD
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="localhost"):
        load_config(path, dotenv_path=None, require_discord_token=False)


@pytest.mark.asyncio
async def test_admin_web_status_and_settings(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    for operator in runtime.operators.values():
        operator.probe = AsyncMock(return_value="offline")
        operator.is_online = AsyncMock(return_value=False)
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            index = await client.get("/")
            assert index.status == 200
            body = await index.text()
            assert "サーバー管理" in body
            assert "Home Server Admin" in body
            assert "サーバーファイル" in body
            assert "SteamCMD を入れる" in body
            assert "ゲームを更新（SteamCMD）" in body
            assert "close_app" in body
            assert "終了する" in body
            assert "管理ツールを終了しますか" in body
            assert "Discord" in body
            assert "保存してボットを起動" in body
            assert "DISCORD_TOKEN" in body
            assert "Discord Developer Portal" in body
            assert "discord.com/developers/applications" in body
            assert "開発者モード" in body
            assert "guild_id" in body
            assert "applications.commands" in body
            assert "URL Generator" in body
            assert "ボットをサーバーに招待" in body
            assert "作り直す必要はありません" in body
            assert "invite-wrap" in body
            assert "Discord からゲームサーバーの起動・停止はできません" in body
            css = await client.get("/app.css")
            assert css.status == 200
            assert "text/css" in css.headers.get("Content-Type", "")
            css_text = (await css.read()).decode()
            assert "--accent" in css_text
            assert ".invite-wrap" in css_text
            assert "flex-direction: column" in css_text
            assert "overflow-wrap" in css_text
            listing = await client.get("/api/servers")
            payload = await listing.json()
            assert payload["ok"] is True
            assert payload["servers"][0]["id"] == "main"
            assert payload["servers"][0]["online"] is False
            assert payload["servers"][0]["status"] == "offline"
            assert payload["servers"][0]["working_directory"]
            assert "update" in payload["servers"][0]
            assert "summary" in payload["servers"][0]["update"]
            favicon = await client.get("/favicon.ico")
            assert favicon.status == 200
            assert payload["servers"][0]["schedule"]["time"] == "05:00"
            assert payload["servers"][0]["schedule"]["enabled"] is True
            assert "join_info" in payload["servers"][0]
            settings = await client.get("/api/servers/main/settings")
            data = await settings.json()
            assert data["common"]["ExpRate"] == "1.000000"
            updated = await client.post(
                "/api/servers/main/settings",
                json={"key": "ExpRate", "value": "2.000000", "restart": False},
            )
            result = await updated.json()
            assert result["ok"] is True
            assert result["new"] == "2.000000"
            logs = await client.get("/api/logs")
            assert logs.status == 200
            log_payload = await logs.json()
            assert log_payload["ok"] is True
            assert "lines" in log_payload
            shutdown = await client.post("/api/shutdown")
            assert shutdown.status == 409
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_discord_get_unconfigured(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config, config_path=str(path))
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/api/discord")
            payload = await resp.json()
            assert resp.status == 200
            assert payload["ok"] is True
            assert payload["configured"] is False
            assert payload["has_token"] is False
            assert "discord_token" not in payload
            assert "token" not in payload
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_discord_post_and_get(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    settings = tmp_path / "PalWorldSettings.ini"
    write_settings_file(settings, {"ExpRate": "1.000000"})
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
admin:
  bind: 127.0.0.1
  port: 8787
servers:
  - id: main
    name: 本鯖
    rest_url: http://127.0.0.1:8212
    admin_password_env: PAL_MAIN_ADMIN_PASSWORD
    process:
      working_directory: {tmp_path}
      start_command: "python3 -c pass"
      settings_file: {settings}
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("PAL_MAIN_ADMIN_PASSWORD=secret-pass\n", encoding="utf-8")
    config = load_config(path, dotenv_path=tmp_path / ".env", require_discord_token=False)
    runtime = AdminRuntime(config, config_path=str(path))
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            post = await client.post(
                "/api/discord",
                json={
                    "discord_token": "dummy-token",
                    "guild_id": "111",
                    "status_channel_id": "222",
                    "notify_channel_id": "333",
                    "owner_user_id": "444",
                },
            )
            assert post.status == 200
            post_body = await post.text()
            assert "dummy-token" not in post_body
            yaml_text = path.read_text(encoding="utf-8")
            assert "guild_id: 111" in yaml_text
            env_text = (tmp_path / ".env").read_text(encoding="utf-8")
            assert "DISCORD_TOKEN=dummy-token" in env_text
            get = await client.get("/api/discord")
            payload = await get.json()
            assert payload["has_token"] is True
            assert payload["configured"] is True
            assert "discord_token" not in payload
            get_body = await get.text()
            assert "dummy-token" not in get_body
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_discord_post_missing_guild(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config, config_path=str(path))
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post(
                "/api/discord",
                json={"discord_token": "tok", "guild_id": "", "status_channel_id": "2"},
            )
            assert resp.status == 400
            payload = await resp.json()
            assert payload["ok"] is False
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_discord_post_missing_token(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config, config_path=str(path))
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post(
                "/api/discord",
                json={"discord_token": "", "guild_id": "1", "status_channel_id": "2"},
            )
            assert resp.status == 400
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_discord_post_invalid_guild_id(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config, config_path=str(path))
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.post(
                "/api/discord",
                json={"discord_token": "tok", "guild_id": "abc", "status_channel_id": "2"},
            )
            assert resp.status == 400
            payload = await resp.json()
            assert payload["ok"] is False
            assert "数字" in payload["error"]
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_shutdown_with_service(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)

    class FakeService:
        def __init__(self) -> None:
            self.stopped = False

        def request_stop(self) -> None:
            self.stopped = True

    service = FakeService()
    app = create_app(runtime, service=service)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            shutdown = await client.post("/api/shutdown")
            payload = await shutdown.json()
            assert shutdown.status == 200
            assert payload["ok"] is True
            assert service.stopped is False
            await asyncio.sleep(0.3)
            assert service.stopped is True
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_start_when_already_online(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    for operator in runtime.operators.values():
        operator.probe = AsyncMock(return_value="online")
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            start = await client.post("/api/servers/main/start")
            payload = await start.json()
            assert start.status == 200
            assert payload["ok"] is True
            assert "すでに起動" in payload["message"]
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_start_returns_error_body(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    for operator in runtime.operators.values():
        operator.start = AsyncMock(side_effect=OperationError("PalServer フォルダがありません: C:/missing"))
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            start = await client.post("/api/servers/main/start")
            payload = await start.json()
            assert start.status == 409
            assert payload["ok"] is False
            assert "PalServer フォルダがありません" in payload["error"]
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_steamcmd_install_and_update(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    installed: list[Path] = []

    async def fake_installer(directory, *, data_dir=None, progress=None, **_kwargs):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        exe = directory / "steamcmd"
        exe.write_bytes(b"x")
        installed.append(exe)
        if progress:
            await progress(f"installed {exe}")
        return exe

    for operator in runtime.operators.values():
        operator.update_with_steamcmd = AsyncMock(return_value="本鯖 を更新して起動しました")

    app = create_app(runtime, steamcmd_installer=fake_installer)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            status = await client.get("/api/steamcmd")
            payload = await status.json()
            assert payload["ok"] is True
            assert "default_directory" in payload
            dest = tmp_path / "SteamCMD"
            install = await client.post("/api/steamcmd/install", json={"directory": str(dest)})
            result = await install.json()
            assert install.status == 200
            assert result["ok"] is True
            assert installed
            update = await client.post(
                "/api/servers/main/steam-update",
                json={"restart": True, "backup": True, "wait_seconds": 0},
            )
            updated = await update.json()
            assert update.status == 200
            assert "更新" in updated["message"]
    await runtime.close()


@pytest.mark.asyncio
async def test_admin_steam_update_error_body(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    for operator in runtime.operators.values():
        operator.update_with_steamcmd = AsyncMock(
            side_effect=OperationError("SteamCMD が見つかりません")
        )
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            update = await client.post("/api/servers/main/steam-update", json={})
            payload = await update.json()
            assert update.status == 409
            assert payload["ok"] is False
            assert "SteamCMD" in payload["error"]
    await runtime.close()


def test_index_html_has_ops_and_unofficial() -> None:
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "非公式。Pocketpair / Palworld とは無関係です。" in text
    assert "入り方と定時再起動を保存" in text
    assert "api/servers/" in text
    assert "/ops" in text
    assert '<details class="guide" open>' not in text


@pytest.mark.asyncio
async def test_admin_server_ops(tmp_path, monkeypatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config, config_path=str(path))
    for operator in runtime.operators.values():
        operator.probe = AsyncMock(return_value="offline")
        operator.is_online = AsyncMock(return_value=False)
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            before = config.servers[0].process.working_directory.as_posix()
            resp = await client.post(
                "/api/servers/main/ops",
                json={
                    "join_info": "203.0.113.10:8211",
                    "restart_enabled": True,
                    "restart_time": "06:30",
                },
            )
            payload = await resp.json()
            assert resp.status == 200
            assert payload["ok"] is True
            assert payload["join_info"] == "203.0.113.10:8211"
            assert payload["schedule"]["enabled"] is True
            assert payload["schedule"]["time"] == "06:30"
            new_config = load_config(path, dotenv_path=None, require_discord_token=False)
            assert new_config.servers[0].join_info == "203.0.113.10:8211"
            assert new_config.servers[0].restart_schedule is not None
            assert new_config.servers[0].restart_schedule.time == "06:30"
            assert new_config.servers[0].process.working_directory.as_posix() == before
            disabled = await client.post(
                "/api/servers/main/ops",
                json={"join_info": "203.0.113.10:8211", "restart_enabled": False},
            )
            disabled_payload = await disabled.json()
            assert disabled.status == 200
            assert disabled_payload["schedule"]["enabled"] is False
    await runtime.close()
