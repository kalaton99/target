import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { Logo } from "../components/game/Logo";
import { useAuth } from "../lib/auth";

export function TablesPage() {
  const [tables, setTables] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  const { user } = useAuth();

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/tables");
      setTables(data.tables || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const join = async (id) => {
    try {
      await api.post(`/tables/${id}/join`);
      nav(`/table/${id}`);
    } catch (e) {
      alert(e?.response?.data?.detail || "Cannot join");
    }
  };

  const createTable = async () => {
    setCreating(true);
    try {
      const { data } = await api.post("/tables", { name: `${user?.username}'s Table`, type: "FREE", stake: 100, max_players: 4 });
      await api.post(`/tables/${data.id}/join`);
      nav(`/table/${data.id}`);
    } catch (e) {
      alert(e?.response?.data?.detail || "Cannot create");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="min-h-screen px-6 py-8">
      <header className="flex items-center justify-between mb-8">
        <button className="btn-ghost" onClick={() => nav("/menu")} data-testid="back-menu">← MENU</button>
        <Logo size={48} />
        <button className="btn-primary" onClick={createTable} disabled={creating} data-testid="create-table-btn">
          {creating ? "..." : "+ CREATE TABLE"}
        </button>
      </header>
      <h1 className="font-display text-3xl text-gold tracking-widest mb-6">OPEN TABLES</h1>
      {loading ? (
        <div className="text-neutral-mid font-luxe">LOADING...</div>
      ) : tables.length === 0 ? (
        <div className="panel p-8 text-center" data-testid="no-tables">
          <div className="text-neutral-mid font-luxe tracking-widest mb-3">NO ACTIVE TABLES</div>
          <button className="btn-primary" onClick={createTable} data-testid="create-table-empty">CREATE THE FIRST TABLE</button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="tables-list">
          {tables.map((t) => {
            const filled = t.seats.filter(s => s.user_id).length;
            return (
              <div key={t.id} className="panel p-5 flex flex-col" data-testid={`table-${t.id}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="font-display text-lg text-gold tracking-widest">{t.name}</div>
                  <div className="text-[10px] uppercase tracking-widest text-neutral-mid">{t.type}</div>
                </div>
                <div className="text-sm text-neutral-mid mb-1">Stake: <span className="text-gold font-num">{t.stake.toLocaleString()}</span></div>
                <div className="text-sm text-neutral-mid mb-3">Players: <span className="text-cyan font-num">{filled}/{t.max_players}</span></div>
                <button className="btn-secondary mt-auto" onClick={() => join(t.id)} disabled={filled >= t.max_players} data-testid={`join-${t.id}`}>JOIN</button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
