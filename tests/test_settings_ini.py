SAMPLE_INI = """[/Script/Pal.PalGameWorldSettings]
OptionSettings=(Difficulty=None,DayTimeSpeedRate=1.000000,ExpRate=1.000000,DeathPenalty=Item,ServerName="Friend World",ServerPlayerMaxNum=8,CrossplayPlatforms=(Steam,Xbox),AdminPassword="secret",RESTAPIEnabled=True,RESTAPIPort=8212,bIsPvP=False)
"""

import pytest

from palworld_discord_bot.settings_ini import (
    SettingsError,
    bootstrap_rest_api,
    load_settings_file,
    parse_option_settings,
    set_setting,
    set_settings,
    write_settings_file,
)


def test_parse_nested_and_quoted_values() -> None:
    body = (
        'Difficulty=None,ExpRate=1.000000,ServerName="A, B",'
        "CrossplayPlatforms=(Steam,Xbox),bIsPvP=False"
    )
    values = parse_option_settings(body)
    assert values["ServerName"] == "A, B"
    assert values["CrossplayPlatforms"] == "(Steam,Xbox)"
    assert values["bIsPvP"] == "False"
    assert values["ExpRate"] == "1.000000"


def test_roundtrip_preserves_keys(tmp_path) -> None:
    path = tmp_path / "PalWorldSettings.ini"
    path.write_text(SAMPLE_INI, encoding="utf-8")
    values = load_settings_file(path)
    values = set_setting(values, "ExpRate", "2.000000")
    values = set_setting(values, "ServerName", "新しい名前")
    write_settings_file(path, values)
    reloaded = load_settings_file(path)
    assert reloaded["ExpRate"] == "2.000000"
    assert reloaded["ServerName"] == "新しい名前"
    assert reloaded["CrossplayPlatforms"] == "(Steam,Xbox)"
    assert reloaded["RESTAPIPort"] == "8212"
    assert path.with_suffix(".ini.bak").is_file()


def test_protected_keys_cannot_change() -> None:
    values = {"AdminPassword": "x", "ExpRate": "1"}
    try:
        set_setting(values, "AdminPassword", "y")
        raise AssertionError("expected SettingsError")
    except SettingsError as exc:
        assert "AdminPassword" in str(exc)


def test_set_settings_applies_multiple_keys() -> None:
    values = {"ExpRate": "1.000000", "ServerName": "Old"}
    updated = set_settings(values, {"ExpRate": "2.000000", "bIsPvP": "True"})
    assert updated["ExpRate"] == "2.000000"
    assert updated["bIsPvP"] == "True"
    assert updated["ServerName"] == "Old"


def test_set_settings_rejects_protected_keys() -> None:
    values = {"RESTAPIEnabled": "True"}
    with pytest.raises(SettingsError, match="RESTAPIEnabled"):
        set_settings(values, {"RESTAPIEnabled": "False"})


def test_bootstrap_rest_api_sets_protected_keys(tmp_path) -> None:
    path = tmp_path / "PalWorldSettings.ini"
    write_settings_file(
        path,
        {
            "ExpRate": "1.000000",
            "RESTAPIEnabled": "False",
            "RESTAPIPort": "1",
            "AdminPassword": "old",
        },
    )
    bootstrap_rest_api(path, "new-pass", 8212)
    values = load_settings_file(path)
    assert values["RESTAPIEnabled"] == "True"
    assert values["RESTAPIPort"] == "8212"
    assert values["AdminPassword"] == "new-pass"
