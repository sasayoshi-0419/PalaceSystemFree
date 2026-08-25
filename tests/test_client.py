from pathlib import Path

import httpx
import pytest
import respx
import yaml

from palworld_discord_bot.config import ConfigError, load_config, soften_windows_yaml
from palworld_discord_bot.palworld import PalworldClient


@pytest.fixture
def config_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "discord": {
                    "guild_id": 1,
                    "status_channel_id": 2,
                    "notify_channel_id": 3,
                    "notify_role_id": None,
                    "owner_user_ids": [99],
                    "poll_interval_seconds": 15,
                },
                "servers": [
                    {
                        "id": "main",
                        "name": "本鯖",
                        "rest_url": "http://127.0.0.1:8212",
                        "admin_password_env": "PAL_MAIN_ADMIN_PASSWORD",
                        "join_info": "example:8211",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_load_config_reads_env_password(config_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(config_files.parent)
    config = load_config(config_files, dotenv_path=None)
    assert config.servers[0].admin_password == "secret-pass"
    assert config.discord.poll_interval_seconds == 15


def test_windows_quoted_backslash_path_is_repaired(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    path = tmp_path / "config.yaml"
    path.write_text(
        'servers:\n  - id: main\n    name: 本鯖\n    rest_url: http://127.0.0.1:8212\n'
        '    admin_password_env: PAL_MAIN_ADMIN_PASSWORD\n    process:\n'
        '      working_directory: "C:\\SteamCMD\\steamapps\\common\\PalServer"\n'
        '      start_command: ["PalServer.exe"]\n'
        '      settings_file: Pal/Saved/Config/WindowsServer/PalWorldSettings.ini\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    assert config.servers[0].process is not None
    assert "SteamCMD" in str(config.servers[0].process.working_directory)
    assert "C:/SteamCMD" in path.read_text(encoding="utf-8")
    assert (tmp_path / "config.yaml.bak").is_file()


def test_soften_windows_yaml_rewrites_drive_path() -> None:
    raw = 'working_directory: "C:\\SteamCMD\\steamapps"\n'
    assert soften_windows_yaml(raw) == 'working_directory: "C:/SteamCMD/steamapps"\n'


@pytest.mark.asyncio
async def test_snapshot_online_via_rest_api() -> None:
    transport = httpx.MockTransport(
        lambda request: _mock_response(request)
    )
    client = PalworldClient("http://127.0.0.1:8212", "secret-pass", transport=transport)
    snapshot = await client.snapshot("main", "本鯖", "join")
    await client.aclose()
    assert snapshot.online
    assert snapshot.info is not None
    assert snapshot.info.name == "Friend World"
    assert snapshot.player_count == 1
    assert snapshot.players[0].display_name == "Alice"


def _mock_response(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/info"):
        return httpx.Response(200, json={"version": "v1.0.3", "servername": "Friend World"})
    if path.endswith("/metrics"):
        return httpx.Response(
            200,
            json={"serverfps": 60, "currentplayernum": 1, "maxplayernum": 8, "serveruptime": 10},
        )
    if path.endswith("/players"):
        return httpx.Response(
            200,
            json={"players": [{"name": "Alice", "userId": "steam_1", "playerId": "p1", "level": 12, "ping": 20}]},
        )
    return httpx.Response(404, json={"error": "missing"})


@pytest.mark.asyncio
async def test_probe_reports_auth_failure() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    client = PalworldClient("http://127.0.0.1:8212", "wrong", transport=transport)
    assert await client.probe() == "auth"
    await client.aclose()


@pytest.mark.asyncio
async def test_snapshot_offline_on_connection_error() -> None:
    respx.get("http://127.0.0.1:8212/v1/api/info").mock(side_effect=httpx.ConnectError("nope"))
    client = PalworldClient("http://127.0.0.1:8212", "secret-pass")
    snapshot = await client.snapshot("main", "本鯖")
    await client.aclose()
    assert not snapshot.online
    assert snapshot.error is not None


@pytest.mark.asyncio
async def test_snapshot_stays_online_when_players_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/players"):
            raise httpx.ReadTimeout("players timeout", request=request)
        return _mock_response(request)

    transport = httpx.MockTransport(handler)
    client = PalworldClient("http://127.0.0.1:8212", "secret-pass", transport=transport)
    snapshot = await client.snapshot("main", "本鯖", "join")
    await client.aclose()
    assert snapshot.online
    assert snapshot.info is not None
    assert snapshot.info.name == "Friend World"
    assert snapshot.players_incomplete
    assert snapshot.players == ()


@pytest.mark.asyncio
async def test_snapshot_info_refused_sets_error_kind() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        try:
            raise ConnectionRefusedError(111, "Connection refused")
        except ConnectionRefusedError as cause:
            err = httpx.ConnectError("connection refused", request=request)
            err.__cause__ = cause
            raise err

    transport = httpx.MockTransport(handler)
    client = PalworldClient("http://127.0.0.1:8212", "secret-pass", transport=transport)
    snapshot = await client.snapshot("main", "本鯖")
    await client.aclose()
    assert not snapshot.online
    assert snapshot.error_kind == "refused"


@pytest.mark.asyncio
async def test_snapshot_info_refused_on_real_connection_refused() -> None:
    client = PalworldClient("http://127.0.0.1:1", "secret-pass", timeout=2.0)
    snapshot = await client.snapshot("main", "本鯖")
    await client.aclose()
    assert not snapshot.online
    assert snapshot.error_kind == "refused"
