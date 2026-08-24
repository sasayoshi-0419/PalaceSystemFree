from palworld_discord_bot.formatting import StatusMessageStore


def test_status_message_store_roundtrip(tmp_path) -> None:
    path = tmp_path / "status_message.json"
    store = StatusMessageStore(path)
    assert store.load() is None
    store.save(11, 22)
    assert store.load() == (11, 22)
