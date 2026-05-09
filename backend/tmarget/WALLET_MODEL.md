# Tmarget Wallet Model

Tmarget uses the shared internal wallet with `source_module="tmarget"`.
Buying YES/NO debits internal demo credits. Selling shares credits internal demo
credits. Resolved winning positions receive demo settlement credits. Cancelled
or invalid markets refund remaining cost basis.

There are no deposit, withdrawal, card, crypto, Telegram, or real-money payment
flows. All credits are internal demo credits. Settlement/refund operations are
idempotent through deterministic keys.
