from pathlib import Path

from palworld_discord_bot.paths import app_root, is_frozen, resolve_user_path
from palworld_discord_bot.setup import apply_setup
from palworld_discord_bot.config import load_config
from palworld_discord_bot.settings_ini import load_settings_file, write_settings_file


def test_resolve_user_path_relative(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert resolve_user_path("config.yaml") == tmp_path / "config.yaml"
    assert is_frozen() is False
    assert app_root() == tmp_path


def test_resolve_user_path_absolute(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "config.yaml"
    assert resolve_user_path(target) == target


def test_apply_setup_writes_files(tmp_path: Path) -> None:
    pal = tmp_path / "PalServer"
    pal.mkdir()
    (pal / "PalServer.exe").write_bytes(b"mz")
    settings = pal / "Pal" / "Saved" / "Config" / "WindowsServer" / "PalWorldSettings.ini"
    settings.parent.mkdir(parents=True)
    write_settings_file(settings, {"ExpRate": "1.000000", "RESTAPIEnabled": "False", "AdminPassword": "old"})
    note = apply_setup(
        root=tmp_path,
        config_path=tmp_path / "config.yaml",
        palserver=pal,
        password="secret-pass",
        name="本鯖",
    )
    assert "REST API" in note
    config = load_config(tmp_path / "config.yaml", dotenv_path=tmp_path / ".env", require_discord_token=False)
    assert config.servers[0].name == "本鯖"
    assert load_settings_file(settings)["RESTAPIEnabled"] == "True"
    assert "PAL_MAIN_ADMIN_PASSWORD=secret-pass" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_setup_gui_importable() -> None:
    from palworld_admin.setup_gui import run_setup_gui

    assert callable(run_setup_gui)
