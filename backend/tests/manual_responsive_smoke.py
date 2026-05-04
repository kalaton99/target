"""Responsive layout smoke test — verifies both desktop (1280) and
mobile (390) viewports render the key responsive behaviours correctly.

Run directly with the plugins venv:
    /opt/plugins-venv/bin/python /tmp/resp_smoke.py
"""
import os
import uuid
from playwright.sync_api import sync_playwright

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


def check_viewport(browser, width: int, height: int, label: str):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    page.goto(f"{BASE}/lobby", wait_until="domcontentloaded")
    page.wait_for_timeout(500)
    # Login
    page.get_by_test_id("username-input").fill(f"H_{uuid.uuid4().hex[:4]}")
    page.get_by_test_id("login-btn").click(force=True)
    page.wait_for_selector('[data-testid="logout-btn"]', timeout=10_000)
    # Create a table
    page.get_by_test_id("target-select").select_option("50")
    page.get_by_test_id("bot-count-input").fill("3")
    page.get_by_test_id("create-table-btn").click(force=True)
    page.wait_for_timeout(1_000)
    # Start
    page.locator('[data-testid^="start-btn-"]').first.click(force=True)
    page.wait_for_selector('[data-testid="actions-bar"]', timeout=10_000)
    page.wait_for_timeout(800)

    actions = page.locator('[data-testid="actions-bar"]').first
    actions_bbox = actions.bounding_box()
    # Opponent card — first one
    opp = page.locator('[data-testid^="opponent-seat-"]').first
    opp_bbox = opp.bounding_box()
    # Status line visibility
    status_visible = page.locator('[data-testid="status-line"]').first.is_visible()

    print(f"\n--- {label} viewport={width}x{height} ---")
    print(f"  actions-bar bbox: {actions_bbox}")
    print(f"  opponent-seat-0 bbox: {opp_bbox}")
    print(f"  status-line visible: {status_visible}")

    # Desktop assertions
    if width >= 640:  # Tailwind `sm:` breakpoint
        # Actions bar should be static (not pinned to bottom): its y should
        # be somewhere mid-page, not near viewport height.
        assert actions_bbox["y"] < height - 20, (
            f"desktop: actions-bar appears pinned to bottom at y={actions_bbox['y']}"
        )
        # Status line visible on desktop
        assert status_visible, "desktop: status-line hidden"
        # Opponent should be 220px min, not full width
        assert opp_bbox["width"] < width - 40, (
            f"desktop: opponent width {opp_bbox['width']} too close to viewport"
        )
    else:  # mobile
        # Actions bar should be sticky at the bottom: bottom edge within
        # ~20px of the viewport bottom (allowing for browser chrome).
        bottom = actions_bbox["y"] + actions_bbox["height"]
        assert (height - bottom) < 25, (
            f"mobile: actions-bar bottom={bottom} not close to viewport bottom {height}"
        )
        # Status line hidden on mobile
        assert not status_visible, "mobile: status-line should be hidden"
        # Opponent row should be full-width minus page padding (p-4 = 16)
        assert opp_bbox["width"] >= width - 48, (
            f"mobile: opponent width {opp_bbox['width']} is not full-bleed (viewport={width})"
        )
        # No horizontal overflow on the root container
        root = page.locator(".max-w-5xl").first.bounding_box()
        assert root["width"] <= width, (
            f"mobile: root container {root['width']} exceeds viewport {width}"
        )
    ctx.close()
    print(f"  {label}: PASS")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            check_viewport(browser, 1280, 800, "DESKTOP")
            check_viewport(browser, 390, 844, "MOBILE iPhone-14")
            check_viewport(browser, 430, 932, "MOBILE iPhone-15 Pro Max")
        finally:
            browser.close()
    print("\nALL PASS")


if __name__ == "__main__":
    main()
