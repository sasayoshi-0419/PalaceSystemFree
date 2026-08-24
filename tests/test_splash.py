from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from palworld_admin import splash
from palworld_admin.desktop import _open_window
from palworld_discord_bot.paths import webview_storage_path


def test_webview_storage_path_uses_localappdata_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("palworld_discord_bot.paths._is_windows", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.chdir(tmp_path)
    path = webview_storage_path()
    assert path == tmp_path / "LocalAppData" / "HomeServerAdmin" / "WebView2"
    assert path.is_dir()


def test_webview_storage_path_falls_back_without_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("palworld_discord_bot.paths._is_windows", lambda: True)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr("palworld_discord_bot.paths.Path.home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    path = webview_storage_path()
    assert path == tmp_path / "AppData" / "Local" / "HomeServerAdmin" / "WebView2"
    assert path.is_dir()


def test_webview_storage_path_uses_data_dir_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("palworld_discord_bot.paths._is_windows", lambda: False)
    monkeypatch.chdir(tmp_path)
    path = webview_storage_path()
    assert path == tmp_path / ".data" / "webview"
    assert path.is_dir()


def test_start_splash_process_spawns_executable_with_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    splash._splash_process = None
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            calls.append(list(args))
            self.returncode = None

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

    monkeypatch.setattr(splash, "_popen_factory", FakePopen)
    monkeypatch.setattr(splash, "is_frozen", lambda: True)
    monkeypatch.delenv("HOMESERVER_NOSPLASH", raising=False)

    splash.start_splash_process()
    splash.start_splash_process()

    assert calls == [[sys.executable, "--splash-only"]]


def test_start_splash_process_respects_nosplash(monkeypatch: pytest.MonkeyPatch) -> None:
    splash._splash_process = None
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, args: list[str], **kwargs: Any) -> None:
            calls.append(list(args))

        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            pass

    monkeypatch.setattr(splash, "_popen_factory", FakePopen)
    monkeypatch.setattr(splash, "is_frozen", lambda: True)
    monkeypatch.setenv("HOMESERVER_NOSPLASH", "1")

    splash.start_splash_process()
    assert calls == []


def test_close_splash_terminates_process(monkeypatch: pytest.MonkeyPatch) -> None:
    terminated: list[bool] = []

    class FakePopen:
        def poll(self) -> None:
            return None

        def terminate(self) -> None:
            terminated.append(True)

    splash._splash_process = FakePopen()
    splash.close_splash()
    splash.close_splash()
    assert terminated == [True]


def test_open_window_hidden_until_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}
    started: dict[str, Any] = {}
    shown = False
    close_calls: list[str] = []

    class FakeLoadedEvent:
        def __init__(self) -> None:
            self.callbacks: list[Any] = []

        def __iadd__(self, callback: Any) -> "FakeLoadedEvent":
            self.callbacks.append(callback)
            return self

    class FakeWindow:
        def __init__(self) -> None:
            self.events = type("Events", (), {"loaded": FakeLoadedEvent()})()

        def show(self) -> None:
            nonlocal shown
            shown = True

    fake_window = FakeWindow()
    fake_webview = MagicMock()
    fake_webview.create_window.side_effect = lambda **kwargs: (
        created.update(kwargs) or fake_window
    )
    fake_webview.start.side_effect = lambda **kwargs: started.update(kwargs)

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr("palworld_admin.desktop.ensure_splash", lambda: None)
    monkeypatch.setattr(
        "palworld_admin.desktop.webview_storage_path",
        lambda: Path("/tmp/webview-test"),
    )
    monkeypatch.setattr(
        "palworld_admin.desktop.close_splash",
        lambda: close_calls.append("close"),
    )

    _open_window("http://127.0.0.1:1/setup.html")

    assert created["hidden"] is True
    assert created["url"] == "http://127.0.0.1:1/setup.html"
    assert started["storage_path"] == "/tmp/webview-test"
    assert started["gui"] == "edgechromium"
    assert shown is False
    assert len(fake_window.events.loaded.callbacks) == 1
    fake_window.events.loaded.callbacks[0]()
    assert shown is True
    assert close_calls.count("close") >= 2


def _wait_for(predicate, timeout: float = 2.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_open_window_without_events_reveals_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, Any] = {}
    shown = False

    class FakeWindow:
        def show(self) -> None:
            nonlocal shown
            shown = True

    fake_window = FakeWindow()
    fake_webview = MagicMock()
    fake_webview.create_window.side_effect = lambda **kwargs: (
        created.update(kwargs) or fake_window
    )
    fake_webview.start.side_effect = lambda **kwargs: None

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr("palworld_admin.desktop.ensure_splash", lambda: None)
    monkeypatch.setattr(
        "palworld_admin.desktop.webview_storage_path",
        lambda: Path("/tmp/webview-test"),
    )
    monkeypatch.setattr("palworld_admin.desktop.close_splash", lambda: None)

    _open_window("http://127.0.0.1:1/setup.html")

    assert created["hidden"] is True
    assert shown is True


def test_open_window_reveals_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._REVEAL_TIMEOUT_SECONDS", 0)
    shown = False

    class FakeLoadedEvent:
        def __init__(self) -> None:
            self.callbacks: list[Any] = []

        def __iadd__(self, callback: Any) -> "FakeLoadedEvent":
            self.callbacks.append(callback)
            return self

    class FakeWindow:
        def __init__(self) -> None:
            self.events = type("Events", (), {"loaded": FakeLoadedEvent()})()

        def show(self) -> None:
            nonlocal shown
            shown = True

    fake_window = FakeWindow()
    fake_webview = MagicMock()
    fake_webview.create_window.side_effect = lambda **kwargs: fake_window
    fake_webview.start.side_effect = lambda **kwargs: None

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr("palworld_admin.desktop.ensure_splash", lambda: None)
    monkeypatch.setattr(
        "palworld_admin.desktop.webview_storage_path",
        lambda: Path("/tmp/webview-test"),
    )
    monkeypatch.setattr("palworld_admin.desktop.close_splash", lambda: None)

    _open_window("http://127.0.0.1:1/setup.html")

    assert len(fake_window.events.loaded.callbacks) == 1
    _wait_for(lambda: shown)
    assert shown is True
