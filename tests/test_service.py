import asyncio
import logging
import socket
from pathlib import Path

import aiohttp
import pytest

from palworld_admin.service import AdminService
from palworld_discord_bot.applog import recent_logs, setup_app_logging
from palworld_discord_bot.config import load_config
from palworld_discord_bot.settings_ini import write_settings_file


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port: int):
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    settings = tmp_path / "PalWorldSettings.ini"
    write_settings_file(settings, {"ExpRate": "1.000000"})
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
admin:
  bind: 127.0.0.1
  port: {port}
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
    return load_config(path, dotenv_path=None, require_discord_token=False)


@pytest.mark.asyncio
async def test_admin_service_logs_and_shutdown(tmp_path, monkeypatch) -> None:
    config = _config(tmp_path, monkeypatch, _free_port())
    setup_app_logging(config.data_dir, also_console=False)
    logging.getLogger("test.service").info("service-boot")
    service = AdminService(config)
    task = asyncio.create_task(service.run(with_bot=False))
    await asyncio.wait_for(service.ready.wait(), timeout=5)
    async with aiohttp.ClientSession() as session:
        async with session.get(service.url + "api/logs") as resp:
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True
            assert any("service-boot" in line for line in body["lines"])
        async with session.post(service.url + "api/shutdown") as resp:
            assert resp.status == 200
            payload = await resp.json()
            assert payload["ok"] is True
    await asyncio.wait_for(task, timeout=5)
    assert service.finished is True
    assert any("終了します" in line for line in recent_logs(50))


def test_gui_module_imports_without_tkinter() -> None:
    import palworld_admin.gui as gui
    import palworld_admin.desktop as desktop

    assert callable(gui.run_gui)
    assert callable(gui.run_setup_window)
    assert callable(gui.ensure_palserver_config)
    assert callable(desktop.run_desktop)


def test_ensure_palserver_config_runs_setup_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import palworld_admin.gui as gui

    called: dict[str, str] = {}

    def fake_setup(path: str, *, mode: str = "setup") -> int:
        called["mode"] = mode
        called["path"] = path
        return 0

    monkeypatch.setattr(gui, "run_setup_window", fake_setup)
    assert gui.ensure_palserver_config(str(tmp_path / "config.yaml"), use_desktop=True) == 0
    assert called["mode"] == "setup"


def test_ensure_palserver_config_skips_when_folder_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import palworld_admin.gui as gui
    from palworld_discord_bot.setup import apply_setup_from_mapping

    monkeypatch.chdir(tmp_path)
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(pal),
            "name": "本鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    monkeypatch.setattr(gui, "run_setup_window", lambda *args, **kwargs: 99)
    assert gui.ensure_palserver_config(str(tmp_path / "config.yaml"), use_desktop=True) == 0


def test_ensure_palserver_config_choose_when_folder_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import palworld_admin.gui as gui
    from palworld_discord_bot.setup import apply_setup_from_mapping

    monkeypatch.chdir(tmp_path)
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(pal),
            "name": "本鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    pal.rename(tmp_path / "gone")
    other = tmp_path / "other"
    other.mkdir()
    (other / "PalServer.exe").write_bytes(b"mz")
    called: dict[str, str] = {}

    def fake_setup(path: str, *, mode: str = "setup") -> int:
        called["mode"] = mode
        return 0

    monkeypatch.setattr(gui, "run_setup_window", fake_setup)
    monkeypatch.setattr(
        "palworld_discord_bot.detect.find_palserver_directories",
        lambda extra=None: [other],
    )
    assert gui.ensure_palserver_config(str(tmp_path / "config.yaml"), use_desktop=True) == 0
    assert called["mode"] == "choose"


def test_palserver_boot_mode_setup_when_missing(tmp_path: Path) -> None:
    from palworld_admin.gui import palserver_boot_mode

    assert palserver_boot_mode(str(tmp_path / "config.yaml")) == "setup"


def test_palserver_boot_mode_admin_when_folder_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from palworld_admin.gui import palserver_boot_mode
    from palworld_discord_bot.setup import apply_setup_from_mapping

    monkeypatch.chdir(tmp_path)
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(pal),
            "name": "本鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    assert palserver_boot_mode(str(tmp_path / "config.yaml")) == "admin"


def test_palserver_boot_mode_choose_when_folder_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from palworld_admin.gui import palserver_boot_mode
    from palworld_discord_bot.setup import apply_setup_from_mapping

    monkeypatch.chdir(tmp_path)
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(pal),
            "name": "本鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    pal.rename(tmp_path / "gone")
    other = tmp_path / "other"
    other.mkdir()
    (other / "PalServer.exe").write_bytes(b"mz")
    monkeypatch.setattr(
        "palworld_discord_bot.detect.find_palserver_directories",
        lambda extra=None: [other],
    )
    assert palserver_boot_mode(str(tmp_path / "config.yaml")) == "choose"


@pytest.mark.asyncio
async def test_apply_discord_restarts_bot(tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock, patch

    port = _free_port()
    config = _config(tmp_path, monkeypatch, port)
    service = AdminService(config, config_path=str(tmp_path / "config.yaml"))
    mock_bot = AsyncMock()
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()

    with patch("palworld_discord_bot.bot.PalworldBot", return_value=mock_bot):
        task = asyncio.create_task(service.run(with_bot=False))
        await asyncio.wait_for(service.ready.wait(), timeout=5)
        await service.apply_discord(
            {
                "discord_token": "dummy-token",
                "guild_id": "111",
                "status_channel_id": "222",
            }
        )
        await asyncio.sleep(0.05)
        mock_bot.start.assert_called()
        assert service.config.discord is not None
        assert service.config.discord.guild_id == 111
        async with aiohttp.ClientSession() as session:
            async with session.get(service.url + "api/discord") as resp:
                payload = await resp.json()
                assert payload["configured"] is True
                assert payload["has_token"] is True
        service.request_stop()
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_apply_server_ops_updates_config_without_palserver(tmp_path, monkeypatch) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    port = _free_port()
    config = _config(tmp_path, monkeypatch, port)
    service = AdminService(config, config_path=str(tmp_path / "config.yaml"))
    mock_bot = MagicMock()
    service.bot = mock_bot
    service.runtime = MagicMock()
    service.runtime.config = config

    with patch.object(service, "_ops_lock", asyncio.Lock()):
        result = await service.apply_server_ops(
            "main",
            {
                "join_info": "203.0.113.10:8211",
                "restart_enabled": True,
                "restart_time": "07:15",
            },
        )

    assert result["ok"] is True
    assert result["join_info"] == "203.0.113.10:8211"
    assert result["schedule"]["time"] == "07:15"
    assert service.config.servers[0].join_info == "203.0.113.10:8211"
    assert mock_bot.config is service.config
    yaml_text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "203.0.113.10:8211" in yaml_text
