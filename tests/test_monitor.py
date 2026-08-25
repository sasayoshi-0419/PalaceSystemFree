from palworld_discord_bot.models import Player, ServerInfo, ServerMetrics, ServerSnapshot
from palworld_discord_bot.monitor import diff_snapshots, stabilize_snapshots
from palworld_discord_bot.palworld import parse_info, parse_metrics, parse_players


def _player(name: str, user_id: str, level: int = 10) -> Player:
    return Player(name=name, player_id=f"p-{user_id}", user_id=user_id, level=level, ping=20.0)


def _snapshot(
    server_id: str,
    *,
    online: bool,
    players: tuple[Player, ...] = (),
    uptime_seconds: int = 120,
    error_kind: str | None = None,
    players_incomplete: bool = False,
) -> ServerSnapshot:
    return ServerSnapshot(
        server_id=server_id,
        display_name="本鯖",
        online=online,
        players=players,
        players_incomplete=players_incomplete,
        error_kind=error_kind,
        info=ServerInfo(name="Friend World", version="v1") if online else None,
        metrics=ServerMetrics(
            current_players=len(players),
            max_players=8,
            uptime_seconds=uptime_seconds if online else None,
        )
        if online
        else None,
    )


def _stabilized_events(
    previous: dict[str, ServerSnapshot] | None,
    raw: dict[str, ServerSnapshot],
    *,
    poll_interval_seconds: int = 20,
    state=None,
):
    new_state, logical, diff_baseline = stabilize_snapshots(
        state,
        previous,
        raw,
        poll_interval_seconds=poll_interval_seconds,
    )
    diff = diff_snapshots(diff_baseline, logical)
    return new_state, logical, diff.events


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


def test_transient_timeout_does_not_emit_down_or_up() -> None:
    alice = _player("Alice", "steam_1")
    online = {"main": _snapshot("main", online=True, players=(alice,), uptime_seconds=500)}
    timeout = {
        "main": ServerSnapshot(
            server_id="main",
            display_name="本鯖",
            online=False,
            error="timeout",
            error_kind="timeout",
        )
    }
    state, logical, events = _stabilized_events(online, timeout)
    assert logical["main"].online
    assert events == ()

    recovered = {"main": _snapshot("main", online=True, players=(alice,), uptime_seconds=520)}
    _, logical2, events2 = _stabilized_events(logical, recovered, state=state)
    assert logical2["main"].online
    assert events2 == ()


def test_single_refused_does_not_emit_server_down() -> None:
    online = {"main": _snapshot("main", online=True, uptime_seconds=500)}
    refused = {
        "main": ServerSnapshot(
            server_id="main",
            display_name="本鯖",
            online=False,
            error="refused",
            error_kind="refused",
        )
    }
    _, logical, events = _stabilized_events(online, refused)
    assert logical["main"].online
    assert events == ()


def test_double_refused_emits_server_down() -> None:
    online = {"main": _snapshot("main", online=True, uptime_seconds=500)}
    refused = {
        "main": ServerSnapshot(
            server_id="main",
            display_name="本鯖",
            online=False,
            error="refused",
            error_kind="refused",
        )
    }
    state, logical, events = _stabilized_events(online, refused)
    assert events == ()
    _, logical2, events2 = _stabilized_events(logical, refused, state=state)
    assert not logical2["main"].online
    assert [event.kind for event in events2] == ["server_down"]


def test_recovery_with_continued_uptime_suppresses_server_up() -> None:
    online = {"main": _snapshot("main", online=True, uptime_seconds=10000)}
    refused = {
        "main": ServerSnapshot(
            server_id="main",
            display_name="本鯖",
            online=False,
            error="refused",
            error_kind="refused",
        )
    }
    state, logical, _ = _stabilized_events(online, refused)
    state, logical, _ = _stabilized_events(logical, refused, state=state)
    assert not logical["main"].online

    recovered = {"main": _snapshot("main", online=True, uptime_seconds=10040)}
    _, logical2, events = _stabilized_events(logical, recovered, state=state)
    assert logical2["main"].online
    assert events == ()


def test_recovery_with_reset_uptime_emits_server_up() -> None:
    online = {"main": _snapshot("main", online=True, uptime_seconds=10000)}
    refused = {
        "main": ServerSnapshot(
            server_id="main",
            display_name="本鯖",
            online=False,
            error="refused",
            error_kind="refused",
        )
    }
    state, logical, _ = _stabilized_events(online, refused)
    state, logical, _ = _stabilized_events(logical, refused, state=state)
    recovered = {"main": _snapshot("main", online=True, uptime_seconds=12)}
    _, _, events = _stabilized_events(logical, recovered, state=state)
    assert [event.kind for event in events] == ["server_up"]


def test_players_incomplete_does_not_emit_player_leave() -> None:
    alice = _player("Alice", "steam_1")
    before = {"main": _snapshot("main", online=True, players=(alice,), uptime_seconds=200)}
    incomplete = {
        "main": _snapshot(
            "main",
            online=True,
            players=(),
            uptime_seconds=220,
            players_incomplete=True,
        )
    }
    _, logical, events = _stabilized_events(before, incomplete)
    assert logical["main"].players == (alice,)
    assert events == ()
