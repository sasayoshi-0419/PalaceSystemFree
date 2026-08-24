from palworld_discord_bot.models import Player, ServerMetrics, ServerSnapshot
from palworld_discord_bot.monitor import diff_snapshots
from palworld_discord_bot.palworld import parse_info, parse_metrics, parse_players


def _player(name: str, user_id: str, level: int = 10) -> Player:
    return Player(name=name, player_id=f"p-{user_id}", user_id=user_id, level=level, ping=20.0)


def _snapshot(
    server_id: str,
    *,
    online: bool,
    players: tuple[Player, ...] = (),
) -> ServerSnapshot:
    return ServerSnapshot(
        server_id=server_id,
        display_name="本鯖",
        online=online,
        players=players,
        metrics=ServerMetrics(current_players=len(players), max_players=8, uptime_seconds=120),
    )


def test_parse_info_and_metrics() -> None:
    info = parse_info(
        {
            "version": "v1.0.3",
            "servername": "Friend World",
            "description": "private",
            "worldguid": "abc-123",
        }
    )
    metrics = parse_metrics(
        {
            "serverfps": 58,
            "currentplayernum": 2,
            "maxplayernum": 8,
            "serveruptime": 3900,
            "days": 14,
            "basecount": 3,
        }
    )
    assert info.name == "Friend World"
    assert info.version == "v1.0.3"
    assert metrics.current_players == 2
    assert metrics.max_players == 8
    assert metrics.uptime_seconds == 3900
    assert metrics.days == 14


def test_parse_players_ignores_ip() -> None:
    players = parse_players(
        {
            "players": [
                {
                    "name": "Alice",
                    "playerId": "pid-1",
                    "userId": "steam_1",
                    "ip": "203.0.113.9",
                    "ping": 42.5,
                    "level": 21,
                }
            ]
        }
    )
    assert len(players) == 1
    assert players[0].display_name == "Alice"
    assert players[0].user_id == "steam_1"
    assert not hasattr(players[0], "ip")


def test_first_poll_emits_no_events() -> None:
    current = {
        "main": _snapshot("main", online=True, players=(_player("Alice", "steam_1"),)),
    }
    diff = diff_snapshots(None, current)
    assert diff.events == ()


def test_server_up_and_down() -> None:
    offline = {"main": _snapshot("main", online=False)}
    online = {"main": _snapshot("main", online=True)}
    up = diff_snapshots(offline, online)
    down = diff_snapshots(online, offline)
    assert [event.kind for event in up.events] == ["server_up"]
    assert [event.kind for event in down.events] == ["server_down"]


def test_player_join_and_leave() -> None:
    alice = _player("Alice", "steam_1")
    bob = _player("Bob", "steam_2")
    before = {"main": _snapshot("main", online=True, players=(alice,))}
    after = {"main": _snapshot("main", online=True, players=(alice, bob))}
    joined = diff_snapshots(before, after)
    left = diff_snapshots(after, before)
    assert joined.events[0].kind == "player_join"
    assert joined.events[0].player_name == "Bob"
    assert left.events[0].kind == "player_leave"
    assert left.events[0].player_name == "Bob"
