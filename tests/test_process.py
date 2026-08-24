from pathlib import Path

import pytest

from palworld_discord_bot.process import ProcessError, resolve_start_command


def test_resolve_command_uses_file_in_working_directory(tmp_path: Path) -> None:
    exe = tmp_path / "PalServer.exe"
    exe.write_text("dummy", encoding="utf-8")
    resolved = resolve_start_command(("PalServer.exe", "-port=8211"), tmp_path, os_name="nt")
    assert resolved[0] == str(exe)
    assert resolved[1] == "-port=8211"


def test_resolve_command_rejects_shell_script_on_windows(tmp_path: Path) -> None:
    with pytest.raises(ProcessError, match="PalServer.exe"):
        resolve_start_command(("./PalServer.sh", "-port=8211"), tmp_path, os_name="nt")
