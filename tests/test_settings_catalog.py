import re
from pathlib import Path

import pytest

from palworld_discord_bot.settings_catalog import (
    OFFICIAL_KEYS,
    _infer_kind,
    merge_settings_view,
    serialize_field_value,
    serialize_platforms,
    setting_fields,
)
from palworld_discord_bot.settings_ini import PROTECTED_KEYS, write_settings_file

EXPECTED_OFFICIAL_KEYS = frozenset(
    {
        "BaseCampMaxNum",
        "BaseCampMaxNumInGuild",
        "BaseCampWorkerMaxNum",
        "ItemContainerForceMarkDirtyInterval",
        "MaxBuildingLimitNum",
        "PhysicsActiveDropItemMaxNum",
        "ServerReplicatePawnCullDistance",
        "AdminPassword",
        "AllowConnectPlatform",
        "bAllowClientMod",
        "bEnableBuildingPlayerUIdDisplay",
        "bIsShowJoinLeftMessage",
        "bIsUseBackupSaveData",
        "ChatPostLimitPerMinute",
        "CrossplayPlatforms",
        "LogFormatType",
        "PublicIP",
        "PublicPort",
        "RCONEnabled",
        "RCONPort",
        "RESTAPIEnabled",
        "RESTAPIPort",
        "ServerDescription",
        "ServerName",
        "ServerPassword",
        "ServerPlayerMaxNum",
        "AutoResetGuildTimeNoOnlinePlayers",
        "bAllowEnemyCampSpawnNearBaseCamp",
        "bAllowEnhanceStat_Attack",
        "bAllowEnhanceStat_Health",
        "bAllowEnhanceStat_Stamina",
        "bAllowEnhanceStat_Weight",
        "bAllowEnhanceStat_WorkSpeed",
        "bAllowGlobalPalboxExport",
        "bAllowGlobalPalboxImport",
        "bAutoResetGuildNoOnlinePlayers",
        "bBuildAreaLimit",
        "bCharacterRecreateInHardcore",
        "bDisplayPvPItemNumOnWorldMap_BaseCamp",
        "bDisplayPvPItemNumOnWorldMap_Player",
        "bEnableFastTravel",
        "bEnableFastTravelOnlyBaseCamp",
        "bEnableInvaderEnemy",
        "bEnableVoiceChat",
        "bExistPlayerAfterLogout",
        "bHardcore",
        "bInvisibleOtherGuildBaseCampAreaFX",
        "bIsPvP",
        "bIsRandomizerPalLevelRandom",
        "bIsStartLocationSelectByMap",
        "bShowPlayerList",
        "RandomizerSeed",
        "RandomizerType",
        "VoiceChatMaxVolumeDistance",
        "VoiceChatZeroVolumeDistance",
        "AdditionalDropItemNumWhenPlayerKillingInPvPMode",
        "AdditionalDropItemWhenPlayerKillingInPvPMode",
        "bAdditionalDropItemWhenPlayerKillingInPvPMode",
        "BlockRespawnTime",
        "bPalLost",
        "BuildObjectDamageRate",
        "BuildObjectDeteriorationDamageRate",
        "CollectionDropRate",
        "CollectionObjectHpRate",
        "CollectionObjectRespawnSpeedRate",
        "DayTimeSpeedRate",
        "DeathPenalty",
        "DenyTechnologyList",
        "EnemyDropItemRate",
        "EquipmentDurabilityDamageRate",
        "ExpRate",
        "GuildPlayerMaxNum",
        "GuildRejoinCooldownMinutes",
        "ItemCorruptionMultiplier",
        "ItemWeightRate",
        "MonsterFarmActionSpeedRate",
        "NightTimeSpeedRate",
        "PalAutoHPRegeneRate",
        "PalAutoHpRegeneRateInSleep",
        "PalCaptureRate",
        "PalDamageRateAttack",
        "PalDamageRateDefense",
        "PalEggDefaultHatchingTime",
        "PalSpawnNumRate",
        "PalStaminaDecreaceRate",
        "PalStomachDecreaceRate",
        "PlayerAutoHPRegeneRate",
        "PlayerAutoHpRegeneRateInSleep",
        "PlayerDamageRateAttack",
        "PlayerDamageRateDefense",
        "PlayerStaminaDecreaceRate",
        "PlayerStomachDecreaceRate",
        "RespawnPenaltyDurationThreshold",
        "RespawnPenaltyTimeScale",
        "SupplyDropSpan",
    }
)


PALWORLD_10_EXTRA_KEYS = (
    "BuildObjectHpRate",
    "AutoTransferMasterThresholdDays",
    "AutoTransferMasterCheckIntervalSeconds",
    "BuildingNameDisplayCacheTTLSeconds",
    "MaxGuildsPerFrame",
    "PlayerDataPalStorageUpdateCheckTickInterval",
)

_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def test_catalog_contains_palworld_10_extra_keys() -> None:
    by_key = {field["key"]: field for field in setting_fields()}
    for key in PALWORLD_10_EXTRA_KEYS:
        field = by_key[key]
        assert field.get("official", True) is False, key
        assert _JAPANESE_RE.search(field["label"]), key
        assert _JAPANESE_RE.search(field["description"]), key
        assert field["label"] != field["description"], key


def test_catalog_all_labels_and_descriptions_have_japanese() -> None:
    for field in setting_fields():
        assert _JAPANESE_RE.search(field["label"]), field["key"]
        assert _JAPANESE_RE.search(field["description"]), field["key"]


def test_catalog_contains_all_official_keys() -> None:
    catalog_keys = {field["key"] for field in setting_fields() if field.get("official", True)}
    assert EXPECTED_OFFICIAL_KEYS <= catalog_keys
    assert OFFICIAL_KEYS == catalog_keys


def test_catalog_labels_differ_from_descriptions() -> None:
    same = []
    for field in setting_fields():
        assert field["label"] != field["description"], field["key"]
        assert field["label"].strip(), field["key"]
        assert len(field["description"]) > len(field["label"]), field["key"]
        if field["label"] == field["description"]:
            same.append(field["key"])
    assert same == []


def test_merge_settings_view_includes_defaults_for_sparse_ini() -> None:
    fields = merge_settings_view({"ExpRate": "2.000000"})
    by_key = {field["key"]: field for field in fields}
    assert by_key["ExpRate"]["value"] == "2.000000"
    assert by_key["ExpRate"]["present"] is True
    assert by_key["PalCaptureRate"]["value"] == "1.000000"
    assert by_key["PalCaptureRate"]["present"] is False
    assert by_key["AdminPassword"]["value"] == ""
    assert by_key["AdminPassword"]["present"] is False
    assert by_key["AdminPassword"]["protected"] is True


def test_merge_settings_view_appends_unknown_keys_to_other() -> None:
    fields = merge_settings_view({"CustomFlag": "True", "ExpRate": "1.000000"})
    custom = [field for field in fields if field["key"] == "CustomFlag"]
    assert len(custom) == 1
    assert custom[0]["category"] == "その他"
    assert custom[0]["kind"] == "bool"
    assert custom[0]["description"] != "CustomFlag"
    assert _JAPANESE_RE.search(custom[0]["description"])


def test_infer_kind_parenthesized_non_platform_is_text() -> None:
    assert _infer_kind('("PALBOX", "RepairBench")') == "text"
    assert _infer_kind("(Steam,Xbox,PS5,Mac)") == "platforms"
    assert _infer_kind("(Steam,Xbox)") == "platforms"


def test_merge_settings_view_unknown_parenthesized_value_is_text() -> None:
    fields = merge_settings_view({"DenyTechnologyList": '("PALBOX", "RepairBench")'})
    by_key = {field["key"]: field for field in fields}
    assert by_key["DenyTechnologyList"]["kind"] == "text"


def test_death_penalty_has_japanese_option_labels() -> None:
    fields = {field["key"]: field for field in setting_fields()}
    labels = fields["DeathPenalty"]["option_labels"]
    assert labels["None"] == "ロスト無し"
    assert labels["All"] == "全ての装備品と手持ちパル"


def test_serialize_field_value_platforms_fallback() -> None:
    assert serialize_platforms([]) == "(Steam,Xbox,PS5,Mac)"
    assert serialize_field_value({"kind": "platforms"}, []) == "(Steam,Xbox,PS5,Mac)"
    assert serialize_field_value({"kind": "platforms"}, ["Steam", "Xbox"]) == "(Steam,Xbox)"


def test_protected_keys_match_ini() -> None:
    assert PROTECTED_KEYS == {"AdminPassword", "RESTAPIEnabled", "RESTAPIPort"}


@pytest.mark.asyncio
async def test_settings_get_fields_and_bulk_post(tmp_path, monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from palworld_admin.runtime import AdminRuntime
    from palworld_admin.web import create_app
    from palworld_discord_bot.config import load_config
    from palworld_discord_bot.settings_ini import load_settings_file

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
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/api/servers/main/settings")
            payload = await resp.json()
            assert payload["ok"] is True
            fields = {field["key"]: field for field in payload["fields"]}
            assert fields["ExpRate"]["kind"] == "float"
            assert fields["ExpRate"]["min"] == 0.1
            assert fields["ExpRate"]["max"] == 20
            assert fields["ExpRate"]["label"] == "経験値の入手倍率"
            assert "経験値" in fields["ExpRate"]["description"]
            assert "1が標準" in fields["ExpRate"]["description"]
            assert fields["PalCaptureRate"]["present"] is False
            assert payload["all"].get("AdminPassword") != "secret-pass"
            assert fields["DeathPenalty"]["option_labels"]["None"] == "ロスト無し"

            blocked = await client.post(
                "/api/servers/main/settings",
                json={"changes": {"AdminPassword": "hack"}, "restart": False},
            )
            assert blocked.status == 409

            updated = await client.post(
                "/api/servers/main/settings",
                json={
                    "changes": {
                        "ExpRate": "2.000000",
                        "DeathPenalty": "None",
                        "bIsPvP": "True",
                    },
                    "restart": False,
                },
            )
            result = await updated.json()
            assert result["ok"] is True
            assert len(result["updated"]) == 3
            assert result["restarted"] is False
            values = load_settings_file(settings)
            assert values["ExpRate"] == "2.000000"
            assert values["DeathPenalty"] == "None"
            assert values["bIsPvP"] == "True"
    await runtime.close()


@pytest.mark.asyncio
async def test_settings_get_masks_admin_password_in_all(tmp_path, monkeypatch) -> None:
    from aiohttp.test_utils import TestClient, TestServer

    from palworld_admin.runtime import AdminRuntime
    from palworld_admin.web import create_app
    from palworld_discord_bot.config import load_config

    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    settings = tmp_path / "PalWorldSettings.ini"
    write_settings_file(
        settings,
        {"ExpRate": "1.000000", "AdminPassword": "top-secret", "RESTAPIEnabled": "True", "RESTAPIPort": "8212"},
    )
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
    config = load_config(path, dotenv_path=None, require_discord_token=False)
    runtime = AdminRuntime(config)
    app = create_app(runtime)
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/api/servers/main/settings")
            payload = await resp.json()
            assert payload["ok"] is True
            assert payload["all"]["AdminPassword"] == "********"
            assert "top-secret" not in payload["all"].values()
            admin_field = next(field for field in payload["fields"] if field["key"] == "AdminPassword")
            assert admin_field["value"] == "********"
    await runtime.close()


def test_index_html_settings_ui_markers() -> None:
    html = Path("palworld_admin/static/index.html").read_text(encoding="utf-8")
    assert 'type="range"' in html
    assert "DeathPenalty" in html
    assert "経験値" in html
    assert "data-custom-key" not in html
    assert "設定を読み込む" not in html
    assert "settings-panel" in html
    assert "app.css?v=11" in html
    assert "!entry.settingsLoaded" in html
    assert "loadSettingsPanel(server.id, entry)" in html
    assert 'value="${esc(field.value)}"' in html
