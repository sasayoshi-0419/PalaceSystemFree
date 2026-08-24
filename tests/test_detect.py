from pathlib import Path

from palworld_discord_bot.detect import (
    DRIVE_CDROM,
    DRIVE_FIXED,
    DRIVE_REMOTE,
    describe_palserver,
    find_palserver_directories,
    has_server_binary,
    list_palserver_candidates,
    needs_palserver_picker,
    palserver_kind,
    palserver_label,
    path_is_safe_to_probe,
    reset_drive_probe_cache,
    windows_drive_type,
)


def _pal(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "PalServer.exe").write_bytes(b"mz")
    return folder


def test_path_is_safe_to_probe_skips_optical_and_remote(monkeypatch, tmp_path: Path) -> None:
    reset_drive_probe_cache()
    monkeypatch.setattr("palworld_discord_bot.detect.windows_drive_type", lambda _path: DRIVE_CDROM)
    assert path_is_safe_to_probe(Path("D:/SteamCMD")) is False
    reset_drive_probe_cache()
    monkeypatch.setattr("palworld_discord_bot.detect.windows_drive_type", lambda _path: DRIVE_REMOTE)
    assert path_is_safe_to_probe(Path("Z:/SteamCMD")) is False
    reset_drive_probe_cache()
    monkeypatch.setattr("palworld_discord_bot.detect.windows_drive_type", lambda _path: DRIVE_FIXED)
    assert path_is_safe_to_probe(Path("D:/SteamCMD")) is True
    assert windows_drive_type(tmp_path) is None


def test_find_palserver_skips_unsafe_roots(tmp_path: Path, monkeypatch) -> None:
    reset_drive_probe_cache()
    cdrom = tmp_path / "cdrom" / "SteamCMD"
    pal = _pal(cdrom / "PalServer")

    def fake_safe(path: Path) -> bool:
        return "cdrom" not in str(path).replace("\\", "/").lower()

    monkeypatch.setattr("palworld_discord_bot.detect.path_is_safe_to_probe", fake_safe)
    monkeypatch.setattr("palworld_discord_bot.detect._candidate_roots", lambda: [cdrom])
    assert find_palserver_directories() == []
    found = find_palserver_directories(extra=pal)
    assert pal.resolve() in [item.resolve() for item in found]


def test_detect_finds_extra_palserver(tmp_path: Path) -> None:
    _pal(tmp_path)
    found = find_palserver_directories(extra=tmp_path)
    assert tmp_path.resolve() in [item.resolve() for item in found]


def test_palserver_labels_distinguish_steamcmd_and_steam(tmp_path: Path) -> None:
    steamcmd = _pal(tmp_path / "SteamCMD" / "steamapps" / "common" / "PalServer")
    steam = _pal(tmp_path / "Steam" / "steamapps" / "common" / "Palworld Dedicated Server")
    other = _pal(tmp_path / "servers" / "PalServer")
    assert palserver_kind(steamcmd) == "steamcmd"
    assert palserver_kind(steam) == "steam"
    assert palserver_kind(other) == "folder"
    assert "SteamCMD" in palserver_label(steamcmd)
    assert "Steam" in palserver_label(steam)
    saved = steamcmd / "Pal" / "Saved" / "SaveGames"
    saved.mkdir(parents=True)
    (saved / "slot").write_text("x", encoding="utf-8")
    info = describe_palserver(steamcmd)
    assert info["has_saves"] is True
    assert info["has_binary"] is True
    assert info["path"].endswith("PalServer")


def test_list_candidates_includes_extra(tmp_path: Path) -> None:
    pal = _pal(tmp_path / "PalServer")
    items = list_palserver_candidates(extra=pal)
    paths = [item["path"] for item in items]
    assert pal.resolve().as_posix() in paths


def test_needs_palserver_picker(tmp_path: Path) -> None:
    one = _pal(tmp_path / "one")
    two = _pal(tmp_path / "two")
    missing = tmp_path / "missing"
    assert needs_palserver_picker(one, found=[one, two]) is False
    assert needs_palserver_picker(missing, found=[one, two]) is True
    assert needs_palserver_picker(missing, found=[one]) is True
    assert needs_palserver_picker(missing, found=[]) is False
    assert needs_palserver_picker(None, found=[one, two]) is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert has_server_binary(empty) is False
    assert needs_palserver_picker(empty, found=[one]) is True
