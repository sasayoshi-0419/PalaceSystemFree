from __future__ import annotations

from palworld_discord_bot.models import ServerSnapshot, SnapshotDiff, StatusEvent


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
