import importlib.util
import runpy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "home_server_admin.spec"
ENTRY = ROOT / "packaging" / "run_admin.py"
BAT = ROOT / "build-windows.bat"
MESSAGES = ROOT / "packaging" / "build_windows_messages.py"
PREPARE = ROOT / "packaging" / "prepare_windows_dist.py"


def _load_prepare():
    spec = importlib.util.spec_from_file_location("prepare_windows_dist", PREPARE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_stage(dist_dir: Path, *, exe_body: bytes = b"mz-new", internal: bool = True) -> Path:
    stage = dist_dir / "_pyi" / "HomeServerAdmin"
    stage.mkdir(parents=True)
    (stage / "HomeServerAdmin.exe").write_bytes(exe_body)
    if internal:
        internal_dir = stage / "_internal"
        internal_dir.mkdir()
        (internal_dir / "app.dll").write_bytes(b"new")
        (internal_dir / "python310.dll").write_bytes(b"py-dll-new")
    return stage


def test_pyinstaller_entry_script_is_beside_spec() -> None:
    assert SPEC.is_file()
    assert ENTRY.is_file()
    text = SPEC.read_text(encoding="utf-8")
    assert "entry_script" in text
    assert "[str(entry_script)]" in text
    assert '["packaging/' not in text
    assert '["packaging\\' not in text


def test_build_windows_bat_is_ascii_and_prints_via_python() -> None:
    BAT.read_bytes().decode("ascii")
    text = BAT.read_text(encoding="ascii")
    assert "if not exist" in text.lower()
    assert "errorlevel" in text.lower()
    assert "build_windows_messages.py" in text
    assert "prepare_windows_dist.py" in text
    assert "dist\\_pyi" in text
    assert "ok" in text


def test_build_windows_messages_ok(capsys: pytest.CaptureFixture[str]) -> None:
    loaded = runpy.run_path(str(MESSAGES))
    assert loaded["main"](["ok"]) == 0
    out = capsys.readouterr().out
    assert "出力: dist\\HomeServerAdmin\\HomeServerAdmin.exe" in out
    assert "PalServer" in out
    assert "使い方.txt" in out
    assert "SteamCMD" in out


def test_build_windows_messages_cli() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(MESSAGES), "ok"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert "HomeServerAdmin.exe" in result.stdout
    assert "出力" in result.stdout


def test_build_windows_messages_pyinstaller_failed_mentions_lock(capsys: pytest.CaptureFixture[str]) -> None:
    loaded = runpy.run_path(str(MESSAGES))
    assert loaded["main"](["pyinstaller-failed"]) == 0
    out = capsys.readouterr().out
    assert "WinError 5" in out
    assert "HomeServerAdmin.exe" in out


def test_publish_dist_copies_usage_and_license(tmp_path: Path) -> None:
    module = _load_prepare()
    _make_stage(tmp_path)
    module.publish_dist(tmp_path)
    dest = tmp_path / "HomeServerAdmin"
    assert (dest / "使い方.txt").is_file()
    assert (dest / "LICENSE").is_file()
    usage = (dest / "使い方.txt").read_text(encoding="utf-8")
    assert "非公式" in usage
    assert "PalServer" in usage


def test_publish_dist_renames_stage_when_dest_missing(tmp_path: Path) -> None:
    module = _load_prepare()
    stage = _make_stage(tmp_path)
    module.publish_dist(tmp_path)
    dest = tmp_path / "HomeServerAdmin"
    assert dest.is_dir()
    assert (dest / "HomeServerAdmin.exe").read_bytes() == b"mz-new"
    assert not stage.exists()
    assert not (tmp_path / "_pyi").exists()


def test_publish_main_succeeds_with_stage(tmp_path: Path) -> None:
    module = _load_prepare()
    _make_stage(tmp_path)
    assert module.main([str(tmp_path)]) == 0
    assert (tmp_path / "HomeServerAdmin" / "HomeServerAdmin.exe").is_file()


def test_publish_dist_preserves_keep_files_and_updates_exe(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    (dest / "config.yaml").write_text("user: keep-me\n", encoding="utf-8")
    (dest / ".env").write_text("DISCORD_TOKEN=secret\n", encoding="utf-8")
    (dest / "HomeServerAdmin.exe").write_bytes(b"mz-old")
    old_internal = dest / "_internal"
    old_internal.mkdir()
    (old_internal / "app.dll").write_bytes(b"old")

    _make_stage(tmp_path, exe_body=b"mz-new")
    (tmp_path / "_pyi" / "HomeServerAdmin" / "config.yaml").write_text("user: stage\n", encoding="utf-8")

    module.publish_dist(tmp_path)

    assert (dest / "config.yaml").read_text(encoding="utf-8") == "user: keep-me\n"
    assert (dest / ".env").read_text(encoding="utf-8") == "DISCORD_TOKEN=secret\n"
    assert (dest / "HomeServerAdmin.exe").read_bytes() == b"mz-new"
    assert (dest / "_internal" / "app.dll").read_bytes() == b"new"
    assert (dest / "_internal" / "python310.dll").read_bytes() == b"py-dll-new"
    assert not (tmp_path / "_pyi").exists()


def test_publish_dist_reports_busy_on_copy_failure(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    (dest / "HomeServerAdmin.exe").write_bytes(b"mz-old")
    _make_stage(tmp_path)

    def boom_copy(_src: Path, _dest: Path) -> None:
        raise PermissionError(5, "Access is denied")

    with pytest.raises(module.DistBusy) as caught:
        module.publish_dist(
            tmp_path,
            copy_file=boom_copy,
            locker_finder=lambda _dest: [],
            sleeper=lambda _s: None,
            retry_attempts=3,
        )
    text = "\n".join(module.format_busy_lines(caught.value))
    assert "HomeServerAdmin.exe が使われているため" not in text
    assert "config.yaml" in text
    assert "エクスプローラー" in text
    assert "build-windows.bat" in text
    assert caught.value.pids == []
    assert "Defender" in text or "Windows Defender" in text
    assert "_pyi" in text
    assert "taskkill" in text
    assert "フォルダごと削除しない" in text
    assert "python310.dll" in text
    assert "Windows のエラー:" in text


def test_publish_dist_retries_transient_copy_failure(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    (dest / "HomeServerAdmin.exe").write_bytes(b"mz-old")
    stage = _make_stage(tmp_path, exe_body=b"mz-new")

    attempts = {"count": 0}
    sleeps: list[float] = []

    def flaky_copy(src: Path, copy_dest: Path) -> None:
        attempts["count"] += 1
        if attempts["count"] <= 2:
            raise PermissionError(5, "Access is denied")
        shutil.copy2(src, copy_dest)

    module.publish_dist(
        tmp_path,
        copy_file=flaky_copy,
        sleeper=lambda seconds: sleeps.append(seconds),
        retry_attempts=6,
    )

    assert (dest / "HomeServerAdmin.exe").read_bytes() == b"mz-new"
    assert attempts["count"] == 5
    assert sleeps == [1.5]
    assert not stage.exists()


def test_publish_dist_replaces_exe_via_rename_when_overwrite_blocked(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    exe = dest / "HomeServerAdmin.exe"
    exe.write_bytes(b"mz-old")
    _make_stage(tmp_path, exe_body=b"mz-new")

    sleeps: list[float] = []

    def blocked_overwrite_copy(src: Path, copy_dest: Path) -> None:
        if copy_dest.exists():
            raise PermissionError(5, "Access is denied")
        shutil.copy2(src, copy_dest)

    module.publish_dist(
        tmp_path,
        copy_file=blocked_overwrite_copy,
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    assert exe.read_bytes() == b"mz-new"
    assert sleeps == []
    assert not Path(f"{exe}.old").exists()


def test_publish_dist_busy_lines_show_locker_names(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    exe = dest / "HomeServerAdmin.exe"
    exc = module.DistBusy(
        exe,
        [],
        "Access is denied",
        lockers=[(1234, "Cursor.exe")],
    )
    text = "\n".join(module.format_busy_lines(exc))
    assert "Cursor.exe (PID 1234)" in text
    assert "HomeServerAdmin.exe が起動中" not in text


def test_publish_dist_busy_lines_when_exe_running(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    exe = dest / "HomeServerAdmin.exe"
    exc = module.DistBusy(exe, [4242], "Access is denied")
    text = "\n".join(module.format_busy_lines(exc))
    assert "HomeServerAdmin.exe が起動中" in text
    assert "PID 4242" in text


def test_publish_main_prints_busy(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    exe = dest / "HomeServerAdmin.exe"

    def boom(_dist_dir: Path, **_kwargs):
        raise module.DistBusy(exe, [], "Access is denied", lockers=[(99, "Cursor.exe")])

    monkeypatch.setattr(module, "publish_dist", boom)
    assert module.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Cursor.exe (PID 99)" in out
    assert "config.yaml" in out


def test_publish_main_missing_stage(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_prepare()
    assert module.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "PyInstaller" in out


def test_publish_dist_preserves_internal_when_copytree_fails(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    (dest / "HomeServerAdmin.exe").write_bytes(b"mz-old")
    old_internal = dest / "_internal"
    old_internal.mkdir()
    (old_internal / "python310.dll").write_bytes(b"old-dll")
    _make_stage(tmp_path)

    def boom_copytree(_src: Path, _dest: Path) -> None:
        raise PermissionError(5, "Access is denied")

    with pytest.raises(module.DistBusy):
        module.publish_dist(
            tmp_path,
            copy_tree=boom_copytree,
            locker_finder=lambda _dest: [],
            sleeper=lambda _s: None,
            retry_attempts=2,
        )

    assert (dest / "_internal" / "python310.dll").read_bytes() == b"old-dll"
    assert (dest / "HomeServerAdmin.exe").read_bytes() == b"mz-old"
    assert (tmp_path / "_pyi").exists()


def test_publish_dist_restores_internal_when_swap_rename_fails(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    (dest / "HomeServerAdmin.exe").write_bytes(b"mz-old")
    old_internal = dest / "_internal"
    old_internal.mkdir()
    (old_internal / "python310.dll").write_bytes(b"old-dll")
    _make_stage(tmp_path)

    real_rename = Path.rename

    def flaky_rename(src: Path, dst: Path) -> None:
        if str(src).endswith(".new") and dst == old_internal:
            raise PermissionError(5, "Access is denied")
        real_rename(src, dst)

    with pytest.raises(module.DistBusy):
        module.publish_dist(
            tmp_path,
            rename=flaky_rename,
            locker_finder=lambda _dest: [],
            sleeper=lambda _s: None,
            retry_attempts=2,
        )

    assert (dest / "_internal" / "python310.dll").read_bytes() == b"old-dll"


def test_publish_dist_remove_tree_never_targets_dest_internal(tmp_path: Path) -> None:
    module = _load_prepare()
    dest = tmp_path / "HomeServerAdmin"
    dest.mkdir()
    (dest / "HomeServerAdmin.exe").write_bytes(b"mz-old")
    old_internal = dest / "_internal"
    old_internal.mkdir()
    (old_internal / "python310.dll").write_bytes(b"old-dll")
    _make_stage(tmp_path)

    removed: list[Path] = []
    real_rmtree = shutil.rmtree

    def track_rmtree(path: Path, *args, **kwargs) -> None:
        removed.append(path)
        real_rmtree(path, *args, **kwargs)

    module.publish_dist(tmp_path, remove_tree=track_rmtree)

    assert not any(path.name == "_internal" and path.parent == dest for path in removed)
    assert (dest / "_internal" / "python310.dll").read_bytes() == b"py-dll-new"


def test_restart_manager_lockers_empty_on_linux() -> None:
    module = _load_prepare()
    assert module._restart_manager_lockers([Path("/tmp/example")]) == []


def test_find_lockers_falls_back_to_tasklist_pids(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_prepare()
    monkeypatch.setattr(module, "_restart_manager_lockers", lambda _paths: [])
    monkeypatch.setattr(module, "running_image_pids", lambda _image: [777])
    assert module.find_lockers(Path("/tmp/HomeServerAdmin")) == [(777, "HomeServerAdmin.exe")]


def test_parse_tasklist_csv() -> None:
    module = _load_prepare()
    text = '"HomeServerAdmin.exe","4242","Console","1","12,345 K"\n'
    assert module.parse_tasklist_csv(text, "HomeServerAdmin.exe") == [4242]
    assert module.parse_tasklist_csv("INFO: No tasks are running\n", "HomeServerAdmin.exe") == []


def test_spec_includes_splash_hiddenimport() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert "palworld_admin.splash" in text


def test_run_admin_supports_splash_only() -> None:
    text = ENTRY.read_text(encoding="utf-8")
    assert "--splash-only" in text
    assert "run_standalone" in text
    assert "start_splash_process" in text
    assert "close_splash" in text


def test_run_admin_closes_splash_on_main_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []

    def fake_close() -> None:
        closed.append(True)

    def fake_main() -> int:
        raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "palworld_admin.__main__", type(sys)("main"))
    sys.modules["palworld_admin.__main__"].main = fake_main
    monkeypatch.setitem(sys.modules, "palworld_admin.splash", type(sys)("splash"))
    sys.modules["palworld_admin.splash"].close_splash = fake_close
    monkeypatch.setattr(sys, "argv", [str(ENTRY)])
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    with pytest.raises(RuntimeError, match="boom"):
        runpy.run_path(str(ENTRY), run_name="__main__")

    assert closed == [True]
