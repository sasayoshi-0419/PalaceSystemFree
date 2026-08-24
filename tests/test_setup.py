from argparse import Namespace
from pathlib import Path

import pytest

from palworld_admin.__main__ import main as admin_main
from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.settings_ini import load_settings_file, write_settings_file
from palworld_discord_bot.setup import (
    _choose_palserver,
    _parse_discord_mapping_fields,
    _parse_discord_owner_user_ids,
    apply_discord_from_mapping,
    apply_server_ops_from_mapping,
    apply_setup_from_mapping,
    game_port_from_command,
    retarget_palserver,
    run_setup,
)


def test_setup_writes_config_env_and_rest(tmp_path: Path, monkeypatch) -> None:
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    settings = pal / "Pal" / "Saved" / "Config" / "WindowsServer" / "PalWorldSettings.ini"
    settings.parent.mkdir(parents=True)
    write_settings_file(
        settings,
        {
            "ExpRate": "1.000000",
            "RESTAPIEnabled": "False",
            "RESTAPIPort": "1",
            "AdminPassword": "old",
        },
    )
    monkeypatch.chdir(tmp_path)
    args = Namespace(
        config="config.yaml",
        yes=True,
        force=False,
        palserver=str(pal),
        name="本鯖",
        server_id="main",
        port=8211,
        rest_port=8212,
        admin_password="secret-pass",
        join_info="",
        skip_discord=True,
        discord_token=None,
        guild_id=None,
        status_channel_id=None,
        notify_channel_id=None,
        owner_user_id=None,
    )
    assert run_setup(args, cwd=tmp_path) == 0
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].name == "本鯖"
    assert config.servers[0].process is not None
    assert config.servers[0].process.start_command[0].endswith("PalServer.exe") or config.servers[0].process.start_command[0] == "PalServer.exe"
    values = load_settings_file(settings)
    assert values["RESTAPIEnabled"] == "True"
    assert values["AdminPassword"] == "secret-pass"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "PAL_MAIN_ADMIN_PASSWORD=secret-pass" in env_text


def test_admin_setup_cli(tmp_path: Path, monkeypatch) -> None:
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    monkeypatch.chdir(tmp_path)
    assert (
        admin_main(
            [
                "setup",
                "--yes",
                "--palserver",
                str(pal),
                "--admin-password",
                "pw",
                "--skip-discord",
            ]
        )
        == 0
    )
    assert (tmp_path / "config.yaml").is_file()


def test_apply_setup_from_mapping(tmp_path: Path) -> None:
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    note = apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(pal),
            "name": "テスト鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    assert "REST API" in note or "ini" in note.lower() or "起動" in note
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "テスト鯖" in text
    with pytest.raises(ConfigError, match="フォルダ"):
        apply_setup_from_mapping(tmp_path, tmp_path / "config.yaml", {"palserver": "", "password": "x"})
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ConfigError, match="PalServer.exe"):
        apply_setup_from_mapping(tmp_path, tmp_path / "config.yaml", {"palserver": str(empty), "password": "x"})


def test_choose_palserver_auto_rejects_multiple(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    for folder in (one, two):
        folder.mkdir()
        (folder / "PalServer.exe").write_bytes(b"mz")
    monkeypatch.setattr(
        "palworld_discord_bot.setup.find_palserver_directories",
        lambda extra=None: [one, two],
    )
    with pytest.raises(ConfigError, match="複数"):
        _choose_palserver(None, auto=True)


def test_choose_palserver_interactive_picks_second(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    for folder in (one, two):
        folder.mkdir()
        (folder / "PalServer.exe").write_bytes(b"mz")
    monkeypatch.setattr(
        "palworld_discord_bot.setup.find_palserver_directories",
        lambda extra=None: [one, two],
    )
    monkeypatch.setattr("palworld_discord_bot.setup._ask", lambda prompt, default="": "2")
    assert _choose_palserver(None, auto=False).resolve() == two.resolve()


def test_choose_palserver_interactive_requires_choice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    for folder in (one, two):
        folder.mkdir()
        (folder / "PalServer.exe").write_bytes(b"mz")
    monkeypatch.setattr(
        "palworld_discord_bot.setup.find_palserver_directories",
        lambda extra=None: [one, two],
    )
    monkeypatch.setattr("palworld_discord_bot.setup._ask", lambda prompt, default="": default)
    with pytest.raises(ConfigError, match="選んで"):
        _choose_palserver(None, auto=False)


def test_retarget_palserver_keeps_discord(tmp_path: Path) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    for folder in (old, new):
        folder.mkdir()
        (folder / "PalServer.exe").write_bytes(b"mz")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(old),
            "name": "本鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": True,
            "discord_token": "dummy-token",
            "guild_id": "1",
            "status_channel_id": "2",
            "notify_channel_id": "3",
            "owner_user_id": "4",
        },
    )
    note = retarget_palserver(tmp_path / "config.yaml", new)
    assert new.as_posix() in note or str(new.resolve().as_posix()) in note.replace("\\", "/")
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].process is not None
    assert config.servers[0].process.working_directory.resolve() == new.resolve()
    assert config.discord is not None
    assert config.discord.guild_id == 1


def test_game_port_from_command() -> None:
    assert game_port_from_command(["PalServer.exe", "-port=9000"]) == 9000
    assert game_port_from_command("PalServer.exe -port=8211") == 8211
    assert game_port_from_command(["PalServer.exe"]) == 8211


def test_apply_discord_from_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(pal),
            "name": "テスト鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    note = apply_discord_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "discord_token": "dummy-token",
            "guild_id": "111",
            "status_channel_id": "222",
            "notify_channel_id": "333",
            "owner_user_id": "444",
        },
    )
    assert "Discord" in note
    after = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "テスト鯖" in after
    assert before.count("テスト鯖") == after.count("テスト鯖")
    assert "discord:" in after
    assert "guild_id: 111" in after
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN=dummy-token" in env_text
    assert "PAL_MAIN_ADMIN_PASSWORD=secret-pass" in env_text
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.discord is not None
    assert config.discord.guild_id == 111
    assert config.servers[0].name == "テスト鯖"


def test_apply_discord_keeps_existing_token(tmp_path: Path) -> None:
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
    (tmp_path / ".env").write_text(
        "PAL_MAIN_ADMIN_PASSWORD=secret-pass\nDISCORD_TOKEN=existing-token\n",
        encoding="utf-8",
    )
    apply_discord_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "discord_token": "",
            "guild_id": "1",
            "status_channel_id": "2",
        },
    )
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN=existing-token" in env_text


def test_apply_discord_requires_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
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
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        apply_discord_from_mapping(
            tmp_path,
            tmp_path / "config.yaml",
            {"discord_token": "", "guild_id": "1", "status_channel_id": "2"},
        )


def test_apply_discord_requires_guild(tmp_path: Path) -> None:
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
    with pytest.raises(ConfigError, match="サーバー ID"):
        apply_discord_from_mapping(
            tmp_path,
            tmp_path / "config.yaml",
            {
                "discord_token": "tok",
                "guild_id": "",
                "status_channel_id": "2",
            },
        )


def test_apply_discord_keeps_poll_interval(tmp_path: Path) -> None:
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
            "discord": True,
            "discord_token": "tok",
            "guild_id": "1",
            "status_channel_id": "2",
        },
    )
    path = tmp_path / "config.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("poll_interval_seconds: 20", "poll_interval_seconds: 30"), encoding="utf-8")
    apply_discord_from_mapping(
        tmp_path,
        path,
        {
            "discord_token": "tok",
            "guild_id": "9",
            "status_channel_id": "8",
        },
    )
    assert "poll_interval_seconds: 30" in path.read_text(encoding="utf-8")


def test_parse_discord_mapping_fields_invalid_id() -> None:
    with pytest.raises(ConfigError, match="数字"):
        _parse_discord_mapping_fields(
            {"guild_id": "abc", "status_channel_id": "222"},
            "tok",
        )


def test_parse_discord_owner_user_ids_invalid() -> None:
    with pytest.raises(ConfigError, match="ユーザー ID"):
        _parse_discord_owner_user_ids("abc", None)


def test_apply_discord_preserves_owner_user_ids(tmp_path: Path) -> None:
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
    path = tmp_path / "config.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + """
discord:
  guild_id: 1
  status_channel_id: 2
  notify_channel_id: 2
  notify_role_id: null
  owner_user_ids:
    - 10
    - 20
  poll_interval_seconds: 20
""",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "PAL_MAIN_ADMIN_PASSWORD=secret-pass\nDISCORD_TOKEN=tok\n",
        encoding="utf-8",
    )
    apply_discord_from_mapping(
        tmp_path,
        path,
        {
            "discord_token": "tok",
            "guild_id": "1",
            "status_channel_id": "2",
            "owner_user_id": "10",
        },
    )
    config = load_config(path, dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.discord is not None
    assert config.discord.owner_user_ids == frozenset({10, 20})

    apply_discord_from_mapping(
        tmp_path,
        path,
        {
            "discord_token": "tok",
            "guild_id": "1",
            "status_channel_id": "2",
            "owner_user_id": "",
        },
    )
    config = load_config(path, dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.discord is not None
    assert config.discord.owner_user_ids == frozenset({10, 20})

    apply_discord_from_mapping(
        tmp_path,
        path,
        {
            "discord_token": "tok",
            "guild_id": "1",
            "status_channel_id": "2",
            "owner_user_id": "99",
        },
    )
    config = load_config(path, dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.discord is not None
    assert config.discord.owner_user_ids == frozenset({99})


def test_apply_setup_join_info_empty(tmp_path: Path) -> None:
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
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "join_info: ''" in text or 'join_info: ""' in text or "join_info:\n" in text or "join_info: \n" in text
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].join_info == ""


def test_apply_setup_join_info_custom(tmp_path: Path) -> None:
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
            "join_info": "203.0.113.10:8211",
            "discord": False,
        },
    )
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].join_info == "203.0.113.10:8211"


def test_apply_setup_restart_disabled(tmp_path: Path) -> None:
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
            "restart_enabled": False,
            "discord": False,
        },
    )
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].restart_schedule is None


def test_apply_setup_restart_time(tmp_path: Path) -> None:
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
            "restart_time": "06:30",
            "discord": False,
        },
    )
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].restart_schedule is not None
    assert config.servers[0].restart_schedule.time == "06:30"


def test_validate_restart_time_accepts_seconds(tmp_path: Path) -> None:
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
            "restart_time": "06:30:00",
            "discord": False,
        },
    )
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].restart_schedule is not None
    assert config.servers[0].restart_schedule.time == "06:30"


def test_validate_restart_time_rejects_invalid(tmp_path: Path) -> None:
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
            "discord": False,
        },
    )
    with pytest.raises(ConfigError, match="HH:MM"):
        apply_server_ops_from_mapping(
            tmp_path / "config.yaml",
            "main",
            {"restart_enabled": True, "restart_time": "abc"},
        )
    with pytest.raises(ConfigError, match="範囲外"):
        apply_server_ops_from_mapping(
            tmp_path / "config.yaml",
            "main",
            {"restart_enabled": True, "restart_time": "25:00"},
        )


def test_apply_server_ops_preserves_schedule_when_omitted(tmp_path: Path) -> None:
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
            "discord": False,
        },
    )
    apply_server_ops_from_mapping(
        tmp_path / "config.yaml",
        "main",
        {"join_info": "203.0.113.10:8211"},
    )
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].join_info == "203.0.113.10:8211"
    assert config.servers[0].restart_schedule is not None
    assert config.servers[0].restart_schedule.time == "05:00"


def test_apply_server_ops_does_not_create_schedule_when_absent(tmp_path: Path) -> None:
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
            "restart_enabled": False,
            "discord": False,
        },
    )
    apply_server_ops_from_mapping(
        tmp_path / "config.yaml",
        "main",
        {"join_info": "203.0.113.10:8211"},
    )
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].join_info == "203.0.113.10:8211"
    assert config.servers[0].restart_schedule is None

