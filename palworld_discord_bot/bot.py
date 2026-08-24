from __future__ import annotations

import base64

import discord
from discord.ext import commands

from palworld_discord_bot.config import AppConfig, ConfigError
from palworld_discord_bot.palworld import PalworldClient

# チャンネルを見る + メッセージを送信 + 埋め込みリンク + メッセージ履歴を読む
BOT_INVITE_PERMISSIONS = 84992


def application_id_from_token(token: str) -> int | None:
    try:
        first = token.strip().split(".", 1)[0]
        padded = first + "=" * (-len(first) % 4)
        return int(base64.b64decode(padded).decode("ascii"))
    except (ValueError, OSError, UnicodeDecodeError):
        return None


def bot_invite_url(application_id: int) -> str:
    return (
        "https://discord.com/oauth2/authorize"
        f"?client_id={application_id}"
        f"&permissions={BOT_INVITE_PERMISSIONS}"
        "&scope=bot%20applications.commands"
    )


def missing_access_message(guild_id: int, application_id: int | None) -> str:
    invite = (
        bot_invite_url(application_id)
        if application_id
        else "Developer Portal の OAuth2 → URL Generator で bot と applications.commands を付けて招待"
    )
    return (
        f"Discord サーバー (guild_id={guild_id}) にスラッシュコマンドを登録できませんでした。\n"
        "ボットがそのサーバーにいないか、招待時に applications.commands が付いていません。\n"
        "guild_id はチャンネル ID ではなく、サーバー名を右クリックしてコピーした ID です。\n"
        "サーバーからボットを一度キックして、次の URL で入れ直してください:\n"
        f"{invite}"
    )


class PalworldBot(commands.Bot):
    def __init__(self, config: AppConfig) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", help_command=None, intents=intents)
        self.config = config
        if config.discord is None:
            raise ValueError("Discord ボットには discord 設定が必要です")
        self.clients = {
            server.id: PalworldClient(server.rest_url, server.admin_password)
            for server in config.servers
        }

    async def setup_hook(self) -> None:
        discord_config = self.config.discord
        if discord_config is None:
            raise ValueError("Discord ボットには discord 設定が必要です")
        await self.load_extension("palworld_discord_bot.cogs.status")
        guild = discord.Object(id=discord_config.guild_id)
        self.tree.copy_global_to(guild=guild)
        try:
            await self.tree.sync(guild=guild)
        except discord.Forbidden as exc:
            raise ConfigError(
                missing_access_message(discord_config.guild_id, self.application_id)
            ) from exc

    async def close(self) -> None:
        for client in self.clients.values():
            await client.aclose()
        await super().close()


def run_bot(config: AppConfig) -> None:
    bot = PalworldBot(config)
    try:
        bot.run(config.discord_token)
    except discord.LoginFailure as exc:
        raise ConfigError(
            "DISCORD_TOKEN が無効です。Developer Portal の Bot トークンを .env に書き直してください。"
        ) from exc
