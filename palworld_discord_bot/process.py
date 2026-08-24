from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from palworld_discord_bot.config import ProcessConfig

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class ProcessError(RuntimeError):
    """Raised when a dedicated-server process cannot be started or stopped."""


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return int(code.value) == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def resolve_start_command(
    command: tuple[str, ...],
    working_directory: Path,
    *,
    os_name: str = os.name,
) -> list[str]:
    if not command:
        raise ProcessError("start_command が空です")
    cmd = [str(part) for part in command]
    first = cmd[0]
    name = Path(first.replace("\\", "/")).name.lower()
    if os_name == "nt" and name.endswith(".sh"):
        raise ProcessError(
            "Windows では PalServer.sh は使えません。"
            "start_command に PalServer.exe を指定し、"
            "settings_file は Pal/Saved/Config/WindowsServer/PalWorldSettings.ini にしてください。"
        )
    path = Path(first)
    if path.is_file():
        return cmd
    nested = working_directory / first
    if nested.is_file():
        cmd[0] = str(nested)
        return cmd
    if os_name == "nt":
        exe_name = first if first.lower().endswith(".exe") else f"{Path(first).name}.exe"
        exe = working_directory / Path(exe_name).name
        if exe.is_file():
            cmd[0] = str(exe)
    return cmd


class ProcessController:
    def __init__(self, process: ProcessConfig, pid_path: Path) -> None:
        self.process = process
        self.pid_path = pid_path
        self._proc: subprocess.Popen[bytes] | None = None

    def read_pid(self) -> int | None:
        if self._proc is not None:
            if self._proc.poll() is None:
                return self._proc.pid
            self.clear_pid()
            self._proc = None
            return None
        if not self.pid_path.is_file():
            return None
        try:
            pid = int(self.pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        if not pid_is_alive(pid):
            self.clear_pid()
            return None
        return pid

    def write_pid(self, pid: int) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(pid), encoding="utf-8")

    def clear_pid(self) -> None:
        try:
            self.pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    def is_running(self) -> bool:
        return self.read_pid() is not None

    def child_exit_code(self) -> int | None:
        if self._proc is None:
            return None
        return self._proc.poll()

    def log_tail(self, limit: int = 30) -> str:
        path = self.process.log_file
        if path is None or not path.is_file():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(lines[-limit:]).strip()

    def start(self) -> int:
        if self.is_running():
            raise ProcessError(
                "プロセスはすでに起動しています。"
                "管理パネルの状態がオフラインでも、別のウィンドウで PalServer が動いていることがあります。"
            )
        if not self.process.working_directory.is_dir():
            raise ProcessError(
                f"PalServer フォルダがありません: {self.process.working_directory}。"
                "フォルダの場所を確認するか、初回セットアップで正しい PalServer フォルダを選び直してください。"
            )
        command = resolve_start_command(
            self.process.start_command, self.process.working_directory
        )
        log_handle = None
        stdout: int | object = subprocess.DEVNULL
        if self.process.log_file is not None:
            self.process.log_file.parent.mkdir(parents=True, exist_ok=True)
            log_handle = self.process.log_file.open("ab")
            stdout = log_handle
        popen_kwargs: dict[str, object] = {
            "cwd": str(self.process.working_directory),
            "stdout": stdout,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            popen_kwargs["close_fds"] = False
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
            popen_kwargs["close_fds"] = True
        try:
            proc = subprocess.Popen(command, **popen_kwargs)
        except FileNotFoundError as exc:
            raise ProcessError(
                f"起動ファイルが見つかりません: {command[0]}。"
                f"working_directory ({self.process.working_directory}) に PalServer.exe があるか確認してください。"
            ) from exc
        except OSError as exc:
            raise ProcessError(f"起動コマンドを実行できません: {exc}") from exc
        finally:
            if log_handle is not None:
                log_handle.close()
        self._proc = proc
        self.write_pid(proc.pid)
        return proc.pid

    def terminate(self) -> None:
        pid = self.read_pid()
        if pid is None:
            return
        _terminate_pid(pid)
        if self._proc is not None:
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if not pid_is_alive(pid):
            self._proc = None
            self.clear_pid()


def _terminate_pid(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
