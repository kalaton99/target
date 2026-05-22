# Jackget Game Rules Draft

Jackget is a separate Axwins local demo game. It is not Target, Diceget, Flipget, or Tmarget.

Current phase: internal demo credits only. No payment, crypto, deposit, withdrawal, cash-out, KYC/AML, oracle, production settlement, SQL/Postgres activation, or durable production storage is implemented by this rules draft.

## Table Shape

- Minimum participants: 2
- Maximum participants: 4
- Local demo users can auto-fill empty seats with demo opponents.
- Status flow: `waiting`, `ready`, `in_progress`, `settled`, `cancelled`.

## Turn Loop

- Each participant has one 3-reel display.
- Each participant spins exactly 3 times.
- A spin produces exactly 3 reel values.
- A participant can spin only on their own turn.
- After each single spin, turn moves to the next participant who still has spins left.
- Demo opponents spin automatically when their turn arrives, then turn returns to the human participant when applicable.
- When every participant has completed 3 spins, the table settles.

## Reels

Reels can show numbers `1` through `7`, or symbols:

- Cherry
- Bell
- Star
- Crown
- Diamond
- Seven

## Scoring

- Three Seven symbols: 100 points
- Three Diamonds: 90 points
- Three Crowns: 80 points
- Three Stars: 70 points
- Three Bells: 60 points
- Three Cherries: 50 points
- Any three identical numbers: number x 10 points
- Any three identical non-special symbols not listed above: 40 points
- Any two matching reels: 15 points
- Mixed result: sum numeric values, symbols count as 5 points each

Highest total score wins. If multiple participants share the top score, Jackget reports a tie with multiple winners. No real-money settlement or tie payout behavior is implemented.

## Product Boundary

Jackget uses `/api/jackget` and `/jackget`. It must not use Target lobby, Target play routes, Target WebSocket paths, Diceget endpoints, Flipget endpoints, or Tmarget market endpoints.
