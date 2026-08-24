from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Player:
    name: str
    player_id: str
    user_id: str
    level: int
    ping: float
    account_name: str = ""

    @property
    def identity(self) -> str:
        return self.user_id or self.player_id or self.name

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.account_name:
            return self.account_name
        return self.identity or "不明なプレイヤー"


@dataclass(frozen=True)
class ServerInfo:
    name: str
    version: str
    description: str = ""
    world_guid: str = ""


@dataclass(frozen=True)
class ServerMetrics:
    fps: int | None = None
    current_players: int | None = None
    max_players: int | None = None
    uptime_seconds: int | None = None
    days: int | None = None
    base_count: int | None = None


@dataclass(frozen=True)
class ServerSnapshot:
    server_id: str
    display_name: str
    online: bool
    error: str | None = None
    info: ServerInfo | None = None
    metrics: ServerMetrics | None = None
    players: tuple[Player, ...] = ()
    join_info: str = ""

    @property
    def player_count(self) -> int:
        if self.metrics and self.metrics.current_players is not None:
            return self.metrics.current_players
        return len(self.players)

    @property
    def max_players(self) -> int | None:
        if self.metrics:
            return self.metrics.max_players
        return None

    @property
    def player_names(self) -> tuple[str, ...]:
        return tuple(player.display_name for player in self.players)


@dataclass(frozen=True)
class StatusEvent:
    kind: str
    server_id: str
    server_name: str
    player_name: str | None = None


@dataclass(frozen=True)
class SnapshotDiff:
    events: tuple[StatusEvent, ...] = ()
    snapshots: dict[str, ServerSnapshot] = field(default_factory=dict)
