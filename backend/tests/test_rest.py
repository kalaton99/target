"""REST API tests: auth, wallet, tables."""
import os
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://gracious-raman-3.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Health ----------
def test_health():
    r = requests.get(f"{API}/health", timeout=10)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root():
    r = requests.get(f"{API}/", timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "TARGET"


# ---------- Auth ----------
def test_register_creates_user_with_signup_bonus():
    rnd = uuid.uuid4().hex[:8]
    email = f"test_{rnd}@targetgame.app"
    payload = {"email": email, "username": f"TEST_{rnd}", "password": "Target!2025"}
    r = requests.post(f"{API}/auth/register", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "token" in data and isinstance(data["token"], str)
    assert data["user"]["email"] == email
    assert data["user"]["balance"] == 10000
    # /me reflects balance
    r2 = requests.get(f"{API}/auth/me", headers=_h(data["token"]), timeout=10)
    assert r2.status_code == 200
    assert r2.json()["balance"] == 10000


def test_register_duplicate_returns_409():
    rnd = uuid.uuid4().hex[:8]
    email = f"test_{rnd}@targetgame.app"
    payload = {"email": email, "username": f"TEST_{rnd}", "password": "Target!2025"}
    r1 = requests.post(f"{API}/auth/register", json=payload, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/auth/register", json=payload, timeout=15)
    assert r2.status_code == 409


def test_login_invalid_credentials():
    r = requests.post(f"{API}/auth/login", json={"email": "nonexistent_xx@targetgame.app", "password": "wrong"}, timeout=15)
    assert r.status_code == 401


def test_login_player1(player1):
    assert player1["token"]
    assert player1["user"]["email"] == "player1@targetgame.app"


def test_me_requires_auth():
    r = requests.get(f"{API}/auth/me", timeout=10)
    assert r.status_code in (401, 403)


# ---------- Wallet ----------
def test_wallet_balance(player1):
    r = requests.get(f"{API}/wallet/balance", headers=_h(player1["token"]), timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert "balance" in j and isinstance(j["balance"], int)
    assert "version" in j and isinstance(j["version"], int)


def test_wallet_balance_unauth():
    r = requests.get(f"{API}/wallet/balance", timeout=10)
    assert r.status_code in (401, 403)


# ---------- Tables ----------
def test_create_table(player1):
    r = requests.post(
        f"{API}/tables",
        headers=_h(player1["token"]),
        json={"name": "TEST_table", "type": "FREE", "stake": 100, "max_players": 4},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["name"] == "TEST_table"
    assert t["max_players"] == 4
    assert t["stake"] == 100
    assert t["status"] == "OPEN"
    assert len(t["seats"]) == 4
    assert t["commission_rate_bps"] == 2500
    assert "_id" not in t


def test_create_table_invalid_max_players(player1):
    r = requests.post(
        f"{API}/tables",
        headers=_h(player1["token"]),
        json={"name": "TEST_bad", "type": "FREE", "stake": 100, "max_players": 99},
        timeout=15,
    )
    assert r.status_code == 400


def test_list_tables(player1):
    r = requests.get(f"{API}/tables", headers=_h(player1["token"]), timeout=10)
    assert r.status_code == 200
    assert "tables" in r.json()


def test_quick_join_returns_table_and_seat(player1):
    r = requests.post(
        f"{API}/tables/quick-join",
        headers=_h(player1["token"]),
        json={"type": "FREE"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert "table_id" in j
    assert "seat_index" in j
    assert isinstance(j["seat_index"], int)


def test_quick_join_idempotent_same_user(player1):
    """Calling quick-join twice should keep player at the same (or another valid) seat."""
    r1 = requests.post(f"{API}/tables/quick-join", headers=_h(player1["token"]), json={"type": "FREE"}, timeout=15)
    assert r1.status_code == 200
    j1 = r1.json()
    # Calling /join on the same table should return same seat (already-seated path)
    r2 = requests.post(f"{API}/tables/{j1['table_id']}/join", headers=_h(player1["token"]), timeout=15)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["table_id"] == j1["table_id"]
    assert j2["seat_index"] == j1["seat_index"]


def test_get_table(player1):
    r = requests.post(f"{API}/tables/quick-join", headers=_h(player1["token"]), json={"type": "FREE"}, timeout=15)
    assert r.status_code == 200
    tid = r.json()["table_id"]
    r2 = requests.get(f"{API}/tables/{tid}", headers=_h(player1["token"]), timeout=10)
    assert r2.status_code == 200
    assert r2.json()["id"] == tid


def test_get_nonexistent_table(player1):
    r = requests.get(f"{API}/tables/t_doesnotexist", headers=_h(player1["token"]), timeout=10)
    assert r.status_code == 404
