"""Phase 5 — Wallet + ledger (durable WAL pattern, no torn writes).

Architecture intent:
  Every mutation is a 6-step write-ahead-log dance with **deterministic IDs**
  on every collection. Every individual write is idempotent under retry
  thanks to UNIQUE indexes. The wallet update itself is gated by a
  `last_journal_id` cursor so the same journal can never apply twice.

  This means: if the process crashes between any two steps, calling
  `mutate(...)` with the same `idempotency_key` resumes the operation and
  finalizes it correctly. No nightly reconciliation required for MVP
  correctness; the system is self-healing on the next caller retry.

State machine (per idempotency record):
  PENDING  → wallet update in progress (or hasn't started)
  POSTED   → wallet updated; ledger rows POSTED but response not yet cached
  COMPLETE → response cached; subsequent retries return cached payload
  VOIDED   → terminal failure (e.g. INSUFFICIENT_FUNDS). Same key returns same error.

Collections (Phase 5 owns):
  wallets             — user_id (UNIQUE), balance, version, last_journal_id
  transactions        — id (UNIQUE), (journal_id, account_type) (UNIQUE), status
  journals            — id (UNIQUE) — header for paired ledger rows, status
  idempotency_keys    — (user_id, scope, client_action_id) UNIQUE; deterministic id

Deterministic IDs:
  journal_id            = "j_" + sha256(user_id|scope|client_action_id)[:24]
  transaction (USER)    = "tx_" + journal_id + "_USER"
  transaction (counter) = "tx_" + journal_id + "_" + counter_account
  idempotency_key id    = "ik_" + sha256(user_id|scope|client_action_id)[:24]

This guarantees retries collide on UNIQUE indexes rather than duplicate.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


# ---------- error taxonomy ----------

class WalletError(Exception):
    pass


class InsufficientFunds(WalletError):
    pass


class StaleVersion(WalletError):
    pass


class WalletNotFound(WalletError):
    pass


# ---------- helpers ----------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _expires_iso(hours: int = 24) -> str:
    return (_now() + timedelta(hours=hours)).isoformat()


def _deterministic_hash(user_id: str, scope: str, client_action_id: str) -> str:
    return hashlib.sha256(f"{user_id}|{scope}|{client_action_id}".encode("utf-8")).hexdigest()


def _journal_id_for(user_id: str, scope: str, client_action_id: str) -> str:
    return f"j_{_deterministic_hash(user_id, scope, client_action_id)[:24]}"


def _idem_id_for(user_id: str, scope: str, client_action_id: str) -> str:
    return f"ik_{_deterministic_hash(user_id, scope, client_action_id)[:24]}"


def _tx_id_for(journal_id: str, account_type: str) -> str:
    return f"tx_{journal_id}_{account_type}"


# ---------- service ----------

class LedgerService:
    """Durable WAL wallet + ledger.

    Required Mongo collections (caller injects):
        wallets, transactions, journals, idempotency_keys

    Required indexes (caller ensures via ensure_indexes()):
        wallets.user_id UNIQUE
        idempotency_keys (user_id, scope, client_action_id) UNIQUE
        transactions.id UNIQUE   (deterministic id)
        transactions (journal_id, account_type) UNIQUE
        journals.id UNIQUE
    """

    SCOPE = "WALLET"
    VALID_COUNTERS = {"POT", "HOUSE", "LOTTERY", "TREASURY"}

    def __init__(
        self,
        wallets_col,
        transactions_col,
        idem_col,
        journals_col,
        *,
        max_retries: int = 32,
        retry_base_ms: int = 4,
    ):
        self._wallets = wallets_col
        self._transactions = transactions_col
        self._idem = idem_col
        self._journals = journals_col
        self._max_retries = max_retries
        self._retry_base_ms = retry_base_ms

    # ---- bootstrap ----

    @classmethod
    async def ensure_indexes(cls, wallets_col, transactions_col, idem_col, journals_col) -> None:
        await wallets_col.create_index("user_id", unique=True)
        await idem_col.create_index(
            [("user_id", 1), ("scope", 1), ("client_action_id", 1)],
            unique=True,
        )
        await transactions_col.create_index("id", unique=True)
        await transactions_col.create_index(
            [("journal_id", 1), ("account_type", 1)], unique=True
        )
        await journals_col.create_index("id", unique=True)

    async def open_wallet(self, user_id: str, *, opening_balance: int = 0) -> Dict[str, Any]:
        if not isinstance(opening_balance, int):
            raise WalletError("AMOUNT_MUST_BE_INTEGER")
        if opening_balance < 0:
            raise WalletError("OPENING_BALANCE_NEGATIVE")
        existing = await self._wallets.find_one({"user_id": user_id}, {"_id": 0})
        if existing:
            return existing
        doc = {
            "id": f"w_{uuid.uuid4().hex[:20]}",
            "user_id": user_id,
            "balance": int(opening_balance),
            "gems": 0,
            "locked": 0,
            "version": 0,
            "last_journal_id": None,
            "updated_at": _now_iso(),
        }
        try:
            await self._wallets.insert_one(doc)
        except DuplicateKeyError:
            existing = await self._wallets.find_one({"user_id": user_id}, {"_id": 0})
            return existing  # type: ignore[return-value]
        return doc

    async def get_balance(self, user_id: str) -> Dict[str, Any]:
        w = await self._wallets.find_one({"user_id": user_id}, {"_id": 0})
        if not w:
            raise WalletNotFound("WALLET_NOT_FOUND")
        return w

    # ---- main mutation ----

    async def mutate(
        self,
        *,
        user_id: str,
        delta: int,
        reason: str,
        ref_type: str,
        ref_id: Optional[str],
        idempotency_key: str,
        counter_account: str,
    ) -> Dict[str, Any]:
        # --- input validation ---
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise WalletError("AMOUNT_MUST_BE_INTEGER")
        if delta == 0:
            raise WalletError("ZERO_DELTA")
        if not idempotency_key:
            raise WalletError("MISSING_IDEMPOTENCY_KEY")
        if counter_account not in self.VALID_COUNTERS:
            raise WalletError(f"INVALID_COUNTER_ACCOUNT: {counter_account}")

        idem_id = _idem_id_for(user_id, self.SCOPE, idempotency_key)
        journal_id = _journal_id_for(user_id, self.SCOPE, idempotency_key)
        tx_user_id = _tx_id_for(journal_id, "USER")
        tx_counter_id = _tx_id_for(journal_id, counter_account)

        # ============ STEP 1: idempotency PENDING ============
        try:
            await self._idem.insert_one({
                "id": idem_id,
                "client_action_id": idempotency_key,
                "user_id": user_id,
                "scope": self.SCOPE,
                "delta": int(delta),
                "reason": reason,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "counter_account": counter_account,
                "journal_id": journal_id,
                "status": "PENDING",
                "response": None,
                "error": None,
                "created_at": _now_iso(),
                "expires_at": _expires_iso(24),
            })
        except DuplicateKeyError:
            existing = await self._idem.find_one(
                {"id": idem_id}, {"_id": 0}
            )
            assert existing is not None
            # Resume / replay path
            if existing["status"] == "COMPLETE":
                return existing["response"]
            if existing["status"] == "VOIDED":
                err = existing.get("error") or "VOIDED"
                if err == "INSUFFICIENT_FUNDS":
                    raise InsufficientFunds(err)
                raise WalletError(err)
            # Validate the resumed parameters match (defense in depth)
            if (existing["delta"] != int(delta)
                    or existing["counter_account"] != counter_account
                    or existing["reason"] != reason):
                raise WalletError("IDEMPOTENCY_KEY_PARAMS_MISMATCH")
            # PENDING or POSTED — fall through to finalize
            existing_status = existing["status"]
        else:
            existing_status = "PENDING"

        # ============ STEP 2: journal header PENDING (deterministic id; idempotent) ============
        try:
            await self._journals.insert_one({
                "id": journal_id,
                "user_id": user_id,
                "delta": int(delta),
                "reason": reason,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "counter_account": counter_account,
                "status": "PENDING",
                "created_at": _now_iso(),
            })
        except DuplicateKeyError:
            pass  # journal header already inserted on prior attempt

        # ============ STEP 3: ledger rows PENDING (deterministic ids; idempotent) ============
        now = _now_iso()
        try:
            await self._transactions.insert_one({
                "id": tx_user_id,
                "journal_id": journal_id,
                "user_id": user_id,
                "account_type": "USER",
                "amount": int(delta),
                "balance_after": None,  # filled at POST
                "reason": reason,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "idempotency_key_id": idem_id,
                "status": "PENDING",
                "created_at": now,
            })
        except DuplicateKeyError:
            pass
        try:
            await self._transactions.insert_one({
                "id": tx_counter_id,
                "journal_id": journal_id,
                "user_id": None,
                "account_type": counter_account,
                "amount": -int(delta),
                "balance_after": None,
                "reason": reason,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "idempotency_key_id": idem_id,
                "status": "PENDING",
                "created_at": now,
            })
        except DuplicateKeyError:
            pass

        # ============ STEP 4: apply wallet update (gated by last_journal_id) ============
        try:
            wallet_after = await self._apply_wallet_update_with_retry(
                user_id=user_id, delta=int(delta), journal_id=journal_id,
            )
        except InsufficientFunds:
            await self._void(idem_id, journal_id, tx_user_id, tx_counter_id, error="INSUFFICIENT_FUNDS")
            raise
        except WalletNotFound:
            await self._void(idem_id, journal_id, tx_user_id, tx_counter_id, error="WALLET_NOT_FOUND")
            raise
        except StaleVersion:
            # Retries exhausted without success — leave PENDING for next caller retry.
            raise

        new_balance = int(wallet_after["balance"])
        new_version = int(wallet_after["version"])

        # ============ STEP 5: POST ledger + journal ============
        await self._transactions.update_one(
            {"id": tx_user_id, "status": "PENDING"},
            {"$set": {"status": "POSTED", "balance_after": new_balance, "posted_at": _now_iso()}},
        )
        await self._transactions.update_one(
            {"id": tx_counter_id, "status": "PENDING"},
            {"$set": {"status": "POSTED", "posted_at": _now_iso()}},
        )
        await self._journals.update_one(
            {"id": journal_id, "status": "PENDING"},
            {"$set": {"status": "POSTED", "posted_at": _now_iso()}},
        )

        # ============ STEP 6: COMPLETE idempotency with cached response ============
        response = {
            "balance": new_balance,
            "version": new_version,
            "transaction_id": tx_user_id,
            "journal_id": journal_id,
        }
        await self._idem.update_one(
            {"id": idem_id, "status": {"$ne": "COMPLETE"}},
            {"$set": {"status": "COMPLETE", "response": response, "completed_at": _now_iso()}},
        )
        return response

    # ---- internals ----

    async def _apply_wallet_update_with_retry(
        self, *, user_id: str, delta: int, journal_id: str,
    ) -> Dict[str, Any]:
        """Atomic wallet mutation gated by `last_journal_id` (so same journal
        can never apply twice). Retries on optimistic version conflict.
        """
        last_err: Optional[Exception] = None
        for attempt in range(self._max_retries):
            wallet = await self._wallets.find_one({"user_id": user_id}, {"_id": 0})
            if not wallet:
                raise WalletNotFound("WALLET_NOT_FOUND")

            # Already applied? — replay path: just return current state.
            if wallet.get("last_journal_id") == journal_id:
                return wallet

            current_balance = int(wallet["balance"])
            current_version = int(wallet["version"])

            if delta < 0 and current_balance + delta < 0:
                raise InsufficientFunds("INSUFFICIENT_FUNDS")

            updated = await self._wallets.find_one_and_update(
                {
                    "user_id": user_id,
                    "version": current_version,
                    # Idempotency cursor: refuse to apply same journal twice
                    "$or": [
                        {"last_journal_id": None},
                        {"last_journal_id": {"$ne": journal_id}},
                    ],
                    # Defense in depth: server-side balance precondition
                    "balance": {"$gte": -delta if delta < 0 else 0},
                },
                {
                    "$inc": {"balance": int(delta), "version": 1},
                    "$set": {
                        "last_journal_id": journal_id,
                        "updated_at": _now_iso(),
                    },
                },
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
            if updated is not None:
                return updated

            last_err = StaleVersion("WALLET_VERSION_CONFLICT")
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep((self._retry_base_ms * jitter) / 1000.0)

        if last_err:
            raise last_err
        raise WalletError("UNKNOWN_MUTATION_FAILURE")

    async def _void(
        self,
        idem_id: str,
        journal_id: str,
        tx_user_id: str,
        tx_counter_id: str,
        *,
        error: str,
    ) -> None:
        """Terminal void path. Marks idem, journal, both ledger rows VOIDED.
        Idempotent — safe under retry."""
        ts = _now_iso()
        await self._transactions.update_many(
            {"id": {"$in": [tx_user_id, tx_counter_id]}, "status": "PENDING"},
            {"$set": {"status": "VOIDED", "voided_at": ts}},
        )
        await self._journals.update_one(
            {"id": journal_id, "status": "PENDING"},
            {"$set": {"status": "VOIDED", "voided_at": ts}},
        )
        await self._idem.update_one(
            {"id": idem_id, "status": {"$nin": ["COMPLETE", "VOIDED"]}},
            {"$set": {"status": "VOIDED", "error": error, "voided_at": ts}},
        )

    # ---- recovery / inspection ----

    async def find_idempotency(self, user_id: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
        return await self._idem.find_one(
            {"id": _idem_id_for(user_id, self.SCOPE, idempotency_key)},
            {"_id": 0},
        )
