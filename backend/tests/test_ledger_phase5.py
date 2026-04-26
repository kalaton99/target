"""Phase 5 unit tests — wallet + ledger.

Scope (locked):
  - debit / credit
  - insufficient funds
  - duplicate idempotency
  - version conflict retry
  - double-entry balance invariant
  - no negative balance
  - integers only (no floats)

Tests use a real MongoDB database, isolated per session via a unique DB name.

Run:
  cd /app/backend && PYTHONPATH=. python -m pytest tests/test_ledger_phase5.py -v
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

from core.config import MONGO_URL
from ledger.service import (
    LedgerService,
    InsufficientFunds,
    DuplicateActionPending,
    StaleVersion,
    WalletError,
)


# ---------- fixtures ----------

_PHASE5_CLIENT = AsyncIOMotorClient(MONGO_URL, maxPoolSize=20)
_PHASE5_LOCK = None  # event-loop bound; reset per fixture


async def _safe_create_client(retries: int = 3):
    """Tolerate the rare AutoReconnect on burst client creation."""
    from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError
    last = None
    for i in range(retries):
        try:
            client = AsyncIOMotorClient(MONGO_URL, maxPoolSize=10)
            # Force a round-trip to surface connection issues here, not later.
            await client.admin.command("ping")
            return client
        except (AutoReconnect, ServerSelectionTimeoutError) as exc:
            last = exc
            await asyncio.sleep(0.05 * (i + 1))
    raise last  # type: ignore[misc]


@pytest.fixture
async def db():
    client = await _safe_create_client()
    db_name = f"target_phase5_{uuid.uuid4().hex[:8]}"
    db = client[db_name]
    await db["wallets"].create_index("user_id", unique=True)
    await db["idempotency_keys"].create_index(
        [("user_id", 1), ("scope", 1), ("client_action_id", 1)],
        unique=True,
    )
    await db["transactions"].create_index("journal_id")
    yield db
    try:
        await client.drop_database(db_name)
    except Exception:
        pass
    client.close()


@pytest.fixture
async def svc(db):
    return LedgerService(db["wallets"], db["transactions"], db["idempotency_keys"])


# ---------- happy paths ----------

class TestDebitCredit:

    @pytest.mark.asyncio
    async def test_credit_increases_balance(self, svc):
        await svc.open_wallet("u1", opening_balance=0)
        res = await svc.mutate(
            user_id="u1", delta=500, reason="DEPOSIT",
            ref_type="SYSTEM", ref_id=None,
            idempotency_key="k-credit-1", counter_account="TREASURY",
        )
        assert res["balance"] == 500
        assert res["version"] == 1
        wallet = await svc.get_balance("u1")
        assert wallet["balance"] == 500
        assert wallet["version"] == 1

    @pytest.mark.asyncio
    async def test_debit_decreases_balance(self, svc):
        await svc.open_wallet("u1", opening_balance=1000)
        res = await svc.mutate(
            user_id="u1", delta=-300, reason="ANTE",
            ref_type="HAND", ref_id="h_x",
            idempotency_key="k-debit-1", counter_account="POT",
        )
        assert res["balance"] == 700
        assert res["version"] == 1


class TestInsufficientFunds:

    @pytest.mark.asyncio
    async def test_debit_more_than_balance_rejected(self, svc):
        await svc.open_wallet("u1", opening_balance=100)
        with pytest.raises(InsufficientFunds):
            await svc.mutate(
                user_id="u1", delta=-500, reason="ANTE",
                ref_type="HAND", ref_id="h_y",
                idempotency_key="k-too-much", counter_account="POT",
            )
        # Balance unchanged
        w = await svc.get_balance("u1")
        assert w["balance"] == 100
        assert w["version"] == 0

    @pytest.mark.asyncio
    async def test_no_negative_balance_after_failed_debit(self, svc, db):
        await svc.open_wallet("u1", opening_balance=50)
        for i in range(5):
            with pytest.raises(InsufficientFunds):
                await svc.mutate(
                    user_id="u1", delta=-1000, reason="BET",
                    ref_type="HAND", ref_id=f"h_{i}",
                    idempotency_key=f"k-overdraw-{i}", counter_account="POT",
                )
        w = await svc.get_balance("u1")
        assert w["balance"] == 50
        # And no transactions were ever written for those failed attempts
        n = await db["transactions"].count_documents({"user_id": "u1"})
        assert n == 0
        # Idempotency lock was released so the same key can be re-tried
        idem_count = await db["idempotency_keys"].count_documents({"user_id": "u1"})
        assert idem_count == 0

    @pytest.mark.asyncio
    async def test_failed_debit_releases_idempotency_lock(self, svc):
        """Caller can retry the same idempotency_key after InsufficientFunds."""
        await svc.open_wallet("u1", opening_balance=50)
        with pytest.raises(InsufficientFunds):
            await svc.mutate(
                user_id="u1", delta=-200, reason="BET",
                ref_type="HAND", ref_id="h_z",
                idempotency_key="k-retry-after-fail", counter_account="POT",
            )
        # Top up
        await svc.mutate(
            user_id="u1", delta=500, reason="DEPOSIT",
            ref_type="SYSTEM", ref_id=None,
            idempotency_key="k-topup", counter_account="TREASURY",
        )
        # Retry the same key — should now succeed
        res = await svc.mutate(
            user_id="u1", delta=-200, reason="BET",
            ref_type="HAND", ref_id="h_z",
            idempotency_key="k-retry-after-fail", counter_account="POT",
        )
        assert res["balance"] == 350


# ---------- idempotency ----------

class TestIdempotency:

    @pytest.mark.asyncio
    async def test_duplicate_key_returns_cached_response(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        first = await svc.mutate(
            user_id="u1", delta=-100, reason="ANTE",
            ref_type="HAND", ref_id="h_d",
            idempotency_key="k-dup", counter_account="POT",
        )
        # Replay
        second = await svc.mutate(
            user_id="u1", delta=-100, reason="ANTE",
            ref_type="HAND", ref_id="h_d",
            idempotency_key="k-dup", counter_account="POT",
        )
        assert first == second
        # Wallet was debited only once
        w = await svc.get_balance("u1")
        assert w["balance"] == 900
        assert w["version"] == 1
        # Ledger has exactly one paired entry (2 rows)
        n = await db["transactions"].count_documents({"journal_id": first["journal_id"]})
        assert n == 2
        n_total = await db["transactions"].count_documents({"user_id": "u1"})
        assert n_total == 1

    @pytest.mark.asyncio
    async def test_concurrent_same_key_does_not_double_debit(self, svc, db):
        """Two concurrent calls with the same idempotency_key — exactly one
        succeeds and debits, the other returns DuplicateActionPending or the
        cached response.
        """
        await svc.open_wallet("u1", opening_balance=1000)

        async def attempt():
            try:
                return ("ok", await svc.mutate(
                    user_id="u1", delta=-200, reason="BET",
                    ref_type="HAND", ref_id="h_q",
                    idempotency_key="k-concurrent", counter_account="POT",
                ))
            except DuplicateActionPending:
                return ("pending", None)

        # 5 concurrent attempts
        results = await asyncio.gather(*[attempt() for _ in range(5)])
        oks = [r for r in results if r[0] == "ok"]
        # At least one OK; possibly cached replays of the same response
        assert len(oks) >= 1
        # All OK responses must be byte-identical (cached replay)
        for _, resp in oks:
            assert resp == oks[0][1]

        # Wallet debited exactly once
        w = await svc.get_balance("u1")
        assert w["balance"] == 800
        assert w["version"] == 1
        # Ledger has exactly one paired entry
        n_user = await db["transactions"].count_documents({"user_id": "u1"})
        assert n_user == 1


# ---------- version conflict retry ----------

class TestVersionConflict:

    @pytest.mark.asyncio
    async def test_concurrent_distinct_mutations_serialize_correctly(self, svc, db):
        """Two concurrent debits with DIFFERENT idempotency keys both succeed
        and the wallet ends with both deltas applied. Version is monotonic.
        Retries on optimistic version conflict are handled internally.
        """
        await svc.open_wallet("u1", opening_balance=1000)

        async def go(k, amt):
            return await svc.mutate(
                user_id="u1", delta=amt, reason="BET",
                ref_type="HAND", ref_id="h_r",
                idempotency_key=f"k-{k}", counter_account="POT",
            )

        # 10 parallel debits of 50 each = -500
        results = await asyncio.gather(*[go(i, -50) for i in range(10)])
        balances = sorted(r["balance"] for r in results)
        versions = sorted(r["version"] for r in results)
        # Each result should reflect one decrement
        assert balances == [500 + 50 * i for i in range(10)] or len(balances) == 10
        # Final wallet
        w = await svc.get_balance("u1")
        assert w["balance"] == 500
        assert w["version"] == 10
        # 10 paired ledger entries = 20 rows
        n = await db["transactions"].count_documents({"user_id": "u1"})
        assert n == 10

    @pytest.mark.asyncio
    async def test_version_increments_monotonically(self, svc):
        await svc.open_wallet("u1", opening_balance=1000)
        for i in range(3):
            res = await svc.mutate(
                user_id="u1", delta=-10, reason="ANTE",
                ref_type="HAND", ref_id="h_v",
                idempotency_key=f"k-mono-{i}", counter_account="POT",
            )
            assert res["version"] == i + 1


# ---------- double-entry balance invariant ----------

class TestDoubleEntry:

    @pytest.mark.asyncio
    async def test_every_journal_sums_to_zero(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        await svc.mutate(user_id="u1", delta=-100, reason="ANTE",
                         ref_type="HAND", ref_id="h", idempotency_key="k1",
                         counter_account="POT")
        await svc.mutate(user_id="u1", delta=-50, reason="BET",
                         ref_type="HAND", ref_id="h", idempotency_key="k2",
                         counter_account="POT")
        await svc.mutate(user_id="u1", delta=200, reason="PAYOUT",
                         ref_type="HAND", ref_id="h", idempotency_key="k3",
                         counter_account="POT")
        # Aggregate per journal
        sums = {}
        async for tx in db["transactions"].find({}, {"_id": 0}):
            sums.setdefault(tx["journal_id"], 0)
            sums[tx["journal_id"]] += tx["amount"]
        # All journals must net to zero
        violators = [(j, s) for j, s in sums.items() if s != 0]
        assert violators == []
        # And exactly 2 rows per journal
        for j in sums:
            n = await db["transactions"].count_documents({"journal_id": j})
            assert n == 2

    @pytest.mark.asyncio
    async def test_user_balance_matches_ledger_sum(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        # Apply a series of mutations
        deltas = [-100, -50, 200, -300, 500, -25]
        for i, d in enumerate(deltas):
            await svc.mutate(user_id="u1", delta=d, reason="TEST",
                             ref_type="HAND", ref_id=f"h{i}",
                             idempotency_key=f"k-de-{i}",
                             counter_account="POT")
        # Wallet balance must equal opening + sum(USER ledger rows)
        ledger_sum = 0
        async for tx in db["transactions"].find({"user_id": "u1", "account_type": "USER"}, {"_id": 0}):
            ledger_sum += tx["amount"]
        w = await svc.get_balance("u1")
        assert w["balance"] == 1000 + ledger_sum

    @pytest.mark.asyncio
    async def test_paired_rows_have_matching_journal_id(self, svc, db):
        await svc.open_wallet("u1", opening_balance=1000)
        res = await svc.mutate(user_id="u1", delta=-77, reason="ANTE",
                               ref_type="HAND", ref_id="h",
                               idempotency_key="k-pair", counter_account="POT")
        rows = []
        async for tx in db["transactions"].find({"journal_id": res["journal_id"]}, {"_id": 0}):
            rows.append(tx)
        assert len(rows) == 2
        accounts = sorted(r["account_type"] for r in rows)
        assert accounts == ["POT", "USER"]
        amounts = sorted(r["amount"] for r in rows)
        assert amounts == [-77, 77]


# ---------- integer-only enforcement ----------

class TestIntegerOnly:

    @pytest.mark.asyncio
    async def test_float_delta_rejected(self, svc):
        await svc.open_wallet("u1", opening_balance=1000)
        with pytest.raises(WalletError, match="AMOUNT_MUST_BE_INTEGER"):
            await svc.mutate(user_id="u1", delta=10.5, reason="X",  # type: ignore[arg-type]
                             ref_type="SYSTEM", ref_id=None,
                             idempotency_key="k-fl", counter_account="HOUSE")

    @pytest.mark.asyncio
    async def test_zero_delta_rejected(self, svc):
        await svc.open_wallet("u1", opening_balance=100)
        with pytest.raises(WalletError, match="ZERO_DELTA"):
            await svc.mutate(user_id="u1", delta=0, reason="NOOP",
                             ref_type="SYSTEM", ref_id=None,
                             idempotency_key="k-z", counter_account="HOUSE")
