# Target Wallet Model

Target currently locks the table stake when a player creates or joins a table.
Pre-game leave unlocks that same stake. Once a table is RUNNING, PAYOUT, ENDED,
or otherwise final, the bridge treats the stake as non-refundable.

At PAYOUT, the wallet bridge mirrors the existing engine payout plan into the
durable ledger. It does not calculate winners, change payout math, or alter the
Target reducer. Settlement uses deterministic idempotency keys per table, user,
and hand so repeated PAYOUT publication does not duplicate credits or debits.

In-hand betting beyond the locked table stake remains engine-local for now. The
recommended MVP platform model is to lock a full buy-in up front, sized to cover
the maximum expected in-hand exposure. Per-bet ledger locking should be a later,
higher-risk phase because it would touch reducer timing, betting actions, and
more gameplay state transitions.

Live deposits, withdrawals, card payments, crypto transfers, and Telegram/Web3
bridges remain out of scope for this phase.
