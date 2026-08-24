"""cmd.exe は UTF-8 の .bat を Shift-JIS として読むので、日本語はここから出す。"""

from __future__ import annotations

import sys

MESSAGES: dict[str, tuple[str, ...]] = {
    "pip-failed": (
        "pip でパッケージの導入に失敗しました。Python 3.10 以上が入っているか確認してください。",
    ),
    "pyinstaller-failed": (
        "PyInstaller が失敗しました。上の ERROR を確認してください。",
        "アクセスが拒否されました (WinError 5) なら、HomeServerAdmin.exe を終了してから再実行してください。",
    ),
    "exe-missing": (
        "EXE が dist\\HomeServerAdmin\\HomeServerAdmin.exe にありません。",
    ),
    "ok": (
        "",
        "出力: dist\\HomeServerAdmin\\HomeServerAdmin.exe",
        "PalServer や SteamCMD は入っていません。フォルダごとコピーして使います。",
        "フォルダ内の 使い方.txt を読んでください。",
    ),
}


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    key = args[0] if args else "ok"
    lines = MESSAGES.get(key)
    if lines is None:
        print(f"unknown build message: {key}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
