from pathlib import Path

import pytest

from palworld_discord_bot.updates import (
    ManifestInfo,
    UpdateNoticeStore,
    evaluate_update,
    find_appmanifest,
    inspect_update,
    parse_appmanifest,
    parse_steamcmd_info,
    read_manifest,
)


SAMPLE_ACF = """
"AppState"
{
	"appid"		"2394010"
	"Universe"		"1"
	"name"		"Palworld Dedicated Server"
	"StateFlags"		"4"
	"installdir"		"PalServer"
	"LastUpdated"		"1720000000"
	"buildid"		"100"
	"LastOwner"		"0"
	"UpdateResult"		"0"
	"TargetBuildID"		"200"
}
"""


def test_parse_appmanifest_reads_build_ids() -> None:
    values = parse_appmanifest(SAMPLE_ACF)
    assert values["buildid"] == "100"
    assert values["TargetBuildID"] == "200"


def test_find_appmanifest_from_common_folder(tmp_path: Path) -> None:
    steamapps = tmp_path / "steamapps"
    common = steamapps / "common" / "PalServer"
    common.mkdir(parents=True)
    manifest = steamapps / "appmanifest_2394010.acf"
    manifest.write_text(SAMPLE_ACF, encoding="utf-8")
    found = find_appmanifest(common)
    assert found == manifest
    info = read_manifest(found)
    assert info is not None
    assert info.buildid == "100"
    assert info.target_buildid == "200"


def test_evaluate_update_detects_newer_steam_build() -> None:
    manifest = ManifestInfo(
        path=Path("appmanifest_2394010.acf"),
        buildid="100",
        target_buildid="100",
        last_updated=None,
    )
    without_install = evaluate_update(running_version="v1.0.3", latest_buildid="200")
    assert without_install.update_available is False
    available = evaluate_update(
        running_version="v1.0.3",
        manifest=manifest,
        latest_buildid="200",
    )
    assert available.update_available is True
    assert "更新あり" in available.summary
    assert available.hint is not None
    assert "管理画面" in available.hint
    current = evaluate_update(manifest=manifest, latest_buildid="100")
    assert current.update_available is False


def test_evaluate_update_uses_target_buildid() -> None:
    manifest = ManifestInfo(
        path=Path("appmanifest_2394010.acf"),
        buildid="100",
        target_buildid="150",
        last_updated=None,
    )
    status = evaluate_update(manifest=manifest, latest_buildid=None)
    assert status.update_available is True


def test_parse_steamcmd_info_public_branch() -> None:
    payload = {
        "data": {
            "2394010": {
                "depots": {"branches": {"public": {"buildid": "20481234"}}}
            }
        }
    }
    assert parse_steamcmd_info(payload) == "20481234"


def test_update_notice_store_notifies_once(tmp_path: Path) -> None:
    store = UpdateNoticeStore(tmp_path / "game_updates.json")
    assert store.should_notify("main", "200") is True
    store.mark("main", notified="200", running_version="v1")
    assert store.should_notify("main", "200") is False
    assert store.should_notify("main", "201") is True
    assert store.last_running_version("main") == "v1"


@pytest.mark.asyncio
async def test_inspect_update_uses_local_manifest_and_latest(tmp_path: Path, monkeypatch) -> None:
    steamapps = tmp_path / "steamapps"
    pal = steamapps / "common" / "PalServer"
    pal.mkdir(parents=True)
    (steamapps / "appmanifest_2394010.acf").write_text(SAMPLE_ACF, encoding="utf-8")

    async def latest() -> str:
        return "300"

    monkeypatch.setattr("palworld_discord_bot.updates.fetch_latest_buildid", latest)
    status = await inspect_update(pal, running_version="v1.0.3")
    assert status.installed_buildid == "100"
    assert status.latest_buildid == "300"
    assert status.update_available is True
    assert status.running_version == "v1.0.3"
