import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { Logo } from "../components/game/Logo";

export function AuthPage({ mode = "login" }) {
  const { login, register } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (mode === "register") await register(email, username, password);
      else await login(email, password);
      nav("/menu");
    } catch (ex) {
      setErr(ex?.response?.data?.detail || "Authentication failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="flex justify-center mb-8">
          <Logo size={72} />
        </div>
        <div className="panel p-8" data-testid={`auth-form-${mode}`}>
          <h1 className="font-display text-3xl text-gold tracking-[0.2em] mb-6 text-center">
            {mode === "register" ? "CREATE ACCOUNT" : "ENTER THE TABLE"}
          </h1>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-[10px] uppercase tracking-widest text-neutral-mid">Email</label>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} data-testid="auth-email" />
            </div>
            {mode === "register" && (
              <div>
                <label className="text-[10px] uppercase tracking-widest text-neutral-mid">Username</label>
                <input type="text" required value={username} onChange={(e) => setUsername(e.target.value)} data-testid="auth-username" />
              </div>
            )}
            <div>
              <label className="text-[10px] uppercase tracking-widest text-neutral-mid">Password</label>
              <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} data-testid="auth-password" />
            </div>
            {err && <div className="text-red-target text-sm font-luxe" data-testid="auth-error">{err}</div>}
            <button type="submit" disabled={busy} className="btn-primary w-full" data-testid="auth-submit">
              {busy ? "..." : (mode === "register" ? "REGISTER" : "LOGIN")}
            </button>
          </form>
          <div className="mt-5 text-center text-sm text-neutral-mid">
            {mode === "register" ? (
              <>Already have an account? <Link to="/login" className="text-gold underline" data-testid="link-login">Login</Link></>
            ) : (
              <>New player? <Link to="/register" className="text-gold underline" data-testid="link-register">Create account</Link></>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
