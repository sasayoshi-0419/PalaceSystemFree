from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from palworld_admin.service import AdminService
from palworld_admin.setup_app import create_setup_app
from palworld_discord_bot.applog import setup_app_logging
from palworld_discord_bot.config import ConfigError, load_config
from palworld_admin.splash import close_splash, ensure_splash
from palworld_discord_bot.paths import app_root, resolve_user_path, webview_storage_path

logger = logging.getLogger(__name__)

WINDOW_TITLE = "Home Server Admin"
# pywebview の js_api 呼び出し中に destroy() すると、JS の await と
# WebView の終了待ちが互いに待って固まる。戻してから閉じる。
_CLOSE_DELAY_SECONDS = 0.15
_HANDOFF_LOAD_DELAY_SECONDS = 0.2
_SETUP_CLEANUP_DELAY_SECONDS = 1.0
_REVEAL_TIMEOUT_SECONDS = 8.0


def _folder_dialog_type(webview: Any) -> Any:
    file_dialog = getattr(webview, "FileDialog", None)
    if file_dialog is not None:
        return file_dialog.FOLDER
    return webview.FOLDER_DIALOG


class DesktopBridge:
    def __init__(
        self,
        state: dict[str, Any],
        *,
        on_setup_done: Callable[[], str | None] | None = None,
        on_after_load: Callable[[], None] | None = None,
    ) -> None:
        self.state = state
        self._window = None
        self._on_setup_done = on_setup_done
        self._on_after_load = on_after_load
        self._switching = False

    def browse_folder(self) -> str:
        import webview

        if self._window is None:
            return ""
        chosen = self._window.create_file_dialog(_folder_dialog_type(webview))
        if not chosen:
            return ""
        return str(chosen[0])

    def finish(self, ok: bool = True) -> dict[str, Any]:
        if ok and self._on_setup_done is not None:
            if self._switching:
                return {
                    "ok": True,
                    "pending": True,
                    "url": str(self.state.get("admin_url") or ""),
                }
            self._switching = True

            def _handoff() -> None:
                try:
                    url = str(self._on_setup_done() or "")
                except Exception as exc:
                    logger.exception("セットアップ後の管理画面を開けませんでした")
                    self._switching = False
                    self.state["code"] = 2
                    self._report_handoff_error(str(exc))
                    return
                self.state["admin_url"] = url
                self.state["code"] = 0
                if url:
                    self._load_url_soon(url)

            threading.Thread(
                target=_handoff,
                name="setup-handoff",
                daemon=True,
            ).start()
            return {"ok": True, "pending": True}
        self.state["code"] = 0 if ok else 1
        self.close_app()
        return {"ok": False}

    def _report_handoff_error(self, message: str) -> None:
        window = self._window
        if window is None:
            return
        msg = json.dumps(message)
        js = (
            "(function(){"
            f"var t={msg};"
            "var el=document.getElementById('error');"
            "if(el){el.classList.add('error');el.textContent=t;}"
            "var s=document.getElementById('save');if(s)s.disabled=false;"
            "var c=document.getElementById('choose-save');if(c)c.disabled=false;"
            "})();"
        )
        try:
            evaluate_js = getattr(window, "evaluate_js", None)
            if evaluate_js is not None:
                evaluate_js(js)
        except Exception:
            logger.exception("セットアップ画面へのエラー表示に失敗しました")

    def close_app(self) -> None:
        window = self._window
        self._window = None
        if window is None:
            return
        threading.Thread(
            target=self._destroy_window,
            args=(window,),
            name="close-webview",
            daemon=True,
        ).start()

    def _load_url_soon(self, url: str) -> None:
        window = self._window
        if window is None:
            return

        def _load() -> None:
            time.sleep(_HANDOFF_LOAD_DELAY_SECONDS)
            try:
                window.load_url(url)
            except Exception:
                logger.exception("管理画面への切り替えに失敗しました")
                return
            on_after_load = self._on_after_load
            if on_after_load is not None:
                time.sleep(_SETUP_CLEANUP_DELAY_SECONDS)
                try:
                    on_after_load()
                except Exception:
                    logger.exception("セットアップ用サーバーの停止に失敗しました")

        threading.Thread(target=_load, name="load-admin", daemon=True).start()

    def _destroy_window(self, window: Any) -> None:
        time.sleep(_CLOSE_DELAY_SECONDS)
        try:
            window.destroy()
        except Exception:
            logger.exception("ウィンドウの終了に失敗しました")
        try:
            webview = sys.modules.get("webview")
            if webview is None:
                return
            for extra in list(getattr(webview, "windows", []) or []):
                try:
                    extra.destroy()
                except Exception:
                    logger.exception("追加ウィンドウの終了に失敗しました")
        except Exception:
            pass


def _start_loop() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run, name="palworld-admin-loop", daemon=True)
    thread.start()
    return loop, thread


def _stop_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


def _wait_service_ready(
    service: AdminService, boot_error: list[BaseException], timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if boot_error or service.ready.is_set():
            return
        time.sleep(0.05)


def _open_window(url: str, *, js_api: DesktopBridge | None = None) -> None:
    ensure_splash()
    import webview

    storage = webview_storage_path()
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(storage))
    os.environ.setdefault("PYWEBVIEW_GUI", "edgechromium")

    revealed = False

    def _reveal_window() -> None:
        nonlocal revealed
        if revealed:
            return
        revealed = True
        close_splash()
        try:
            window.show()
        except Exception:
            logger.exception("WebView ウィンドウの表示に失敗しました")

    create_kwargs: dict[str, Any] = {
        "title": WINDOW_TITLE,
        "url": url,
        "width": 1180,
        "height": 780,
        "min_size": (920, 620),
        "js_api": js_api,
        "text_select": True,
    }
    use_hidden = True
    try:
        window = webview.create_window(**create_kwargs, hidden=True)
    except TypeError:
        use_hidden = False
        window = webview.create_window(**create_kwargs)

    if js_api is not None:
        js_api._window = window

    events = getattr(window, "events", None)
    loaded = getattr(events, "loaded", None) if events is not None else None
    shown_event = getattr(events, "shown", None) if events is not None else None
    has_reveal_event = loaded is not None or shown_event is not None

    if loaded is not None:
        loaded += _reveal_window
    elif shown_event is not None:
        shown_event += _reveal_window
    elif use_hidden:
        _reveal_window()

    if use_hidden and has_reveal_event:

        def _timeout_reveal() -> None:
            time.sleep(_REVEAL_TIMEOUT_SECONDS)
            _reveal_window()

        threading.Thread(
            target=_timeout_reveal,
            name="webview-reveal-timeout",
            daemon=True,
        ).start()

    kwargs = {
        "debug": False,
        "http_server": False,
        "private_mode": False,
        "storage_path": str(storage),
        "gui": "edgechromium",
    }
    try:
        try:
            webview.start(**kwargs)
        except TypeError:
            webview.start()
    except Exception:
        close_splash()
        raise
    finally:
        close_splash()


def run_setup_desktop(config_path: str, *, mode: str = "setup") -> int:
    ensure_splash()
    config_file = resolve_user_path(config_path)
    assert config_file is not None
    dest = Path(config_file)
    root = app_root()
    if not dest.is_absolute():
        dest = root / dest
    state: dict[str, Any] = {"code": 1, "note": ""}
    loop, thread = _start_loop()
    runner: Any = None
    fallback = False
    try:
        app = create_setup_app(root, dest, state, mode=mode)

        async def boot() -> tuple[Any, int]:
            local_runner = web_runner(app)
            await local_runner.setup()
            sock = socket.create_server(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
            sock.close()
            site = web_site(local_runner, "127.0.0.1", port)
            await site.start()
            return local_runner, port

        runner, port = asyncio.run_coroutine_threadsafe(boot(), loop).result(timeout=10)
        bridge = DesktopBridge(state)
        try:
            _open_window(f"http://127.0.0.1:{port}/setup.html", js_api=bridge)
        except Exception:
            logger.exception("WebView を開けなかったので、従来のセットアップ画面に切り替えます")
            fallback = True
    finally:
        if runner is not None:
            try:
                asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(timeout=5)
            except Exception:
                logger.exception("セットアップ用サーバーの停止に失敗しました")
        _stop_loop(loop, thread)
        close_splash()
    if fallback:
        from palworld_admin.setup_gui import run_setup_gui

        return run_setup_gui(str(dest), mode=mode)
    return int(state.get("code") or 1)


def run_desktop(
    config_path: str,
    *,
    with_bot: bool = True,
    open_browser: bool = False,
) -> int:
    import webbrowser

    from palworld_admin.gui import _show_error, palserver_boot_mode

    ensure_splash()
    config_file = resolve_user_path(config_path)
    assert config_file is not None
    root = app_root()
    dest = Path(config_file)
    if not dest.is_absolute():
        dest = root / dest

    mode = palserver_boot_mode(str(config_file))
    loop, thread = _start_loop()
    setup_runner: Any = None
    service: AdminService | None = None
    boot_future: Any = None
    boot_error: list[BaseException] = []
    state: dict[str, Any] = {"code": 1}
    webview_failed = False
    bridge = DesktopBridge(state)

    def start_admin_service(config: Any) -> AdminService:
        nonlocal boot_future
        setup_app_logging(config.data_dir, also_console=False)
        local = AdminService(config, config_path=dest)

        async def boot() -> None:
            try:
                await local.run(with_bot=with_bot)
            except Exception as exc:
                boot_error.append(exc)
                logger.exception("管理サービスが異常終了しました")
                local.ready.set()

        boot_future = asyncio.run_coroutine_threadsafe(boot(), loop)
        _wait_service_ready(local, boot_error)
        return local

    def cleanup_setup_runner() -> None:
        nonlocal setup_runner
        runner = setup_runner
        setup_runner = None
        if runner is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(runner.cleanup(), loop).result(timeout=5)
        except Exception:
            logger.exception("セットアップ用サーバーの停止に失敗しました")

    def open_admin_after_setup() -> str:
        nonlocal service
        config = load_config(dest, require_discord_token=False)
        logger.info("管理ツールをデスクトップ画面で起動します")
        service = start_admin_service(config)
        if boot_error:
            raise boot_error[0]
        if not service.ready.is_set():
            raise RuntimeError("管理パネルを起動できませんでした")
        state["code"] = 0
        return service.url

    if mode in {"setup", "choose"}:
        bridge._on_setup_done = open_admin_after_setup
        bridge._on_after_load = cleanup_setup_runner

    try:
        if mode in {"setup", "choose"}:
            app = create_setup_app(root, dest, state, mode=mode)

            async def boot_setup() -> tuple[Any, int]:
                local_runner = web_runner(app)
                await local_runner.setup()
                sock = socket.create_server(("127.0.0.1", 0))
                port = int(sock.getsockname()[1])
                sock.close()
                site = web_site(local_runner, "127.0.0.1", port)
                await site.start()
                return local_runner, port

            setup_runner, port = asyncio.run_coroutine_threadsafe(boot_setup(), loop).result(
                timeout=10
            )
            url = f"http://127.0.0.1:{port}/setup.html"
        else:
            try:
                config = load_config(config_file, require_discord_token=False)
            except ConfigError as exc:
                _show_error("設定エラー", str(exc))
                return 2
            logger.info("管理ツールをデスクトップ画面で起動します")
            service = start_admin_service(config)
            if boot_error:
                _show_error("起動に失敗しました", str(boot_error[0]))
                return 2
            url = service.url
            state["code"] = 0

        if open_browser:
            webbrowser.open(url)
        try:
            _open_window(url, js_api=bridge)
        except Exception as exc:
            webview_failed = True
            logger.exception("WebView を開けませんでした")
            if service is not None:
                webbrowser.open(service.url)
                _show_error(
                    "WebView を開けませんでした",
                    "Edge WebView2 をインストールするか、ブラウザで操作してください。\n" + str(exc),
                )
            else:
                _show_error("WebView を開けませんでした", str(exc))
    finally:
        if setup_runner is not None:
            try:
                asyncio.run_coroutine_threadsafe(setup_runner.cleanup(), loop).result(timeout=5)
            except Exception:
                logger.exception("セットアップ用サーバーの停止に失敗しました")
        if service is not None:
            service.request_stop()
            if boot_future is not None:
                try:
                    boot_future.result(timeout=10)
                except Exception:
                    logger.exception("管理サービスの停止待ちに失敗しました")
        _stop_loop(loop, thread)
        close_splash()

    if webview_failed and mode in {"setup", "choose"} and int(state.get("code") or 1) != 0:
        from palworld_admin.setup_gui import run_setup_gui

        return run_setup_gui(str(dest), mode=mode)
    return 0 if int(state.get("code") or 1) == 0 else int(state.get("code") or 1)


def web_runner(app: Any) -> Any:
    from aiohttp import web

    return web.AppRunner(app)


def web_site(runner: Any, host: str, port: int) -> Any:
    from aiohttp import web

    return web.TCPSite(runner, host, port)
