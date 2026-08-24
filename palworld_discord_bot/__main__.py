from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from palworld_discord_bot.config import ConfigError, load_config
from palworld_discord_bot.setup import add_setup_arguments, run_setup
from palworld_discord_bot.formatting import format_uptime
from palworld_discord_bot.palworld import PalworldClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="パルワールド専用サーバーの稼働状況を Discord に伝えるボット"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="設定ファイル (default: config.yaml)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Discord に接続せず、各サーバーの状況を一度だけ表示する",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="設定の読み込みだけ確認する",
    )
    parser.add_argument(
        "--invite",
        action="store_true",
        help="ボットをサーバーへ入れる招待 URL を表示する",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="config.yaml と .env の初回セットアップを行う",
    )
    add_setup_arguments(parser)
    return parser


def _print_snapshot(snapshot) -> None:
    status = "オンライン" if snapshot.online else "オフライン"
    print(f"[{snapshot.server_id}] {snapshot.display_name}: {status}")
    if not snapshot.online:
        print(f"  理由: {snapshot.error}")
        return
    print(f"  人数: {snapshot.player_count}/{snapshot.max_players or '?'}")
    if snapshot.players:
        names = ", ".join(player.display_name for player in snapshot.players)
        print(f"  プレイヤー: {names}")
    if snapshot.metrics:
        print(f"  稼働時間: {format_uptime(snapshot.metrics.uptime_seconds)}")
        if snapshot.metrics.fps is not None:
            print(f"  FPS: {snapshot.metrics.fps}")
    if snapshot.info and snapshot.info.version:
        print(f"  バージョン: {snapshot.info.version}")


async def _run_once(config_path: str) -> int:
    config = load_config(config_path, require_discord_token=False)
    clients = [
        (server, PalworldClient(server.rest_url, server.admin_password))
        for server in config.servers
    ]
    try:
        for server, client in clients:
            snapshot = await client.snapshot(server.id, server.name, server.join_info)
            _print_snapshot(snapshot)
    finally:
        for _, client in clients:
            await client.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = Path(args.config)
    try:
        if args.setup:
            return run_setup(args)
        if args.check_config:
            config = load_config(config_path, require_discord_token=False)
            print(f"OK: {len(config.servers)} 台のサーバー設定を読み込みました")
            for server in config.servers:
                print(f"  - {server.id}: {server.name} ({server.rest_url})")
            return 0
        if args.invite:
            from palworld_discord_bot.bot import application_id_from_token, bot_invite_url

            config = load_config(config_path, require_discord_token=True)
            app_id = application_id_from_token(config.discord_token)
            if app_id is None:
                raise ConfigError("DISCORD_TOKEN からアプリケーション ID を読めませんでした")
            print(bot_invite_url(app_id))
            print("Scopes に bot と applications.commands が付いている URL です。ブラウザで開いてサーバーへ入れてください。")
            return 0
        if args.once:
            return asyncio.run(_run_once(str(config_path)))
        from palworld_discord_bot.applog import setup_app_logging
        from palworld_discord_bot.bot import run_bot

        config = load_config(config_path, require_discord_token=True)
        if config.discord is None:
            raise ConfigError("Discord ボットには discord.guild_id などの設定が必要です")
        also_console = sys.stdout is not None and sys.stdout.isatty()
        setup_app_logging(config.data_dir, also_console=also_console)
        run_bot(config)
        return 0
    except ConfigError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
