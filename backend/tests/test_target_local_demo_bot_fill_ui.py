from pathlib import Path


def test_target_lobby_exposes_local_demo_bot_fill_control():
    source = (Path(__file__).resolve().parents[2] / "frontend/src/pages/LobbyPage.jsx").read_text(encoding="utf-8")

    assert "auto-fill-target-bots-btn" in source
    assert "Auto-fill demo bots" in source
    assert "For a one-human local demo" in source
    assert "fills the remaining" in source
    assert "setBotCount(String(perTargetBotMax))" in source
    assert "target-lobby-back-btn" in source
    assert "Back to Games" in source
