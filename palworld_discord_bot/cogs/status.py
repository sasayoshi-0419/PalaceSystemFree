from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from palworld_discord_bot.formatting import (
    StatusMessageStore,
    build_join_embed,
    build_status_embed,
    event_message,
    presence_text,
)
from palworld_discord_bot.models import ServerSnapshot
from palworld_discord_bot.monitor import diff_snapshots, stabilize_snapshots
from palworld_discord_bot.palworld import PalworldAPIError

if TYPE_CHECKING:
    from palworld_discord_bot.bot import PalworldBot

logger = logging.getLogger(__name__)


class StatusCog(commands.Cog):
    def __init__(self, bot: PalworldBot) -> None:
        self.bot = bot
        self.store = StatusMessageStore(bot.config.data_dir / "status_message.json")
        self._previous: dict[str, ServerSnapshot] | None = None
        self._latest: dict[str, ServerSnapshot] = {}
        self._stabilizer_state = None
        self._lock = asyncio.Lock()

    async def cog_load(self) -> None:
        self.poll_servers.start()

    async def cog_unload(self) -> None:
        self.poll_servers.cancel()

    def _discord(self):
        config = self.bot.config.discord
        if config is None:
            raise RuntimeError("discord 設定がありません")
        return config

    def _server_choices(self) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=server.name, value=server.id)
            for server in self.bot.config.servers
        ]

    def _selected_snapshots(self, server_id: str | None) -> list[ServerSnapshot]:
        snapshots = list(self._latest.values())
        if not snapshots:
            snapshots = [
                ServerSnapshot(
                    server_id=server.id,
                    display_name=server.name,
                    online=False,
                    error="まだ取得していません。少し待ってから再実行してください。",
                    join_info=server.join_info,
                )
                for server in self.bot.config.servers
            ]
        if server_id:
            snapshots = [item for item in snapshots if item.server_id == server_id]
        return snapshots

    async def _poll(self) -> dict[str, ServerSnapshot]:
        results = await asyncio.gather(
            *[
                self.bot.clients[server.id].snapshot(
                    server.id, server.name, server.join_info
                )
                for server in self.bot.config.servers
            ]
        )
        return {snapshot.server_id: snapshot for snapshot in results}

    async def _update_presence(self, snapshots: list[ServerSnapshot]) -> None:
        await self.bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=presence_text(snapshots),
            )
        )

    async def _update_status_message(self, snapshots: list[ServerSnapshot]) -> None:
        channel = self.bot.get_channel(self._discord().status_channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "状況チャンネル %s を見つけられません",
                self._discord().status_channel_id,
            )
            return
        embed = build_status_embed(snapshots)
        stored = self.store.load()
        if stored and stored[0] == channel.id:
            try:
                message = await channel.fetch_message(stored[1])
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        message = await channel.send(embed=embed)
        self.store.save(channel.id, message.id)

    async def _notify(self, events) -> None:
        if not events:
            return
        channel = self.bot.get_channel(self._discord().notify_channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "通知チャンネル %s を見つけられません",
                self._discord().notify_channel_id,
            )
            return
        role_mention = None
        if self._discord().notify_role_id:
            role_mention = f"<@&{self._discord().notify_role_id}>"
        for event in events:
            mention = role_mention if event.kind == "server_up" else None
            await channel.send(event_message(event, mention))

    @tasks.loop(seconds=20)
    async def poll_servers(self) -> None:
        self.poll_servers.change_interval(seconds=self._discord().poll_interval_seconds)
        try:
            async with self._lock:
                raw = await self._poll()
                self._stabilizer_state, logical, diff_baseline, next_previous = stabilize_snapshots(
                    self._stabilizer_state,
                    self._previous,
                    raw,
                    poll_interval_seconds=self._discord().poll_interval_seconds,
                )
                diff = diff_snapshots(diff_baseline, logical)
                self._previous = next_previous
                self._latest = logical
                snapshots = [logical[server.id] for server in self.bot.config.servers]
                await self._update_status_message(snapshots)
                await self._update_presence(snapshots)
                await self._notify(diff.events)
        except Exception:
            logger.exception("サーバー状況の取得に失敗しました")

    @poll_servers.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="status", description="各サーバーの稼働状況を表示します")
    @app_commands.describe(server="特定のサーバーだけ表示するとき")
    async def status(self, interaction: discord.Interaction, server: str | None = None) -> None:
        snapshots = self._selected_snapshots(server)
        if not snapshots:
            await interaction.response.send_message("指定したサーバーが見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(embed=build_status_embed(snapshots))

    @status.autocomplete("server")
    async def status_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = current.lower()
        return [
            choice
            for choice in self._server_choices()
            if query in choice.name.lower() or query in choice.value.lower()
        ][:25]

    @app_commands.command(name="players", description="今遊んでいる人を表示します")
    @app_commands.describe(server="特定のサーバーだけ表示するとき")
    async def players(self, interaction: discord.Interaction, server: str | None = None) -> None:
        snapshots = self._selected_snapshots(server)
        if not snapshots:
            await interaction.response.send_message("指定したサーバーが見つかりません。", ephemeral=True)
            return
        lines: list[str] = []
        for snapshot in snapshots:
            if not snapshot.online:
                lines.append(f"**{snapshot.display_name}**: オフライン")
                continue
            if snapshot.players:
                names = "、".join(
                    f"{player.display_name} (Lv{player.level})" for player in snapshot.players
                )
            else:
                names = "誰もいません"
            lines.append(f"**{snapshot.display_name}**: {names}")
        await interaction.response.send_message("\n".join(lines))

    @players.autocomplete("server")
    async def players_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self.status_autocomplete(interaction, current)

    @app_commands.command(name="join", description="サーバーへの入り方を表示します")
    async def join(self, interaction: discord.Interaction) -> None:
        snapshots = self._selected_snapshots(None)
        await interaction.response.send_message(embed=build_join_embed(snapshots))

    @app_commands.command(name="announce", description="ゲーム内にメッセージを流します（管理者用）")
    @app_commands.describe(server="対象サーバー", message="ゲーム内に表示する文章")
    async def announce(
        self, interaction: discord.Interaction, server: str, message: str
    ) -> None:
        if interaction.user.id not in self._discord().owner_user_ids:
            await interaction.response.send_message("このコマンドは管理者専用です。", ephemeral=True)
            return
        client = self.bot.clients.get(server)
        target = next((item for item in self.bot.config.servers if item.id == server), None)
        if client is None or target is None:
            await interaction.response.send_message("サーバーが見つかりません。", ephemeral=True)
            return
        try:
            await client.announce(message)
        except PalworldAPIError as exc:
            await interaction.response.send_message(f"送信に失敗しました: {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**{target.name}** にアナウンスしました: {message}",
            ephemeral=True,
        )

    @announce.autocomplete("server")
    async def announce_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return await self.status_autocomplete(interaction, current)


async def setup(bot: PalworldBot) -> None:
    await bot.add_cog(StatusCog(bot))
