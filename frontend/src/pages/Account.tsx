import { useState } from "react";
import { api, isIOS, isStandalone, setToken } from "../api";
import { useUser } from "../app";
import { Icon, useToast } from "../ui";

const PLAN_INFO: [string, string, string[]][] = [
  ["free", "Free", ["30 min processing / month", "Clean edit", "720p exports with watermark"]],
  ["creator", "Creator", ["300 min / month", "1080p, no watermark", "TikTok Shop tools, captions, AI chat", "5 variations per run"]],
  ["pro", "Pro", ["1,500 min / month", "4K", "Batch generation (Phase 2)", "Analytics & performance learning (Phase 3)"]],
  ["agency", "Agency / Team", ["6,000 min / month", "Multiple users & brand libraries (Phase 3)", "Review workflows (Phase 3)"]],
];

export function AccountPage() {
  const { user, setUser } = useUser();
  const toast = useToast();
  const [name, setName] = useState(user?.name || "");
  const [pw, setPw] = useState({ cur: "", next: "" });
  const [delPw, setDelPw] = useState("");
  if (!user) return null;
  const L = user.limits;
  const saveName = async () => { const u = await api<any>("/account", { method: "PATCH", body: { name } }); setUser(u); toast("Saved"); };
  const changePw = async () => {
    try { await api("/account", { method: "PATCH", body: { password: pw.cur, new_password: pw.next } }); setPw({ cur: "", next: "" }); toast("Password changed"); }
    catch (e: any) { toast(e.message, true); }
  };
  const deleteAccount = async () => {
    if (!confirm("Permanently delete your account, all projects, footage, products and exports? This cannot be undone.")) return;
    try { await api("/account", { method: "DELETE", body: { password: delPw } }); setToken(null); setUser(null); }
    catch (e: any) { toast(e.message, true); }
  };
  return (
    <div>
      <div className="page-head"><h1>Account</h1><button className="btn" onClick={() => { setToken(null); setUser(null); }}>Sign out</button></div>
      <div className="grid two">
        <div className="col gap-l">
          <div className="card col">
            <h3>Profile</h3>
            <div className="small muted">{user.email}</div>
            <label className="field"><span>Name</span><div className="row"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /><button className="btn" onClick={saveName}>Save</button></div></label>
          </div>
          <div className="card col">
            <div className="row between"><h3>Usage this month</h3><span className="badge ember">{user.plan}</span></div>
            <div className="kv"><span>Processing</span><span>{L.used_minutes} / {L.minutes} min</span></div>
            <div className="progress"><div style={{ width: `${Math.min(100, (100 * L.used_minutes) / L.minutes)}%` }} /></div>
            <div className="kv"><span>Exports</span><span>{L.exports}</span></div>
            <div className="kv"><span>Max export</span><span>{L.max_height >= 2160 ? "4K" : `${L.max_height}p`}</span></div>
            <div className="tiny faint">Project recovery, checkpoints and access to your original footage are never limited by plan.</div>
          </div>
          {isIOS() && !isStandalone() && (
            <div className="card col"><div className="row"><Icon n="share" /><h3>Install on iPhone</h3></div>
              <ol className="small muted" style={{ margin: 0, paddingLeft: 18 }}><li>Open Rushline in Safari</li><li>Tap the Share button</li><li>Choose “Add to Home Screen”</li></ol></div>
          )}
          <div className="card col">
            <h3>Password</h3>
            <input className="input" type="password" placeholder="Current password" autoComplete="current-password" value={pw.cur} onChange={(e) => setPw({ ...pw, cur: e.target.value })} />
            <input className="input" type="password" placeholder="New password (8+ characters)" autoComplete="new-password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
            <button className="btn" onClick={changePw} disabled={!pw.cur || pw.next.length < 8}>Change password</button>
          </div>
        </div>
        <div className="col gap-l">
          <div className="card col">
            <div className="row between"><h3>Plans</h3><span className="badge soon">Billing COMING SOON</span></div>
            {PLAN_INFO.map(([k, t, feats]) => (
              <div key={k} className="card flat" style={{ borderColor: user.plan === k ? "var(--ember)" : undefined, border: user.plan === k ? "1px solid var(--ember)" : undefined }}>
                <div className="row between"><b>{t}</b>{user.plan === k && <span className="badge ember">Current</span>}</div>
                <ul className="small muted" style={{ margin: "6px 0 0", paddingLeft: 18 }}>{feats.map((f) => <li key={f}>{f}</li>)}</ul>
              </div>
            ))}
            <div className="tiny faint">Subscriptions (Stripe) are designed into the backend (plans, limits, metering) but checkout isn't live yet.</div>
          </div>
          <div className="card col">
            <div className="row"><Icon n="shield" /><h3>Privacy & data</h3></div>
            <div className="small muted">Your footage is private to your account and served only through short-lived signed links. Exports are kept 30 days. You can delete any clip from the Media library, or everything below.</div>
            <input className="input" type="password" placeholder="Password to confirm" value={delPw} onChange={(e) => setDelPw(e.target.value)} />
            <button className="btn danger" disabled={!delPw} onClick={deleteAccount}><Icon n="trash" />Delete account & all data</button>
          </div>
        </div>
      </div>
    </div>
  );
}
