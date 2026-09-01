from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from palworld_admin.runtime import AdminRuntime
from palworld_admin.web import create_app
from palworld_admin.worldmap import (
    _copy_sav_for_read,
    extract_bases_from_world_save,
    get_bases_for_operator,
    map_player_to_dict,
    parse_map_players,
    world_to_paldex,
)
from palworld_discord_bot.config import load_config
from palworld_discord_bot.settings_ini import write_settings_file


def _admin_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    return path


def test_world_to_paldex_fixture() -> None:
    paldex_x, paldex_y = world_to_paldex(-167230, 96430)
    assert paldex_y == pytest.approx(-94, abs=1)
    assert paldex_x == pytest.approx(-134, abs=10)


def test_parse_map_players_keeps_locations_drops_ip() -> None:
    players = parse_map_players(
        {
            "players": [
                {
                    "name": "Alice",
                    "playerId": "p1",
                    "userId": "steam_1",
                    "level": 12,
                    "ip": "203.0.113.9",
                    "location_x": -167230,
                    "location_y": 96430,
                }
            ]
        }
    )
    assert len(players) == 1
    assert players[0].name == "Alice"
    assert players[0].level == 12
    assert players[0].user_id == "steam_1"
    assert players[0].player_id == "p1"
    assert players[0].left > 0
    assert players[0].top > 0
    dumped = {
        "name": players[0].name,
        "level": players[0].level,
        "user_id": players[0].user_id,
        "player_id": players[0].player_id,
        "left": players[0].left,
        "top": players[0].top,
    }
    assert "ip" not in dumped


def test_parse_map_players_without_location() -> None:
    players = parse_map_players(
        {
            "players": [
                {
                    "name": "Bob",
                    "playerId": "p2",
                    "userId": "steam_2",
                    "level": 5,
                    "ip": "203.0.113.9",
                }
            ]
        }
    )
    assert len(players) == 1
    assert players[0].name == "Bob"
    assert players[0].left is None
    assert players[0].top is None
    dumped = map_player_to_dict(players[0])
    assert "left" not in dumped
    assert "top" not in dumped
    assert "ip" not in dumped


def test_copy_sav_for_read_keeps_single_cache_file(tmp_path: Path) -> None:
    data_dir = tmp_path / ".data"
    server_id = "main"
    source = tmp_path / "Level.sav"
    source.write_bytes(b"level sav bytes")
    cache_dir = data_dir / "worldmap_cache"
    cache_dir.mkdir(parents=True)
    stale = cache_dir / f"{server_id}-1234567890.sav"
    stale.write_bytes(b"stale copy")

    dest = _copy_sav_for_read(source, data_dir, server_id)
    assert dest == cache_dir / f"{server_id}.sav"
    assert dest.is_file()
    assert not stale.exists()
    sav_files = list(cache_dir.glob("*.sav"))
    assert sav_files == [dest]

    # Same mtime should not create another file
    again = _copy_sav_for_read(source, data_dir, server_id)
    assert again == dest
    assert list(cache_dir.glob("*.sav")) == [dest]


def test_extract_bases_from_synthetic_world_save() -> None:
    group_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    base_id = "11111111-2222-3333-4444-555555555555"
    world_save = {
        "GroupSaveDataMap": {
            "value": [
                {
                    "key": group_id,
                    "value": {
                        "GroupType": {"value": {"value": "EPalGroupType::Guild"}},
                        "RawData": {
                            "value": {
                                "group_id": group_id,
                                "guild_name": "テストギルド",
                                "base_ids": [base_id],
                            }
                        },
                    },
                }
            ]
        },
        "BaseCampSaveData": {
            "value": [
                {
                    "key": base_id,
                    "value": {
                        "RawData": {
                            "value": {
                                "id": base_id,
                                "transform": {
                                    "translation": {"x": -167230.0, "y": 96430.0, "z": 0.0}
                                },
                                "group_id_belong_to": group_id,
                            }
                        }
                    },
                }
            ]
        },
    }
    bases = extract_bases_from_world_save(world_save)
    assert len(bases) == 1
    assert bases[0].id == base_id
    assert bases[0].guild == "テストギルド"
    assert bases[0].left > 0
    assert bases[0].top > 0


def test_extract_bases_guild_via_base_ids_without_group_id() -> None:
    group_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    base_id = "11111111-2222-3333-4444-555555555555"
    world_save = {
        "GroupSaveDataMap": {
            "value": [
                {
                    "key": group_id,
                    "value": {
                        "GroupType": {"value": {"value": "EPalGroupType::Guild"}},
                        "RawData": {
                            "value": {
                                "group_id": group_id,
                                "guild_name": "base_ids ギルド",
                                "base_ids": [base_id],
                            }
                        },
                    },
                }
            ]
        },
        "BaseCampSaveData": {
            "value": [
                {
                    "key": base_id,
                    "value": {
                        "RawData": {
                            "value": {
                                "id": base_id,
                                "transform": {
                                    "translation": {"x": -167230.0, "y": 96430.0, "z": 0.0}
                                },
                            }
                        }
                    },
                }
            ]
        },
    }
    bases = extract_bases_from_world_save(world_save)
    assert len(bases) == 1
    assert bases[0].guild == "base_ids ギルド"


def test_missing_sav_sets_bases_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    operator = runtime.operator("main")
    bases, error = get_bases_for_operator(operator)
    assert bases == []
    assert error is not None
    assert "Level.sav" in error


@pytest.mark.asyncio
async def test_map_api_returns_locations_without_ip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    operator = runtime.operator("main")
    operator.probe = AsyncMock(return_value="online")
    operator.client.players_payload = AsyncMock(
        return_value={
            "players": [
                {
                    "name": "Alice",
                    "playerId": "p1",
                    "userId": "steam_1",
                    "level": 12,
                    "ip": "203.0.113.9",
                    "location_x": -167230,
                    "location_y": 96430,
                }
            ]
        }
    )
    operator.client.info = AsyncMock(
        return_value=type(
            "Info",
            (),
            {"world_guid": "", "name": "", "version": "", "description": ""},
        )()
    )

    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/api/servers/main/map")
            body_text = await resp.text()
            payload = await resp.json()
            assert resp.status == 200
            assert payload["ok"] is True
            assert payload["status"] == "online"
            assert len(payload["players"]) == 1
            assert "left" in payload["players"][0]
            assert "top" in payload["players"][0]
            assert "ip" not in body_text.lower()
            assert payload["bases_error"] is not None
    await runtime.close()


@pytest.mark.asyncio
async def test_map_api_unknown_server_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/api/servers/missing/map")
            assert resp.status == 404
    await runtime.close()


def test_index_html_map_svg_silhouette() -> None:
    html = Path("palworld_admin/static/index.html").read_text(encoding="utf-8")
    assert 'viewBox="0 0 100 100"' in html
    stage_start = html.index('class="worldmap-stage"')
    stage_end = html.index("</div>", html.index("worldmap-markers", stage_start))
    stage_block = html[stage_start:stage_end]
    assert "<svg" in stage_block
    assert "worldmap-bg" not in html
    assert "worldmap-main" in html
    land_shapes = stage_block.count('class="worldmap-land')
    assert land_shapes >= 3


def test_index_html_map_has_no_external_map_assets() -> None:
    html = Path("palworld_admin/static/index.html").read_text(encoding="utf-8")
    static_dir = Path("palworld_admin/static")
    assert "http://" not in html[html.index("worldmap-stage"):html.index("worldmap-side")]
    assert "https://" not in html[html.index("worldmap-stage"):html.index("worldmap-side")]
    for pattern in ("*map*.png", "*map*.jpg", "*map*.webp", "*worldmap*.png", "*worldmap*.jpg", "*worldmap*.webp"):
        assert not list(static_dir.glob(pattern)), pattern


@pytest.mark.asyncio
async def test_index_html_has_map_panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _admin_config(tmp_path, monkeypatch)
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            index = await client.get("/")
            body = await index.text()
            assert "data-nav=\"map\"" in body
            assert "panel-map" in body
            assert "マップ" in body
    await runtime.close()
