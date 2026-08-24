import pytest


@pytest.fixture(autouse=True)
def _skip_steam_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_latest() -> None:
        return None

    def _no_steamcmd_download(*_args, **_kwargs):
        raise RuntimeError("tests must not download SteamCMD from Valve")

    monkeypatch.setattr("palworld_discord_bot.updates.fetch_latest_buildid", _no_latest)
    monkeypatch.setattr(
        "palworld_discord_bot.steamcmd.download_steamcmd_archive",
        _no_steamcmd_download,
    )
