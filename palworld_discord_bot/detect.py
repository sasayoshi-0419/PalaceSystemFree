from __future__ import annotations

import os
import re
import threading
from pathlib import Path

_LIBRARY_PATH = re.compile(r'"path"\s+"([^"]+)"')
_PAL_DIR_NAMES = ("PalServer", "Palworld Dedicated Server")

DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

_UNSAFE_DRIVE_TYPES = {DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR, DRIVE_REMOTE, DRIVE_CDROM}
_probe_cache: dict[str, bool] = {}


def has_server_binary(folder: Path) -> bool:
    return (folder / "PalServer.exe").is_file() or (folder / "PalServer.sh").is_file()


def _has_server_binary(folder: Path) -> bool:
    return has_server_binary(folder)


def reset_drive_probe_cache() -> None:
    _probe_cache.clear()


def _drive_cache_key(path: Path) -> str:
    text = str(path).replace("/", "\\")
    if text.startswith("\\\\"):
        return "unc"
    if len(text) >= 2 and text[1] == ":":
        return text[0].upper()
    return ""


def windows_drive_type(path: Path) -> int | None:
    text = str(path).replace("/", "\\")
    if text.startswith("\\\\"):
        return DRIVE_REMOTE
    if os.name != "nt":
        return None
    if len(text) < 2 or text[1] != ":":
        return None
    root = text[0].upper() + ":\\"
    try:
        import ctypes

        func = ctypes.windll.kernel32.GetDriveTypeW
        func.argtypes = [ctypes.c_wchar_p]
        func.restype = ctypes.c_uint
        return int(func(root))
    except Exception:
        return None


def _drive_root_ready(letter: str, timeout: float = 0.2) -> bool:
    result = {"ok": False}

    def worker() -> None:
        try:
            result["ok"] = os.path.isdir(f"{letter}:\\")
        except OSError:
            result["ok"] = False

    thread = threading.Thread(target=worker, daemon=True, name=f"drive-probe-{letter}")
    thread.start()
    thread.join(timeout)
    return bool(result["ok"]) and not thread.is_alive()


def path_is_safe_to_probe(path: Path) -> bool:
    """Skip CD-ROM, disconnected shares, and empty card readers that freeze Windows."""
    key = _drive_cache_key(path)
    if key in _probe_cache:
        return _probe_cache[key]
    dtype = windows_drive_type(path)
    if dtype is None:
        ok = True
    elif dtype in _UNSAFE_DRIVE_TYPES:
        ok = False
    elif dtype in {DRIVE_FIXED, DRIVE_RAMDISK}:
        ok = True
    elif dtype == DRIVE_REMOVABLE and key:
        ok = _drive_root_ready(key)
    else:
        ok = True
    if key:
        _probe_cache[key] = ok
    return ok


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    roots.extend(
        [
            program_files_x86 / "Steam",
            program_files / "Steam",
            home / "Steam",
        ]
    )
    for guess in (
        Path("C:/SteamCMD"),
        Path("C:/steamcmd"),
        Path("D:/SteamCMD"),
        Path("E:/SteamCMD"),
    ):
        if path_is_safe_to_probe(guess):
            roots.append(guess)
    steam = _steam_install_path()
    if steam is not None:
        roots.append(steam)
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _steam_install_path() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _unused = winreg.QueryValueEx(key, "SteamPath")
    except OSError:
        return None
    path = Path(str(value))
    if not path_is_safe_to_probe(path):
        return None
    return path if path.is_dir() else None


def _steam_libraries(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return libraries
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    for match in _LIBRARY_PATH.finditer(text):
        folder = Path(match.group(1).replace("\\", "/"))
        if path_is_safe_to_probe(folder) and folder.is_dir():
            libraries.append(folder)
    return libraries


def find_palserver_directories(extra: Path | None = None) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def add(folder: Path, *, forced: bool = False) -> None:
        if not forced and not path_is_safe_to_probe(folder):
            return
        try:
            resolved = folder.expanduser().resolve()
        except OSError:
            resolved = folder.expanduser()
        if not _has_server_binary(resolved):
            return
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        found.append(resolved)

    if extra is not None:
        add(extra, forced=True)
    for root in _candidate_roots():
        if not path_is_safe_to_probe(root):
            continue
        steamapps = root / "steamapps"
        for library in _steam_libraries(root) if steamapps.is_dir() else [root]:
            common = library / "steamapps" / "common"
            for name in _PAL_DIR_NAMES:
                add(common / name)
            add(library / "steamapps" / "common" / "PalServer")
            add(root / "steamapps" / "common" / "PalServer")
            add(root / "PalServer")
    return found


def palserver_kind(folder: Path) -> str:
    text = str(folder).replace("\\", "/").lower()
    if "steamcmd" in text:
        return "steamcmd"
    if "steamapps/common" in text:
        return "steam"
    return "folder"


def palserver_label(folder: Path) -> str:
    kind = palserver_kind(folder)
    if kind == "steamcmd":
        return "SteamCMD の専用サーバー"
    if kind == "steam":
        if "dedicated" in folder.name.lower():
            return "Steam の専用サーバー"
        return "Steam ライブラリの PalServer"
    return "PalServer フォルダ"


def has_save_data(folder: Path) -> bool:
    saved = folder / "Pal" / "Saved"
    if not saved.is_dir():
        return False
    try:
        return any(saved.iterdir())
    except OSError:
        return False


def describe_palserver(folder: Path) -> dict[str, object]:
    try:
        resolved = folder.expanduser().resolve()
    except OSError:
        resolved = folder.expanduser()
    return {
        "path": resolved.as_posix(),
        "label": palserver_label(resolved),
        "kind": palserver_kind(resolved),
        "has_saves": has_save_data(resolved),
        "has_binary": has_server_binary(resolved),
    }


def list_palserver_candidates(extra: Path | None = None) -> list[dict[str, object]]:
    return [describe_palserver(path) for path in find_palserver_directories(extra=extra)]


def needs_palserver_picker(
    working_directory: Path | None,
    found: list[Path] | None = None,
) -> bool:
    """True when the configured folder is unusable and at least one PalServer exists."""
    if working_directory is None:
        return False
    folder = working_directory.expanduser()
    try:
        folder = folder.resolve()
    except OSError:
        pass
    if folder.is_dir() and has_server_binary(folder):
        return False
    candidates = found if found is not None else find_palserver_directories()
    return len(candidates) >= 1


def default_settings_file(working_directory: Path) -> Path:
    windows = working_directory / "Pal" / "Saved" / "Config" / "WindowsServer" / "PalWorldSettings.ini"
    linux = working_directory / "Pal" / "Saved" / "Config" / "LinuxServer" / "PalWorldSettings.ini"
    if windows.is_file() or os.name == "nt":
        return windows
    if linux.is_file():
        return linux
    return windows if os.name == "nt" else linux


def start_command_for(working_directory: Path, game_port: int) -> list[str]:
    flags = [
        f"-port={game_port}",
        "-useperfthreads",
        "-NoAsyncLoadingThread",
        "-UseMultithreadForDS",
    ]
    if (working_directory / "PalServer.exe").is_file() or os.name == "nt":
        return ["PalServer.exe", *flags]
    return ["./PalServer.sh", *flags]
