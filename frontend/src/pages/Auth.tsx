import { useState } from "react";
import { api } from "../api";
import { Logo } from "../ui";

export function AuthPage({ onAuthed }: { onAuthed: (u: any, token: string) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("signup");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: any) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const r = await api<any>(`/auth/${mode}`, { body: { email, password: pw, name }, retries: 0 });
      onAuthed(r.user, r.token);
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="auth">
      <form className="card col gap-l" onSubmit={submit}>
        <div>
          <div className="hero-mark"><Logo size={56} /></div>
          <h1>{mode === "signup" ? "Raw takes in. Ready ads out." : "Welcome back"}</h1>
          <p className="muted small">Rushline cleans your footage, understands your product and builds high-retention ad versions.</p>
        </div>
        {mode === "signup" && (
          <label className="field"><span>Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
        )}
        <label className="field"><span>Email</span>
          <input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" inputMode="email" autoCapitalize="none" />
        </label>
        <label className="field"><span>Password</span>
          <input className="input" type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)}
            autoComplete={mode === "signup" ? "new-password" : "current-password"} />
        </label>
        {err && <div className="note fail small">{err}</div>}
        <button className="btn primary" disabled={busy}>{busy ? "…" : mode === "signup" ? "Create account" : "Sign in"}</button>
        <button type="button" className="btn ghost sm" onClick={() => { setMode(mode === "signup" ? "login" : "signup"); setErr(""); }}>
          {mode === "signup" ? "Already have an account? Sign in" : "New here? Create an account"}
        </button>
        <p className="tiny faint">Your footage is private to your account. Originals are never modified.</p>
      </form>
    </div>
  );
}
