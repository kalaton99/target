import React, { useEffect, useState } from "react";

/**
 * BettingPanel — renders FOLD / CALL / BET-RAISE controls.
 * Also renders HIT / STAND for DRAW phase.
 */
export function BettingPanel({ phase, isMyTurn, currentBet, myBet, balance, minRaise, onAction, turnDeadlineMs }) {
  const owed = Math.max(0, currentBet - myBet);
  const [raise, setRaise] = useState(Math.max(minRaise || 0, 100));
  const [secondsLeft, setSecondsLeft] = useState(0);

  useEffect(() => {
    if (!turnDeadlineMs) {
      setSecondsLeft(0);
      return;
    }
    const tick = () => {
      const ms = Math.max(0, turnDeadlineMs - Date.now());
      setSecondsLeft(Math.ceil(ms / 1000));
    };
    tick();
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [turnDeadlineMs]);

  const disabled = !isMyTurn;

  return (
    <div className="panel p-5" data-testid="betting-panel">
      <div className="flex items-center justify-between mb-3">
        <div className="text-[10px] uppercase tracking-[0.4em] text-neutral-mid font-luxe">Phase</div>
        <div className="font-display text-base text-gold tracking-widest" data-testid="phase-name">{phase}</div>
        <div className="text-[10px] uppercase tracking-[0.4em] text-neutral-mid font-luxe">
          {isMyTurn ? <span className="text-cyan font-display tracking-widest" data-testid="your-turn">YOUR TURN</span> : <span>WAIT</span>}
        </div>
      </div>

      {isMyTurn && turnDeadlineMs && (
        <div className="mb-3" data-testid="turn-timer">
          <div className="flex justify-between text-[10px] uppercase tracking-widest text-neutral-mid">
            <span>Time</span>
            <span className={secondsLeft <= 5 ? "text-red-target" : "text-cyan"}>{secondsLeft}s</span>
          </div>
          <div className="h-1 bg-black rounded-full overflow-hidden mt-1">
            <div
              className={`h-full transition-[width] duration-200 ${secondsLeft <= 5 ? "bg-red-500" : "bg-cyan-400"}`}
              style={{ width: `${Math.min(100, (secondsLeft / 15) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {phase === "DRAW" ? (
        <div className="grid grid-cols-2 gap-3" data-testid="draw-controls">
          <button className="btn-secondary" disabled={disabled} onClick={() => onAction("HIT")} data-testid="action-hit">HIT</button>
          <button className="btn-primary" disabled={disabled} onClick={() => onAction("STAND")} data-testid="action-stand">STAND</button>
        </div>
      ) : phase === "BETTING" ? (
        <>
          <div className="grid grid-cols-3 gap-3">
            <button className="btn-danger" disabled={disabled} onClick={() => onAction("FOLD")} data-testid="action-fold">FOLD</button>
            {owed > 0 ? (
              <button className="btn-secondary" disabled={disabled} onClick={() => onAction("CALL")} data-testid="action-call">
                <div className="leading-tight">
                  <div>CALL</div>
                  <div className="font-num text-xs">{owed.toLocaleString()}</div>
                </div>
              </button>
            ) : (
              <button className="btn-secondary" disabled={disabled} onClick={() => onAction("CHECK")} data-testid="action-check">CHECK</button>
            )}
            <button className="btn-primary" disabled={disabled || raise <= 0} onClick={() => onAction("RAISE", { amount: raise })} data-testid="action-raise">
              <div className="leading-tight">
                <div>BET / RAISE</div>
                <div className="font-num text-xs">{raise.toLocaleString()}</div>
              </div>
            </button>
          </div>
          <div className="mt-4">
            <div className="flex justify-between text-[10px] uppercase tracking-widest text-neutral-mid mb-1">
              <span>Bet Amount</span>
              <span className="text-gold font-num">{raise.toLocaleString()}</span>
            </div>
            <input
              type="range"
              min={minRaise || 100}
              max={balance || 10000}
              step={50}
              value={raise}
              onChange={(e) => setRaise(parseInt(e.target.value))}
              data-testid="bet-slider"
            />
            <div className="flex justify-between mt-2 gap-2">
              <button className="btn-ghost" onClick={() => setRaise(minRaise || 100)} data-testid="bet-min">MIN</button>
              <button className="btn-ghost" onClick={() => setRaise(Math.min(balance, raise * 2))} data-testid="bet-x2">x2</button>
              <button className="btn-ghost" onClick={() => setRaise(Math.min(balance, Math.floor((currentBet + raise) / 2)))} data-testid="bet-half">1/2 POT</button>
              <button className="btn-ghost" onClick={() => setRaise(balance || 10000)} data-testid="bet-max">MAX</button>
            </div>
          </div>
        </>
      ) : (
        <div className="text-center py-4 text-neutral-mid font-luxe tracking-widest" data-testid="phase-idle">
          {phase === "WAITING" ? "WAITING FOR PLAYERS..." :
           phase === "ENDED" ? "HAND COMPLETE" :
           phase === "PAYOUT" ? "PAYING OUT..." :
           "·"}
        </div>
      )}
    </div>
  );
}
