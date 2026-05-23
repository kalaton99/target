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
        assert "howToPlayOpen" in source, name
        assert "setHowToPlayOpen(true)" in source, name
        assert "Close" in source, name
        assert "Joinable Demo Tables" not in source, name
        assert "Quick Table" not in source, name


def test_lobby_lists_default_to_five_visible_rows_without_backend_caps():
    expected = {
        "Target": ("frontend/src/pages/LobbyPage.jsx", "const visibleTables = showAllTables ? currentTargetTables : currentTargetTables.slice(0, 5);"),
        "Diceget": ("frontend/src/pages/DicegetPage.jsx", "const visibleTables = showAllTables ? sortedTables : sortedTables.slice(0, 5);"),
        "Flipget": ("frontend/src/pages/FlipgetPage.jsx", "const visibleTables = showAllTables ? sortedTables : sortedTables.slice(0, 5);"),
        "Jackget": ("frontend/src/pages/JackgetPage.jsx", "const visibleTables = showAllTables ? sortedTables : sortedTables.slice(0, 5);"),
        "Tmarget": ("frontend/src/pages/TmargetPages.jsx", "const visibleMarkets = showAllMarkets ? sortedMarkets : sortedMarkets.slice(0, 5);"),
    }
    for name, (relative, cap_expression) in expected.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert cap_expression in source, name
        assert "Show all" in source, name


def test_lobby_lists_filter_or_deprioritize_stale_tables():
    target = (ROOT / "frontend/src/pages/LobbyPage.jsx").read_text(encoding="utf-8")
    diceget = (ROOT / "frontend/src/pages/DicegetPage.jsx").read_text(encoding="utf-8")
    flipget = (ROOT / "frontend/src/pages/FlipgetPage.jsx").read_text(encoding="utf-8")
    jackget = (ROOT / "frontend/src/pages/JackgetPage.jsx").read_text(encoding="utf-8")

    assert "VALID_TARGET_TIERS" in target
    for legacy in ("new Set([30", "50, 75, 100", "target 30", "target 100"):
        assert legacy not in target
    assert "currentTargetTables = tables.filter" in target
    assert "TABLE_STATUS_RANK" in diceget
    assert "TABLE_STATUS_RANK" in flipget
    assert "TABLE_STATUS_RANK" in jackget


def test_how_to_play_copy_covers_current_rules():
    target = (ROOT / "frontend/src/pages/LobbyPage.jsx").read_text(encoding="utf-8")
    diceget = (ROOT / "frontend/src/pages/DicegetPage.jsx").read_text(encoding="utf-8")
    flipget = (ROOT / "frontend/src/pages/FlipgetPage.jsx").read_text(encoding="utf-8")
    jackget = (ROOT / "frontend/src/pages/JackgetPage.jsx").read_text(encoding="utf-8")
    tmarget = (ROOT / "frontend/src/pages/TmargetPages.jsx").read_text(encoding="utf-8")

    for text in ("31, 41, 51, and 61", "31/41 use 4-seat tables", "J/Q/K score 10", "5 cards", "reserved demo stake"):
        assert text in target
    for text in ("Sprint 40", "Classic 70", "Marathon 120", "roll dice", "Give Up"):
        assert text in diceget
    for text in ("Single Flip", "Best of 3", "Best of 5", "fresh Heads/Tails choice", "one demo opponent"):
        assert text in flipget
    for text in ("2-4 players", "3-reel slot", "exactly 3 spins", "Demo opponents spin automatically"):
        assert text in jackget
    for text in ("demo prediction-market product", "YES/NO positions", "Market volume", "No real-money trading"):
        assert text in tmarget


def test_diceget_visible_surrender_copy_is_clear_without_renaming_api():
    source = (ROOT / "frontend/src/pages/DicegetPage.jsx").read_text(encoding="utf-8")

    assert ">Forfeit<" not in source
    assert "Give Up" in source
    assert "reserved demo stake may be lost" in source
    assert "/forfeit" in source
