from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.paths import is_frozen, prepare_frozen_cwd, resolve_user_path
from palworld_discord_bot.setup import add_setup_arguments, run_setup
from palworld_discord_bot.operations import OperationError
from palworld_discord_bot.settings_ini import COMMON_KEYS
from palworld_discord_bot.steamcmd import (
    SteamCmdError,
    default_install_directory,
    install_steamcmd,
)
from palworld_admin.runtime import AdminRuntime
from palworld_admin.service import AdminService
from palworld_discord_bot.applog import setup_app_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="サーバー PC で動かす Palworld 管理ツール（起動・定時再起動・設定変更）"
    )
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("web", help="localhost の管理パネルと定時再起動を起動する")
    gui = sub.add_parser("gui", help="コマンドプロンプトを出さず、同じ画面で管理する")
    gui.add_argument("--no-bot", action="store_true", help="Discord ボットを同時起動しない")
    gui.add_argument("--no-browser", action="store_true", help="外部ブラウザを開かない（既定）")
    gui.add_argument("--browser", action="store_true", help="Chrome など外部ブラウザでも開く")

    setup = sub.add_parser("setup", help="config.yaml と .env を対話で作る")
    add_setup_arguments(setup)

    start = sub.add_parser("start", help="サーバーを起動する")
    start.add_argument("server")
    stop = sub.add_parser("stop", help="サーバーを保存して停止する")
    stop.add_argument("server")
    stop.add_argument("--wait", type=int, default=30)
    restart = sub.add_parser("restart", help="サーバーを保存して再起動する")
    restart.add_argument("server")
    restart.add_argument("--wait", type=int, default=60)

    settings = sub.add_parser("settings", help="PalWorldSettings.ini を表示または変更する")
    settings_sub = settings.add_subparsers(dest="settings_command", required=True)
    show = settings_sub.add_parser("show")
    show.add_argument("server")
    show.add_argument("key", nargs="?")
    set_cmd = settings_sub.add_parser("set")
    set_cmd.add_argument("server")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")
    set_cmd.add_argument("--restart", action="store_true")

    steamcmd_install = sub.add_parser(
        "steamcmd-install",
        help="Valve 公式の SteamCMD をダウンロードして展開する（同梱ではない）",
    )
    steamcmd_install.add_argument(
        "--directory",
        default=None,
        help="導入フォルダ（省略時は C:/SteamCMD または ~/SteamCMD）",
    )

    update = sub.add_parser("update", help="SteamCMD で専用サーバーを更新する")
    update.add_argument("server")
    update.add_argument("--wait", type=int, default=30)
    update.add_argument("--no-backup", action="store_true", help="セーブ退避をしない")
    update.add_argument("--no-restart", action="store_true", help="更新後に起動しない")
    return parser


async def _with_runtime(config_path: str, action) -> int:
    config = load_config(config_path, require_discord_token=False)
    runtime = AdminRuntime(config)
    try:
        await action(runtime)
        return 0
    finally:
        await runtime.close()


async def _cli_start(runtime: AdminRuntime, server_id: str) -> None:
    operator = runtime.operator(server_id)
    await operator.start(progress=_print_progress)
    print(f"{operator.server.name} を起動しました")


async def _cli_stop(runtime: AdminRuntime, server_id: str, wait: int) -> None:
    operator = runtime.operator(server_id)
    await operator.stop(wait_seconds=wait, progress=_print_progress)
    print(f"{operator.server.name} を停止しました")


async def _cli_restart(runtime: AdminRuntime, server_id: str, wait: int) -> None:
    operator = runtime.operator(server_id)
    await operator.restart(wait_seconds=wait, progress=_print_progress)
    print(f"{operator.server.name} を再起動しました")


async def _print_progress(message: str) -> None:
    print(message)


async def _cli_steamcmd_install(runtime: AdminRuntime, directory: str | None) -> None:
    target = Path(directory).expanduser() if directory else default_install_directory()
    path = await install_steamcmd(
        target,
        data_dir=runtime.config.data_dir,
        progress=_print_progress,
    )
    print(f"SteamCMD: {path}")


async def _cli_update(runtime: AdminRuntime, args) -> None:
    operator = runtime.operator(args.server)
    message = await operator.update_with_steamcmd(
        restart_after=not args.no_restart,
        backup=not args.no_backup,
        wait_seconds=args.wait,
        progress=_print_progress,
    )
    print(message)


async def _cli_settings(runtime: AdminRuntime, args) -> None:
    operator = runtime.operator(args.server)
    if args.settings_command == "show":
        values = operator.read_settings()
        if args.key:
            if args.key not in values:
                raise OperationError(f"{args.key} はファイルにありません")
            print(f"{args.key}={values[args.key]}")
            return
        keys = [key for key in COMMON_KEYS if key in values] or list(values)
        for key in keys:
            print(f"{key}={values[key]}")
        return
    if args.restart:
        old, new = await operator.apply_setting_and_restart(
            args.key, args.value, progress=_print_progress
        )
    else:
        old, new = operator.apply_setting(args.key, args.value)
    print(f"{args.key}: {old} -> {new}")


async def _run_web(config_path: str) -> int:
    config = load_config(config_path, require_discord_token=False)
    setup_app_logging(config.data_dir, also_console=True)
    logging.getLogger(__name__).info(
        "管理パネル: http://%s:%s/  （このプロセスを動かしている間、定時再起動も実行されます）",
        config.admin.bind,
        config.admin.port,
    )
    await AdminService(config, config_path=config_path).run(with_bot=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    prepare_frozen_cwd()
    raw = list(argv) if argv is not None else sys.argv[1:]
    if is_frozen() and not raw:
        raw = ["gui"]
    args = _parser().parse_args(raw)
    config_file = resolve_user_path(args.config)
    assert config_file is not None
    config_path = str(config_file)
    try:
        if args.command == "setup":
            if is_frozen():
                from palworld_admin.gui import run_setup_window

                return run_setup_window(config_path)
            return run_setup(args)
        if args.command == "gui":
            from palworld_admin.gui import run_gui

            return run_gui(
                config_path,
                with_bot=not args.no_bot,
                open_browser=bool(getattr(args, "browser", False)) and not args.no_browser,
            )
        if args.command in {None, "web"}:
            if is_frozen():
                from palworld_admin.gui import run_gui

                return run_gui(config_path)
            return asyncio.run(_run_web(config_path))
        if args.command == "start":
            return asyncio.run(
                _with_runtime(config_path, lambda runtime: _cli_start(runtime, args.server))
            )
        if args.command == "stop":
            return asyncio.run(
                _with_runtime(
                    config_path, lambda runtime: _cli_stop(runtime, args.server, args.wait)
                )
            )
        if args.command == "restart":
            return asyncio.run(
                _with_runtime(
                    config_path,
                    lambda runtime: _cli_restart(runtime, args.server, args.wait),
                )
            )
        if args.command == "settings":
            return asyncio.run(_with_runtime(config_path, lambda runtime: _cli_settings(runtime, args)))
        if args.command == "steamcmd-install":
            return asyncio.run(
                _with_runtime(
                    config_path,
                    lambda runtime: _cli_steamcmd_install(runtime, args.directory),
                )
            )
        if args.command == "update":
            return asyncio.run(_with_runtime(config_path, lambda runtime: _cli_update(runtime, args)))
        return 2
    except KeyboardInterrupt:
        print("停止しました")
        return 0
    except (ConfigError, OperationError, SteamCmdError, KeyError) as exc:
        if is_frozen():
            from palworld_admin.gui import _show_error

            _show_error("エラー", str(exc))
        else:
            print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
