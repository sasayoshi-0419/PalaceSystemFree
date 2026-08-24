from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PALWORLD_DS_APP_ID = 2394010
STEAMCMD_INFO_URL = f"https://api.steamcmd.net/v1/info/{PALWORLD_DS_APP_ID}"
_CACHE_SECONDS = 1800
_acf_value = re.compile(r'"([^"]+)"\s+"([^"]*)"')

_latest_cache: tuple[float, str | None] | None = None


@dataclass(frozen=True)
class ManifestInfo:
    path: Path
    buildid: str | None
    target_buildid: str | None
    last_updated: str | None


@dataclass(frozen=True)
class UpdateStatus:
    running_version: str | None
    installed_buildid: str | None
    target_buildid: str | None
    latest_buildid: str | None
    update_available: bool
    summary: str
    hint: str | None = None
    manifest_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "running_version": self.running_version,
            "installed_buildid": self.installed_buildid,
            "target_buildid": self.target_buildid,
            "latest_buildid": self.latest_buildid,
            "update_available": self.update_available,
            "summary": self.summary,
            "hint": self.hint,
        }


def parse_appmanifest(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in _acf_value.findall(text):
        if key not in values:
            values[key] = value
    return values


def read_manifest(path: Path) -> ManifestInfo | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    values = parse_appmanifest(text)
    return ManifestInfo(
        path=path,
        buildid=(values.get("buildid") or "").strip() or None,
        target_buildid=(values.get("TargetBuildID") or values.get("targetbuildid") or "").strip()
        or None,
        last_updated=(values.get("LastUpdated") or "").strip() or None,
    )


def find_appmanifest(
    working_directory: Path | None,
    *,
    app_id: int = PALWORLD_DS_APP_ID,
) -> Path | None:
    if working_directory is None:
        return None
    name = f"appmanifest_{app_id}.acf"
    seen: set[str] = set()
    current = working_directory.expanduser()
    try:
        current = current.resolve()
    except OSError:
        pass
    candidates: list[Path] = []
    for _ in range(6):
        candidates.extend(
            [
                current / "steamapps" / name,
                current / name,
            ]
        )
        if current.parent == current:
            break
        current = current.parent
    for path in candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path
    return None


def _buildid_newer(latest: str | None, installed: str | None) -> bool:
    if not latest or not installed or latest == installed:
        return False
    if latest.isdigit() and installed.isdigit():
        return int(latest) > int(installed)
    return latest != installed


def evaluate_update(
    *,
    running_version: str | None = None,
    manifest: ManifestInfo | None = None,
    latest_buildid: str | None = None,
) -> UpdateStatus:
    installed = manifest.buildid if manifest else None
    target = manifest.target_buildid if manifest else None
    pending_local = _buildid_newer(target, installed)
    pending_steam = _buildid_newer(latest_buildid, installed)
    update_available = pending_local or pending_steam
    parts: list[str] = []
    if running_version:
        parts.append(f"稼働 {running_version}")
    if installed:
        parts.append(f"導入ビルド {installed}")
    if latest_buildid:
        parts.append(f"Steam 最新 {latest_buildid}")
    elif installed is None and running_version is None:
        parts.append("バージョン情報なし")
    summary = " / ".join(parts) if parts else "バージョン情報なし"
    hint = None
    if update_available:
        summary = f"更新あり — {summary}"
        hint = (
            "管理画面の「ゲームを更新（SteamCMD）」を押してください。"
            "更新中はサーバーが停止します。"
            "PalServer は同梱していません。自動では更新しません。"
        )
    return UpdateStatus(
        running_version=running_version or None,
        installed_buildid=installed,
        target_buildid=target,
        latest_buildid=latest_buildid,
        update_available=update_available,
        summary=summary,
        hint=hint,
        manifest_path=str(manifest.path) if manifest else None,
    )


def parse_steamcmd_info(payload: dict[str, Any], *, app_id: int = PALWORLD_DS_APP_ID) -> str | None:
    data = payload.get("data")
    app = None
    if isinstance(data, dict):
        app = data.get(str(app_id)) or data.get(app_id)
    if not isinstance(app, dict):
        return None
    depots = app.get("depots")
    if not isinstance(depots, dict):
        return None
    branches = depots.get("branches")
    if not isinstance(branches, dict):
        return None
    public = branches.get("public")
    if not isinstance(public, dict):
        return None
    buildid = str(public.get("buildid") or "").strip()
    return buildid or None


async def fetch_latest_buildid(*, timeout: float = 8.0) -> str | None:
    global _latest_cache
    now = time.monotonic()
    if _latest_cache is not None and now - _latest_cache[0] < _CACHE_SECONDS:
        return _latest_cache[1]
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(STEAMCMD_INFO_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, OSError) as exc:
        logger.info("Steam の最新ビルドを取得できませんでした: %s", exc)
        _latest_cache = (now, None)
        return None
    if not isinstance(payload, dict):
        _latest_cache = (now, None)
        return None
    latest = parse_steamcmd_info(payload)
    _latest_cache = (now, latest)
    return latest


def clear_latest_cache() -> None:
    global _latest_cache
    _latest_cache = None


async def inspect_update(
    working_directory: Path | None,
    *,
    running_version: str | None = None,
) -> UpdateStatus:
    path = find_appmanifest(working_directory)
    manifest = read_manifest(path) if path else None
    latest = await fetch_latest_buildid()
    return evaluate_update(
        running_version=running_version,
        manifest=manifest,
        latest_buildid=latest,
    )


class UpdateNoticeStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def should_notify(self, server_id: str, token: str) -> bool:
        data = self._load()
        entry = data.get(server_id) or {}
        return str(entry.get("notified") or "") != token

    def mark(self, server_id: str, *, notified: str | None, running_version: str | None) -> None:
        data = self._load()
        current = dict(data.get(server_id) or {})
        if notified is not None:
            current["notified"] = notified
        if running_version is not None:
            current["running_version"] = running_version
        data[server_id] = current
        self._save(data)

    def last_running_version(self, server_id: str) -> str | None:
        data = self._load()
        value = (data.get(server_id) or {}).get("running_version")
        return str(value) if value else None
