# Diceget Wallet Model

Diceget locks a table stake when a player creates or joins a table. Pre-game
leave unlocks that stake. Active, showdown, and settled tables are
non-refundable.

Dice scoring is engine-local. Rolls, holds, busts, and forfeits do not move
money and do not perform per-action ledger locking.

Final settlement mirrors the Diceget showdown result into the durable ledger.
Settlement is idempotent through deterministic per-user payout keys:
`diceget:{table_id}:payout:{user_id}:{round_id}`.

Per-roll or per-action ledger locking is intentionally deferred. The MVP model
is table-stake or full-buy-in locking at join/create, followed by final ledger
settlement after showdown.
