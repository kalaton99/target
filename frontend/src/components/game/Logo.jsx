import React from "react";

export function Logo({ size = 60 }) {
  return (
    <div className="flex items-center gap-3" data-testid="target-logo">
      <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
        <defs>
          <radialGradient id="g1" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#ffe89a" />
            <stop offset="60%" stopColor="#FFD166" />
            <stop offset="100%" stopColor="#7a5f1f" />
          </radialGradient>
        </defs>
        <circle cx="32" cy="32" r="26" fill="none" stroke="url(#g1)" strokeWidth="3" />
        <circle cx="32" cy="32" r="16" fill="none" stroke="url(#g1)" strokeWidth="2" />
        <circle cx="32" cy="32" r="6" fill="url(#g1)" />
        <line x1="32" y1="2" x2="32" y2="14" stroke="url(#g1)" strokeWidth="3" strokeLinecap="round" />
        <line x1="32" y1="50" x2="32" y2="62" stroke="url(#g1)" strokeWidth="3" strokeLinecap="round" />
        <line x1="2" y1="32" x2="14" y2="32" stroke="url(#g1)" strokeWidth="3" strokeLinecap="round" />
        <line x1="50" y1="32" x2="62" y2="32" stroke="url(#g1)" strokeWidth="3" strokeLinecap="round" />
        <text x="32" y="36" textAnchor="middle" fontSize="9" fontFamily="Cinzel" fontWeight="800" fill="#0b0b10">♠</text>
      </svg>
      <div>
        <div className="font-display text-2xl text-gold leading-none tracking-widest" style={{textShadow:"0 0 18px rgba(255,209,102,0.45)"}}>TARGET</div>
        <div className="font-luxe text-[9px] text-gold/70 tracking-[0.35em] uppercase">Premium Card Game</div>
      </div>
    </div>
  );
}
