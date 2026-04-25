import React from "react";

export function PotDisplay({ pot, phase }) {
  return (
    <div className="flex flex-col items-center" data-testid="pot-display">
      <div className="pot-ring px-12 py-8 flex flex-col items-center min-w-[240px] animate-pulse-gold bg-black/60">
        <div className="text-[10px] uppercase tracking-[0.4em] text-gold/70 font-luxe">Current Pot</div>
        <div className="font-display text-5xl text-gold mt-1" style={{textShadow:"0 0 28px rgba(255,209,102,0.6)"}}>
          {(pot ?? 0).toLocaleString()}
        </div>
        <div className="text-[10px] uppercase tracking-[0.3em] text-gold/60 font-luxe mt-1">CREDITS</div>
      </div>
      {phase && (
        <div className="mt-3 px-5 py-1.5 panel">
          <div className="text-[9px] uppercase tracking-[0.4em] text-neutral-mid">Phase</div>
          <div className="font-display text-base text-cyan tracking-widest text-center">{phase}</div>
        </div>
      )}
    </div>
  );
}
