from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palworld_discord_bot.operations import ServerOperator
from palworld_discord_bot.palworld import PalworldAPIError, PalworldClient

logger = logging.getLogger(__name__)

# palworld-coord (MIT-compatible constants; not a dependency)
TRANSL_X = 123888
TRANSL_Y = 158000
SCALE = 459

# Paldex coordinate bounds for CSS percent mapping (generous for map expansions)
PALDEX_X_MIN = -1500.0
PALDEX_X_MAX = 1500.0
PALDEX_Y_MIN = -1500.0
PALDEX_Y_MAX = 1500.0

BASES_CACHE_TTL_SECONDS = 60.0

CUSTOM_PROPERTY_KEYS = (
    ".worldSaveData.GroupSaveDataMap",
    ".worldSaveData.BaseCampSaveData.Value.RawData",
)


@dataclass(frozen=True)
class MapPlayer:
    name: str
    level: int
    user_id: str
    player_id: str
    left: float
    top: float


@dataclass(frozen=True)
class MapBase:
    id: str
    guild: str
    left: float
    top: float


_bases_cache: dict[str, tuple[float, float, list[MapBase], str | None]] = {}


def world_to_paldex(x: float, y: float) -> tuple[float, float]:
    new_x = x + TRANSL_X
    new_y = y - TRANSL_Y
    paldex_x = new_y / SCALE
    paldex_y = new_x / SCALE
    return paldex_x, paldex_y


def paldex_to_percent(paldex_x: float, paldex_y: float) -> tuple[float, float]:
    span_x = PALDEX_X_MAX - PALDEX_X_MIN
    span_y = PALDEX_Y_MAX - PALDEX_Y_MIN
    left = (paldex_x - PALDEX_X_MIN) / span_x * 100.0
    top = (PALDEX_Y_MAX - paldex_y) / span_y * 100.0
    return round(left, 2), round(top, 2)


def world_to_percent(x: float, y: float) -> tuple[float, float]:
    return paldex_to_percent(*world_to_paldex(x, y))


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_map_players(payload: dict[str, Any] | list[Any]) -> list[MapPlayer]:
    raw_players = payload
    if isinstance(payload, dict):
        raw_players = payload.get("players") or []
    players: list[MapPlayer] = []
    if not isinstance(raw_players, list):
        return players
    for item in raw_players:
        if not isinstance(item, dict):
            continue
        loc_x = _as_float(item.get("location_x") or item.get("locationX"))
        loc_y = _as_float(item.get("location_y") or item.get("locationY"))
        if loc_x is None or loc_y is None:
            continue
        left, top = world_to_percent(loc_x, loc_y)
        players.append(
            MapPlayer(
                name=str(item.get("name") or ""),
                level=_as_int(item.get("level")),
                user_id=str(item.get("userId") or item.get("user_id") or ""),
                player_id=str(item.get("playerId") or item.get("player_id") or ""),
                left=left,
                top=top,
            )
        )
    return players


def map_player_to_dict(player: MapPlayer) -> dict[str, Any]:
    return {
        "name": player.name,
        "level": player.level,
        "user_id": player.user_id,
        "player_id": player.player_id,
        "left": player.left,
        "top": player.top,
    }


def map_base_to_dict(base: MapBase) -> dict[str, Any]:
    return {
        "id": base.id,
        "guild": base.guild,
        "left": base.left,
        "top": base.top,
    }


def _normalize_guid(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text.replace("-", "")


def _guild_type_value(group_value: dict[str, Any]) -> str:
    group_type = group_value.get("GroupType") or {}
    inner = group_type.get("value") or {}
    if isinstance(inner, dict):
        return str(inner.get("value") or "")
    return str(inner)


def _raw_data_value(entry_value: dict[str, Any]) -> dict[str, Any] | None:
    raw = entry_value.get("RawData") or {}
    inner = raw.get("value")
    return inner if isinstance(inner, dict) else None


def extract_bases_from_world_save(world_save_data: dict[str, Any]) -> list[MapBase]:
    guild_names: dict[str, str] = {}
    group_map = world_save_data.get("GroupSaveDataMap") or {}
    group_entries = group_map.get("value") or []
    if isinstance(group_entries, list):
        for entry in group_entries:
            if not isinstance(entry, dict):
                continue
            value = entry.get("value") or {}
            if not isinstance(value, dict):
                continue
            group_type = _guild_type_value(value)
            if group_type not in (
                "EPalGroupType::Guild",
                "EPalGroupType::IndependentGuild",
            ):
                continue
            raw = _raw_data_value(value)
            if raw is None:
                continue
            guild_name = str(raw.get("guild_name") or raw.get("guild_name_2") or "").strip()
            group_key = _normalize_guid(entry.get("key"))
            if group_key:
                guild_names[group_key] = guild_name or "ギルド"
            group_id = _normalize_guid(raw.get("group_id"))
            if group_id:
                guild_names[group_id] = guild_name or guild_names.get(group_id, "ギルド")

    bases: list[MapBase] = []
    base_camp = world_save_data.get("BaseCampSaveData") or {}
    base_entries = base_camp.get("value") or []
    if not isinstance(base_entries, list):
        return bases

    for entry in base_entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get("value") or {}
        if not isinstance(value, dict):
            continue
        raw = _raw_data_value(value)
        if raw is None:
            continue
        transform = raw.get("transform") or {}
        translation = transform.get("translation") or {}
        world_x = _as_float(translation.get("x"))
        world_y = _as_float(translation.get("y"))
        if world_x is None or world_y is None:
            continue
        base_id = str(raw.get("id") or entry.get("key") or "")
        group_id = _normalize_guid(raw.get("group_id_belong_to"))
        guild = guild_names.get(group_id, "ギルド")
        left, top = world_to_percent(world_x, world_y)
        bases.append(MapBase(id=base_id, guild=guild, left=left, top=top))

    return bases


def _custom_properties() -> dict[str, Any]:
    from palworld_save_tools.paltypes import PALWORLD_CUSTOM_PROPERTIES

    props: dict[str, Any] = {}
    for key in CUSTOM_PROPERTY_KEYS:
        if key in PALWORLD_CUSTOM_PROPERTIES:
            props[key] = PALWORLD_CUSTOM_PROPERTIES[key]
    return props


def _parse_level_sav_copy(sav_copy: Path) -> dict[str, Any]:
    from palworld_save_tools.gvas import GvasFile
    from palworld_save_tools.palsav import decompress_sav_to_gvas
    from palworld_save_tools.paltypes import PALWORLD_TYPE_HINTS

    raw = sav_copy.read_bytes()
    raw_gvas, _ = decompress_sav_to_gvas(raw)
    gvas_file = GvasFile.read(
        raw_gvas,
        PALWORLD_TYPE_HINTS,
        _custom_properties(),
        allow_nan=True,
    )
    return gvas_file.dump()


def _world_save_data_from_dump(dump: dict[str, Any]) -> dict[str, Any] | None:
    properties = dump.get("properties") or {}
    world_save = properties.get("worldSaveData") or {}
    value = world_save.get("value")
    return value if isinstance(value, dict) else None


def find_level_sav(working_directory: Path, world_guid: str | None = None) -> Path | None:
    save_root = working_directory / "Pal" / "Saved" / "SaveGames"
    if not save_root.is_dir():
        return None
    candidates = [path for path in save_root.rglob("Level.sav") if path.is_file()]
    if not candidates:
        return None
    if world_guid:
        guid = world_guid.strip()
        preferred = [
            path
            for path in candidates
            if guid in path.as_posix() or path.parent.name == guid
        ]
        if preferred:
            candidates = preferred
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _copy_sav_for_read(source: Path, data_dir: Path, server_id: str) -> Path:
    cache_dir = data_dir / "worldmap_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mtime_ns = source.stat().st_mtime_ns
    dest = cache_dir / f"{server_id}-{mtime_ns}.sav"
    if not dest.is_file():
        shutil.copy2(source, dest)
    return dest


def load_bases_from_sav(
    sav_path: Path,
    data_dir: Path,
    server_id: str,
) -> tuple[list[MapBase], str | None]:
    try:
        sav_copy = _copy_sav_for_read(sav_path, data_dir, server_id)
        dump = _parse_level_sav_copy(sav_copy)
        world_save = _world_save_data_from_dump(dump)
        if world_save is None:
            return [], "Level.sav の worldSaveData を読み取れませんでした。"
        return extract_bases_from_world_save(world_save), None
    except Exception as exc:
        logger.warning("Level.sav の拠点読み取りに失敗: %s", exc)
        return [], f"Level.sav の拠点を読み取れませんでした: {exc}"


def get_bases_for_operator(
    operator: ServerOperator,
    world_guid: str | None = None,
) -> tuple[list[MapBase], str | None]:
    process = operator.server.process
    if process is None:
        return [], "PalServer の作業フォルダが設定されていません。"
    working_directory = process.working_directory
    if not working_directory.is_dir():
        return [], f"PalServer フォルダが見つかりません: {working_directory}"

    sav_path = find_level_sav(working_directory, world_guid)
    if sav_path is None:
        return [], "Level.sav が見つかりません。サーバーを一度起動してセーブを作成してください。"

    server_id = operator.server.id
    try:
        mtime = sav_path.stat().st_mtime
    except OSError as exc:
        return [], f"Level.sav を開けませんでした: {exc}"

    now = time.monotonic()
    cached = _bases_cache.get(server_id)
    if cached is not None:
        cached_mtime, expiry, bases, error = cached
        if cached_mtime == mtime and now < expiry:
            return bases, error

    bases, error = load_bases_from_sav(sav_path, operator.data_dir, server_id)
    _bases_cache[server_id] = (mtime, now + BASES_CACHE_TTL_SECONDS, bases, error)
    return bases, error


async def fetch_map_data(operator: ServerOperator, status: str) -> dict[str, Any]:
    players: list[MapPlayer] = []
    players_error: str | None = None
    world_guid: str | None = None

    if status == "online":
        try:
            payload = await operator.client.players_payload()
            players = parse_map_players(payload)
        except PalworldAPIError as exc:
            players_error = str(exc)
        try:
            info = await operator.client.info()
            world_guid = info.world_guid or None
        except PalworldAPIError:
            pass

    bases, bases_error = get_bases_for_operator(operator, world_guid)

    return {
        "ok": True,
        "server_id": operator.server.id,
        "server_name": operator.server.name,
        "status": status,
        "players": [map_player_to_dict(player) for player in players],
        "bases": [map_base_to_dict(base) for base in bases],
        "bases_error": bases_error,
        "players_error": players_error,
    }
