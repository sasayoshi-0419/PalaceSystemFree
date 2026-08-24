from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from palworld_discord_bot.config import ConfigError, _load_yaml_mapping
from palworld_discord_bot.detect import (
    default_settings_file,
    describe_palserver,
    find_palserver_directories,
    has_server_binary,
    start_command_for,
)
from palworld_discord_bot.settings_ini import SettingsError, bootstrap_rest_api


def add_setup_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--yes", action="store_true", help="質問せず既定値で書き出す")
    parser.add_argument("--force", action="store_true", help="既存の config.yaml を上書きする")
    parser.add_argument("--palserver", help="PalServer フォルダ")
    parser.add_argument("--name", default="本鯖")
    parser.add_argument("--server-id", default="main")
    parser.add_argument("--port", type=int, default=8211, help="ゲームの接続ポート")
    parser.add_argument("--rest-port", type=int, default=8212)
    parser.add_argument("--admin-password", help="REST API / AdminPassword")
    parser.add_argument("--join-info", default="")
    parser.add_argument("--skip-discord", action="store_true")
    parser.add_argument("--discord-token")
    parser.add_argument("--guild-id", type=int)
    parser.add_argument("--status-channel-id", type=int)
    parser.add_argument("--notify-channel-id", type=int)
    parser.add_argument("--owner-user-id", type=int)


def _posix(path: Path) -> str:
    return path.expanduser().resolve().as_posix()


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def require_palserver_folder(path: Path) -> Path:
    folder = path.expanduser()
    try:
        folder = folder.resolve()
    except OSError:
        pass
    if not folder.is_dir():
        raise ConfigError(f"PalServer フォルダがありません: {folder}")
    if not has_server_binary(folder):
        raise ConfigError(
            f"{folder} に PalServer.exe / PalServer.sh がありません。"
            "専用サーバーのフォルダを選んでください。"
        )
    return folder


def game_port_from_command(command: Any, default: int = 8211) -> int:
    if isinstance(command, str):
        parts = command.split()
    elif isinstance(command, (list, tuple)):
        parts = [str(part) for part in command]
    else:
        return default
    for part in parts:
        if part.startswith("-port="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return default
    return default


def _choose_palserver(explicit: str | None, *, auto: bool) -> Path:
    if explicit:
        return require_palserver_folder(Path(explicit))
    found = find_palserver_directories()
    if auto:
        if len(found) == 1:
            return found[0]
        if not found:
            raise ConfigError(
                "PalServer フォルダが見つかりません。--palserver でフォルダを指定してください。"
            )
        listing = "\n".join(f"  {path}" for path in found)
        raise ConfigError(f"PalServer フォルダが複数あります。--palserver で選んでください:\n{listing}")
    if found:
        print("見つかった PalServer:")
        for index, path in enumerate(found, start=1):
            info = describe_palserver(path)
            saves = " / セーブあり" if info["has_saves"] else ""
            print(f"  {index}) {info['label']}: {path}{saves}")
        default = "1" if len(found) == 1 else ""
        choice = _ask("番号を選ぶか、フォルダを貼り付けてください", default)
        if not choice:
            raise ConfigError("PalServer フォルダを選んでください")
        if choice.isdigit() and 1 <= int(choice) <= len(found):
            return found[int(choice) - 1]
        return require_palserver_folder(Path(choice))
    typed = _ask("PalServer フォルダのパス")
    if not typed:
        raise ConfigError("PalServer フォルダのパスを入力してください")
    return require_palserver_folder(Path(typed))


def _merge_env(path: Path, updates: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    order: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            existing[key.strip()] = value
            order.append(key.strip())
    for key, value in updates.items():
        existing[key] = value
        if key not in order:
            order.append(key)
    lines = [
        "# setup が書き出した環境変数です。パスワードとトークンはここにだけ置きます。",
        *[f"{key}={existing[key]}" for key in order],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _validate_restart_time(time_text: str) -> str:
    text = str(time_text or "").strip()
    if not text or ":" not in text:
        raise ConfigError("定時再起動の時刻は HH:MM 形式で書いてください")
    parts = text.split(":")
    if len(parts) < 2:
        raise ConfigError("定時再起動の時刻は HH:MM 形式で書いてください")
    hour, minute = parts[0], parts[1]
    try:
        hour_n = int(hour)
        minute_n = int(minute)
    except ValueError as exc:
        raise ConfigError("定時再起動の時刻は HH:MM 形式で書いてください") from exc
    if not (0 <= hour_n <= 23 and 0 <= minute_n <= 59):
        raise ConfigError(f"定時再起動の時刻が範囲外です: {text}")
    return f"{hour_n:02d}:{minute_n:02d}"


def _restart_enabled_from_mapping(data: dict[str, Any], *, default: bool = True) -> bool:
    if "restart_enabled" not in data:
        return default
    raw = data.get("restart_enabled")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    text = str(raw).strip().lower()
    if text in {"false", "0", "no", "off"}:
        return False
    if text in {"true", "1", "yes", "on"}:
        return True
    return default


def _default_restart_schedule(time_text: str = "05:00") -> dict[str, Any]:
    return {
        "time": _validate_restart_time(time_text),
        "timezone": "Asia/Tokyo",
        "warn_seconds": 120,
        "message": "定時再起動します",
    }


def _restart_schedule_from_mapping(
    data: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
    default_enabled: bool = True,
) -> dict[str, Any] | None:
    if not _restart_enabled_from_mapping(data, default=default_enabled):
        return None
    if isinstance(existing, dict):
        schedule = {
            "time": str(existing.get("time") or "05:00").strip() or "05:00",
            "timezone": str(existing.get("timezone") or "Asia/Tokyo").strip() or "Asia/Tokyo",
            "warn_seconds": existing.get("warn_seconds", 120),
            "message": str(existing.get("message") or "定時再起動します").strip() or "定時再起動します",
        }
    else:
        schedule = _default_restart_schedule()
    restart_time = str(data.get("restart_time") or "").strip()
    if restart_time:
        schedule["time"] = _validate_restart_time(restart_time)
    else:
        schedule["time"] = _validate_restart_time(schedule["time"])
    return schedule


def build_config_payload(
    *,
    palserver: Path,
    server_id: str,
    name: str,
    game_port: int,
    rest_port: int,
    join_info: str,
    restart_schedule: dict[str, Any] | None = None,
    discord: dict[str, Any] | None,
) -> dict[str, Any]:
    working = palserver.expanduser().resolve()
    settings = default_settings_file(working)
    try:
        settings_rel = settings.relative_to(working).as_posix()
    except ValueError:
        settings_rel = _posix(settings)
    payload: dict[str, Any] = {
        "admin": {"bind": "127.0.0.1", "port": 8787, "allow_lan": False},
        "servers": [
            {
                "id": server_id,
                "name": name,
                "rest_url": f"http://127.0.0.1:{rest_port}",
                "admin_password_env": "PAL_MAIN_ADMIN_PASSWORD",
                "join_info": join_info,
                "process": {
                    "working_directory": _posix(working),
                    "start_command": start_command_for(working, game_port),
                    "settings_file": settings_rel,
                    "start_timeout_seconds": 180,
                    "stop_timeout_seconds": 90,
                },
            }
        ],
    }
    if restart_schedule is not None:
        payload["servers"][0]["restart_schedule"] = restart_schedule
    if discord:
        payload["discord"] = discord
    return payload


def write_config_yaml(path: Path, payload: dict[str, Any]) -> None:
    body = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False)
    path.write_text(
        "# setup コマンドが生成した設定です。Windows のパスは / 区切りです。\n" + body,
        encoding="utf-8",
    )


def apply_setup(
    *,
    root: Path,
    config_path: Path,
    palserver: Path,
    password: str,
    name: str = "本鯖",
    server_id: str = "main",
    game_port: int = 8211,
    rest_port: int = 8212,
    join_info: str = "",
    restart_schedule: dict[str, Any] | None = None,
    discord: dict[str, Any] | None = None,
    discord_token: str = "",
) -> str:
    """Write config.yaml and .env. Returns a note about REST API setup."""
    palserver = require_palserver_folder(palserver)
    if not password.strip():
        raise ConfigError("AdminPassword / REST パスワードが空です")
    payload = build_config_payload(
        palserver=palserver,
        server_id=server_id,
        name=name,
        game_port=game_port,
        rest_port=rest_port,
        join_info=join_info,
        restart_schedule=restart_schedule,
        discord=discord,
    )
    write_config_yaml(config_path, payload)
    env_updates = {"PAL_MAIN_ADMIN_PASSWORD": password.strip()}
    token = discord_token.strip()
    if token:
        env_updates["DISCORD_TOKEN"] = token
    _merge_env(root / ".env", env_updates)
    settings = default_settings_file(palserver)
    rest_note = (
        "PalWorldSettings.ini がまだないので、サーバーを一度起動してから setup を再実行するか、"
        "ini を手で直してください。"
    )
    if settings.is_file():
        try:
            bootstrap_rest_api(settings, password.strip(), rest_port)
            rest_note = f"REST API を有効にしました: {settings}"
        except SettingsError as exc:
            rest_note = f"REST API の自動設定に失敗しました: {exc}"
    return rest_note


def _resolve_discord_token(root: Path, data: dict[str, Any]) -> str:
    token = str(data.get("discord_token") or "").strip()
    if token:
        return token
    env_path = root / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DISCORD_TOKEN":
                return value.strip()
    return os.getenv("DISCORD_TOKEN", "").strip()


def _parse_discord_owner_user_ids(
    owner_raw: str,
    existing_discord: dict[str, Any] | None,
) -> list[int]:
    existing_ids: list[int] = []
    if isinstance(existing_discord, dict):
        for uid in existing_discord.get("owner_user_ids") or []:
            try:
                existing_ids.append(int(uid))
            except (TypeError, ValueError):
                pass
    if not owner_raw:
        return existing_ids
    try:
        new_id = int(owner_raw)
    except (TypeError, ValueError):
        raise ConfigError("ユーザー ID は数字で書いてください")
    if existing_ids:
        if new_id in existing_ids:
            return existing_ids
        return [new_id]
    return [new_id]


def _parse_discord_mapping_fields(
    data: dict[str, Any],
    token: str,
    *,
    existing_discord: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not token:
        raise ConfigError("DISCORD_TOKEN が空です")
    guild_raw = str(data.get("guild_id") or "").strip()
    status_raw = str(data.get("status_channel_id") or "").strip()
    notify_raw = str(data.get("notify_channel_id") or "").strip()
    owner_raw = str(data.get("owner_user_id") or "").strip()
    if not guild_raw or not status_raw:
        raise ConfigError("サーバー ID と状況チャンネル ID が必要です")
    try:
        status_id = int(status_raw)
        guild_id = int(guild_raw)
        notify_id = int(notify_raw) if notify_raw else status_id
    except (TypeError, ValueError):
        raise ConfigError("サーバー ID とチャンネル ID は数字で書いてください")
    return {
        "guild_id": guild_id,
        "status_channel_id": status_id,
        "notify_channel_id": notify_id,
        "notify_role_id": None,
        "owner_user_ids": _parse_discord_owner_user_ids(owner_raw, existing_discord),
        "poll_interval_seconds": 20,
    }


def apply_discord_from_mapping(root: Path, config_path: Path, data: dict[str, Any]) -> str:
    if not config_path.is_file():
        raise ConfigError(f"{config_path} がありません")
    raw = _load_yaml_mapping(config_path)
    token = _resolve_discord_token(root, data)
    existing_discord = raw.get("discord")
    fields = _parse_discord_mapping_fields(
        data,
        token,
        existing_discord=existing_discord if isinstance(existing_discord, dict) else None,
    )
    if isinstance(existing_discord, dict):
        if "notify_role_id" in existing_discord:
            fields["notify_role_id"] = existing_discord.get("notify_role_id")
        if "poll_interval_seconds" in existing_discord:
            fields["poll_interval_seconds"] = existing_discord.get("poll_interval_seconds")
    raw["discord"] = fields
    write_config_yaml(config_path, raw)
    _merge_env(root / ".env", {"DISCORD_TOKEN": token})
    os.environ["DISCORD_TOKEN"] = token
    return "Discord 設定を書き出しました"


def retarget_palserver(config_path: Path, palserver: Path) -> str:
    """Point an existing config.yaml at another PalServer folder. Keeps Discord and passwords."""
    if not str(palserver).strip() or str(palserver).strip() in {".", "./"}:
        raise ConfigError("PalServer フォルダを指定してください")
    working = require_palserver_folder(palserver)
    if not config_path.is_file():
        raise ConfigError(f"{config_path} がありません")
    raw = _load_yaml_mapping(config_path)
    servers = raw.get("servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict):
        raise ConfigError("servers がありません。先にセットアップしてください。")
    process = servers[0].get("process")
    if not isinstance(process, dict):
        process = {}
        servers[0]["process"] = process
    port = game_port_from_command(process.get("start_command"), 8211)
    process["working_directory"] = _posix(working)
    process["start_command"] = start_command_for(working, port)
    settings = default_settings_file(working)
    try:
        process["settings_file"] = settings.relative_to(working).as_posix()
    except ValueError:
        process["settings_file"] = _posix(settings)
    write_config_yaml(config_path, raw)
    return f"サーバーファイルを {working.as_posix()} にしました"


def apply_server_ops_from_mapping(config_path: Path, server_id: str, data: dict[str, Any]) -> str:
    if not config_path.is_file():
        raise ConfigError(f"{config_path} がありません")
    raw = _load_yaml_mapping(config_path)
    servers = raw.get("servers")
    if not isinstance(servers, list):
        raise ConfigError("servers がありません")
    target: dict[str, Any] | None = None
    for item in servers:
        if isinstance(item, dict) and str(item.get("id") or "") == server_id:
            target = item
            break
    if target is None:
        raise ConfigError(f"サーバー {server_id} がありません")
    target["join_info"] = str(data.get("join_info") or "").strip()
    existing = target.get("restart_schedule")
    existing_dict = existing if isinstance(existing, dict) else None
    restart_schedule = _restart_schedule_from_mapping(
        data,
        existing=existing_dict,
        default_enabled=existing_dict is not None,
    )
    if restart_schedule is None:
        target.pop("restart_schedule", None)
    else:
        target["restart_schedule"] = restart_schedule
    write_config_yaml(config_path, raw)
    return "入り方と定時再起動を保存しました"


def apply_setup_from_mapping(root: Path, config_path: Path, data: dict[str, Any]) -> str:
    raw = str(data.get("palserver") or "").strip()
    if not raw:
        raise ConfigError("PalServer フォルダを指定してください")
    palserver = require_palserver_folder(Path(raw))
    password = str(data.get("password") or "").strip()
    name = str(data.get("name") or "本鯖").strip() or "本鯖"
    game_port = int(str(data.get("game_port") or "8211").strip() or "8211")
    rest_port = int(str(data.get("rest_port") or "8212").strip() or "8212")
    join_info = str(data.get("join_info") or "").strip()
    restart_schedule = _restart_schedule_from_mapping(data)
    discord_payload = None
    token = str(data.get("discord_token") or "").strip()
    if data.get("discord"):
        discord_payload = _parse_discord_mapping_fields(data, token)
    return apply_setup(
        root=root,
        config_path=config_path,
        palserver=palserver,
        password=password,
        name=name,
        game_port=game_port,
        rest_port=rest_port,
        join_info=join_info,
        restart_schedule=restart_schedule,
        discord=discord_payload,
        discord_token=token,
    )


def run_setup(
    args: argparse.Namespace,
    *,
    cwd: Path | None = None,
    stdin_interactive: bool | None = None,
) -> int:
    root = cwd or Path.cwd()
    config_path = Path(getattr(args, "config", "config.yaml"))
    if not config_path.is_absolute():
        config_path = root / config_path
    auto = bool(args.yes) if stdin_interactive is None else not stdin_interactive
    if config_path.exists() and not args.force and auto:
        raise ConfigError(f"{config_path} は既にあります。上書きするには --force を付けてください。")
    if config_path.exists() and not args.force and not auto:
        confirm = _ask(f"{config_path.name} を上書きしますか? (y/N)", "N")
        if confirm.lower() not in {"y", "yes"}:
            print("中止しました")
            return 1

    palserver = _choose_palserver(args.palserver, auto=auto)

    name = args.name
    server_id = args.server_id
    game_port = args.port
    rest_port = args.rest_port
    join_info = args.join_info
    password = args.admin_password or os.getenv("PAL_MAIN_ADMIN_PASSWORD", "").strip()
    if not auto:
        name = _ask("サーバー表示名", name)
        game_port = int(_ask("ゲームポート", str(game_port)))
        rest_port = int(_ask("REST API ポート", str(rest_port)))
        join_info = _ask("友達への入り方 (空なら未設定)", join_info)
        if not password:
            password = getpass.getpass("AdminPassword / REST パスワード: ").strip()
    if not password:
        raise ConfigError("--admin-password か環境変数 PAL_MAIN_ADMIN_PASSWORD が必要です")

    discord_payload = None
    token = args.discord_token or os.getenv("DISCORD_TOKEN", "").strip()
    use_discord = not args.skip_discord
    if not auto:
        answer = _ask("Discord ボットも設定しますか? (y/N)", "N")
        use_discord = answer.lower() in {"y", "yes"}
        if use_discord and not token:
            token = _ask("DISCORD_TOKEN")
    if use_discord:
        guild_id = args.guild_id
        status_id = args.status_channel_id
        notify_id = args.notify_channel_id or status_id
        owner_id = args.owner_user_id
        if not auto:
            guild_id = int(_ask("サーバー ID (guild_id)", str(guild_id or "")))
            status_id = int(_ask("状況チャンネル ID", str(status_id or "")))
            notify_id = int(_ask("通知チャンネル ID (空なら状況と同じ)", str(notify_id or status_id)))
            owner_id = int(_ask("あなたのユーザー ID", str(owner_id or "")))
        if not token or not guild_id or not status_id:
            raise ConfigError("Discord を使う場合はトークンと guild_id、status_channel_id が必要です")
        discord_payload = {
            "guild_id": guild_id,
            "status_channel_id": status_id,
            "notify_channel_id": notify_id or status_id,
            "notify_role_id": None,
            "owner_user_ids": [owner_id] if owner_id else [],
            "poll_interval_seconds": 20,
        }

    restart_schedule = _default_restart_schedule()
    rest_note = apply_setup(
        root=root,
        config_path=config_path,
        palserver=palserver,
        password=password,
        name=name,
        server_id=server_id,
        game_port=game_port,
        rest_port=rest_port,
        join_info=join_info,
        restart_schedule=restart_schedule,
        discord=discord_payload,
        discord_token=token,
    )

    print(f"書き出しました: {config_path}")
    print(f"書き出しました: {root / '.env'}")
    print(rest_note)
    print("別ウィンドウで、次のコマンドを実行してください:")
    print("  python -m palworld_admin")
    if discord_payload:
        print("  python -m palworld_discord_bot --invite")
        print("  python -m palworld_discord_bot")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="無料版の初回セットアップ（config.yaml と .env を作る）")
    parser.add_argument("--config", default="config.yaml")
    add_setup_arguments(parser)
    args = parser.parse_args(argv)
    try:
        return run_setup(args)
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

