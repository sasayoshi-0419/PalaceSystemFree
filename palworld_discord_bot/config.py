from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import load_dotenv

from palworld_discord_bot.paths import app_root, resolve_user_path


class ConfigError(ValueError):
    """Raised when config.yaml or required secrets are invalid."""


def _yaml_error_message(path: Path, exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    where = f"{path}"
    if mark is not None:
        where = f"{path} の {mark.line + 1} 行目"
    hint = ""
    text = str(exc)
    if "escape" in text.lower():
        hint = (
            " Windows のパスを \"C:\\SteamCMD\\...\" のように二重引用符で書くと、\\ がエスケープになります。"
            ' working_directory: "C:/SteamCMD/steamapps/common/PalServer" のように / にするか、'
            r" 単一引用符 'C:\SteamCMD\steamapps\common\PalServer' を使ってください。"
        )
    return f"{where} の YAML が壊れています。{hint}".strip()


def soften_windows_yaml(text: str) -> str:
    """Turn quoted Windows paths like C:\\Steam into YAML-safe C:/Steam."""

    def _quoted(match: re.Match[str]) -> str:
        return '"' + match.group(1).replace("\\", "/") + '"'

    return re.sub(r'"([^"\n]*)"', _quoted, text)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as first:
        repaired = soften_windows_yaml(text)
        if repaired == text:
            raise ConfigError(_yaml_error_message(path, first)) from first
        try:
            raw = yaml.safe_load(repaired) or {}
        except yaml.YAMLError:
            raise ConfigError(_yaml_error_message(path, first)) from first
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(text, encoding="utf-8")
        path.write_text(repaired, encoding="utf-8")
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} の YAML はマップ形式で書いてください")
    return raw


@dataclass(frozen=True)
class RestartSchedule:
    time: str
    timezone: str
    warn_seconds: int
    message: str

    @property
    def hour_minute(self) -> tuple[int, int]:
        hour_text, minute_text = self.time.split(":", 1)
        return int(hour_text), int(minute_text)


@dataclass(frozen=True)
class ProcessConfig:
    working_directory: Path
    start_command: tuple[str, ...]
    settings_file: Path
    log_file: Path | None
    start_timeout_seconds: int
    stop_timeout_seconds: int
    world_option_sav: Path | None


@dataclass(frozen=True)
class ServerConfig:
    id: str
    name: str
    rest_url: str
    admin_password: str
    join_info: str = ""
    process: ProcessConfig | None = None
    restart_schedule: RestartSchedule | None = None


@dataclass(frozen=True)
class AdminUiConfig:
    bind: str
    port: int


@dataclass(frozen=True)
class DiscordConfig:
    guild_id: int
    status_channel_id: int
    notify_channel_id: int
    notify_role_id: int | None
    owner_user_ids: frozenset[int]
    poll_interval_seconds: int


@dataclass(frozen=True)
class AppConfig:
    discord_token: str
    discord: DiscordConfig | None
    admin: AdminUiConfig
    servers: tuple[ServerConfig, ...]
    data_dir: Path = field(default_factory=lambda: Path(".data"))


def _require_int(raw: Any, key: str) -> int:
    if raw is None:
        raise ConfigError(f"{key} が設定されていません")
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} は整数である必要があります: {raw!r}") from exc


def _optional_int(raw: Any, key: str) -> int | None:
    if raw in (None, "", "null"):
        return None
    return _require_int(raw, key)


def _parse_restart_schedule(raw: Any, prefix: str) -> RestartSchedule | None:
    if not raw:
        return None
    time_text = str(raw.get("time") or "").strip()
    if not time_text or ":" not in time_text:
        raise ConfigError(f"{prefix}.time は HH:MM 形式で書いてください")
    hour, minute = time_text.split(":", 1)
    try:
        hour_n = int(hour)
        minute_n = int(minute)
    except ValueError as exc:
        raise ConfigError(f"{prefix}.time は HH:MM 形式で書いてください") from exc
    if not (0 <= hour_n <= 23 and 0 <= minute_n <= 59):
        raise ConfigError(f"{prefix}.time が範囲外です: {time_text}")
    warn_seconds = _require_int(raw.get("warn_seconds", 120), f"{prefix}.warn_seconds")
    if warn_seconds < 0:
        raise ConfigError(f"{prefix}.warn_seconds は 0 以上にしてください")
    timezone_name = str(raw.get("timezone") or "Asia/Tokyo").strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(
            f"{prefix}.timezone '{timezone_name}' が使えません。"
            "Windows では `pip install tzdata` を実行してください。"
        ) from exc
    return RestartSchedule(
        time=f"{hour_n:02d}:{minute_n:02d}",
        timezone=timezone_name,
        warn_seconds=warn_seconds,
        message=str(raw.get("message") or "定時再起動します").strip(),
    )


def _parse_process(raw: Any, prefix: str, server_id: str, data_dir: Path) -> ProcessConfig | None:
    if not raw:
        return None
    working = Path(str(raw.get("working_directory") or "")).expanduser()
    if not str(raw.get("working_directory") or "").strip():
        raise ConfigError(f"{prefix}.working_directory が空です")
    command_raw = raw.get("start_command")
    if isinstance(command_raw, str):
        command = tuple(shlex.split(command_raw, posix=(os.name != "nt")))
    elif isinstance(command_raw, list):
        command = tuple(str(part) for part in command_raw)
    else:
        raise ConfigError(f"{prefix}.start_command は文字列か配列で書いてください")
    if not command:
        raise ConfigError(f"{prefix}.start_command が空です")
    settings_raw = str(raw.get("settings_file") or "").strip()
    if not settings_raw:
        raise ConfigError(f"{prefix}.settings_file が空です")
    settings_file = Path(settings_raw).expanduser()
    if not settings_file.is_absolute():
        settings_file = working / settings_file
    log_raw = str(raw.get("log_file") or "").strip()
    log_file = None
    if log_raw:
        log_file = Path(log_raw).expanduser()
        if not log_file.is_absolute():
            log_file = data_dir / log_file
    else:
        log_file = data_dir / f"{server_id}-server.log"
    world_raw = str(raw.get("world_option_sav") or "").strip()
    world_option = None
    if world_raw:
        world_option = Path(world_raw).expanduser()
        if not world_option.is_absolute():
            world_option = working / world_option
    start_timeout = _require_int(
        raw.get("start_timeout_seconds", 180), f"{prefix}.start_timeout_seconds"
    )
    stop_timeout = _require_int(
        raw.get("stop_timeout_seconds", 90), f"{prefix}.stop_timeout_seconds"
    )
    return ProcessConfig(
        working_directory=working,
        start_command=command,
        settings_file=settings_file,
        log_file=log_file,
        start_timeout_seconds=start_timeout,
        stop_timeout_seconds=stop_timeout,
        world_option_sav=world_option,
    )


def _parse_admin(raw: Any) -> AdminUiConfig:
    data = raw or {}
    bind = str(data.get("bind") or "127.0.0.1").strip()
    port = _require_int(data.get("port", 8787), "admin.port")
    if not (1 <= port <= 65535):
        raise ConfigError("admin.port が範囲外です")
    allow_lan = bool(data.get("allow_lan", False))
    if bind not in {"127.0.0.1", "localhost", "::1"} and not allow_lan:
        raise ConfigError(
            "管理パネルは既定で localhost のみです。LAN 公開が必要なら admin.allow_lan: true を書いてください。"
        )
    return AdminUiConfig(bind=bind, port=port)


def _parse_discord(raw: Any, *, required: bool) -> DiscordConfig | None:
    if not raw:
        if required:
            raise ConfigError("discord が設定されていません")
        return None
    if not required and raw.get("guild_id") in (None, "", 0):
        return None
    poll_interval = _require_int(
        raw.get("poll_interval_seconds", 20),
        "discord.poll_interval_seconds",
    )
    if poll_interval < 5:
        raise ConfigError("discord.poll_interval_seconds は 5 秒以上にしてください")
    return DiscordConfig(
        guild_id=_require_int(raw.get("guild_id"), "discord.guild_id"),
        status_channel_id=_require_int(
            raw.get("status_channel_id"), "discord.status_channel_id"
        ),
        notify_channel_id=_require_int(
            raw.get("notify_channel_id"), "discord.notify_channel_id"
        ),
        notify_role_id=_optional_int(raw.get("notify_role_id"), "discord.notify_role_id"),
        owner_user_ids=frozenset(
            _require_int(user_id, "discord.owner_user_ids[]")
            for user_id in raw.get("owner_user_ids") or []
        ),
        poll_interval_seconds=poll_interval,
    )


def load_config(
    config_path: Path | str = "config.yaml",
    *,
    dotenv_path: Path | str | None = ".env",
    require_discord_token: bool = True,
) -> AppConfig:
    env_file = resolve_user_path(dotenv_path)
    if env_file is not None:
        load_dotenv(env_file)

    path = resolve_user_path(config_path)
    assert path is not None
    if not path.is_file():
        raise ConfigError(
            f"{path} が見つかりません。初回はセットアップ画面か `python -m palworld_admin setup` で"
            " config.yaml を作ってください。"
        )

    raw = _load_yaml_mapping(path)

    data_dir = Path(str(raw.get("data_dir") or ".data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = app_root() / data_dir
    discord = _parse_discord(raw.get("discord"), required=require_discord_token)
    admin = _parse_admin(raw.get("admin"))

    servers_raw = raw.get("servers") or []
    if not servers_raw:
        raise ConfigError("servers が空です。1 台以上の Palworld サーバーを書いてください。")

    servers: list[ServerConfig] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(servers_raw):
        server_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        rest_url = str(item.get("rest_url") or "").strip().rstrip("/")
        env_name = str(item.get("admin_password_env") or "").strip()
        prefix = f"servers[{index}]"
        if not server_id:
            raise ConfigError(f"{prefix}.id が空です")
        if server_id in seen_ids:
            raise ConfigError(f"サーバー ID が重複しています: {server_id}")
        seen_ids.add(server_id)
        if not name:
            raise ConfigError(f"{prefix}.name が空です")
        if not rest_url:
            raise ConfigError(f"{prefix}.rest_url が空です")
        if not env_name:
            raise ConfigError(f"{prefix}.admin_password_env が空です")
        password = os.getenv(env_name, "").strip()
        if not password:
            raise ConfigError(
                f"{env_name} が環境変数にありません。.env に AdminPassword を書いてください。"
            )
        servers.append(
            ServerConfig(
                id=server_id,
                name=name,
                rest_url=rest_url,
                admin_password=password,
                join_info=str(item.get("join_info") or "").strip(),
                process=_parse_process(item.get("process"), f"{prefix}.process", server_id, data_dir),
                restart_schedule=_parse_restart_schedule(
                    item.get("restart_schedule"), f"{prefix}.restart_schedule"
                ),
            )
        )

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if require_discord_token and not token:
        raise ConfigError("DISCORD_TOKEN が環境変数にありません。.env を確認してください。")

    return AppConfig(
        discord_token=token,
        discord=discord,
        admin=admin,
        servers=tuple(servers),
        data_dir=data_dir,
    )
