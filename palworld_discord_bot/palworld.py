from __future__ import annotations

from typing import Any, Literal

import httpx

from palworld_discord_bot.models import Player, ServerInfo, ServerMetrics, ServerSnapshot


class PalworldAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_info(payload: dict[str, Any]) -> ServerInfo:
    return ServerInfo(
        name=str(payload.get("servername") or payload.get("serverName") or ""),
        version=str(payload.get("version") or ""),
        description=str(payload.get("description") or ""),
        world_guid=str(payload.get("worldguid") or payload.get("worldGuid") or ""),
    )


def parse_metrics(payload: dict[str, Any]) -> ServerMetrics:
    uptime = payload.get("serveruptime", payload.get("uptime"))
    days = payload.get("days", payload.get("day"))
    bases = payload.get("basecount", payload.get("baseCount"))
    return ServerMetrics(
        fps=_as_int(payload.get("serverfps", payload.get("serverFps"))),
        current_players=_as_int(
            payload.get("currentplayernum", payload.get("currentPlayerNum"))
        ),
        max_players=_as_int(payload.get("maxplayernum", payload.get("maxPlayerNum"))),
        uptime_seconds=_as_int(uptime),
        days=_as_int(days),
        base_count=_as_int(bases),
    )


def parse_players(payload: dict[str, Any] | list[Any]) -> tuple[Player, ...]:
    raw_players = payload
    if isinstance(payload, dict):
        raw_players = payload.get("players") or []
    players: list[Player] = []
    for item in raw_players:
        if not isinstance(item, dict):
            continue
        players.append(
            Player(
                name=str(item.get("name") or ""),
                player_id=str(item.get("playerId") or item.get("player_id") or ""),
                user_id=str(item.get("userId") or item.get("user_id") or ""),
                level=_as_int(item.get("level")) or 0,
                ping=_as_float(item.get("ping")),
                account_name=str(item.get("accountName") or item.get("account_name") or ""),
            )
        )
    return tuple(players)


class PalworldClient:
    def __init__(
        self,
        rest_url: str,
        admin_password: str,
        *,
        timeout: float = 8.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"{rest_url.rstrip('/')}/v1/api",
            auth=("admin", admin_password),
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> Any:
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise PalworldAPIError(f"REST API に接続できません: {exc}") from exc
        if response.status_code == 401:
            raise PalworldAPIError("REST API の認証に失敗しました", status_code=401)
        if response.is_error:
            raise PalworldAPIError(
                f"REST API が {response.status_code} を返しました",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise PalworldAPIError("REST API の応答が JSON ではありません") from exc

    async def info(self) -> ServerInfo:
        payload = await self._get("/info")
        if not isinstance(payload, dict):
            raise PalworldAPIError("/info の応答形式が不正です")
        return parse_info(payload)

    async def metrics(self) -> ServerMetrics:
        payload = await self._get("/metrics")
        if not isinstance(payload, dict):
            raise PalworldAPIError("/metrics の応答形式が不正です")
        return parse_metrics(payload)

    async def players(self) -> tuple[Player, ...]:
        payload = await self._get("/players")
        if not isinstance(payload, (dict, list)):
            raise PalworldAPIError("/players の応答形式が不正です")
        return parse_players(payload)

    async def _post(self, path: str, json_body: dict[str, Any] | None = None) -> None:
        try:
            response = await self._client.post(path, json=json_body)
        except httpx.HTTPError as exc:
            raise PalworldAPIError(f"REST API に接続できません: {exc}") from exc
        if response.status_code == 401:
            raise PalworldAPIError("REST API の認証に失敗しました", status_code=401)
        if response.is_error:
            raise PalworldAPIError(
                f"REST API が {response.status_code} を返しました ({path})",
                status_code=response.status_code,
            )

    async def announce(self, message: str) -> None:
        await self._post("/announce", {"message": message})

    async def save(self) -> None:
        await self._post("/save")

    async def shutdown(self, wait_seconds: int, message: str) -> None:
        await self._post("/shutdown", {"waittime": wait_seconds, "message": message})

    async def stop(self) -> None:
        await self._post("/stop")

    async def probe(self) -> Literal["online", "auth", "offline"]:
        try:
            await self.info()
            return "online"
        except PalworldAPIError as exc:
            if exc.status_code == 401:
                return "auth"
            return "offline"

    async def is_online(self) -> bool:
        return await self.probe() == "online"

    async def snapshot(self, server_id: str, display_name: str, join_info: str = "") -> ServerSnapshot:
        try:
            info = await self.info()
            metrics = await self.metrics()
            players = await self.players()
        except PalworldAPIError as exc:
            return ServerSnapshot(
                server_id=server_id,
                display_name=display_name,
                online=False,
                error=str(exc),
                join_info=join_info,
            )
        return ServerSnapshot(
            server_id=server_id,
            display_name=display_name,
            online=True,
            info=info,
            metrics=metrics,
            players=players,
            join_info=join_info,
        )
