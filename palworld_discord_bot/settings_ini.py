from __future__ import annotations

import re
import shutil
from pathlib import Path

STRING_KEYS = frozenset(
    {
        "ServerName",
        "ServerDescription",
        "ServerPassword",
        "AdminPassword",
        "PublicIP",
        "Region",
        "BanListURL",
        "RandomizerSeed",
        "AdditionalDropItemWhenPlayerKillingInPvPMode",
    }
)
PROTECTED_KEYS = frozenset({"AdminPassword", "RESTAPIEnabled", "RESTAPIPort"})
HEADER = "[/Script/Pal.PalGameWorldSettings]"
COMMON_KEYS = (
    "ServerName",
    "ServerDescription",
    "ServerPassword",
    "ServerPlayerMaxNum",
    "ExpRate",
    "PalCaptureRate",
    "PalSpawnNumRate",
    "CollectionDropRate",
    "DeathPenalty",
    "DayTimeSpeedRate",
    "NightTimeSpeedRate",
    "PalEggDefaultHatchingTime",
    "bIsPvP",
    "bEnableInvaderEnemy",
    "bEnableFastTravel",
    "GuildPlayerMaxNum",
    "CoopPlayerMaxNum",
)

_OPTION_START = re.compile(r"OptionSettings\s*=\s*\(", re.IGNORECASE)


class SettingsError(ValueError):
    """Raised when PalWorldSettings.ini cannot be parsed or updated."""


def _find_option_body(text: str) -> tuple[int, int]:
    match = _OPTION_START.search(text)
    if not match:
        raise SettingsError("OptionSettings=(...) が見つかりません")
    start = match.end()
    depth = 1
    in_quotes = False
    escape = False
    index = start
    while index < len(text):
        char = text[index]
        if in_quotes:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_quotes = False
        elif char == '"':
            in_quotes = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return start, index
        index += 1
    raise SettingsError("OptionSettings=(...) の閉じ括弧がありません")


def parse_option_settings(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    index = 0
    length = len(body)
    while index < length:
        while index < length and body[index] in " \t\r\n":
            index += 1
        if index >= length:
            break
        key_start = index
        while index < length and body[index] not in "=\t\r\n":
            index += 1
        if index >= length or body[index] != "=":
            raise SettingsError(f"キーの解析に失敗しました: {body[key_start:key_start + 40]!r}")
        key = body[key_start:index].strip()
        index += 1
        value, index = _read_value(body, index)
        if not key:
            raise SettingsError("空の設定キーがあります")
        result[key] = value
        while index < length and body[index] in " \t\r\n":
            index += 1
        if index < length and body[index] == ",":
            index += 1
    return result


def _read_value(body: str, index: int) -> tuple[str, int]:
    length = len(body)
    while index < length and body[index] in " \t":
        index += 1
    if index >= length:
        return "", index
    if body[index] == '"':
        index += 1
        chars: list[str] = []
        escape = False
        while index < length:
            char = body[index]
            if escape:
                chars.append(char)
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                return "".join(chars), index + 1
            else:
                chars.append(char)
            index += 1
        raise SettingsError("文字列の閉じクォートがありません")

    start = index
    depth = 0
    while index < length:
        char = body[index]
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        elif char == "," and depth == 0:
            break
        index += 1
    return body[start:index].strip(), index


def format_option_value(value: str, key: str = "") -> str:
    stripped = value.strip()
    if key in STRING_KEYS:
        escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if stripped in {"True", "False", "None"}:
        return stripped
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        return stripped
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", stripped):
        return stripped
    escaped = stripped.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def serialize_option_settings(values: dict[str, str]) -> str:
    items = ",".join(f"{key}={format_option_value(value, key)}" for key, value in values.items())
    return f"OptionSettings=({items})"


def load_settings_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SettingsError(f"設定ファイルがありません: {path}")
    text = path.read_text(encoding="utf-8")
    start, end = _find_option_body(text)
    return parse_option_settings(text[start:end])


def write_settings_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = serialize_option_settings(values)
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        text = path.read_text(encoding="utf-8")
        match = _OPTION_START.search(text)
        if match:
            _, end = _find_option_body(text)
            path.write_text(text[: match.start()] + serialized + text[end + 1 :], encoding="utf-8")
            return
    path.write_text(f"{HEADER}\n{serialized}\n", encoding="utf-8")


def bootstrap_rest_api(path: Path, password: str, rest_port: int = 8212) -> dict[str, str]:
    """Enable the official REST API during first-run setup only."""
    if not password.strip():
        raise SettingsError("AdminPassword が空です")
    if not 1 <= rest_port <= 65535:
        raise SettingsError(f"RESTAPIPort が不正です: {rest_port}")
    values = load_settings_file(path)
    values["RESTAPIEnabled"] = "True"
    values["RESTAPIPort"] = str(rest_port)
    values["AdminPassword"] = password.strip()
    write_settings_file(path, values)
    return values


def set_setting(values: dict[str, str], key: str, value: str) -> dict[str, str]:
    if key in PROTECTED_KEYS:
        raise SettingsError(
            f"{key} は管理画面からは変更できません。REST API や管理パスワードが壊れないように保護しています。"
        )
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
        raise SettingsError(f"不正な設定キーです: {key}")
    updated = dict(values)
    updated[key] = value
    return updated


def set_settings(values: dict[str, str], changes: dict[str, str]) -> dict[str, str]:
    updated = dict(values)
    for key, value in changes.items():
        updated = set_setting(updated, key, value)
    return updated
