/**
 * 2026-05 v3 — Slice 1: deterministic SVG avatar system.
 *
 * Pure inline SVG. Zero deps. No fetch, no images. Hash(user_id) →
 * one of 12 hand-drawn portrait variants. Yellow line-work on slate
 * matches the existing TARGET aesthetic (see LobbyPage / PlayPage
 * tone tokens). Sizes:
 *   - 24 px for opponent / row contexts
 *   - 64 px for the local player's seat header
 *
 * Bots (`u_bot_*`) get a small "BOT" ribbon corner. No engine /
 * reducer / RNG / protocol coupling — purely cosmetic.
 */
import React from "react";

// Stable, fast non-crypto hash (FNV-1a 32-bit).
function fnv1a(str) {
  let h = 0x811c9dc5 >>> 0;
  for (let i = 0; i < (str || "").length; i++) {
    h ^= str.charCodeAt(i);
    h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) >>> 0;
  }
  return h >>> 0;
}

// Twelve TARGET-style portraits. Each variant draws a unique silhouette
// from the same primitive set: head shape, hair/hat, glasses, beard,
// neck/collar. All use `currentColor` for line-work so the parent
// drives the accent (yellow). Background is a fixed slate fill.
const VARIANTS = [
  // 0 — short crop
  (h) => (
    <g key="v0">
      <circle cx="32" cy="26" r="11" />
      <path d="M21,22 q11,-12 22,0" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 1 — wavy hair
  (h) => (
    <g key="v1">
      <circle cx="32" cy="27" r="11" />
      <path d="M20,21 q3,-6 6,0 q3,-6 6,0 q3,-6 6,0 q3,-6 6,0" />
      <path d="M17,52 q15,-15 30,0" />
    </g>
  ),
  // 2 — beanie
  (h) => (
    <g key="v2">
      <circle cx="32" cy="28" r="11" />
      <path d="M21,22 q11,-10 22,0 l-1,4 l-20,0 z" />
      <line x1="21" y1="22" x2="43" y2="22" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 3 — top knot
  (h) => (
    <g key="v3">
      <circle cx="32" cy="28" r="11" />
      <circle cx="32" cy="14" r="3" />
      <line x1="32" y1="17" x2="32" y2="21" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 4 — round glasses
  (h) => (
    <g key="v4">
      <circle cx="32" cy="27" r="11" />
      <circle cx="28" cy="27" r="2.4" fill="none" />
      <circle cx="36" cy="27" r="2.4" fill="none" />
      <line x1="30.4" y1="27" x2="33.6" y2="27" />
      <path d="M21,22 q11,-12 22,0" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 5 — beard
  (h) => (
    <g key="v5">
      <circle cx="32" cy="26" r="11" />
      <path d="M22,30 q10,12 20,0" />
      <path d="M21,22 q11,-12 22,0" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 6 — long hair
  (h) => (
    <g key="v6">
      <circle cx="32" cy="27" r="11" />
      <path d="M20,22 q12,-12 24,0 l-2,18 l-20,0 z" fill="currentColor" fillOpacity="0.10" />
      <path d="M17,52 q15,-15 30,0" />
    </g>
  ),
  // 7 — cap with brim
  (h) => (
    <g key="v7">
      <circle cx="32" cy="29" r="10.5" />
      <path d="M22,22 q10,-9 20,0 l4,3 l-28,0 z" />
      <path d="M19,52 q13,-13 26,0" />
    </g>
  ),
  // 8 — square jaw
  (h) => (
    <g key="v8">
      <rect x="22" y="17" width="20" height="22" rx="4" ry="4" />
      <path d="M19,52 q13,-13 26,0" />
    </g>
  ),
  // 9 — pointy hair
  (h) => (
    <g key="v9">
      <circle cx="32" cy="27" r="11" />
      <path d="M22,21 l3,-6 l3,4 l3,-6 l3,4 l3,-6 l3,6" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 10 — earrings
  (h) => (
    <g key="v10">
      <circle cx="32" cy="27" r="11" />
      <circle cx="22" cy="30" r="1.5" />
      <circle cx="42" cy="30" r="1.5" />
      <path d="M21,22 q11,-12 22,0" />
      <path d="M18,52 q14,-14 28,0" />
    </g>
  ),
  // 11 — ponytail
  (h) => (
    <g key="v11">
      <circle cx="32" cy="27" r="11" />
      <path d="M44,28 q5,2 5,8 q-1,4 -4,5" />
      <path d="M21,22 q11,-12 22,0" />
      <path d="M17,52 q15,-15 30,0" />
    </g>
  ),
];

// Per-variant slate background tint so two adjacent identical variants
// still look distinct (modulo the FNV salt).
const BG_TINTS = [
  "#0f1216", "#10171b", "#11141a", "#0e151b",
  "#13141b", "#0e1218", "#121518", "#0c151b",
  "#10141a", "#0f1217", "#13161c", "#0e1416",
];

function isBotId(uid) {
  return typeof uid === "string" && uid.startsWith("u_bot_");
}

/**
 * Avatar — deterministic SVG portrait keyed off `userId`.
 *
 * Props:
 *   userId  : string         — required for stable selection
 *   size    : number         — pixel diameter (default 24)
 *   bot     : boolean        — explicit override; defaults to `isBotId(userId)`
 *   active  : boolean        — render a subtle outer ring (turn cue)
 *   className : string       — pass-through classes for the outer wrapper
 */
export function Avatar({
  userId,
  size = 24,
  bot,
  active = false,
  className = "",
  testid,
}) {
  const isBot = typeof bot === "boolean" ? bot : isBotId(userId);
  const h = fnv1a(userId || "anon");
  const idx = h % VARIANTS.length;
  const tint = BG_TINTS[idx];
  const stroke = isBot ? "#94a3b8" : "#facc15"; // bot=slate-400, human=yellow-400
  const ringStyle = active
    ? { boxShadow: "0 0 0 2px rgba(250,204,21,0.55)" }
    : undefined;
  const sw = Math.max(1.5, size / 24); // visual stroke scales with size
  // Note: <svg viewBox="0 0 64 64"> matches the path math in VARIANTS;
  // the wrapping <span> sets the rendered pixel size + clip-circle.
  return (
    <span
      data-testid={testid}
      className={`relative inline-flex items-center justify-center rounded-full overflow-hidden border border-zinc-700 ${className}`}
      style={{
        width: size,
        height: size,
        background: tint,
        ...ringStyle,
      }}
      aria-hidden
    >
      <svg
        viewBox="0 0 64 64"
        width={size}
        height={size}
        style={{ color: stroke }}
        xmlns="http://www.w3.org/2000/svg"
      >
        <g
          fill="none"
          stroke="currentColor"
          strokeWidth={sw}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {VARIANTS[idx](h)}
        </g>
      </svg>
      {isBot && size >= 36 && (
        // Larger sizes get a real ribbon; smaller ones get a dot to
        // avoid layout pressure.
        <span
          data-testid={testid ? `${testid}-bot-ribbon` : undefined}
          className="absolute bottom-0 inset-x-0 text-center text-[8px] tracking-[0.2em] uppercase bg-slate-700/80 text-slate-200 leading-tight py-[1px]"
        >
          BOT
        </span>
      )}
      {isBot && size < 36 && (
        <span
          data-testid={testid ? `${testid}-bot-dot` : undefined}
          className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-slate-400 border border-zinc-900"
          title="bot"
        />
      )}
    </span>
  );
}

export default Avatar;
