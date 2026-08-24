import logging
from pathlib import Path

from palworld_discord_bot.applog import recent_logs, setup_app_logging


def test_memory_and_file_logs(tmp_path: Path) -> None:
    setup_app_logging(tmp_path, also_console=False)
    logging.getLogger("test.logger").info("hello-from-app")
    lines = recent_logs(50)
    assert any("hello-from-app" in line for line in lines)
    written = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "hello-from-app" in written


def test_console_logging(tmp_path: Path, capsys) -> None:
    setup_app_logging(tmp_path, also_console=True)
    logging.getLogger("test.logger").warning("console-visible")
    captured = capsys.readouterr()
    assert "console-visible" in captured.err + captured.out
