from palworld_discord_bot.formatting import (
    build_join_embed,
    build_status_embed,
    event_message,
    format_uptime,
    presence_text,
)
from palworld_discord_bot.models import Player, ServerInfo, ServerMetrics, ServerSnapshot, StatusEvent


def _online() -> ServerSnapshot:
    return ServerSnapshot(
        server_id="main",
        display_name="本鯖",
        online=True,
        info=ServerInfo(name="Friend World", version="v1.0.3"),
        metrics=ServerMetrics(
            fps=60,
            current_players=1,
            max_players=8,
            uptime_seconds=3900,
            days=12,
        ),
        players=(
            Player(name="Alice", player_id="p1", user_id="steam_1", level=20, ping=30.0),
        ),
        join_info="203.0.113.10:8211",
    )


def test_format_uptime() -> None:
    assert format_uptime(3900) == "1時間5分"
    assert format_uptime(90) == "1分"


def test_status_embed_hides_offline_reason_and_players() -> None:
    embed = build_status_embed([_online()])
    assert embed.title == "パルワールド サーバー状況"
    field = embed.fields[0]
    assert "Alice" in field.value
    assert "1/8" in field.value
    assert "v1.0.3" in field.value
    assert "203.0.113" not in field.value


def test_join_embed_uses_configured_info() -> None:
    embed = build_join_embed([_online()])
    assert "203.0.113.10:8211" in embed.fields[0].value


def test_presence_and_event_copy() -> None:
    assert "本鯖で 1/8人がプレイ中" == presence_text([_online()])
    assert "起動しました" in event_message(
        StatusEvent(kind="server_up", server_id="main", server_name="本鯖")
    )
    assert "Alice" in event_message(
        StatusEvent(
            kind="player_join",
            server_id="main",
            server_name="本鯖",
            player_name="Alice",
        )
    )
