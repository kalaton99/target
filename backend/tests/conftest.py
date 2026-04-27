"""Shared fixtures.

Note on test credentials:
    The legacy /api/auth/login REST endpoints (Phase 1) require a password.
    These fixtures provision four throwaway accounts on the *test* backend
    and reuse a constant password between runs so /api/auth/login can
    short-circuit on second invocation. The password is NOT a production
    credential — it lives only in this test environment and against the
    legacy endpoints that the Phase-11 lobby flow has already replaced
    (see legacy/auth dir, marked out-of-scope in PRD).

    To override, set TARGET_TEST_PASSWORD in the test runner's env.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gracious-raman-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Test-only password for the legacy /auth/login fixtures. Override via env.
DEFAULT_PASSWORD = os.environ.get("TARGET_TEST_PASSWORD", "Target!2025")
TEST_USERS = [
    ("player1@targetgame.app", "player_one"),
    ("player2@targetgame.app", "player_two"),
    ("player3@targetgame.app", "player_three"),
    ("player4@targetgame.app", "player_four"),
]


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_url():
    return API


def _login_or_register(email, username, password=DEFAULT_PASSWORD):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code == 200:
        return r.json()
    # try register
    r2 = requests.post(f"{API}/auth/register", json={"email": email, "username": username, "password": password}, timeout=15)
    if r2.status_code == 200:
        return r2.json()
    if r2.status_code == 409:
        # exists with different pw probably; try login again
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
        if r.status_code == 200:
            return r.json()
    raise RuntimeError(f"login/register failed for {email}: login={r.status_code} reg={r2.status_code} body={r2.text}")


@pytest.fixture(scope="session")
def players():
    """Login or register the 4 standard test players."""
    out = []
    for email, username in TEST_USERS:
        out.append(_login_or_register(email, username))
    return out


@pytest.fixture(scope="session")
def player1(players):
    return players[0]


@pytest.fixture(scope="session")
def player2(players):
    return players[1]
