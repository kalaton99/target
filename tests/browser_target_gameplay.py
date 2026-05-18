"""Live browser regression for the Target lobby/play WebSocket loop.

Run with backend and frontend already running:

    backend\\.venv\\Scripts\\python.exe -m pytest tests\\browser_target_gameplay.py

The test skips cleanly when Playwright, Chrome/Edge, or the local backend is
unavailable. It intentionally targets only the Target game flow.
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


def _api(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{BACKEND}{path}",
        data=data,
        headers=headers,
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
        self.requests: list[str] = []
        self.websockets: list[str] = []
        page.on("console", self._console)
        page.on("request", self._request)
        page.on("requestfailed", self._request_failed)
        page.on("websocket", self._websocket)

    def _is_app_url(self, url: str) -> bool:
        return FRONTEND in url or BACKEND in url

    def _console(self, msg):
        if msg.type not in {"error", "warning"}:
            return
        if "React DevTools" in msg.text:
            return
        self.console_errors.append(f"{msg.type}: {msg.text}")

    def _request(self, request):
        if self._is_app_url(request.url):
            self.requests.append(request.url)

    def _request_failed(self, request):
        url = request.url
        if not self._is_app_url(url):
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
        if websocket.url.endswith("/ws"):
            return
        websocket.on(
            "socketerror",
            lambda error: self.failed_requests.append(f"WS {websocket.url} {error}"),
        )

    def assert_clean(self):
        assert self.console_errors == []
        assert self.failed_requests == []


def test_target_lobby_table_and_websocket_loop_stays_target_only():
    try:
        manager = sync_playwright()
        playwright = manager.__enter__()
    except PermissionError as exc:  # pragma: no cover - local OS sandbox guard
        pytest.skip(f"Playwright driver could not start in this environment: {exc}")
    try:
        browser = playwright.chromium.launch(headless=True, executable_path=_chrome_path())
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        audit = BrowserAudit(page)
        try:
            page.goto(f"{FRONTEND}/games/target", wait_until="domcontentloaded")
            page.wait_for_url("**/lobby", timeout=10_000)
            assert page.url == f"{FRONTEND}/lobby"

            page.goto(f"{FRONTEND}/target", wait_until="domcontentloaded")
            page.wait_for_url("**/lobby", timeout=10_000)
            assert page.url == f"{FRONTEND}/lobby"

            if page.get_by_test_id("logout-btn").count() == 0:
                page.get_by_test_id("username-input").fill(f"target{random.randint(1000, 9999)}")
                page.get_by_test_id("login-btn").click()
                page.get_by_test_id("logout-btn").wait_for(timeout=10_000)

            page.get_by_test_id("bot-count-input").fill("1")
            page.get_by_test_id("create-table-btn").click()
            page.wait_for_timeout(500)
            start_buttons = page.locator("[data-testid^='start-btn-']")
            assert start_buttons.count() >= 1
            start_buttons.first.click(timeout=10_000)
            page.wait_for_url("**/play/*", timeout=10_000)
            assert "/play/" in page.url

            page.get_by_test_id("actions-bar").wait_for(timeout=15_000)
            page.get_by_test_id("target-pill").wait_for(timeout=15_000)
            page.get_by_test_id("my-hand").wait_for(timeout=15_000)
            page.get_by_test_id("target-action-hint").wait_for(timeout=15_000)
            page.wait_for_function(
                """
                () => {
                  const check = document.querySelector('[data-testid="check-btn"]');
                  return check && !check.disabled;
                }
                """,
                timeout=15_000,
            )
            hint = page.get_by_test_id("target-action-hint").inner_text(timeout=5_000)
            assert "Your betting turn" in hint
            page.get_by_test_id("check-btn").click(timeout=10_000)
            page.wait_for_function(
                """
                () => {
                  const status = document.querySelector('[data-testid="status-line"]');
                  return status && status.textContent.includes('ACK CHECK');
                }
                """,
                timeout=10_000,
            )

            assert any("/api/v2/lobby" in url for url in audit.requests)
            assert not any("/api/diceget" in url for url in audit.requests)
            assert not any("/api/flipget" in url for url in audit.requests)
            assert not any("/api/tmarget" in url for url in audit.requests)

            target_ws = [
                url for url in audit.websockets
                if "/api/v2/ws/table/" in url
            ]
            assert target_ws, audit.websockets
            assert all("%3Ftoken" not in url for url in target_ws)
            assert all("/api/v2/ws/table/" in url for url in target_ws)

            body = page.locator("body").inner_text(timeout=5_000)
            assert "Target Platform" not in body
            assert "Tmarget game" not in body
            audit.assert_clean()
        finally:
            context.close()
            browser.close()
    finally:
        manager.__exit__(None, None, None)
