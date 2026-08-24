from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from palworld_discord_bot.steamcmd import (
    SteamCmdError,
    describe_steamcmd,
    extract_steamcmd_archive,
    find_steamcmd,
    install_steamcmd,
    looks_like_steam_client_install,
    save_stored_path,
    self_update_arguments,
    update_arguments,
    update_palworld_server,
)


def _write_zip(path: Path, name: str = "steamcmd.exe") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr(name, b"fake-steamcmd")
    return path


def _write_tgz(path: Path, name: str = "steamcmd") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"fake-steamcmd"
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return path


def test_update_arguments_include_anonymous_app_update(tmp_path: Path) -> None:
    args = update_arguments(tmp_path / "PalServer")
    assert "+login" in args
    assert "anonymous" in args
    assert "+app_update" in args
    assert "2394010" in args
    assert "validate" in args
    assert "+quit" in args
    assert "+quit" in self_update_arguments()


def test_find_steamcmd_skips_unreadable_drive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "SteamCMD" / "steamcmd.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    monkeypatch.setattr("palworld_discord_bot.steamcmd.path_is_safe_to_probe", lambda _path: False)
    assert find_steamcmd(exe) is None


def test_find_steamcmd_uses_stored_path(tmp_path: Path) -> None:
    exe = tmp_path / "steamcmd"
    exe.write_bytes(b"x")
    save_stored_path(tmp_path, exe)
    found = find_steamcmd(data_dir=tmp_path)
    assert found == exe
    status = describe_steamcmd(tmp_path)
    assert status["found"] is True
    assert status["path"] == exe.as_posix()


def test_looks_like_steam_client_install(tmp_path: Path) -> None:
    steam = tmp_path / "Steam"
    pal = steam / "steamapps" / "common" / "PalServer"
    pal.mkdir(parents=True)
    (steam / "steam.exe").write_bytes(b"x")
    assert looks_like_steam_client_install(pal) is True
    cmd = tmp_path / "SteamCMD" / "steamapps" / "common" / "PalServer"
    cmd.mkdir(parents=True)
    assert looks_like_steam_client_install(cmd) is False


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../evil", b"nope")
    with pytest.raises(SteamCmdError, match="不正"):
        extract_steamcmd_archive(archive, tmp_path / "out")


def test_extract_zip_finds_binary(tmp_path: Path) -> None:
    archive = _write_zip(tmp_path / "steamcmd.zip")
    found = extract_steamcmd_archive(archive, tmp_path / "out")
    assert found.name == "steamcmd.exe"


@pytest.mark.asyncio
async def test_install_steamcmd_downloads_and_self_updates(tmp_path: Path) -> None:
    dest = tmp_path / "SteamCMD"
    downloaded: list[Path] = []

    def fake_download(archive: Path, *, url: str | None = None) -> Path:
        downloaded.append(archive)
        if archive.name.endswith(".zip"):
            return _write_zip(archive)
        return _write_tgz(archive)

    runs: list[tuple[Path, tuple[str, ...]]] = []

    async def fake_runner(executable: Path, extra_args, *, progress=None) -> int:
        runs.append((executable, tuple(extra_args)))
        if progress:
            await progress("SteamCMD: fake")
        return 7 if len(runs) == 1 else 0

    path = await install_steamcmd(
        dest,
        data_dir=tmp_path / "data",
        download=fake_download,
        runner=fake_runner,
    )
    assert downloaded
    assert path.is_file()
    assert len(runs) == 2
    again = await install_steamcmd(
        dest,
        data_dir=tmp_path / "data",
        download=fake_download,
        runner=fake_runner,
    )
    assert again == path
    assert len(runs) == 2


@pytest.mark.asyncio
async def test_install_steamcmd_rejects_palserver_folder(tmp_path: Path) -> None:
    (tmp_path / "PalServer.exe").write_bytes(b"x")
    with pytest.raises(SteamCmdError, match="PalServer"):
        await install_steamcmd(tmp_path, data_dir=tmp_path / "data")


@pytest.mark.asyncio
async def test_update_palworld_server_requires_zero_exit(tmp_path: Path) -> None:
    exe = tmp_path / "steamcmd"
    exe.write_bytes(b"x")

    async def fail_runner(executable: Path, extra_args, *, progress=None) -> int:
        return 8

    with pytest.raises(SteamCmdError, match="exit=8"):
        await update_palworld_server(exe, tmp_path / "PalServer", runner=fail_runner)


@pytest.mark.asyncio
async def test_run_steamcmd_reads_output(tmp_path: Path) -> None:
    from palworld_discord_bot.steamcmd import run_steamcmd

    script = tmp_path / "steamcmd"
    script.write_text(
        "#!/usr/bin/env python3\nimport sys\nprint('hello-steamcmd')\nsys.exit(0)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    lines: list[str] = []

    async def progress(message: str) -> None:
        lines.append(message)

    code = await run_steamcmd(script, ["+quit"], progress=progress)
    assert code == 0
    assert any("hello-steamcmd" in line for line in lines)
