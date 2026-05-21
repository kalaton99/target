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
        "frontend/src/pages/TmargetPages.jsx",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "deposit now" not in source.lower()
        assert "connect wallet" not in source.lower()
        assert "cash out" not in source.lower()
