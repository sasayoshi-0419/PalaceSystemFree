# Palworld 自宅サーバー管理（無料版）

友達鯖の主催者向けです。**管理は自分の PC**、**Discord は友達への状況通知**です。

**非公式です。Pocketpair / Palworld とは無関係です。** PalServer や SteamCMD は同梱しません。ゲーム本体は Steam の専用サーバーから入れてください。

Windows では `HomeServerAdmin.exe` をダブルクリックして使います。ソースから Python で動かすこともできます。ライセンスは MIT（`LICENSE`）です。未署名の無料版なので、SmartScreen やウイルス対策が警告することがあります。

## 動作環境

- Windows 10 以降（64bit）
- 同じ PC に Palworld Dedicated Server（PalServer）が入っていること
- Discord 通知は任意（ボットを作る場合だけ Developer Portal のトークンが必要）

## 最短の始め方（Windows / EXE）

1. zip を入手する
   - GitHub Actions の [Windows EXE](https://github.com/sasayoshi-0419/PalaceSystemFree/actions/workflows/windows-exe.yml) で、最新の成功した実行を開き、成果物 `HomeServerAdmin-windows` をダウンロードする（GitHub へのログインが必要なことがあります）
   - または自分で `build-windows.bat` した `dist\HomeServerAdmin`
2. 好きな場所へフォルダごと展開する（例: `Documents\HomeServerAdmin`）
3. フォルダ内の `使い方.txt` を読む
4. `HomeServerAdmin.exe` をダブルクリックする

初回は同じ窓でセットアップです。PalServer が複数見つかったときは、セーブと設定があるフォルダを自分で選びます（見つかった順には使いません）。見つからないときは Steam のツールから専用サーバーを入れて、「参照」でフォルダを指定します。

セットアップで入れる **AdminPassword** は REST API 用です。友達がサーバーに入るときのパスワードではありません。

**友達の入り方**（グローバル IP とゲームポート）と **定時再起動** はセットアップでも、あとの管理画面でも変えられます。空のままにすると、Discord の `/join` は「まだ設定されていません」と出します。`127.0.0.1` は自分の PC からしか使えません。

定時再起動は、**この管理ツールを開いている間だけ**動きます。窓を閉じてもゲームサーバーは止まりませんが、定時再起動も止まります。

未署名の EXE なので、SmartScreen やウイルス対策が警告することがあります。PalServer.exe は入っていません。初回起動は「起動しています…」のスプラッシュが出てから画面の準備が進みます（初回やビルド直後は少し時間がかかることがあります。2 回目以降は速くなります）。空の DVD / カードリーダーは探しに行きません。外部の Chrome は開きません。コマンドプロンプトは出ません。

## 自分で EXE を作る場合

1. `HomeServerAdmin.exe` が起動していれば終了する（起動中だと EXE の上書きに失敗します）
2. `build-windows.bat` を実行する（`config.yaml` を Cursor で開いたままでもビルドできます。タスク マネージャーに EXE が無くても Defender 等で一時ロックすることがあります。`dist\HomeServerAdmin` フォルダごとは消さないでください。`HomeServerAdmin.exe` と `_internal` はセットです）
3. `dist\HomeServerAdmin\` フォルダごと、好きな場所へコピーする
4. `HomeServerAdmin.exe` をダブルクリックする

再ビルドするときも `dist\HomeServerAdmin` フォルダごと消さないでください。`config.yaml` / `.env` / `.data` は残ります。

## Python から動かす場合

1. Python 3.10 以上を入れる
2. このフォルダで:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .
setup.bat
```

`setup.bat` が PalServer フォルダを探します。1 つならそれを使い、複数あるときは番号で選びます。そのあと `config.yaml` と `.env` を書きます。`PalWorldSettings.ini` があれば REST API も有効にします。

3. 管理ツール（ライトユーザー向け。コマンドプロンプトは出ません）:

```bat
start-admin.bat
```

ログ付きの Windows アプリが開きます。起動・停止・SteamCMD・ログは同じ窓です。Discord は初回 setup または管理画面の **Discord** パネルから設定できます。保存後は同じプロセスでボットが起動します。招待 URL は画面に出ます。ウィンドウを閉じると管理ツールとボットが止まります。ゲーム本体は止まりません。ログは画面と `.data/app.log` に残ります。外部ブラウザでも見たいときは `python -m palworld_admin gui --browser` です。

上級者向けにコンソールで動かす場合は `python -m palworld_admin` です。ボットだけ裏で動かしたいときは `start-bot.bat` です。

## コマンド

```bat
python -m palworld_admin setup
python -m palworld_admin gui
python -m palworld_admin
python -m palworld_discord_bot --check-config
python -m palworld_discord_bot --once
python -m palworld_discord_bot
build-windows.bat
```

手動で書く場合の Windows パスは `C:/SteamCMD/...` のように `/` を使ってください。二重引用符の中の `C:\` は YAML エラーになります。古いファイルは起動時に自動で直して `.bak` を残します。

## Discord ボット

初回セットアップ（ステップ 2）と管理画面の **Discord** パネルに、ボット作成・ID のコピー・招待の手順があります。[Discord Developer Portal](https://discord.com/developers/applications) で Application → Bot を作り、トークンをコピーします。Discord の設定で **開発者モード** をオンにし、サーバー名を右クリックしてコピーした ID が `guild_id`（サーバー ID。チャンネル ID ではない）です。保存後は画面の「ボットをサーバーに招待」から入れます。このリンクはアプリがトークンから自動生成するので、Portal の OAuth2 → URL Generator で権限にチェックして URL を作り直す必要はありません（`bot` + `applications.commands` と必要権限が入っています）。

初回セットアップで飛ばしても、管理画面の **Discord** パネルからあとからトークンとチャンネル ID を設定できます。保存すると `config.yaml` と `.env` が更新され、同じプロセスでボットが起動（または再起動）します。ゲームサーバーは止まりません。トークンは API に返しません。招待 URL は画面に表示されます。

- 状況チャンネルの定期更新
- 起動・停止・参加・退出の通知
- `/status` `/players` `/join`
- `/announce`（`owner_user_ids` のみ）

招待 URL の Scopes は `bot` と `applications.commands` の両方です。自分で Portal の URL Generator から作るときだけ、両方の Scope と Bot Permissions の4つ（チャンネルを見る・メッセージ送信・埋め込み・履歴の閲覧）にチェックしてください。通常は保存後に画面に出るリンクを使えば十分です。`Missing Access` ならボットをキックして同じ招待 URL で入れ直してください。`guild_id` はサーバー ID です。

## 管理ツール

起動・停止・定時再起動・友達の入り方・`PalWorldSettings.ini` の変更。マップ画面ではオンラインのプレイヤー位置（REST API）とギルド拠点（`Level.sav`）を非公式の概略図で表示します。公式のゲーム地図は同梱しません。Discord には座標を出しません。管理画面では公式パラメータをカテゴリ別・日本語説明付きで編集でき、数値はスライダーと入力、真偽値と列挙はドロップダウンです。変更分だけを一括保存し、稼働中なら保存 → 停止 → 書き込み → 起動を 1 回だけ行います。`AdminPassword` / `RESTAPIEnabled` / `RESTAPIPort` は管理画面からは変えません（初回 setup のみ）。友達の入り方と定時再起動の保存ではゲームサーバーを止めません。

ゲーム側の更新は検知します。稼働中なら REST のバージョン、SteamCMD 導入なら `appmanifest_2394010.acf` の buildid、Steam 上の最新 public ビルドを比べます。自動では入れません。管理画面の「SteamCMD を入れる」と「ゲームを更新（SteamCMD）」で、Valve 公式アーカイブのダウンロードと `app_update 2394010 validate` までアプリ内で実行できます。黒いコマンドプロンプトは出しません。ログは画面と `.data/app.log` に出ます。更新前に `Pal/Saved` を `.data/backups/` へコピーします。

CLI:

```bat
python -m palworld_admin start main
python -m palworld_admin restart main --wait 60
python -m palworld_admin steamcmd-install
python -m palworld_admin update main
python -m palworld_admin settings show main
python -m palworld_admin settings set main ExpRate 2.000000 --restart
python -m palworld_admin stop main
```

パネルは localhost のみです。LAN に出す場合は `admin.allow_lan: true` が必要です。

## REST API

setup が ini を見つけられないときは、サーバーを止めて手で書いてください。

```ini
RESTAPIEnabled=True
RESTAPIPort=8212
AdminPassword="強いパスワード"
```

`.env` の `PAL_MAIN_ADMIN_PASSWORD` と同じ値にします。REST ポートはルーターで公開しないでください。

## セキュリティ

- `.env` と `config.yaml` は Git に含めない
- このツールは非公式です。Pocketpair / Palworld とは無関係です
- Discord にはプレイヤー IP を出さない
