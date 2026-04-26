"""Phase 5 (revised) — durable WAL wallet/ledger tests.

Covers:
  - debit / credit
  - insufficient funds (terminal VOIDED)
  - duplicate idempotency (returns cached COMPLETE)
  - version conflict retry under contention
  - double-entry balance invariant
  - no negative balance
  - integers only

Crash / recovery scenarios (the architectural reason for this rewrite):
  - crash after idempotency PENDING (steps 1 only)
  - crash after journal+ledger PENDING (steps 1-3) before wallet update
  - crash after wallet update before ledger POSTED (between steps 4 and 5)
  - crash after ledger POSTED before idempotency COMPLETE (between 5 and 6)
  - retry finalizes without double debit
  - ledger and wallet remain consistent after recovery
  - no duplicate journal rows under retries
  - idempotency COMPLETE returns cached response
"""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError

from core.config import MONGO_URL
from ledger.service import (
    LedgerService,
    InsufficientFunds,
    WalletError,
    WalletNotFound,
    _journal_id_for,
    _idem_id_for,
    _tx_id_for,
)


async def _safe_client(retries: int = 3):
    last = None
    for i in range(retries):
        try:
            client = AsyncIOMotorClient(MONGO_URL, maxPoolSize=10)
            await client.admin.command("ping")
            return client
        except (AutoReconnect, ServerSelectionTimeoutError) as exc:
            last = exc
            await asyncio.sleep(0.05 * (i + 1))
    raise last  # type: ignore[misc]


# ---------- fixtures ----------

@pytest.fixture
async def db():
    client = await _safe_client()
    name = f"target_phase5_{uuid.uuid4().hex[:8]}"
    db = client[name]
    await LedgerService.ensure_indexes(
        db["wallets"], db["transactions"], db["idempotency_keys"], db["journals"]
    )
    yield db
    try:
        await client.drop_database(name)
    except Exception:
        pass
    client.close()


@pytest.fixture
async def svc(db):
    return LedgerService(
        db["wallets"], db["transactions"], db["idempotency_keys"], db["journals"],
    )


# ---------- happy path ----------

class TestBasic:

    @pytest.mark.asyncio
    async def test_credit_increases_balance(self, svc):
        await svc.open_wallet("u1", opening_balance=0)
        res = await svc.mutate(
            user_id="u1", delta=500, reason="DEPOSIT",
            ref_type="SYSTEM", ref_id=None,
            idempotency_key="k1", counter_account="TREASURY",
        )
        assert res["balance"] == 500
        assert res["version"] == 1

    @pytest.mark.asyncio
    async def test_debit_decreases_balance(self, svc):
        await svc.open_wallet("u1", opening_balance=1000)
        res = await svc.mutate(
            user_id="u1", delta=-300, reason="ANTE",
            ref_type="HAND", ref_id="h1",
            idempotency_key="k2", counter_account="POT",
        )
        assert res["balance"] == 700

    @pytest.mark.asyncio
    async def test_no_negative_balance(self, svc):
        await svc.open_wallet("u1", opening_balance=100)
        with pytest.raises(InsufficientFunds):
            await svc.mutate(
                user_id="u1", delta=-500, reason="ANTE",
                ref_type="HAND", ref_id="h",
                idempotency_key="k3", counter_account="POT",
            )
        w = await svc.get_balance("u1")
        assert w["balance"] == 100
        assert w["version"] == 0

    @pytest.mark.asyncio
    async def test_integer_only(self, svc):
        await svc.open_wallet("u1", opening_balance=100)
        with pytest.raises(WalletError, match="AMOUNT_MUST_BE_INTEGER"):
            await svc.mutate(
                user_id="u1", delta=10.5, reason="X",  # type: ignore[arg-type]
                ref_type="SYSTEM", ref_id=None,
                idempotency_key="k4", counter_account="HOUSE",
            )


# ---------- idempotency / cached response ----------

class TestIdempotency:

    @pytest.mark.asyncio
    async def test_complete_returns_cached_response(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        first = await svc.mutate(
            user_id="u1", delta=-100, reason="ANTE",
            ref_type="HAND", ref_id="h", idempotency_key="kx",
            counter_account="POT",
        )
        second = await svc.mutate(
            user_id="u1", delta=-100, reason="ANTE",
            ref_type="HAND", ref_id="h", idempotency_key="kx",
            counter_account="POT",
        )
        assert first == second
        w = await svc.get_balance("u1")
        assert w["balance"] == 900
        assert w["version"] == 1
        # exactly one paired ledger entry
        n_user = await db["transactions"].count_documents({"user_id": "u1"})
        assert n_user == 1

    @pytest.mark.asyncio
    async def test_voided_returns_same_error(self, svc):
        await svc.open_wallet("u1", opening_balance=10)
        with pytest.raises(InsufficientFunds):
            await svc.mutate(
                user_id="u1", delta=-100, reason="ANTE",
                ref_type="HAND", ref_id="h", idempotency_key="kv",
                counter_account="POT",
            )
        # Even after top up, same key remains VOIDED
        await svc.mutate(
            user_id="u1", delta=500, reason="TOPUP",
            ref_type="SYSTEM", ref_id=None,
            idempotency_key="topup1", counter_account="TREASURY",
        )
        with pytest.raises(InsufficientFunds):
            await svc.mutate(
                user_id="u1", delta=-100, reason="ANTE",
                ref_type="HAND", ref_id="h", idempotency_key="kv",
                counter_account="POT",
            )

    @pytest.mark.asyncio
    async def test_concurrent_same_key_no_double_debit(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)

        async def go():
            try:
                return ("ok", await svc.mutate(
                    user_id="u1", delta=-200, reason="BET",
                    ref_type="HAND", ref_id="h",
                    idempotency_key="kc", counter_account="POT",
                ))
            except WalletError as e:
                return ("err", str(e))

        results = await asyncio.gather(*[go() for _ in range(8)])
        oks = [r for r in results if r[0] == "ok"]
        assert len(oks) >= 1
        for _, r in oks:
            assert r == oks[0][1]  # all OKs are byte-identical (cached replay)

        w = await svc.get_balance("u1")
        assert w["balance"] == 800
        n_user = await db["transactions"].count_documents({"user_id": "u1", "status": "POSTED"})
        assert n_user == 1


# ---------- version conflict retry ----------

class TestVersionConflict:

    @pytest.mark.asyncio
    async def test_concurrent_distinct_keys_all_apply(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)

        async def go(i):
            return await svc.mutate(
                user_id="u1", delta=-50, reason="BET",
                ref_type="HAND", ref_id="h",
                idempotency_key=f"k-{i}", counter_account="POT",
            )

        results = await asyncio.gather(*[go(i) for i in range(10)])
        w = await svc.get_balance("u1")
        assert w["balance"] == 500
        assert w["version"] == 10
        # 10 paired POSTED entries = 10 user-side rows
        n = await db["transactions"].count_documents({"user_id": "u1", "status": "POSTED"})
        assert n == 10


# ---------- double-entry balance invariant ----------

class TestDoubleEntry:

    @pytest.mark.asyncio
    async def test_every_journal_sums_to_zero(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        for i, d in enumerate([-100, -50, 200, -300]):
            await svc.mutate(
                user_id="u1", delta=d, reason="X",
                ref_type="HAND", ref_id="h",
                idempotency_key=f"de-{i}", counter_account="POT",
            )
        sums: dict = {}
        async for tx in db["transactions"].find({"status": "POSTED"}, {"_id": 0}):
            sums.setdefault(tx["journal_id"], 0)
            sums[tx["journal_id"]] += tx["amount"]
        assert all(v == 0 for v in sums.values())
        assert len(sums) == 4

    @pytest.mark.asyncio
    async def test_balance_equals_opening_plus_user_ledger(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        for i, d in enumerate([-100, -50, 200, -300, 500]):
            await svc.mutate(
                user_id="u1", delta=d, reason="X",
                ref_type="HAND", ref_id=f"h{i}",
                idempotency_key=f"be-{i}", counter_account="POT",
            )
        ledger_sum = 0
        async for tx in db["transactions"].find(
            {"user_id": "u1", "account_type": "USER", "status": "POSTED"}, {"_id": 0}
        ):
            ledger_sum += tx["amount"]
        w = await svc.get_balance("u1")
        assert w["balance"] == 1000 + ledger_sum

    @pytest.mark.asyncio
    async def test_no_duplicate_journal_rows_under_repeat_calls(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        # Same key called many times
        for _ in range(5):
            await svc.mutate(
                user_id="u1", delta=-77, reason="X",
                ref_type="HAND", ref_id="h",
                idempotency_key="dup-key", counter_account="POT",
            )
        n_journals = await db["journals"].count_documents({})
        assert n_journals == 1
        n_tx = await db["transactions"].count_documents({})
        assert n_tx == 2  # one paired entry only


# ---------- crash / recovery scenarios ----------
#
# We simulate "crash after step N" by manually setting up the persistent
# state in the same shape the service would have left it after a partial
# run, then calling mutate(...) with the same idempotency_key. The retry
# must finalize correctly and produce a consistent terminal state.

class TestCrashRecovery:

    @pytest.mark.asyncio
    async def test_crash_after_idem_pending_only(self, svc, db):
        """Process died right after Step 1 (idempotency PENDING). No journal
        row, no ledger rows, no wallet update yet. Retry must complete the
        mutation cleanly and produce a single posted journal."""
        await svc.open_wallet("u1", opening_balance=1000)
        idem_id = _idem_id_for("u1", "WALLET", "kr1")
        journal_id = _journal_id_for("u1", "WALLET", "kr1")
        await db["idempotency_keys"].insert_one({
            "id": idem_id,
            "client_action_id": "kr1",
            "user_id": "u1",
            "scope": "WALLET",
            "delta": -200,
            "reason": "BET",
            "ref_type": "HAND",
            "ref_id": "h",
            "counter_account": "POT",
            "journal_id": journal_id,
            "status": "PENDING",
            "response": None,
            "error": None,
            "created_at": "now",
            "expires_at": "later",
        })

        res = await svc.mutate(
            user_id="u1", delta=-200, reason="BET",
            ref_type="HAND", ref_id="h",
            idempotency_key="kr1", counter_account="POT",
        )
        assert res["balance"] == 800
        # Journal & ledger now POSTED
        j = await db["journals"].find_one({"id": journal_id}, {"_id": 0})
        assert j["status"] == "POSTED"
        n_tx = await db["transactions"].count_documents(
            {"journal_id": journal_id, "status": "POSTED"}
        )
        assert n_tx == 2
        # Idempotency now COMPLETE
        idem = await db["idempotency_keys"].find_one({"id": idem_id}, {"_id": 0})
        assert idem["status"] == "COMPLETE"

    @pytest.mark.asyncio
    async def test_crash_after_ledger_pending_before_wallet(self, svc, db):
        """Steps 1-3 done; wallet not yet updated. Retry must apply wallet
        exactly once, post ledger, complete idem."""
        await svc.open_wallet("u1", opening_balance=1000)
        idem_id = _idem_id_for("u1", "WALLET", "kr2")
        journal_id = _journal_id_for("u1", "WALLET", "kr2")
        tx_user_id = _tx_id_for(journal_id, "USER")
        tx_pot_id = _tx_id_for(journal_id, "POT")
        await db["idempotency_keys"].insert_one({
            "id": idem_id, "client_action_id": "kr2", "user_id": "u1",
            "scope": "WALLET", "delta": -150, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "journal_id": journal_id, "status": "PENDING",
            "response": None, "error": None, "created_at": "now", "expires_at": "later",
        })
        await db["journals"].insert_one({
            "id": journal_id, "user_id": "u1", "delta": -150, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "status": "PENDING", "created_at": "now",
        })
        await db["transactions"].insert_many([
            {"id": tx_user_id, "journal_id": journal_id, "user_id": "u1",
             "account_type": "USER", "amount": -150, "balance_after": None,
             "reason": "BET", "ref_type": "HAND", "ref_id": "h",
             "idempotency_key_id": idem_id, "status": "PENDING", "created_at": "now"},
            {"id": tx_pot_id, "journal_id": journal_id, "user_id": None,
             "account_type": "POT", "amount": 150, "balance_after": None,
             "reason": "BET", "ref_type": "HAND", "ref_id": "h",
             "idempotency_key_id": idem_id, "status": "PENDING", "created_at": "now"},
        ])

        res = await svc.mutate(
            user_id="u1", delta=-150, reason="BET",
            ref_type="HAND", ref_id="h",
            idempotency_key="kr2", counter_account="POT",
        )
        assert res["balance"] == 850
        w = await svc.get_balance("u1")
        assert w["balance"] == 850
        assert w["version"] == 1
        # No duplicate journal/ledger rows
        assert await db["journals"].count_documents({"id": journal_id}) == 1
        assert await db["transactions"].count_documents({"journal_id": journal_id}) == 2

    @pytest.mark.asyncio
    async def test_crash_after_wallet_update_before_posted(self, svc, db):
        """Wallet was updated (last_journal_id stamped) but ledger rows still
        PENDING. Retry must NOT double-debit; must only POST ledger + COMPLETE idem.
        """
        await svc.open_wallet("u1", opening_balance=1000)
        idem_id = _idem_id_for("u1", "WALLET", "kr3")
        journal_id = _journal_id_for("u1", "WALLET", "kr3")
        tx_user_id = _tx_id_for(journal_id, "USER")
        tx_pot_id = _tx_id_for(journal_id, "POT")
        # Set up the partial state: idem+journal+ledger PENDING, wallet ALREADY applied
        await db["idempotency_keys"].insert_one({
            "id": idem_id, "client_action_id": "kr3", "user_id": "u1",
            "scope": "WALLET", "delta": -250, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "journal_id": journal_id, "status": "PENDING",
            "response": None, "error": None, "created_at": "now", "expires_at": "later",
        })
        await db["journals"].insert_one({
            "id": journal_id, "user_id": "u1", "delta": -250, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "status": "PENDING", "created_at": "now",
        })
        await db["transactions"].insert_many([
            {"id": tx_user_id, "journal_id": journal_id, "user_id": "u1",
             "account_type": "USER", "amount": -250, "balance_after": None,
             "reason": "BET", "ref_type": "HAND", "ref_id": "h",
             "idempotency_key_id": idem_id, "status": "PENDING", "created_at": "now"},
            {"id": tx_pot_id, "journal_id": journal_id, "user_id": None,
             "account_type": "POT", "amount": 250, "balance_after": None,
             "reason": "BET", "ref_type": "HAND", "ref_id": "h",
             "idempotency_key_id": idem_id, "status": "PENDING", "created_at": "now"},
        ])
        # Mark the wallet as already mutated (balance debited, last_journal_id stamped)
        await db["wallets"].update_one(
            {"user_id": "u1"},
            {"$set": {"balance": 750, "version": 1, "last_journal_id": journal_id}},
        )

        # Retry should NOT double-debit because last_journal_id already matches.
        res = await svc.mutate(
            user_id="u1", delta=-250, reason="BET",
            ref_type="HAND", ref_id="h",
            idempotency_key="kr3", counter_account="POT",
        )
        assert res["balance"] == 750
        assert res["version"] == 1

        w = await svc.get_balance("u1")
        assert w["balance"] == 750
        assert w["version"] == 1
        # Ledger now POSTED
        n_posted = await db["transactions"].count_documents(
            {"journal_id": journal_id, "status": "POSTED"}
        )
        assert n_posted == 2
        # Idempotency now COMPLETE
        idem = await db["idempotency_keys"].find_one({"id": idem_id}, {"_id": 0})
        assert idem["status"] == "COMPLETE"

    @pytest.mark.asyncio
    async def test_crash_after_posted_before_complete(self, svc, db):
        """Wallet + ledger POSTED + journal POSTED, but idem still PENDING.
        Retry must just COMPLETE the idem with the cached response.
        """
        await svc.open_wallet("u1", opening_balance=1000)
        idem_id = _idem_id_for("u1", "WALLET", "kr4")
        journal_id = _journal_id_for("u1", "WALLET", "kr4")
        tx_user_id = _tx_id_for(journal_id, "USER")
        tx_pot_id = _tx_id_for(journal_id, "POT")
        await db["idempotency_keys"].insert_one({
            "id": idem_id, "client_action_id": "kr4", "user_id": "u1",
            "scope": "WALLET", "delta": -300, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "journal_id": journal_id, "status": "PENDING",
            "response": None, "error": None, "created_at": "now", "expires_at": "later",
        })
        await db["journals"].insert_one({
            "id": journal_id, "user_id": "u1", "delta": -300, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "status": "POSTED", "created_at": "now", "posted_at": "now",
        })
        await db["transactions"].insert_many([
            {"id": tx_user_id, "journal_id": journal_id, "user_id": "u1",
             "account_type": "USER", "amount": -300, "balance_after": 700,
             "reason": "BET", "ref_type": "HAND", "ref_id": "h",
             "idempotency_key_id": idem_id, "status": "POSTED",
             "created_at": "now", "posted_at": "now"},
            {"id": tx_pot_id, "journal_id": journal_id, "user_id": None,
             "account_type": "POT", "amount": 300, "balance_after": None,
             "reason": "BET", "ref_type": "HAND", "ref_id": "h",
             "idempotency_key_id": idem_id, "status": "POSTED",
             "created_at": "now", "posted_at": "now"},
        ])
        await db["wallets"].update_one(
            {"user_id": "u1"},
            {"$set": {"balance": 700, "version": 1, "last_journal_id": journal_id}},
        )

        res = await svc.mutate(
            user_id="u1", delta=-300, reason="BET",
            ref_type="HAND", ref_id="h",
            idempotency_key="kr4", counter_account="POT",
        )
        assert res["balance"] == 700
        assert res["version"] == 1
        idem = await db["idempotency_keys"].find_one({"id": idem_id}, {"_id": 0})
        assert idem["status"] == "COMPLETE"

    @pytest.mark.asyncio
    async def test_recovery_no_duplicate_journal_under_many_retries(self, svc, db):
        """Stress: simulate many process restarts mid-mutation by calling
        mutate(...) repeatedly with the same key. Final state must be
        consistent and contain exactly one journal."""
        await svc.open_wallet("u1", opening_balance=1000)
        for _ in range(20):
            res = await svc.mutate(
                user_id="u1", delta=-10, reason="ANTE",
                ref_type="HAND", ref_id="h",
                idempotency_key="solo", counter_account="POT",
            )
        w = await svc.get_balance("u1")
        assert w["balance"] == 990
        assert w["version"] == 1
        n_j = await db["journals"].count_documents({})
        assert n_j == 1
        n_tx = await db["transactions"].count_documents({})
        assert n_tx == 2

    @pytest.mark.asyncio
    async def test_idempotency_params_mismatch_rejected(self, svc, db):
        """If a caller retries with the same idempotency_key but DIFFERENT
        parameters, that's a programming bug — surface it loudly.
        """
        await svc.open_wallet("u1", opening_balance=1000)
        # Pre-create a PENDING idem with a specific delta
        idem_id = _idem_id_for("u1", "WALLET", "params-x")
        journal_id = _journal_id_for("u1", "WALLET", "params-x")
        await db["idempotency_keys"].insert_one({
            "id": idem_id, "client_action_id": "params-x", "user_id": "u1",
            "scope": "WALLET", "delta": -100, "reason": "BET",
            "ref_type": "HAND", "ref_id": "h", "counter_account": "POT",
            "journal_id": journal_id, "status": "PENDING",
            "response": None, "error": None, "created_at": "now", "expires_at": "later",
        })
        with pytest.raises(WalletError, match="IDEMPOTENCY_KEY_PARAMS_MISMATCH"):
            await svc.mutate(
                user_id="u1", delta=-200, reason="BET",  # mismatch
                ref_type="HAND", ref_id="h",
                idempotency_key="params-x", counter_account="POT",
            )
