import base64

from palworld_discord_bot.bot import (
    application_id_from_token,
    bot_invite_url,
    missing_access_message,
)
from palworld_discord_bot.__main__ import main as bot_main


def test_application_id_from_bot_token() -> None:
    token = base64.b64encode(b"123456789012345678").decode("ascii").rstrip("=") + ".xxx.yyy"
    assert application_id_from_token(token) == 123456789012345678


def test_missing_access_message_includes_invite() -> None:
    message = missing_access_message(111, 222)
    assert "111" in message
    assert "applications.commands" in message
    assert bot_invite_url(222) in message
    assert "84992" in bot_invite_url(222)


def test_invite_cli(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("PAL_MAIN_ADMIN_PASSWORD", "secret-pass")
    token = base64.b64encode(b"987654321098765432").decode("ascii").rstrip("=") + ".xxx.yyy"
    monkeypatch.setenv("DISCORD_TOKEN", token)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
discord:
  guild_id: 1
  status_channel_id: 2
  notify_channel_id: 3
  notify_role_id: null
  owner_user_ids: [99]
  poll_interval_seconds: 20
servers:
  - id: main
    name: 本鯖
    rest_url: http://127.0.0.1:8212
    admin_password_env: PAL_MAIN_ADMIN_PASSWORD
    join_info: example:8211
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert bot_main(["--config", str(config_path), "--invite"]) == 0
    output = capsys.readouterr().out
    assert "client_id=987654321098765432" in output
    assert "applications.commands" in output
