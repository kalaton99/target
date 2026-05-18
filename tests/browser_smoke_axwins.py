"""Live browser smoke checks for Axwins product isolation and demo loops.

Run with local backend/frontend already running:

    backend\\.venv\\Scripts\\python.exe -m pytest tests\\browser_smoke_axwins.py

The test uses Playwright when installed. It skips cleanly when Playwright or a
local Chromium/Chrome executable is unavailable.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover - environment guard
    sync_playwright = None


FRONTEND = os.environ.get("AXWINS_FRONTEND_URL", "http://localhost:3000").rstrip("/")
BACKEND = os.environ.get("AXWINS_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def _chrome_path() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return shutil.which("chrome") or shutil.which("msedge")


def _api(method: str, path: str, body: dict | None = None, token: str | None = None, headers: dict | None = None):
    request_headers = {"Content-Type": "application/json"}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    if headers:
        request_headers.update(headers)
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{BACKEND}{path}",
        data=data,
        headers=request_headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read().decode("utf-8")
        return json.loads(payload) if payload else None


def _backend_available() -> bool:
    try:
        return _api("GET", "/api/health") == {"status": "ok"}
    except (OSError, urllib.error.URLError):
        return False


pytestmark = pytest.mark.skipif(
    sync_playwright is None or _chrome_path() is None or not _backend_available(),
    reason="Playwright, local Chrome/Edge, or local Axwins backend is unavailable",
)


class BrowserAudit:
    def __init__(self, page):
        self.console_errors: list[str] = []
        self.failed_requests: list[str] = []
        self.websockets: list[str] = []
        page.on("console", self._console)
        page.on("requestfailed", self._request_failed)
        page.on("websocket", self._websocket)

    def _console(self, msg):
        if msg.type not in {"error", "warning"}:
            return
        if "React DevTools" in msg.text:
            return
        self.console_errors.append(f"{msg.type}: {msg.text}")

    def _request_failed(self, request):
        url = request.url
        if "localhost:3000" not in url and "127.0.0.1:8000" not in url:
            return
        if url.endswith("/ws"):
            return
        raw_failure = request.failure
        failure = getattr(raw_failure, "error_text", raw_failure) or "unknown"
        if "ERR_ABORTED" in str(failure):
            return
        self.failed_requests.append(f"{request.method} {url} {failure}")

    def _websocket(self, websocket):
        self.websockets.append(websocket.url)
        websocket.on("socketerror", lambda error: self.failed_requests.append(f"WS {websocket.url} {error}"))

    def assert_clean(self):
        app_console = [
            item
            for item in self.console_errors
            if "401 (Unauthorized)" not in item
        ]
        assert app_console == []
        assert self.failed_requests == []


def _login(page):
    page.goto(f"{FRONTEND}/lobby", wait_until="domcontentloaded")
    if page.get_by_test_id("logout-btn").count() == 0:
        page.get_by_test_id("username-input").fill(f"u{random.randint(1000, 9999)}")
        page.get_by_test_id("login-btn").click()
        page.get_by_test_id("logout-btn").wait_for(timeout=10_000)


def _stored_user(page) -> dict:
    raw = page.evaluate("window.localStorage.getItem('target_user')")
    return json.loads(raw)


def test_product_routes_and_demo_loops_do_not_cross_wire():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=_chrome_path())
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        audit = BrowserAudit(page)
        try:
            for route in ["/", "/games", "/games/target", "/target", "/diceget", "/flipget", "/tmarget", "/wallet"]:
                page.goto(f"{FRONTEND}{route}", wait_until="domcontentloaded")
                body = page.locator("body").inner_text(timeout=5_000)
                assert "Tmarget game" not in body
                assert "Target Platform" not in body

            assert page.url == f"{FRONTEND}/wallet"
            _login(page)
            user = _stored_user(page)

            # Diceget: create table, fill with bots, start, and roll.
            page.goto(f"{FRONTEND}/diceget", wait_until="domcontentloaded")
            page.get_by_role("button", name="Create Diceget Table").click(timeout=10_000)
            page.wait_for_url("**/diceget/*", timeout=10_000)
            assert "/diceget/" in page.url
            for _ in range(3):
                add_bot = page.get_by_role("button", name="Add Bot Seat")
                add_bot.click(timeout=10_000)
                page.wait_for_timeout(250)
            page.get_by_role("button", name="Start Diceget").click(timeout=10_000)
            page.wait_for_timeout(500)
            roll = page.get_by_role("button", name="Roll")
            assert roll.is_enabled()
            roll.click(timeout=10_000)
            page.wait_for_timeout(500)
            diceget_body = page.locator("body").inner_text(timeout=5_000)
            assert "ROLL HISTORY" in diceget_body
            assert "/api/v2/ws/table" not in diceget_body

            # Flipget: a single signed-in user is intentionally blocked until a
            # second participant joins; the UI must say so and must not use
            # Target WebSocket routes.
            page.goto(f"{FRONTEND}/flipget", wait_until="domcontentloaded")
            page.get_by_role("button", name="Create Flipget Table").click(timeout=10_000)
            page.wait_for_url("**/flipget/*", timeout=10_000)
            assert "/flipget/" in page.url
            page.get_by_role("button", name="Choose heads").click(timeout=10_000)
            page.get_by_role("button", name="Ready Up").click(timeout=10_000)
            flip = page.get_by_role("button", name="Flip Coin")
            assert not flip.is_enabled()
            flipget_body = page.locator("body").inner_text(timeout=5_000)
            assert "Flip unlocks after two players choose unique sides" in flipget_body
            assert "/api/v2/ws/table" not in flipget_body

            # Tmarget: create/open a demo market through API and buy YES through
            # the browser UI using internal demo credits.
            market = _api(
                "POST",
                "/api/tmarget/admin/markets",
                {
                    "title": f"Browser smoke market {random.randint(1000, 9999)}",
                    "description": "Internal demo-credit browser smoke market.",
                    "category": "Audit",
                    "close_time": "2030-01-01T00:00:00Z",
                    "resolution_criteria": "Audit-only criterion.",
                    "source_url": "",
                    "initial_liquidity": 100,
                },
                token=user["token"],
                headers={"X-Axwins-Demo-Admin": "true"},
            )
            _api(
                "POST",
                f"/api/tmarget/admin/markets/{market['id']}/open",
                {},
                token=user["token"],
                headers={"X-Axwins-Demo-Admin": "true"},
            )
            page.goto(f"{FRONTEND}/tmarget/markets/{market['slug']}", wait_until="domcontentloaded")
            page.get_by_role("button", name="Buy Demo Shares").click(timeout=10_000)
            page.wait_for_timeout(500)
            tmarget_body = page.locator("body").inner_text(timeout=5_000)
            assert "Bought 1 YES demo shares." in tmarget_body
            assert "demo prediction market product" in tmarget_body

            assert all("/api/v2/ws/table" not in url for url in audit.websockets)
            audit.assert_clean()
        finally:
            browser.close()
