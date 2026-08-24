from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import discord

from palworld_discord_bot.models import ServerSnapshot, StatusEvent


def format_uptime(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "不明"
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}時間{minutes}分"
    return f"{minutes}分"


def _player_count_text(snapshot: ServerSnapshot) -> str:
    current = snapshot.player_count
    maximum = snapshot.max_players
    if maximum is not None:
        return f"{current}/{maximum}"
    return str(current)


def _player_list_text(snapshot: ServerSnapshot) -> str:
    names = snapshot.player_names
    if not names:
        return "誰もいません"
    return "、".join(names)


def status_color(snapshots: list[ServerSnapshot]) -> discord.Color:
    if snapshots and all(item.online for item in snapshots):
        return discord.Color.green()
    if snapshots and any(item.online for item in snapshots):
        return discord.Color.gold()
    return discord.Color.red()


def build_status_embed(snapshots: list[ServerSnapshot]) -> discord.Embed:
    online_count = sum(1 for item in snapshots if item.online)
    embed = discord.Embed(
        title="パルワールド サーバー状況",
        description=f"{online_count}/{len(snapshots)} 台が稼働中",
        color=status_color(snapshots),
        timestamp=datetime.now(timezone.utc),
    )
    for snapshot in snapshots:
        if snapshot.online:
            version = snapshot.info.version if snapshot.info else "不明"
            days = snapshot.metrics.days if snapshot.metrics else None
            fps = snapshot.metrics.fps if snapshot.metrics else None
            lines = [
                "状態: 🟢 オンライン",
                f"人数: {_player_count_text(snapshot)}",
                f"プレイヤー: {_player_list_text(snapshot)}",
                f"稼働時間: {format_uptime(snapshot.metrics.uptime_seconds if snapshot.metrics else None)}",
            ]
            if days is not None:
                lines.append(f"ゲーム内日数: {days}日")
            if fps is not None:
                lines.append(f"FPS: {fps}")
            if version:
                lines.append(f"バージョン: {version}")
            value = "\n".join(lines)
        else:
            reason = snapshot.error or "応答なし"
            value = f"状態: 🔴 オフライン\n理由: {reason}"
        embed.add_field(name=snapshot.display_name, value=value, inline=False)
    embed.set_footer(text="自動更新")
    return embed


def build_join_embed(snapshots: list[ServerSnapshot]) -> discord.Embed:
    embed = discord.Embed(
        title="接続方法",
        color=discord.Color.blurple(),
    )
    for snapshot in snapshots:
        info = snapshot.join_info or "接続情報はまだ設定されていません。サーバーの主催者に確認してください。"
        status = "🟢 オンライン" if snapshot.online else "🔴 オフライン"
        embed.add_field(
            name=f"{snapshot.display_name}（{status}）",
            value=info,
            inline=False,
        )
    return embed


def presence_text(snapshots: list[ServerSnapshot]) -> str:
    online = [item for item in snapshots if item.online]
    if not online:
        return "全サーバー停止中"
    total_players = sum(item.player_count for item in online)
    if len(online) == 1:
        server = online[0]
        return f"{server.display_name}で {_player_count_text(server)}人がプレイ中"
    return f"{total_players}人がプレイ中 / {len(online)}台が稼働中"


def event_message(event: StatusEvent, role_mention: str | None = None) -> str:
    if event.kind == "server_up":
        prefix = f"{role_mention} " if role_mention else ""
        return f"{prefix}🟢 **{event.server_name}** が起動しました。遊べます。"
    if event.kind == "server_down":
        return f"🔴 **{event.server_name}** が停止しました。"
    if event.kind == "player_join":
        return f"🚪 **{event.player_name}** が **{event.server_name}** に参加しました。"
    if event.kind == "player_leave":
        return f"👋 **{event.player_name}** が **{event.server_name}** から退出しました。"
    return f"{event.kind}: {event.server_name}"


class StatusMessageStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[int, int] | None:
        if not self.path.is_file():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return int(raw["channel_id"]), int(raw["message_id"])
        except (OSError, KeyError, TypeError, ValueError):
            return None

    def save(self, channel_id: int, message_id: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"channel_id": channel_id, "message_id": message_id}),
            encoding="utf-8",
        )
