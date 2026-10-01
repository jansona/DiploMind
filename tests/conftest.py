"""Tests never read or modify the application's persisted room credentials."""
import pytest


@pytest.fixture(autouse=True)
def isolated_saves(tmp_path, monkeypatch):
    from diplomind.session import Session
    monkeypatch.setattr(Session, "SAVES", tmp_path / "saves")
    import diplomind.web as web
    from diplomind.rooms import RoomManager
    monkeypatch.setattr(web, "RM", RoomManager())
