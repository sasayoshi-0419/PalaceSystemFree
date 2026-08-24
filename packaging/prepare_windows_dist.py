"""Publish PyInstaller stage output into dist/HomeServerAdmin without renaming the folder."""

from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DIST_NAME = "HomeServerAdmin"
EXE_NAME = "HomeServerAdmin.exe"
STAGE_DIRNAME = "_pyi"
KEEP_NAMES = frozenset({"config.yaml", "config.yaml.bak", ".env", ".data"})
REPO_ROOT = Path(__file__).resolve().parents[1]


class DistBusy(Exception):
    def __init__(
        self,
        path: Path,
        pids: list[int],
        detail: str,
        lockers: list[tuple[int, str]] | None = None,
    ) -> None:
        self.path = path
        self.pids = pids
        self.lockers = lockers or []
        self.detail = detail
        super().__init__(detail)


def parse_tasklist_csv(text: str, image: str) -> list[int]:
    pids: list[int] = []
    needle = image.lower()
    for raw in text.splitlines():
        if needle not in raw.lower():
            continue
        parts = [part.strip().strip('"') for part in raw.split(",")]
        if len(parts) < 2:
            continue
        try:
            pids.append(int(parts[1]))
        except ValueError:
            continue
    return pids


def running_image_pids(image: str) -> list[int]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_tasklist_csv(result.stdout, image)


def _restart_manager_lockers(paths: list[Path]) -> list[tuple[int, str]]:
    if os.name != "nt":
        return []
    existing = [path for path in paths if path.exists()]
    if not existing:
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []

    try:
        rstrtmgr = ctypes.WinDLL("RstrtMgr")
    except OSError:
        return []

    CCH_RM_SESSION_KEY = 32
    RM_INVALID_SESSION = 0xFFFFFFFF
    ERROR_MORE_DATA = 234

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [
            ("dwProcessId", wintypes.DWORD),
            ("ProcessStartTime", wintypes.FILETIME),
        ]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * 256),
            ("strServiceShortName", wintypes.WCHAR * 64),
            ("ApplicationType", wintypes.DWORD),
            ("AppStatus", wintypes.DWORD),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    session_handle = wintypes.DWORD()
    session_key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
    start = rstrtmgr.RmStartSession
    start.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
    start.restype = wintypes.DWORD
    if start(ctypes.byref(session_handle), 0, session_key) != 0:
        return []

    try:
        wide_paths = [str(path.resolve()) for path in existing]
        path_array = (wintypes.LPCWSTR * len(wide_paths))(*wide_paths)
        register = rstrtmgr.RmRegisterResources
        register.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            ctypes.POINTER(wintypes.LPCWSTR),
            wintypes.UINT,
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.c_void_p,
        ]
        register.restype = wintypes.DWORD
        if register(session_handle, len(wide_paths), path_array, 0, None, 0, None) != 0:
            return []

        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reboot_reasons = wintypes.DWORD()
        get_list = rstrtmgr.RmGetList
        get_list.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.UINT),
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_list.restype = wintypes.DWORD
        result = get_list(session_handle, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reboot_reasons))
        if result not in (0, ERROR_MORE_DATA):
            return []
        if needed.value == 0:
            return []

        count.value = needed.value
        process_info = (RM_PROCESS_INFO * needed.value)()
        result = get_list(
            session_handle,
            ctypes.byref(needed),
            ctypes.byref(count),
            ctypes.byref(process_info),
            ctypes.byref(reboot_reasons),
        )
        if result != 0:
            return []

        lockers: list[tuple[int, str]] = []
        seen: set[int] = set()
        for entry in process_info[: count.value]:
            pid = int(entry.Process.dwProcessId)
            if pid in seen:
                continue
            seen.add(pid)
            name = str(entry.strAppName).strip() or "unknown"
            lockers.append((pid, name))
        return lockers
    finally:
        end = rstrtmgr.RmEndSession
        end.argtypes = [wintypes.DWORD]
        end.restype = wintypes.DWORD
        end(session_handle)


def find_lockers(dest: Path) -> list[tuple[int, str]]:
    candidates = [
        dest,
        dest / EXE_NAME,
        dest / "_internal",
    ]
    lockers = _restart_manager_lockers(candidates)
    if lockers:
        return lockers
    return [(pid, EXE_NAME) for pid in running_image_pids(EXE_NAME)]


def format_busy_lines(exc: DistBusy) -> tuple[str, ...]:
    lines: list[str] = []
    if exc.pids:
        lines.append("HomeServerAdmin.exe が起動中のため、ビルド用フォルダを置き換えできません。")
        shown = ", ".join(f"PID {pid}" for pid in exc.pids)
        lines.append(f"起動中のプロセス: {shown}")
    else:
        lines.append("ビルド用フォルダを置き換えできません。")

    if exc.lockers:
        shown = ", ".join(f"{name} (PID {pid})" for pid, name in exc.lockers)
        lines.append(f"ロックしているプロセス: {shown}")

    if not exc.pids and not exc.lockers:
        lines.extend(
            [
                "タスク マネージャーに HomeServerAdmin.exe が無くても、置き換えに失敗することがあります。",
                "Windows Defender / SmartScreen、OneDrive、エクスプローラーのプレビュー、"
                "msedgewebview2.exe（管理ツール用が残っているとき）などが一時的にファイルをロックすることがあります。",
                "管理者コマンドプロンプトで taskkill /IM HomeServerAdmin.exe /F を試せます。"
                "管理ツール用の msedgewebview2.exe が残っているときだけ taskkill /IM msedgewebview2.exe /F も試せます。",
                "リソースモニター (resmon) → CPU → 関連付けられたハンドル で HomeServerAdmin.exe を検索できます。",
                "PyInstaller 自体は成功している可能性が高く、新しい EXE は dist\\_pyi\\HomeServerAdmin に残っています。",
                "dist\\HomeServerAdmin フォルダごと削除しないでください（config.yaml / .env / .data が消えます）。",
                "数十秒待って build-windows.bat を再実行するか、"
                "python packaging\\prepare_windows_dist.py dist だけ再実行してください。",
            ]
        )

    if exc.detail:
        lines.append(f"Windows のエラー: {exc.detail}")

    lines.extend(
        [
            "PyInstaller の onedir 出力では HomeServerAdmin.exe と _internal フォルダがセットです。",
            "EXE だけ新しくなって _internal が欠けると、起動時に "
            "「Failed to load Python DLL」/ python310.dll が見つからないことがあります。",
            "修復: dist\\_pyi\\HomeServerAdmin\\_internal を dist\\HomeServerAdmin\\_internal へコピー"
            "（例: xcopy /E /I /Y dist\\_pyi\\HomeServerAdmin\\_internal dist\\HomeServerAdmin\\_internal）。"
            "dist\\_pyi が残っているうちはフル再ビルドせず、"
            "python packaging\\prepare_windows_dist.py dist の再実行でもよいです。",
            "タスク マネージャーで HomeServerAdmin.exe（スプラッシュ含む）が残っていれば終了してください。",
            "dist\\HomeServerAdmin をエクスプローラーで開いていれば閉じてください。",
            "Cursor などのエディタで dist\\HomeServerAdmin 内のファイル（とくに config.yaml）を開いていればタブを閉じてください。",
            "そのあと build-windows.bat を再実行してください。",
            f"ロックされたファイル: {exc.path}",
        ]
    )
    return tuple(lines)


def _busy_path(dest: Path) -> Path:
    exe = dest / EXE_NAME
    return exe if exe.exists() else dest


def _is_transient_lock_error(exc: OSError) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror in (5, 32):
        return True
    # PermissionError(5, ...) from Windows-style tests uses errno 5 on Linux too.
    return exc.errno in (5, errno.EACCES, errno.EPERM, errno.EBUSY)


def _best_effort_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _best_effort_remove(path: Path, *, remove_tree=None) -> None:
    do_rmtree = remove_tree or shutil.rmtree
    try:
        if path.is_dir():
            do_rmtree(path)
        else:
            path.unlink()
    except OSError:
        pass


def _backup_dest_path(dest: Path) -> Path:
    candidate = Path(f"{dest}.old")
    if not candidate.exists():
        return candidate
    _best_effort_unlink(candidate)
    if not candidate.exists():
        return candidate
    for index in range(1, 101):
        numbered = Path(f"{dest}.old.{index}")
        if not numbered.exists():
            return numbered
        _best_effort_unlink(numbered)
        if not numbered.exists():
            return numbered
    return Path(f"{dest}.old.101")


def _copy_file_once(
    src: Path,
    dest: Path,
    *,
    do_copy2,
    do_rename,
    backup_paths: list[Path],
) -> None:
    try:
        do_copy2(src, dest)
        return
    except OSError as exc:
        if not _is_transient_lock_error(exc):
            raise
        if not dest.exists():
            raise
        old_path = _backup_dest_path(dest)
        try:
            do_rename(dest, old_path)
            backup_paths.append(old_path)
        except OSError:
            _best_effort_unlink(dest)
        try:
            do_copy2(src, dest)
        except OSError:
            raise


def _replace_file(
    src: Path,
    dest: Path,
    *,
    do_copy2,
    do_rename,
    sleeper,
    retry_attempts: int,
    retry_delay: float,
    backup_paths: list[Path],
) -> None:
    display_path = dest
    last_exc: OSError | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            _copy_file_once(
                src,
                dest,
                do_copy2=do_copy2,
                do_rename=do_rename,
                backup_paths=backup_paths,
            )
            return
        except OSError as exc:
            if not _is_transient_lock_error(exc):
                raise
            last_exc = exc
            if attempt < retry_attempts:
                print(
                    f"置き換えを再試行します ({attempt + 1}/{retry_attempts}): {display_path}"
                )
                sleeper(retry_delay)
    if last_exc is not None:
        raise last_exc


def _replace_tree_once(
    src: Path,
    dest: Path,
    *,
    do_rmtree,
    do_copytree,
    do_rename,
    backup_paths: list[Path],
) -> None:
    incoming = Path(f"{dest}.new")
    if incoming.exists():
        do_rmtree(incoming)
    do_copytree(src, incoming)
    old_path: Path | None = None
    if dest.exists():
        old_path = _backup_dest_path(dest)
        do_rename(dest, old_path)
        backup_paths.append(old_path)
    try:
        do_rename(incoming, dest)
    except OSError as exc:
        if old_path is not None:
            try:
                do_rename(old_path, dest)
                backup_paths.remove(old_path)
            except OSError:
                pass
        raise exc


def _replace_tree(
    src: Path,
    dest: Path,
    *,
    do_rmtree,
    do_copytree,
    do_rename,
    sleeper,
    retry_attempts: int,
    retry_delay: float,
    backup_paths: list[Path],
) -> None:
    display_path = dest
    last_exc: OSError | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            _replace_tree_once(
                src,
                dest,
                do_rmtree=do_rmtree,
                do_copytree=do_copytree,
                do_rename=do_rename,
                backup_paths=backup_paths,
            )
            return
        except OSError as exc:
            if not _is_transient_lock_error(exc):
                raise
            last_exc = exc
            if attempt < retry_attempts:
                print(
                    f"置き換えを再試行します ({attempt + 1}/{retry_attempts}): {display_path}"
                )
                sleeper(retry_delay)
    if last_exc is not None:
        raise last_exc


def _stage_entries(stage: Path) -> list[Path]:
    return sorted(
        stage.iterdir(),
        key=lambda entry: (not entry.is_dir(), entry.name != "_internal", entry.name),
    )


def _stage_python_dll_names(stage: Path) -> list[str]:
    internal = stage / "_internal"
    if not internal.is_dir():
        return []
    return sorted(path.name for path in internal.glob("python*.dll"))


def _verify_stage_python_dlls(stage: Path, dest: Path) -> None:
    missing: list[Path] = []
    for dll_name in _stage_python_dll_names(stage):
        dest_dll = dest / "_internal" / dll_name
        if not dest_dll.is_file():
            missing.append(dest_dll)
    if not missing:
        return
    shown = ", ".join(str(path) for path in missing)
    raise DistBusy(
        dest / "_internal",
        [],
        (
            f"PyInstaller のランタイム DLL が dist にコピーされていません: {shown}\n"
            "新しい EXE だけ置き換わり、_internal\\python310.dll などが欠けていると "
            "起動時に「Failed to load Python DLL」になります。"
            "dist\\_pyi\\HomeServerAdmin\\_internal を dist\\HomeServerAdmin\\_internal へコピーしてください"
            "（例: xcopy /E /I /Y dist\\_pyi\\HomeServerAdmin\\_internal dist\\HomeServerAdmin\\_internal）。"
            "dist\\HomeServerAdmin フォルダごと削除しないでください。"
            "dist\\_pyi が残っているうちは python packaging\\prepare_windows_dist.py dist の再実行でも修復できます。"
        ),
    )


def _copy_dist_docs(dest: Path, *, copy_file=None) -> None:
    do_copy2 = copy_file or shutil.copy2
    usage = REPO_ROOT / "packaging" / "使い方.txt"
    license_path = REPO_ROOT / "LICENSE"
    if usage.is_file():
        do_copy2(usage, dest / "使い方.txt")
    if license_path.is_file():
        do_copy2(license_path, dest / "LICENSE")


def _remove_stage_dir(stage_root: Path, remove_tree=None) -> None:
    if not stage_root.exists():
        return
    do_rmtree = remove_tree or shutil.rmtree
    try:
        do_rmtree(stage_root)
    except OSError as exc:
        print(f"ステージフォルダを削除できませんでした: {stage_root} ({exc})")


def _raise_dist_busy(dest: Path, exc: OSError, find_lockers_fn) -> None:
    pids = [pid for pid, _name in find_lockers_fn(dest) if _name.lower() == EXE_NAME.lower()]
    lockers = find_lockers_fn(dest)
    raise DistBusy(_busy_path(dest), pids, str(exc), lockers) from exc


def publish_dist(
    dist_dir: Path,
    *,
    copy_file=None,
    copy_tree=None,
    remove_tree=None,
    rename=None,
    locker_finder=None,
    sleeper=None,
    retry_attempts: int = 6,
    retry_delay: float = 1.5,
) -> None:
    """Publish dist/_pyi/HomeServerAdmin into dist/HomeServerAdmin."""
    stage = dist_dir / STAGE_DIRNAME / DIST_NAME
    dest = dist_dir / DIST_NAME
    stage_root = dist_dir / STAGE_DIRNAME
    do_copy2 = copy_file or shutil.copy2
    do_copytree = copy_tree or shutil.copytree
    do_rmtree = remove_tree or shutil.rmtree
    do_rename = rename or (lambda src, dest_path: src.rename(dest_path))
    find_lockers_fn = locker_finder or find_lockers
    do_sleep = sleeper if sleeper is not None else time.sleep
    backup_paths: list[Path] = []

    if not stage.is_dir():
        raise FileNotFoundError(
            f"PyInstaller の出力が見つかりません: {stage}\n"
            "PyInstaller が失敗した可能性があります。build-windows.bat のログを確認してください。"
        )

    if not dest.exists():
        do_rename(stage, dest)
        if stage_root.exists() and not any(stage_root.iterdir()):
            stage_root.rmdir()
        _copy_dist_docs(dest, copy_file=do_copy2)
        return

    stage_names = {entry.name for entry in stage.iterdir()}
    for entry in dest.iterdir():
        if entry.name in KEEP_NAMES or entry.name in stage_names:
            continue
        try:
            if entry.is_dir():
                do_rmtree(entry)
            else:
                entry.unlink()
        except OSError:
            pass

    # Copy stage entries into dest, preserving KEEP_NAMES already present.
    for item in _stage_entries(stage):
        target = dest / item.name
        if item.name in KEEP_NAMES and target.exists():
            continue
        try:
            if item.is_dir():
                _replace_tree(
                    item,
                    target,
                    do_rmtree=do_rmtree,
                    do_copytree=do_copytree,
                    do_rename=do_rename,
                    sleeper=do_sleep,
                    retry_attempts=retry_attempts,
                    retry_delay=retry_delay,
                    backup_paths=backup_paths,
                )
            else:
                _replace_file(
                    item,
                    target,
                    do_copy2=do_copy2,
                    do_rename=do_rename,
                    sleeper=do_sleep,
                    retry_attempts=retry_attempts,
                    retry_delay=retry_delay,
                    backup_paths=backup_paths,
                )
        except OSError as exc:
            _raise_dist_busy(dest, exc, find_lockers_fn)

    _verify_stage_python_dlls(stage, dest)

    for backup_path in backup_paths:
        _best_effort_remove(backup_path, remove_tree=do_rmtree)

    _remove_stage_dir(stage_root, remove_tree=do_rmtree)
    _copy_dist_docs(dest, copy_file=do_copy2)


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    dist_dir = Path(args[0]) if args else Path("dist")
    try:
        publish_dist(dist_dir)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    except DistBusy as exc:
        for line in format_busy_lines(exc):
            print(line)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
