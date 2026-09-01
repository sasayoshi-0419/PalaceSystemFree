from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def marker_path(data_dir: Path, server_id: str) -> Path:
    """有料 watchdog と共有する意図停止マーカー。中身は見ない。存在だけが契約。"""
    return data_dir / f"{server_id}.user-stopped"


def mark_user_stopped(data_dir: Path, server_id: str) -> None:
    path = marker_path(data_dir, server_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    except OSError as exc:
        logger.warning("ユーザー停止マーカーの作成に失敗しました: %s (%s)", path, exc)


def clear_user_stopped(data_dir: Path, server_id: str) -> None:
    path = marker_path(data_dir, server_id)
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        logger.warning("ユーザー停止マーカーの削除に失敗しました: %s (%s)", path, exc)
