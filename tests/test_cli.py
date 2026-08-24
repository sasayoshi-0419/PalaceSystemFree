from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from palworld_admin.__main__ import main as admin_main
from palworld_discord_bot.__main__ import main as bot_main
from palworld_discord_bot.settings_ini import load_settings_file, write_settings_file


def _write_config(tmp_path, monkeypatch, *, with_discord: bool = True) -> None:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    settings = tmp_path / "PalWorldSettings.ini"
    write_settings_file(settings, {"ExpRate": "1.000000", "ServerName": "Old"})
    discord = ""
    if with_discord:
        discord = """
discord:
  guild_id: 1
  status_channel_id: 2
  notify_channel_id: 3
  notify_role_id: null
  owner_user_ids: [99]
  poll_interval_seconds: 20
"""
    (tmp_path / "config.yaml").write_text(
        f"""
{discord}
servers:
  - id: main
    name: 本鯖
    rest_url: http://127.0.0.1:8212
    admin_password_env: PAL_MAIN_ADMIN_PASSWORD
    join_info: example:8211
    process:
      working_directory: {tmp_path}
      start_command: "python3 -c 'pass'"
      settings_file: {settings}
""",
        encoding="utf-8",
    )


def test_check_config_cli(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
discord:
  guild_id: 1
  status_channel_id: 2
  notify_channel_id: 3
  notify_role_id: null
  owner_user_ids: [99]
  poll_interval_seconds: 20
servers:
  - id: main
    name: 本鯖
    rest_url: http://127.0.0.1:8212
    admin_password_env: PAL_MAIN_ADMIN_PASSWORD
    join_info: example:8211
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert bot_main(["--config", str(config_path), "--check-config"]) == 0
    output = capsys.readouterr().out
    assert "1 台のサーバー設定を読み込みました" in output
    assert "本鯖" in output


def test_settings_set_cli(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path, monkeypatch, with_discord=False)
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.yaml"
    assert admin_main(["--config", str(config_path), "settings", "set", "main", "ExpRate", "2.5"]) == 0
    output = capsys.readouterr().out
    assert "ExpRate: 1.000000 -> 2.5" in output
    values = load_settings_file(tmp_path / "PalWorldSettings.ini")
    assert values["ExpRate"] == "2.5"
    assert admin_main(["--config", str(config_path), "settings", "show", "main", "ExpRate"]) == 0
    assert "ExpRate=2.5" in capsys.readouterr().out


def test_admin_gui_help(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        admin_main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "コマンドプロンプト" in output
    assert "steamcmd-install" in output
    with pytest.raises(SystemExit) as exc:
        admin_main(["gui", "--help"])
    assert exc.value.code == 0
    assert "--no-bot" in capsys.readouterr().out


def test_frozen_empty_argv_starts_gui(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palworld_admin.__main__.is_frozen", lambda: True)
    monkeypatch.setattr("palworld_admin.__main__.prepare_frozen_cwd", lambda: None)
    called: list[str] = []

    def fake_gui(config_path: str, **kwargs) -> int:
        called.append(config_path)
        return 0

    monkeypatch.setattr("palworld_admin.gui.run_gui", fake_gui)
    assert admin_main([]) == 0
    assert called
    assert called[0].endswith("config.yaml")


def test_frozen_setup_uses_gui(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("palworld_admin.__main__.is_frozen", lambda: True)
    monkeypatch.setattr("palworld_admin.__main__.prepare_frozen_cwd", lambda: None)
    monkeypatch.setattr("palworld_admin.gui.run_setup_window", lambda path: 0)
    assert admin_main(["setup"]) == 0


def test_steamcmd_install_cli(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path, monkeypatch, with_discord=False)
    monkeypatch.chdir(tmp_path)

    async def fake_install(directory, *, data_dir=None, progress=None, **_kwargs):
        if progress:
            await progress("ok")
        return Path(directory) / "steamcmd"

    monkeypatch.setattr("palworld_admin.__main__.install_steamcmd", fake_install)
    config_path = tmp_path / "config.yaml"
    assert (
        admin_main(
            ["--config", str(config_path), "steamcmd-install", "--directory", str(tmp_path / "sc")]
        )
        == 0
    )
    assert "SteamCMD:" in capsys.readouterr().out


def test_update_cli(tmp_path, monkeypatch, capsys) -> None:
    _write_config(tmp_path, monkeypatch, with_discord=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "palworld_discord_bot.operations.ServerOperator.update_with_steamcmd",
        AsyncMock(return_value="本鯖 を更新して起動しました"),
    )
    config_path = tmp_path / "config.yaml"
    assert admin_main(["--config", str(config_path), "update", "main", "--no-restart"]) == 0
    assert "更新" in capsys.readouterr().out
