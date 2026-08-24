from __future__ import annotations

import asyncio
import logging
import threading
import time
import webbrowser

from palworld_admin.service import AdminService
from palworld_discord_bot.applog import recent_logs, setup_app_logging
from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.paths import resolve_user_path

logger = logging.getLogger(__name__)


def _show_error(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        logger.error("%s: %s", title, message)


def palserver_boot_mode(config_path: str) -> str:
    from palworld_discord_bot.detect import needs_palserver_picker

    config_file = resolve_user_path(config_path)
    assert config_file is not None
    if not config_file.is_file():
        return "setup"
    try:
        config = load_config(config_file, require_discord_token=False)
    except ConfigError:
        return "admin"
    working = None
    if config.servers and config.servers[0].process is not None:
        working = config.servers[0].process.working_directory
    if needs_palserver_picker(working):
        return "choose"
    return "admin"


def run_setup_window(config_path: str, *, mode: str = "setup") -> int:
    try:
        import webview  # noqa: F401
    except ImportError:
        from palworld_admin.setup_gui import run_setup_gui

        return run_setup_gui(config_path, mode=mode)
    from palworld_admin.desktop import run_setup_desktop

    return run_setup_desktop(config_path, mode=mode)


def ensure_palserver_config(config_path: str, *, use_desktop: bool) -> int:
    mode = palserver_boot_mode(config_path)
    if mode == "admin":
        return 0
    if use_desktop:
        return run_setup_window(config_path, mode=mode)
    return _run_tk_setup(config_path, mode=mode)


def _run_tk_setup(config_path: str, *, mode: str = "setup") -> int:
    from palworld_admin.setup_gui import run_setup_gui

    return run_setup_gui(config_path, mode=mode)


def run_gui(
    config_path: str,
    *,
    with_bot: bool = True,
    open_browser: bool = False,
) -> int:
    try:
        import webview  # noqa: F401
    except ImportError:
        logger.warning("pywebview がないので、従来のログ画面と外部ブラウザで起動します")
        return run_legacy_gui(config_path, with_bot=with_bot, open_browser=True)
    from palworld_admin.desktop import run_desktop

    return run_desktop(config_path, with_bot=with_bot, open_browser=open_browser)


def run_legacy_gui(
    config_path: str,
    *,
    with_bot: bool = True,
    open_browser: bool = True,
) -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        _show_error("起動できません", "画面を出せません。Python に tkinter が入っているか確認してください。")
        return 2

    config_file = resolve_user_path(config_path)
    assert config_file is not None
    setup_code = ensure_palserver_config(str(config_file), use_desktop=False)
    if setup_code != 0:
        return setup_code

    try:
        config = load_config(config_file, require_discord_token=False)
    except ConfigError as exc:
        _show_error("設定エラー", str(exc))
        return 2

    setup_app_logging(config.data_dir, also_console=False)
    logger.info("管理ツールを画面モードで起動します")

    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, name="palworld-admin-loop", daemon=True)
    thread.start()
    service = AdminService(config, config_path=config_file)
    boot_error: list[BaseException] = []

    async def boot() -> None:
        try:
            await service.run(with_bot=with_bot)
        except Exception as exc:
            boot_error.append(exc)
            logger.exception("管理サービスが異常終了しました")
            service.ready.set()

    boot_future = asyncio.run_coroutine_threadsafe(boot(), loop)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if boot_error or service.ready.is_set():
            break
        time.sleep(0.05)
    if boot_error:
        _show_error("起動に失敗しました", str(boot_error[0]))
        service.request_stop()
        try:
            boot_future.result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        return 2

    if open_browser:
        webbrowser.open(service.url)

    root = tk.Tk()
    root.title("Home Server Admin")
    root.geometry("720x480")
    root.minsize(520, 360)

    header = ttk.Frame(root, padding=12)
    header.pack(fill="x")
    ttk.Label(header, text="WebView が使えないため、ログ画面とブラウザで開いています。").pack(anchor="w")
    ttk.Label(header, text=service.url).pack(anchor="w")

    buttons = ttk.Frame(root, padding=(12, 0))
    buttons.pack(fill="x")

    def open_panel() -> None:
        webbrowser.open(service.url)

    def shutdown() -> None:
        logger.info("終了ボタンが押されました")
        service.request_stop()
        root.after(400, root.destroy)

    ttk.Button(buttons, text="管理パネルを開く", command=open_panel).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="終了", command=shutdown).pack(side="left")

    log_view = ScrolledText(root, wrap="word", height=18, state="disabled")
    log_view.pack(fill="both", expand=True, padx=12, pady=12)
    shown = 0

    def pump_logs() -> None:
        nonlocal shown
        if service.finished:
            root.destroy()
            return
        lines = recent_logs(0)
        if len(lines) < shown:
            shown = 0
            log_view.configure(state="normal")
            log_view.delete("1.0", "end")
            log_view.configure(state="disabled")
        if len(lines) > shown:
            log_view.configure(state="normal")
            log_view.insert("end", "\n".join(lines[shown:]) + "\n")
            log_view.see("end")
            log_view.configure(state="disabled")
            shown = len(lines)
        root.after(400, pump_logs)

    def on_close() -> None:
        shutdown()

    root.protocol("WM_DELETE_WINDOW", on_close)
    pump_logs()
    root.mainloop()
    service.request_stop()
    try:
        boot_future.result(timeout=10)
    except Exception:
        logger.exception("管理サービスの停止待ちに失敗しました")
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    return 0
