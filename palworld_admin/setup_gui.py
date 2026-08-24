from __future__ import annotations

from pathlib import Path

from palworld_discord_bot.config import ConfigError
from palworld_discord_bot.detect import describe_palserver, find_palserver_directories
from palworld_discord_bot.paths import app_root
from palworld_discord_bot.setup import apply_setup_from_mapping, retarget_palserver


def run_setup_gui(config_path: str, *, mode: str = "setup") -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        return 2

    root_dir = app_root()
    dest = Path(config_path)
    if not dest.is_absolute():
        dest = root_dir / dest
    choose_only = mode == "choose"

    window = tk.Tk()
    window.title("サーバーファイルを選ぶ" if choose_only else "初回セットアップ")
    window.geometry("680x560")
    window.minsize(580, 480)
    searching = ttk.Label(window, text="PalServer を探しています…")
    searching.pack(pady=48)
    window.update_idletasks()
    window.update()
    found = find_palserver_directories()
    searching.destroy()

    result: dict[str, int] = {"code": 1}

    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)

    if choose_only:
        if len(found) > 1:
            intro = "PalServer が複数見つかりました。管理する PalServer フォルダを選んでください。"
        elif found:
            intro = "設定に書いた PalServer フォルダがありません。見つかったフォルダを使うか、参照で選んでください。"
        else:
            intro = "設定に書いた PalServer フォルダがありません。参照で選んでください。"
        ttk.Label(frame, text=intro, wraplength=620).pack(anchor="w")
    else:
        ttk.Label(
            frame,
            text="PalServer フォルダとパスワードを指定すると、設定ファイルを作ります。",
            wraplength=620,
        ).pack(anchor="w")

    pal_var = tk.StringVar(value="" if len(found) != 1 else str(found[0]))
    name_var = tk.StringVar(value="本鯖")
    port_var = tk.StringVar(value="8211")
    rest_var = tk.StringVar(value="8212")
    password_var = tk.StringVar()
    discord_var = tk.BooleanVar(value=False)
    token_var = tk.StringVar()
    guild_var = tk.StringVar()
    status_var = tk.StringVar()
    notify_var = tk.StringVar()
    owner_var = tk.StringVar()

    if len(found) > 1:
        ttk.Label(
            frame,
            text="PalServer が複数あります。見つかった順に自動では使いません。一覧から選ぶか、参照で選んでください。",
            wraplength=620,
        ).pack(anchor="w", pady=(8, 4))
        list_frame = ttk.Frame(frame)
        list_frame.pack(fill="both", expand=False, pady=4)
        listbox = tk.Listbox(list_frame, height=min(8, max(3, len(found))), exportselection=False)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for path in found:
            info = describe_palserver(path)
            saves = " / セーブあり" if info["has_saves"] else ""
            listbox.insert("end", f"{info['label']}{saves}  —  {path}")

        def on_select(_event: object | None = None) -> None:
            selection = listbox.curselection()
            if selection:
                pal_var.set(str(found[int(selection[0])]))

        listbox.bind("<<ListboxSelect>>", on_select)

    pal_block = ttk.Frame(frame)
    pal_block.pack(fill="x", pady=8)
    ttk.Label(pal_block, text="PalServer フォルダ", width=22).pack(side="left")
    pal_entry = ttk.Entry(pal_block, textvariable=pal_var)
    pal_entry.pack(side="left", fill="x", expand=True)

    def browse() -> None:
        chosen = filedialog.askdirectory(title="PalServer フォルダ")
        if chosen:
            pal_var.set(chosen)

    ttk.Button(pal_block, text="参照", command=browse).pack(side="left", padx=(8, 0))

    def row(label: str, variable: tk.StringVar, *, show: str | None = None) -> ttk.Entry:
        block = ttk.Frame(frame)
        block.pack(fill="x", pady=4)
        ttk.Label(block, text=label, width=22).pack(side="left")
        entry = ttk.Entry(block, textvariable=variable, show=show or "")
        entry.pack(side="left", fill="x", expand=True)
        return entry

    if not choose_only:
        row("サーバー表示名", name_var)
        row("ゲームポート", port_var)
        row("REST API ポート", rest_var)
        row("AdminPassword", password_var, show="*")
        ttk.Label(
            frame,
            text=(
                "トークンと ID は Discord の画面からコピーしてください。"
                "https://discord.com/developers/applications で Application を作り、Bot を追加します。"
                "Reset Token でトークンを DISCORD_TOKEN に貼ってください。"
                "Discord の設定で開発者モードをオンにし、サーバー名・チャンネル・自分のユーザー名を"
                "右クリックして ID をコピーします（guild_id はサーバー ID）。"
                "保存後は管理画面の Discord に「ボットをサーバーに招待」が出ます。"
                "このツールが招待 URL を作るので、Portal の OAuth2 → URL Generator で"
                "作り直す必要はありません（bot と applications.commands と必要な権限が入っています）。"
                "自分で URL を作るときだけ URL Generator で bot と applications.commands にチェックします。"
                "Discord からゲームサーバーの起動・停止はできません。"
            ),
            wraplength=620,
        ).pack(anchor="w", pady=(12, 4))
        ttk.Checkbutton(frame, text="Discord ボットも設定する", variable=discord_var).pack(anchor="w", pady=(4, 4))
        row("DISCORD_TOKEN", token_var)
        row("サーバー ID (guild_id)", guild_var)
        row("状況チャンネル ID", status_var)
        row("通知チャンネル ID", notify_var)
        row("あなたのユーザー ID", owner_var)

    status = ttk.Label(frame, text="")
    status.pack(anchor="w", pady=(12, 0))

    def save() -> None:
        try:
            if not pal_var.get().strip():
                raise ConfigError("PalServer フォルダを選んでください")
            if choose_only:
                note = retarget_palserver(dest, Path(pal_var.get()))
            else:
                note = apply_setup_from_mapping(
                    root_dir,
                    dest,
                    {
                        "palserver": pal_var.get(),
                        "name": name_var.get(),
                        "game_port": port_var.get(),
                        "rest_port": rest_var.get(),
                        "password": password_var.get(),
                        "discord": discord_var.get(),
                        "discord_token": token_var.get(),
                        "guild_id": guild_var.get(),
                        "status_channel_id": status_var.get(),
                        "notify_channel_id": notify_var.get(),
                        "owner_user_id": owner_var.get(),
                    },
                )
            status.configure(text=note)
            result["code"] = 0
            messagebox.showinfo("セットアップ完了" if not choose_only else "フォルダを更新しました", note)
            window.destroy()
        except (ConfigError, ValueError) as exc:
            messagebox.showerror("セットアップできません", str(exc))

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=16)
    ttk.Button(
        buttons,
        text="このフォルダで起動" if choose_only else "書き出して起動",
        command=save,
    ).pack(side="left")
    ttk.Button(buttons, text="キャンセル", command=window.destroy).pack(side="left", padx=8)
    window.mainloop()
    return result["code"]
