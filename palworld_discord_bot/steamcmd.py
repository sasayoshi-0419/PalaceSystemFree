from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any

import httpx

from palworld_discord_bot.detect import path_is_safe_to_probe
from palworld_discord_bot.updates import PALWORLD_DS_APP_ID

logger = logging.getLogger(__name__)

_STEAMCMD_LOCK = asyncio.Lock()

STEAMCMD_ZIP_WINDOWS = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"
STEAMCMD_TGZ_LINUX = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

Progress = Callable[[str], Awaitable[None]]


class SteamCmdError(RuntimeError):
    """Raised when SteamCMD cannot be installed or run."""


def default_install_directory() -> Path:
    if os.name == "nt":
        return Path("C:/SteamCMD")
    return Path.home() / "SteamCMD"


def stored_path_file(data_dir: Path) -> Path:
    return data_dir / "steamcmd.json"


def load_stored_path(data_dir: Path | None) -> Path | None:
    if data_dir is None:
        return None
    path = stored_path_file(data_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    text = str((raw or {}).get("path") or "").strip()
    if not text:
        return None
    candidate = Path(text)
    return candidate if _is_steamcmd_binary(candidate) else None


def save_stored_path(data_dir: Path | None, executable: Path) -> None:
    if data_dir is None:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    stored_path_file(data_dir).write_text(
        json.dumps({"path": executable.as_posix()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_steamcmd_binary(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    return name in {"steamcmd.exe", "steamcmd.sh", "steamcmd"}


def find_steamcmd(
    *hints: Path | None,
    data_dir: Path | None = None,
) -> Path | None:
    stored = load_stored_path(data_dir)
    names = ("steamcmd.exe", "steamcmd.sh", "steamcmd")
    candidates: list[Path] = []
    if stored is not None:
        candidates.append(stored)
    for hint in hints:
        if hint is None:
            continue
        current = Path(hint).expanduser()
        if _is_steamcmd_binary(current):
            candidates.append(current)
            continue
        if current.suffix.lower() in {".exe", ".sh"}:
            current = current.parent
        for _ in range(7):
            for name in names:
                candidates.append(current / name)
            if current.parent == current:
                break
            current = current.parent
    home = Path.home()
    candidates.extend(
        [
            Path("C:/SteamCMD/steamcmd.exe"),
            Path("D:/SteamCMD/steamcmd.exe"),
            Path("E:/SteamCMD/steamcmd.exe"),
            home / "SteamCMD" / "steamcmd.exe",
            home / "SteamCMD" / "steamcmd.sh",
            home / "steamcmd" / "steamcmd.sh",
            Path("/usr/games/steamcmd"),
        ]
    )
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if not path_is_safe_to_probe(candidate):
            continue
        if _is_steamcmd_binary(candidate):
            return candidate
    return None


def describe_steamcmd(data_dir: Path | None, *hints: Path | None) -> dict[str, Any]:
    found = find_steamcmd(*hints, data_dir=data_dir)
    stored = load_stored_path(data_dir)
    client_like = False
    for hint in hints:
        if hint is None:
            continue
        if looks_like_steam_client_install(Path(hint)):
            client_like = True
            break
    return {
        "found": found is not None,
        "path": found.as_posix() if found else None,
        "stored": stored.as_posix() if stored else None,
        "default_directory": default_install_directory().as_posix(),
        "looks_like_steam_client": client_like,
    }


def looks_like_steam_client_install(working_directory: Path) -> bool:
    text = str(working_directory).replace("\\", "/").lower()
    if "steamapps/common/" not in text:
        return False
    if "steamcmd" in text:
        return False
    current = working_directory
    for _ in range(6):
        if (current / "steam.exe").is_file() or (current / "steam.sh").is_file():
            return True
        if current.parent == current:
            break
        current = current.parent
    return False


def palserver_install_dir(working_directory: Path) -> Path:
    return working_directory.expanduser()


def update_arguments(install_dir: Path, *, app_id: int = PALWORLD_DS_APP_ID) -> list[str]:
    return [
        "+@ShutdownOnFailedCommand",
        "1",
        "+@NoPromptForPassword",
        "1",
        "+force_install_dir",
        str(install_dir),
        "+login",
        "anonymous",
        "+app_update",
        str(app_id),
        "validate",
        "+quit",
    ]


def self_update_arguments() -> list[str]:
    return ["+@ShutdownOnFailedCommand", "1", "+@NoPromptForPassword", "1", "+quit"]


def _archive_url() -> str:
    return STEAMCMD_ZIP_WINDOWS if os.name == "nt" else STEAMCMD_TGZ_LINUX


def download_steamcmd_archive(dest: Path, *, url: str | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    target = url or _archive_url()
    try:
        with httpx.Client(follow_redirects=True, timeout=120.0) as client:
            with client.stream("GET", target) as response:
                response.raise_for_status()
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
    except httpx.HTTPError as exc:
        raise SteamCmdError(
            f"Valve 公式の SteamCMD をダウンロードできませんでした: {exc}"
        ) from exc
    return dest


def _ensure_extracted_under(directory: Path, member_name: str) -> None:
    dest = (directory / member_name).resolve()
    try:
        dest.relative_to(directory.resolve())
    except ValueError as exc:
        raise SteamCmdError("不正なアーカイブです") from exc


def _binary_in_directory(directory: Path) -> Path | None:
    names = ("steamcmd.exe", "steamcmd.sh", "steamcmd")
    for name in names:
        candidate = directory / name
        if _is_steamcmd_binary(candidate):
            return candidate
    if not directory.is_dir():
        return None
    try:
        children = list(directory.iterdir())
    except OSError:
        return None
    for child in children:
        if child.is_dir():
            found = _binary_in_directory(child)
            if found is not None:
                return found
        elif _is_steamcmd_binary(child):
            return child
    return None


def extract_steamcmd_archive(archive: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zipped:
                for info in zipped.infolist():
                    _ensure_extracted_under(directory, info.filename)
                zipped.extractall(directory)
        elif name.endswith(".tar.gz") or name.endswith(".tgz"):
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar.getmembers():
                    _ensure_extracted_under(directory, member.name)
                kwargs: dict[str, Any] = {}
                if sys.version_info >= (3, 12):
                    kwargs["filter"] = "data"
                tar.extractall(directory, **kwargs)
        else:
            raise SteamCmdError(f"未対応の SteamCMD アーカイブです: {archive.name}")
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise SteamCmdError(f"SteamCMD の展開に失敗しました: {exc}") from exc
    found = _binary_in_directory(directory)
    if found is None:
        raise SteamCmdError(f"{directory} に steamcmd が見つかりませんでした")
    if os.name != "nt":
        mode = found.stat().st_mode
        found.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return found


async def run_steamcmd(
    executable: Path,
    extra_args: Iterable[str],
    *,
    progress: Progress | None = None,
) -> int:
    if not _is_steamcmd_binary(executable):
        raise SteamCmdError(f"SteamCMD ではありません: {executable}")
    command = [str(executable), *extra_args]
    logger.info("SteamCMD を実行します: %s", " ".join(command))
    kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.STDOUT,
        "cwd": str(executable.parent),
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = await asyncio.create_subprocess_exec(*command, **kwargs)
    except OSError as exc:
        raise SteamCmdError(f"SteamCMD を起動できません: {exc}") from exc
    assert proc.stdout is not None
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip()
        if not line:
            continue
        logger.info("steamcmd: %s", line)
        if progress is not None:
            await progress(line)
    return await proc.wait()


async def install_steamcmd(
    directory: Path,
    *,
    data_dir: Path | None = None,
    progress: Progress | None = None,
    download=None,
    runner=None,
) -> Path:
    if download is None:
        download = download_steamcmd_archive
    if runner is None:
        runner = run_steamcmd
    directory = directory.expanduser()
    if (directory / "PalServer.exe").is_file() or (directory / "PalServer.sh").is_file():
        raise SteamCmdError("SteamCMD の導入先に PalServer フォルダは使わないでください")
    async with _STEAMCMD_LOCK:
        stored = load_stored_path(data_dir)
        if stored is not None:
            if progress:
                await progress(f"すでにあります: {stored}")
            return stored
        existing = _binary_in_directory(directory) if directory.exists() else None
        if existing is not None:
            save_stored_path(data_dir, existing)
            if progress:
                await progress(f"すでにあります: {existing}")
            return existing
        if progress:
            await progress("Valve 公式の SteamCMD をダウンロードします（同梱ではありません）")
        suffix = ".zip" if os.name == "nt" else ".tar.gz"
        archive = directory / f"steamcmd-official{suffix}"
        await asyncio.to_thread(download, archive)
        if progress:
            await progress("展開しています…")
        executable = await asyncio.to_thread(extract_steamcmd_archive, archive, directory)
        if progress:
            await progress("SteamCMD の自己更新を実行します…")
        code = await runner(executable, self_update_arguments(), progress=progress)
        if code not in {0, 6, 7}:
            raise SteamCmdError(f"SteamCMD の初回起動が失敗しました (exit={code})")
        if code in {6, 7}:
            code = await runner(executable, self_update_arguments(), progress=progress)
            if code not in {0, 6, 7}:
                raise SteamCmdError(f"SteamCMD の自己更新が失敗しました (exit={code})")
        save_stored_path(data_dir, executable)
        if progress:
            await progress(f"SteamCMD を入れました: {executable}")
        return executable


async def update_palworld_server(
    executable: Path,
    install_dir: Path,
    *,
    progress: Progress | None = None,
    runner=None,
    app_id: int = PALWORLD_DS_APP_ID,
) -> None:
    if runner is None:
        runner = run_steamcmd
    install_dir.mkdir(parents=True, exist_ok=True)
    async with _STEAMCMD_LOCK:
        code = await runner(
            executable,
            update_arguments(install_dir, app_id=app_id),
            progress=progress,
        )
        if code != 0:
            raise SteamCmdError(
                f"専用サーバーの更新が失敗しました (exit={code})。"
                "ディスク容量とネットワークを確認してください。"
            )
