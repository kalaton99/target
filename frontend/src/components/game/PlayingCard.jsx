import React from "react";

const SUIT_GLYPH = { S: "♠", H: "♥", D: "♦", C: "♣", "*": "★" };

export function PlayingCard({ rank, suit, code, faceDown = false, redBack = false, selected = false }) {
  if (faceDown) {
    return (
      <div className={`playing-card-back ${redBack ? "red" : ""}`} data-testid={`card-back-${redBack ? 'red' : 'gold'}`} />
    );
  }
  const isRed = suit === "H" || suit === "D";
  const isJoker = rank === "JOKER";
  const display = isJoker ? "JK" : (rank === "10" ? "10" : rank);
  return (
    <div
      className={`playing-card ${isRed ? "red" : ""} ${selected ? "ring-2 ring-cyan-300" : ""}`}
      data-testid={`card-${code || `${rank}${suit}`}`}
      style={{ boxShadow: selected ? "0 0 22px rgba(0,212,255,0.7), 0 6px 18px rgba(0,0,0,0.6)" : undefined }}
    >
      <div className="text-base leading-none">{display}</div>
      <div className="text-2xl text-center">{isJoker ? "★" : SUIT_GLYPH[suit] || ""}</div>
      <div className="text-base leading-none rotate-180 self-end">{display}</div>
    </div>
  );
}
