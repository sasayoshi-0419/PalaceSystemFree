---
name: plan-and-review
description: >-
  ALWAYS use for product work in this repository: bug reports, features,
  refactors, packaging, UI, WebView, Discord bot, EXE, 直して, 実装, 修正, レビュー.
  Planner and reviewer models write implementation briefs and review diffs only.
  Product code is implemented by Composer 2.5. Use at the start of coding
  requests and when reviewing a pull request or uncommitted diff. Do not skip
  even if the user says the change is small.
---

# 実装指示とレビュー（製品コードは Composer 2.5）

役割はモデルで分かれる。

| 自分のモデル | やること |
| --- | --- |
| Composer 2.5 / Composer 2.5 Fast（`composer-2.5`, `composer-2.5-fast`） | `project-bootstrap` を読んだうえで **実装する**。テストを回す |
| それ以外 | 調査して **実装指示** を書く。できた diff を **レビュー** する。製品コードは書かない |

「このチャットで実装して」「自分で直して」と利用者が明示したときだけ、Composer 以外も製品コードを書いてよい。

## 製品コード（計画担当は編集しない）

- `palworld_admin/`（`static/` 含む）
- `palworld_discord_bot/`
- `packaging/`
- `*.bat` / `*.vbs`
- `tests/`（ドキュメント存在チェック以外のテスト）
- `pyproject.toml` の依存追加など、動くソフトを変える変更

計画担当が書いてよいのは `AGENTS.md`、`.cursor/`、README の案内、`tests/test_docs_bootstrap.py` 程度。調査のための Read / Grep はしてよい。

## 計画担当の手順

1. `project-bootstrap` の読みリストを実行する（未読なら）。
2. 関連コードを読んで原因や差し込み位置を特定する。推測だけで指示を書かない。
3. 下のテンプレで **実装指示** をユーザー向けに出す（コピーして Composer 2.5 のチャットに貼れる形）。
4. 自分では `Write` / `StrReplace` で製品コードを変えない。
5. 実装後（diff / PR / 「レビューして」）は下のレビュー手順に進む。

サブエージェントで実装させる場合、`model` は `composer-2.5` のみ。他モデルに実装させない。

## 実装指示テンプレ

```markdown
# 実装指示（Composer 2.5 向け）

最初に `.cursor/skills/project-bootstrap/SKILL.md` を読み、そこに列挙されたドキュメントをファイルから開く。

## 目的
（ユーザーの言葉を、受け入れできる形に言い直す）

## やってはいけないこと
- PalServer / SteamCMD / 公式アセットを同梱しない
- Discord からゲームサーバーを起動・停止しない
- 管理画面から AdminPassword / RESTAPIEnabled / RESTAPIPort を変えさせない
- 1 プロセスで webview.start() を 2 回呼ばない
- js_api 中に window.destroy() しない
- 管理ツール終了で PalServer 本体を止めない
- 有料専用機能（署名インストーラー、ライセンス、クラッシュ再起動の商品化、商用自動更新、有料バックアップ UI）をこの無料 MIT リポジトリに実装しない
（このタスク固有の禁止も書く）

## 変更するファイル
- `path`: 何をするか

## 手順
1.
2.

## 受け入れ条件
- [ ] `pytest tests/ -q` が通る
- [ ] （画面・CLI の具体的な結果）

## 触らないもの
（関係ないパッケージ、設定キー、文言）
```

指示のあとに、利用者へ「Composer 2.5 のチャットにこの指示を貼って実装してください」と書く。EXE を触る作業なら、先に `HomeServerAdmin.exe` を終了することを忘れない。

## レビュー手順

1. 実装指示（または issue）と diff を突き合わせる。指示にない変更は疑う。
2. `AGENTS.md` の制約（同梱禁止、webview、Discord は通知のみ）を破っていないか見る。
3. テストの追加・実行結果があるか見る。不足なら Composer 2.5 向けの追指示を出す。
4. 指摘は **直させる指示** にする。計画担当が製品コードを直してしまわない。
5. ユーザー向けに、直った点・残課題・Windows で確認してほしいことを日本語でまとめる。
