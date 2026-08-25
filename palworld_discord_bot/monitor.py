from __future__ import annotations

from dataclasses import dataclass, field, replace

from palworld_discord_bot.models import ServerSnapshot, SnapshotDiff, StatusEvent

REFUSED_OFFLINE_THRESHOLD = 2


@dataclass
class StabilizerState:
    consecutive_refused: dict[str, int] = field(default_factory=dict)
    last_uptime_seconds: dict[str, int | None] = field(default_factory=dict)
    has_baseline: dict[str, bool] = field(default_factory=dict)


def _merge_players(raw: ServerSnapshot, previous: ServerSnapshot | None) -> ServerSnapshot:
    if raw.players_incomplete and previous is not None and previous.online:
        return replace(raw, players=previous.players)
    return raw


def _uptime_reset(
    last_uptime: int | None,
    current_uptime: int | None,
    poll_interval_seconds: int,
) -> bool:
    if current_uptime is None:
        return True
    if last_uptime is None:
        return False
    if current_uptime < last_uptime:
        return True
    threshold = max(poll_interval_seconds * 2, 60)
    if last_uptime > threshold and current_uptime < threshold:
        return True
    return False


def _uptime_continued(last_uptime: int | None, current_uptime: int | None) -> bool:
    if last_uptime is None or current_uptime is None:
        return False
    return current_uptime >= last_uptime


def _mark_baseline(state: StabilizerState, server_id: str) -> None:
    state.has_baseline[server_id] = True


def stabilize_snapshots(
    state: StabilizerState | None,
    previous: dict[str, ServerSnapshot] | None,
    raw: dict[str, ServerSnapshot],
    *,
    poll_interval_seconds: int = 20,
) -> tuple[
    StabilizerState,
    dict[str, ServerSnapshot],
    dict[str, ServerSnapshot] | None,
    dict[str, ServerSnapshot] | None,
]:
    """Return stabilizer state, logical snapshots, diff baseline, and next previous."""
    new_state = StabilizerState(
        consecutive_refused=dict(state.consecutive_refused) if state else {},
        last_uptime_seconds=dict(state.last_uptime_seconds) if state else {},
        has_baseline=dict(state.has_baseline) if state else {},
    )
    if previous:
        for server_id in previous:
            new_state.has_baseline[server_id] = True
        for server_id, snap in previous.items():
            if snap.online and snap.metrics and snap.metrics.uptime_seconds is not None:
                new_state.last_uptime_seconds.setdefault(
                    server_id, snap.metrics.uptime_seconds
                )
    logical: dict[str, ServerSnapshot] = {}
    diff_baseline: dict[str, ServerSnapshot] | None = (
        None if previous is None else dict(previous)
    )

    for server_id, raw_snap in raw.items():
        prev = previous.get(server_id) if previous else None
        prev_online = prev.online if prev else False

        if raw_snap.online:
            new_state.consecutive_refused[server_id] = 0
            merged = _merge_players(raw_snap, prev)
            cur_up = merged.metrics.uptime_seconds if merged.metrics else None
            last_up = new_state.last_uptime_seconds.get(server_id)
            if merged.metrics and merged.metrics.uptime_seconds is not None:
                new_state.last_uptime_seconds[server_id] = merged.metrics.uptime_seconds
            logical[server_id] = merged
            _mark_baseline(new_state, server_id)

            if prev and not prev_online:
                if _uptime_continued(last_up, cur_up) and not _uptime_reset(
                    last_up, cur_up, poll_interval_seconds
                ):
                    if diff_baseline is not None:
                        diff_baseline[server_id] = merged
        else:
            kind = raw_snap.error_kind or "other"
            if kind == "auth":
                new_state.consecutive_refused[server_id] = 0
                logical[server_id] = raw_snap
                _mark_baseline(new_state, server_id)
            elif kind == "refused":
                count = new_state.consecutive_refused.get(server_id, 0) + 1
                new_state.consecutive_refused[server_id] = count
                if count >= REFUSED_OFFLINE_THRESHOLD:
                    logical[server_id] = raw_snap
                    _mark_baseline(new_state, server_id)
                elif prev and prev_online:
                    logical[server_id] = prev
                else:
                    logical[server_id] = raw_snap
            else:
                new_state.consecutive_refused[server_id] = 0
                if prev and prev_online:
                    logical[server_id] = prev
                else:
                    logical[server_id] = raw_snap

    next_previous = {
        server_id: snap
        for server_id, snap in logical.items()
        if new_state.has_baseline.get(server_id)
    }
    return (
        new_state,
        logical,
        diff_baseline,
        next_previous or None,
    )


def diff_snapshots(
    previous: dict[str, ServerSnapshot] | None,
    current: dict[str, ServerSnapshot],
) -> SnapshotDiff:
    """Compare polls. The first successful baseline emits no join/leave/up/down events."""
    if previous is None:
        return SnapshotDiff(events=(), snapshots=current)

    events: list[StatusEvent] = []
    for server_id, now in current.items():
        before = previous.get(server_id)
        if before is None:
            continue
        if not before.online and now.online:
            events.append(
                StatusEvent(
                    kind="server_up",
                    server_id=server_id,
                    server_name=now.display_name,
                )
            )
        elif before.online and not now.online:
            events.append(
                StatusEvent(
                    kind="server_down",
                    server_id=server_id,
                    server_name=now.display_name,
                )
            )

        if before.online and now.online:
            before_ids = {player.identity: player for player in before.players if player.identity}
            now_ids = {player.identity: player for player in now.players if player.identity}
            for identity, player in now_ids.items():
                if identity not in before_ids:
                    events.append(
                        StatusEvent(
                            kind="player_join",
                            server_id=server_id,
                            server_name=now.display_name,
                            player_name=player.display_name,
                        )
                    )
            for identity, player in before_ids.items():
                if identity not in now_ids:
                    events.append(
                        StatusEvent(
                            kind="player_leave",
                            server_id=server_id,
                            server_name=now.display_name,
                            player_name=player.display_name,
                        )
                    )

    return SnapshotDiff(events=tuple(events), snapshots=current)
