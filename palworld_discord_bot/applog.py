from __future__ import annotations

import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

_MARKER = "palworld_app_log"


class MemoryLogHandler(logging.Handler):
    def __init__(self, maxlen: int = 800) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.handleError(record)


_memory: MemoryLogHandler | None = None


def _tagged(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _MARKER, True)
    return handler


def setup_app_logging(
    data_dir: Path,
    *,
    also_console: bool,
    stream: TextIO | None = None,
) -> MemoryLogHandler:
    global _memory
    data_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, _MARKER, False):
            root.removeHandler(handler)
            handler.close()
    memory = MemoryLogHandler()
    memory.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        data_dir / "app.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(_tagged(memory))
    root.addHandler(_tagged(file_handler))
    if also_console:
        console = logging.StreamHandler(stream)
        console.setFormatter(formatter)
        root.addHandler(_tagged(console))
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    _memory = memory
    return memory


def recent_logs(limit: int = 200) -> list[str]:
    if _memory is None:
        return []
    lines = list(_memory.lines)
    if limit <= 0:
        return lines
    return lines[-limit:]
