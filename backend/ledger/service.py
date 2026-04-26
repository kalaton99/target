"""Phase 5 — Wallet + ledger.

Isolated module. No WS, no game engine, no rewards.

Collections owned:
  wallets            — { user_id, balance, version, gems, locked, updated_at }
  transactions       — append-only double-entry ledger
  idempotency_keys   — { (user_id, scope, key) UNIQUE; status; response }

Invariants enforced:
  - balance is BIGINT; never negative (CHECK semantics + atomic find_one_and_update)
  - every mutation has paired ledger rows (USER + counter); SUM(journal_id) == 0
  - hybrid versioning: optimistic `version` + atomic single-doc update + retry
  - idempotency: re-run with same (user_id, scope, client_action_id) returns cached

Concurrency model (single-instance MVP, mongod is standalone — no multi-doc TXNs):
  Step 1: INSERT idempotency_keys (status='PLANNED'). UNIQUE index makes this
          the linearization point. DUP_KEY → cached response or in-flight reject.
  Step 2: Atomic wallet `findOneAndUpdate` with version + balance precondition.
          Retry up to 3 times on version conflict. Insufficient funds → release
          the idempotency lock so the caller may try again.
  Step 3: insert_many of paired double-entry ledger rows.
  Step 4: UPDATE idempotency_keys → status='COMPLETE' with cached response.

Replica-set transactions would let us collapse steps 2-4 into one TX; we accept
that limitation here. The architecture's reconciliation job (out of Phase 5
scope) covers torn-write recovery should a process die between steps.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError


# ---------- error taxonomy ----------

class WalletError(Exception):
    pass


class InsufficientFunds(WalletError):
    pass


class StaleVersion(WalletError):
    pass


class DuplicateActionPending(WalletError):
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


# ---------- service ----------

class LedgerService:
    """Wallet + ledger operations.

    Required Mongo collections (caller wires them in):
        wallets, transactions, idempotency_keys

    Indexes (caller ensures):
        wallets.user_id UNIQUE
        idempotency_keys (user_id, scope, client_action_id) UNIQUE
        transactions (journal_id, account_type) UNIQUE  -- prevents duplicate ledger rows
    """

    def __init__(self, wallets_col, transactions_col, idem_col, *,
                 max_retries: int = 32, retry_base_ms: int = 4):
        self._wallets = wallets_col
        self._transactions = transactions_col
        self._idem = idem_col
        self._max_retries = max_retries
        self._retry_base_ms = retry_base_ms

    # ---- bootstrap ----

    async def open_wallet(self, user_id: str, *, opening_balance: int = 0) -> Dict[str, Any]:
        if opening_balance < 0:
            raise WalletError("OPENING_BALANCE_NEGATIVE")
        if not isinstance(opening_balance, int):
            raise WalletError("AMOUNT_MUST_BE_INTEGER")
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
            "updated_at": _now_iso(),
        }
        await self._wallets.insert_one(doc)
        return doc

    async def get_balance(self, user_id: str) -> Dict[str, Any]:
        w = await self._wallets.find_one({"user_id": user_id}, {"_id": 0})
        if not w:
            raise WalletNotFound("WALLET_NOT_FOUND")
        return w

    # ---- mutation ----

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
        """Atomic, idempotent, double-entry wallet mutation.

        delta:   signed integer credits (negative = debit, positive = credit)
        reason:  e.g. 'ANTE', 'BET', 'PAYOUT', 'COMMISSION', 'DEPOSIT'
        ref_type: 'HAND' | 'TABLE' | 'SYSTEM'
        ref_id:  hand_id / table_id / None
        idempotency_key: client-supplied UUID; required
        counter_account: 'POT' | 'HOUSE' | 'LOTTERY' | 'TREASURY'

        Returns: {"balance", "version", "transaction_id", "journal_id"}
        """
        if not isinstance(delta, int):
            raise WalletError("AMOUNT_MUST_BE_INTEGER")
        if delta == 0:
            raise WalletError("ZERO_DELTA")
        if not idempotency_key:
            raise WalletError("MISSING_IDEMPOTENCY_KEY")
        if counter_account not in {"POT", "HOUSE", "LOTTERY", "TREASURY"}:
            raise WalletError(f"INVALID_COUNTER_ACCOUNT: {counter_account}")

        # ---- Step 1: claim the operation via idempotency record ----
        idem_id = f"ik_{uuid.uuid4().hex[:20]}"
        try:
            await self._idem.insert_one({
                "id": idem_id,
                "client_action_id": idempotency_key,
                "user_id": user_id,
                "scope": "WALLET",
                "delta": int(delta),
                "reason": reason,
                "ref_type": ref_type,
                "ref_id": ref_id,
                "status": "PLANNED",
                "response": None,
                "created_at": _now_iso(),
                "expires_at": _expires_iso(24),
            })
        except DuplicateKeyError:
            existing = await self._idem.find_one(
                {"user_id": user_id, "scope": "WALLET", "client_action_id": idempotency_key},
                {"_id": 0},
            )
            if existing and existing.get("status") == "COMPLETE":
                return existing["response"]
            # Either still PLANNED (in-flight from another attempt) or unknown.
            raise DuplicateActionPending("DUPLICATE_ACTION_PENDING")

        # ---- Step 2: atomic wallet update with version + balance check ----
        try:
            updated = await self._mutate_wallet_with_retry(user_id, delta)
        except WalletError:
            # Release the idempotency lock so the caller may retry safely.
            await self._idem.delete_one({"id": idem_id})
            raise

        # ---- Step 3: paired double-entry ledger inserts ----
        journal_id = f"j_{uuid.uuid4().hex[:20]}"
        tx_user_id = f"tx_{uuid.uuid4().hex[:20]}"
        tx_counter_id = f"tx_{uuid.uuid4().hex[:20]}"
        now = _now_iso()
        try:
            await self._transactions.insert_many([
                {
                    "id": tx_user_id,
                    "journal_id": journal_id,
                    "user_id": user_id,
                    "account_type": "USER",
                    "amount": int(delta),
                    "balance_after": int(updated["balance"]),
                    "reason": reason,
                    "ref_type": ref_type,
                    "ref_id": ref_id,
                    "idempotency_key_id": idem_id,
                    "created_at": now,
                },
                {
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
                    "created_at": now,
                },
            ])
        except Exception:
            # Ledger insert failed AFTER wallet was already mutated.
            # We do NOT release the idempotency lock — that would let the same
            # action re-debit. The reconciliation job (out-of-scope) will
            # detect and repair the missing ledger entry.
            await self._idem.update_one(
                {"id": idem_id},
                {"$set": {"status": "WALLET_OK_LEDGER_PENDING"}},
            )
            raise

        # ---- Step 4: cache the response ----
        response = {
            "balance": int(updated["balance"]),
            "version": int(updated["version"]),
            "transaction_id": tx_user_id,
            "journal_id": journal_id,
        }
        await self._idem.update_one(
            {"id": idem_id},
            {"$set": {"status": "COMPLETE", "response": response}},
        )
        return response

    # ---- internals ----

    async def _mutate_wallet_with_retry(self, user_id: str, delta: int) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for attempt in range(self._max_retries):
            wallet = await self._wallets.find_one({"user_id": user_id}, {"_id": 0})
            if not wallet:
                raise WalletNotFound("WALLET_NOT_FOUND")
            current_balance = int(wallet["balance"])
            current_version = int(wallet["version"])

            if delta < 0 and current_balance + delta < 0:
                raise InsufficientFunds("INSUFFICIENT_FUNDS")

            updated = await self._wallets.find_one_and_update(
                {
                    "user_id": user_id,
                    "version": current_version,
                    # Defense in depth: server-side balance precondition
                    "balance": {"$gte": -delta if delta < 0 else 0},
                },
                {
                    "$inc": {"balance": int(delta), "version": 1},
                    "$set": {"updated_at": _now_iso()},
                },
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
            if updated is not None:
                return updated

            last_err = StaleVersion("WALLET_VERSION_CONFLICT")
            # Linear backoff with mild randomization to avoid thundering herd.
            import random
            jitter = random.uniform(0.5, 1.5)
            await asyncio.sleep((self._retry_base_ms * jitter) / 1000.0)

        # Exhausted retries
        if last_err:
            raise last_err
        raise WalletError("UNKNOWN_MUTATION_FAILURE")
