# Flipget Wallet Model

Flipget locks the table stake when a player creates or joins a table. Pre-flip
leave unlocks that stake. Once a table is flipping or settled, the stake is
non-refundable.

The coin result is backend-authoritative. The frontend never decides heads or
tails. Final settlement mirrors the stored result into the durable ledger and
uses deterministic idempotency keys so repeated settlement cannot double-pay.

There is no solo mode, no house/bot mode, no live payment flow, no crypto, no
withdrawal path, and no per-action money movement in this phase.
