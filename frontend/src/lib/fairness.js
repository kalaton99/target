// Provably-fair RNG verifier — port of backend/game_engine/{rng,deck}.py.
// Pure browser code: uses Web Crypto SubtleCrypto for SHA-256.
//
// Contract (must match backend bit-for-bit):
//   1. combineClientSeedsBySeat({seat: seed}, [seats]) → sha256_hex
//      Each seat encoded as `seat:seed`, joined by `|`, then sha256.
//   2. computeShuffleSeed(serverSeedHex, combinedHex, nonce) → sha256_hex
//      Pre-image: `${serverSeedHex}:${combinedHex}:${nonce}`.
//   3. shuffleDeck(deck, shuffleSeedHex) → array
//      Fisher–Yates with reject-sampled SHA-256 stream
//      keyed `${shuffleSeedHex}:${counter}`.
//   4. buildFreshDeck({includeJokers}) → array of {rank, suit}.

// Deck construction order MUST match backend exactly (game_engine/cards.py).
// Backend: SUITS = ["S","H","D","C"]; RANKS = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"].
// Then `for s in SUITS: for r in RANKS: deck.append(Card(r, s))`. We mirror that.
const SUITS = ["S", "H", "D", "C"];
const RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"];

export function buildFreshDeck({ includeJokers = true } = {}) {
  const deck = [];
  for (const s of SUITS) {
    for (const r of RANKS) deck.push({ rank: r, suit: s });
  }
  if (includeJokers) {
    deck.push({ rank: "JOKER", suit: "*" });
    deck.push({ rank: "JOKER", suit: "*" });
  }
  return deck;
}

function bytesToHex(bytes) {
  let hex = "";
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, "0");
  }
  return hex;
}

async function sha256Hex(text) {
  const enc = new TextEncoder();
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return bytesToHex(new Uint8Array(buf));
}

async function sha256Bytes(text) {
  const enc = new TextEncoder();
  const buf = await crypto.subtle.digest("SHA-256", enc.encode(text));
  return new Uint8Array(buf);
}

// Identical canonical form to backend `combine_client_seeds_by_seat`:
// strip the `:` and `|` separators from each seed, then join.
export async function combineClientSeedsBySeat(seedsBySeat, seatOrder) {
  const parts = [];
  for (const seat of seatOrder) {
    const raw = seedsBySeat?.[seat] ?? "";
    const clean = String(raw).replace(/\|/g, "").replace(/:/g, "");
    parts.push(`${seat}:${clean}`);
  }
  return await sha256Hex(parts.join("|"));
}

export async function computeShuffleSeed(serverSeedHex, combinedHex, nonce) {
  return await sha256Hex(`${serverSeedHex}:${combinedHex}:${nonce}`);
}

// Read the first 8 bytes of a Uint8Array as a big-endian unsigned 64-bit
// BigInt (matches Python's `int.from_bytes(h[:8], "big")`).
function firstU64BE(bytes) {
  let v = 0n;
  for (let i = 0; i < 8; i++) v = (v << 8n) | BigInt(bytes[i]);
  return v;
}

const TWO_64 = 1n << 64n;

export async function shuffleDeck(deck, shuffleSeedHex) {
  const arr = deck.slice();
  let counter = 0;
  for (let i = arr.length - 1; i > 0; i--) {
    let j;
    // Reject-sample to avoid modulo bias — same algorithm as backend.
    while (true) {
      const bytes = await sha256Bytes(`${shuffleSeedHex}:${counter}`);
      counter += 1;
      const num = firstU64BE(bytes);
      const slot = BigInt(i + 1);
      const limit = TWO_64 - (TWO_64 % slot);
      if (num < limit) {
        j = Number(num % slot);
        break;
      }
    }
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// Convenience: full pipeline, returns shuffled deck.
export async function deriveInitialDeck({
  serverSeedHex, clientSeedsBySeat, seatOrder, nonce, includeJokers = true,
}) {
  const combined = await combineClientSeedsBySeat(clientSeedsBySeat || {}, seatOrder);
  const shuffleSeed = await computeShuffleSeed(serverSeedHex, combined, nonce);
  const deck = buildFreshDeck({ includeJokers });
  const shuffled = await shuffleDeck(deck, shuffleSeed);
  return { deck: shuffled, combined, shuffleSeed };
}

// Fairness disclosure helper: confirm sha256(plain) == commit.
export async function verifyCommit(commitHash, plainSeed) {
  if (!commitHash || !plainSeed) return false;
  const h = await sha256Hex(plainSeed);
  return h === commitHash;
}

// Generate a fresh 32-byte hex seed from window.crypto.
export function randomClientSeed(bytes = 16) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return bytesToHex(buf);
}
