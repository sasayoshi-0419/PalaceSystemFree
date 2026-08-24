---
name: project-bootstrap
description: >-
  ALWAYS use at the start of every conversation in this Palworld home-server
  repository, including new chats, follow-ups after context reset, bug reports,
  feature work, refactors, reviews, packaging, and questions. Read product
  specs before writing code or answering. Also use when the user mentions
  Palworld, PalServer, Discord bot, HomeServerAdmin, 書き出して起動, 終了,
  EXE, SteamCMD, setup, 仕様, or ドキュメント. Do not skip this skill even
  for a one-line fix.
---

# 新規チャットで仕様を読む

このリポジトリの会話は、仕様を読まずに実装すると同じバグを繰り返す。コードを書く前・製品の質問に答える前に、下のリストを **ファイルから読み直す**。記憶や要約だけで済ませない。

同じチャットの途中で小さな修正を続けるだけなら、初回に読んだ内容を使ってよい。新しいチャット、長い中断のあと、別件から戻ったときは、最初からやり直す。

## 必須（この順で Read する）

1. `AGENTS.md`
2. `README.md`（利用者向けの操作）
3. `config.example.yaml`（設定の形。パスは `/`）
4. `LICENSE`（配布 zip に同梱する MIT ライセンス）

## タスクに応じて足す

| 話題 | 読むもの |
| --- | --- |
| 初回セットアップ、PalServer の候補、書き出して起動 | `palworld_admin/desktop.py`, `gui.py`, `setup_app.py`, `static/setup.html`, `palworld_discord_bot/detect.py`, `setup.py` |
| 管理画面、終了、SteamCMD | `static/index.html`, `web.py`, `service.py`, `steamcmd.py` |
| Discord | `palworld_discord_bot/bot.py`, `cogs/status.py` |
| EXE / ビルド | `build-windows.bat`, `packaging/prepare_windows_dist.py`, `packaging/home_server_admin.spec` |
| 設定・ini | `config.py`, `settings_ini.py`（`PROTECTED_KEYS`） |

## 読んだあと守ること

- ユーザー向けの返答は日本語。
- PalServer / SteamCMD / 公式アセットを同梱しない。
- Discord からサーバー起動・停止を足さない。
- 管理画面から AdminPassword / RESTAPIEnabled / RESTAPIPort を変えさせない。
- 1 プロセス 1 回の `webview.start()`。セットアップ成功後は窓を destroy せず URL を切り替える。
- js_api の呼び出し中に `window.destroy()` しない。
- 管理ツール終了で PalServer 本体を止めない。
- テストは `pytest tests/ -q`。触ったモジュールにテストがあれば回す。
- EXE 再ビルドの案内では、先に `HomeServerAdmin.exe` を終了させる。
- 製品コードの実装は Composer 2.5。自分のモデルがそれ以外なら `.cursor/skills/plan-and-review/SKILL.md` に従い、指示とレビューだけする。
- このリポジトリは無料版の MIT コア。有料専用機能（署名インストーラー、ライセンス、クラッシュ再起動の商品化、商用自動更新、有料バックアップ UI）はここに実装しない。
