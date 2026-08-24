from __future__ import annotations

import threading
import time
from typing import Any

from palworld_admin.desktop import DesktopBridge


class FakeWindow:
    def __init__(self) -> None:
        self.destroyed = False
        self.loaded: str | None = None
        self.js_calls: list[str] = []

    def destroy(self) -> None:
        self.destroyed = True

    def load_url(self, url: str) -> None:
        self.loaded = url

    def evaluate_js(self, js: str) -> None:
        self.js_calls.append(js)


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_finish_returns_pending_before_handoff(monkeypatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._HANDOFF_LOAD_DELAY_SECONDS", 0)
    started = threading.Event()
    allow_finish = threading.Event()

    def slow_setup() -> str:
        started.set()
        allow_finish.wait(timeout=2)
        return "http://127.0.0.1:8787/"

    state: dict[str, Any] = {"code": 1}
    window = FakeWindow()
    bridge = DesktopBridge(state, on_setup_done=slow_setup)
    bridge._window = window

    result = bridge.finish(True)

    assert result == {"ok": True, "pending": True}
    assert state["code"] == 1
    assert window.loaded is None
    assert window.destroyed is False
    _wait_for(lambda: started.is_set())
    allow_finish.set()
    _wait_for(lambda: window.loaded == "http://127.0.0.1:8787/")
    assert state["code"] == 0
    assert window.destroyed is False


def test_finish_without_handoff_closes_window(monkeypatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._CLOSE_DELAY_SECONDS", 0)
    state: dict[str, Any] = {"code": 1}
    window = FakeWindow()
    bridge = DesktopBridge(state)
    bridge._window = window

    result = bridge.finish(True)

    assert result == {"ok": False}
    _wait_for(lambda: window.destroyed is True)


def test_finish_reports_handoff_error_in_background(monkeypatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._HANDOFF_LOAD_DELAY_SECONDS", 0)

    def boom() -> str:
        time.sleep(0.1)
        raise RuntimeError("管理パネルを起動できませんでした")

    state: dict[str, Any] = {"code": 1}
    window = FakeWindow()
    bridge = DesktopBridge(state, on_setup_done=boom)
    bridge._window = window

    result = bridge.finish(True)

    assert result == {"ok": True, "pending": True}
    assert state["code"] == 1
    assert window.destroyed is False
    _wait_for(lambda: state["code"] == 2)
    assert window.destroyed is False
    _wait_for(lambda: len(window.js_calls) > 0)
    assert "getElementById('error')" in window.js_calls[0]
    assert "disabled=false" in window.js_calls[0]


def test_finish_twice_runs_handoff_once(monkeypatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._HANDOFF_LOAD_DELAY_SECONDS", 0)
    calls: list[int] = []
    gate = threading.Event()

    def slow_setup() -> str:
        calls.append(1)
        gate.wait(timeout=2)
        return "http://127.0.0.1:8787/"

    state: dict[str, Any] = {"code": 1}
    window = FakeWindow()
    bridge = DesktopBridge(state, on_setup_done=slow_setup)
    bridge._window = window

    result1 = bridge.finish(True)
    result2 = bridge.finish(True)

    assert result1 == {"ok": True, "pending": True}
    assert result2 == {"ok": True, "pending": True, "url": ""}
    gate.set()
    _wait_for(lambda: len(calls) == 1)
    _wait_for(lambda: window.loaded == "http://127.0.0.1:8787/")


def test_on_after_load_runs_after_load_url(monkeypatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._HANDOFF_LOAD_DELAY_SECONDS", 0)
    monkeypatch.setattr("palworld_admin.desktop._SETUP_CLEANUP_DELAY_SECONDS", 0)
    loaded: list[str] = []
    after_load: list[int] = []

    def on_setup_done() -> str:
        return "http://127.0.0.1:8787/"

    def on_after_load() -> None:
        after_load.append(1)

    state: dict[str, Any] = {"code": 1}
    window = FakeWindow()
    bridge = DesktopBridge(
        state,
        on_setup_done=on_setup_done,
        on_after_load=on_after_load,
    )
    bridge._window = window

    bridge.finish(True)
    _wait_for(lambda: window.loaded == "http://127.0.0.1:8787/")
    _wait_for(lambda: len(after_load) == 1)


def test_close_app_destroys_window_after_return(monkeypatch) -> None:
    monkeypatch.setattr("palworld_admin.desktop._CLOSE_DELAY_SECONDS", 0)
    window = FakeWindow()
    bridge = DesktopBridge({})
    bridge._window = window

    bridge.close_app()

    assert bridge._window is None
    _wait_for(lambda: window.destroyed is True)


def test_js_api_exposes_only_callables_and_state() -> None:
    bridge = DesktopBridge({"code": 1})
    public = {k: v for k, v in vars(bridge).items() if not k.startswith("_")}

    assert "window" not in public
    assert set(public.keys()) == {"state"}
    assert public["state"] == {"code": 1}
    for name in ("finish", "browse_folder", "close_app"):
        assert callable(getattr(bridge, name))
