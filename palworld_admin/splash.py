from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable

from palworld_discord_bot.paths import is_frozen

_splash_process: subprocess.Popen[bytes] | None = None
_popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen


def run_standalone() -> None:
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Home Server Admin")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.grid(row=0, column=0, sticky="nsew")
    ttk.Label(frame, text="起動しています…", font=("Segoe UI", 12)).grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        frame,
        text="初回やビルド直後は、画面の準備に少し時間がかかります。",
        font=("Segoe UI", 9),
        wraplength=320,
    ).grid(row=1, column=0, sticky="w", pady=(8, 0))
    root.update_idletasks()
    root.geometry(f"+{root.winfo_screenwidth() // 2 - 180}+{root.winfo_screenheight() // 2 - 60}")
    root.mainloop()


def start_splash_process() -> None:
    global _splash_process
    if os.environ.get("HOMESERVER_NOSPLASH") == "1":
        return
    if not is_frozen():
        return
    if _splash_process is not None and _splash_process.poll() is None:
        return
    _splash_process = _popen_factory(
        [sys.executable, "--splash-only"],
        close_fds=True,
    )


def close_splash() -> None:
    global _splash_process
    proc = _splash_process
    _splash_process = None
    if proc is None:
        return
    try:
        proc.terminate()
    except Exception:
        pass


def ensure_splash() -> None:
    start_splash_process()
