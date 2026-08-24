from __future__ import annotations

from palworld_discord_bot.config import AppConfig
from palworld_discord_bot.operations import ServerOperator
from palworld_discord_bot.palworld import PalworldClient
from palworld_discord_bot.paths import resolve_user_path


class AdminRuntime:
    def __init__(self, config: AppConfig, *, config_path: str | None = None) -> None:
        self.config = config
        self.config_path = (
            resolve_user_path(config_path) if config_path else resolve_user_path("config.yaml")
        )
        self.clients = {
            server.id: PalworldClient(server.rest_url, server.admin_password)
            for server in config.servers
        }
        self.operators = {
            server.id: ServerOperator(server, self.clients[server.id], config.data_dir)
            for server in config.servers
        }

    def operator(self, server_id: str) -> ServerOperator:
        target = self.operators.get(server_id)
        if target is None:
            known = ", ".join(self.operators)
            raise KeyError(f"サーバー ID が見つかりません: {server_id}（候補: {known}）")
        return target

    async def close(self) -> None:
        for client in self.clients.values():
            await client.aclose()
