from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_tmarget_market_detail_warns_before_exiting_active_demo_exposure():
    source = (ROOT / "frontend/src/pages/TmargetPages.jsx").read_text(encoding="utf-8")

    assert "Leave Market Detail?" in source
    assert "Leaving may cause the current demo-credit participation view to be lost." in source
    assert "Your Tmarget positions remain on the backend." in source


def test_product_exit_guards_do_not_replace_backend_rules_with_penalty_logic():
    for relative in (
        "frontend/src/pages/DicegetPage.jsx",
        "frontend/src/pages/FlipgetPage.jsx",
        "frontend/src/pages/JackgetPage.jsx",
        "frontend/src/pages/TmargetPages.jsx",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "deposit now" not in source.lower()
        assert "connect wallet" not in source.lower()
        assert "cash out" not in source.lower()


def test_jackget_frontend_is_separate_from_target_routes_and_warns_on_active_exit():
    source = (ROOT / "frontend/src/pages/JackgetPage.jsx").read_text(encoding="utf-8")
    app = (ROOT / "frontend/src/App.js").read_text(encoding="utf-8")
    games = (ROOT / "frontend/src/pages/PlatformPages.jsx").read_text(encoding="utf-8")

    assert "/api/jackget/tables" in source
    assert "/api/v2/lobby" not in source
    assert "/api/v2/ws/table" not in source
    assert "Leave active Jackget table?" in source
    assert "reserved internal demo credits/stake" in source
    assert 'path="/jackget"' in app
    assert 'path="/jackget/:tableId"' in app
    assert "/games/jackget" in app
    assert "Jackget" in games


def test_game_lobbies_explain_rules_without_separate_quick_table_panels():
    pages = {
        "Target": ROOT / "frontend/src/pages/LobbyPage.jsx",
        "Diceget": ROOT / "frontend/src/pages/DicegetPage.jsx",
        "Flipget": ROOT / "frontend/src/pages/FlipgetPage.jsx",
        "Jackget": ROOT / "frontend/src/pages/JackgetPage.jsx",
        "Tmarget": ROOT / "frontend/src/pages/TmargetPages.jsx",
    }
    for name, path in pages.items():
        source = path.read_text(encoding="utf-8")
        assert "How to Play" in source, name
        assert "Joinable Demo Tables" not in source, name
        assert "Quick Table" not in source, name


def test_diceget_visible_surrender_copy_is_clear_without_renaming_api():
    source = (ROOT / "frontend/src/pages/DicegetPage.jsx").read_text(encoding="utf-8")

    assert ">Forfeit<" not in source
    assert "Give Up" in source
    assert "reserved demo stake may be lost" in source
    assert "/forfeit" in source
