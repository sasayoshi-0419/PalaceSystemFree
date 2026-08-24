from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from palworld_admin.setup_app import create_setup_app
from palworld_admin.web import STATIC_DIR
from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.detect import describe_palserver
from palworld_discord_bot.setup import apply_setup_from_mapping


def _pal(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "PalServer.exe").write_bytes(b"mz")
    return folder


@pytest.mark.asyncio
async def test_setup_app_detect_and_save(tmp_path: Path) -> None:
    pal = _pal(tmp_path / "PalServer")
    state = {"code": 1}
    app = create_setup_app(tmp_path, tmp_path / "config.yaml", state)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            page = await client.get("/setup.html")
            assert page.status == 200
            body = await page.text()
            assert "初回セットアップ" in body
            assert "pal-choices" in body
            assert "自動では使いません" in body
            assert "探しています" in body
            assert "Discord Developer Portal" in body
            assert "discord.com/developers/applications" in body
            assert "開発者モード" in body
            assert "guild_id" in body
            assert "applications.commands" in body
            assert "URL Generator" in body
            assert "作る必要はありません" in body
            assert "Discord からゲームサーバーの起動・停止はできません" in body
            css = await client.get("/app.css")
            assert css.status == 200
            detect = await client.get("/api/setup/detect")
            payload = await detect.json()
            assert payload["ok"] is True
            assert payload["mode"] == "setup"
            assert "candidates" in payload
            saved = await client.post(
                "/api/setup",
                json={
                    "palserver": str(pal),
                    "name": "本鯖",
                    "password": "secret-pass",
                    "game_port": "8211",
                    "rest_port": "8212",
                    "discord": False,
                },
            )
            result = await saved.json()
            assert saved.status == 200
            assert result["ok"] is True
            assert state["code"] == 0
            assert (tmp_path / "config.yaml").is_file()
            bad = await client.post("/api/setup", json={"palserver": "", "password": ""})
            assert bad.status == 400


@pytest.mark.asyncio
async def test_setup_detect_lists_multiple_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = _pal(tmp_path / "SteamCMD" / "steamapps" / "common" / "PalServer")
    two = _pal(tmp_path / "Steam" / "steamapps" / "common" / "Palworld Dedicated Server")
    monkeypatch.setattr(
        "palworld_admin.setup_app.list_palserver_candidates",
        lambda extra=None: [describe_palserver(one), describe_palserver(two)],
    )
    app = create_setup_app(tmp_path, tmp_path / "config.yaml", {"code": 1})
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            detect = await client.get("/api/setup/detect")
            payload = await detect.json()
            assert payload["must_choose"] is True
            assert len(payload["candidates"]) == 2
            assert payload["candidates"][0]["kind"] == "steamcmd"
            assert payload["candidates"][1]["kind"] == "steam"


@pytest.mark.asyncio
async def test_setup_choose_mode_retargets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _pal(tmp_path / "old")
    new = _pal(tmp_path / "new")
    apply_setup_from_mapping(
        tmp_path,
        tmp_path / "config.yaml",
        {
            "palserver": str(old),
            "name": "本鯖",
            "password": "secret-pass",
            "game_port": "8211",
            "rest_port": "8212",
            "discord": False,
        },
    )
    old.rename(tmp_path / "old-gone")
    monkeypatch.setattr(
        "palworld_admin.setup_app.list_palserver_candidates",
        lambda extra=None: [describe_palserver(new)],
    )
    state = {"code": 1}
    app = create_setup_app(tmp_path, tmp_path / "config.yaml", state, mode="choose")
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            detect = await client.get("/api/setup/detect")
            payload = await detect.json()
            assert payload["mode"] == "choose"
            empty = await client.post("/api/setup", json={"palserver": ""})
            assert empty.status == 400
            saved = await client.post("/api/setup", json={"palserver": str(new)})
            result = await saved.json()
            assert saved.status == 200
            assert result["ok"] is True
            assert state["code"] == 0
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "new" in text.replace("\\", "/")


def test_setup_html_does_not_auto_pick_first_candidate() -> None:
    text = (STATIC_DIR / "setup.html").read_text(encoding="utf-8")
    assert "pal-choices" in text
    assert "data.palservers[0]" not in text
    assert "candidates.length === 1" in text
    assert "location.replace" in text
    assert "管理画面を開いています" in text
    assert "!result.pending" in text
    assert "Discord Developer Portal" in text
    assert "開発者モード" in text
    assert "guild_id" in text
    assert "applications.commands" in text
    assert "URL Generator" in text
    assert "作る必要はありません" in text
    assert "Discord からゲームサーバーの起動・停止はできません" in text


def test_setup_html_has_join_info_and_unofficial() -> None:
    text = (STATIC_DIR / "setup.html").read_text(encoding="utf-8")
    assert "非公式です。Pocketpair / Palworld とは無関係です。" in text
    assert 'id="join-info"' in text
    assert 'id="step-2"' in text
    join_idx = text.index('id="join-info"')
    step2_idx = text.index('id="step-2"')
    assert join_idx > step2_idx
    assert 'id="restart-enabled"' in text
    assert "REST API 用の管理パスワード" in text
    assert '<details class="guide" open>' not in text
    assert 'type="password"' in text
    assert 'id="token"' in text


@pytest.mark.asyncio
async def test_setup_post_join_info(tmp_path: Path) -> None:
    pal = _pal(tmp_path / "PalServer")
    app = create_setup_app(tmp_path, tmp_path / "config.yaml", {"code": 1})
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            saved = await client.post(
                "/api/setup",
                json={
                    "palserver": str(pal),
                    "name": "本鯖",
                    "password": "secret-pass",
                    "join_info": "203.0.113.10:8211",
                    "restart_enabled": True,
                    "restart_time": "06:00",
                    "discord": False,
                },
            )
            assert saved.status == 200
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].join_info == "203.0.113.10:8211"
    assert config.servers[0].restart_schedule is not None
    assert config.servers[0].restart_schedule.time == "06:00"


@pytest.mark.asyncio
async def test_setup_post_without_join_info(tmp_path: Path) -> None:
    pal = _pal(tmp_path / "PalServer")
    app = create_setup_app(tmp_path, tmp_path / "config.yaml", {"code": 1})
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            saved = await client.post(
                "/api/setup",
                json={
                    "palserver": str(pal),
                    "name": "本鯖",
                    "password": "secret-pass",
                    "discord": False,
                },
            )
            assert saved.status == 200
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].join_info == ""
