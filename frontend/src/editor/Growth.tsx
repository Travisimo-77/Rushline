import { useState } from "react";
import { fmt } from "../api";
import { Icon } from "../ui";

/** Estimated-attention curve with warning bands and one-tap fixes. Heuristic, clearly labelled. */
export function RetentionMap({ view, onPlan, onSeek }: { view: any; onPlan: (a: string, args?: any) => void; onSeek: (t: number) => void }) {
  const r = view.retention || { curve: [], warnings: [] };
  const D = Math.max(view.timeline.duration, 0.1);
  if (!r.curve.length) return null;
  const W = 300, H = 90;
  const x = (t: number) => (t / D) * W;
  const y = (v: number) => H - (v / 100) * (H - 8) - 4;
  const path = r.curve.map(([t, v]: number[], i: number) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${path} L${x(r.curve[r.curve.length - 1][0]).toFixed(1)},${H} L0,${H} Z`;
  return (
    <section>
      <div className="row between mb"><h3>Retention map</h3><span className="tiny faint">estimate, not a prediction</span></div>
      <svg viewBox={`0 0 ${W} ${H + 14}`} style={{ width: "100%", height: "auto", display: "block" }} onClick={(e) => {
        const b = (e.target as SVGElement).closest("svg")!.getBoundingClientRect();
        onSeek(((e.clientX - b.left) / b.width) * D);
      }}>
        {r.warnings.map((w: any, i: number) => (
          <rect key={i} x={x(w.t0)} y={0} width={Math.max(2, x(w.t1) - x(w.t0))} height={H} fill="rgba(255,178,63,.13)" />
        ))}
        {view.sections.map((s: any, i: number) => <line key={i} x1={x(s.t0)} x2={x(s.t0)} y1={H} y2={H + 5} stroke="var(--faint)" />)}
        <path d={area} fill="rgba(61,219,176,.14)" />
        <path d={path} fill="none" stroke="var(--mint)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <text x="0" y={H + 13} fontSize="9" fill="var(--faint)">0s</text>
        <text x={W} y={H + 13} fontSize="9" fill="var(--faint)" textAnchor="end">{fmt(D)}</text>
      </svg>
      <div className="col gap-s mt">
        {!r.warnings.length && <div className="small muted">No weak spots found — pacing, visuals and product timing look solid.</div>}
        {r.warnings.map((w: any, i: number) => (
          <div key={i} className="note warn small" style={{ alignItems: "center" }}>
            <span className="mono tiny faint" style={{ cursor: "pointer", minWidth: 34 }} onClick={() => onSeek(w.t0)}>{w.t0.toFixed(0)}s</span>
            <div className="grow">{w.message}{w.hint && <div className="tiny faint">{w.hint}</div>}</div>
            {w.fix && <button className="btn sm ai" onClick={() => onPlan(w.fix.action, w.fix.args)}>{w.fix.label}</button>}
          </div>
        ))}
      </div>
    </section>
  );
}

const SEV: Record<string, string> = { high: "fail", medium: "warn", low: "" };

export function ShopSafe({ view, onPlan, onRemoveOverlay, onSeek }: any) {
  const s = view.shop_safe || { status: "safe", total: 0 };
  return (
    <section className="col gap-s">
      <div className="row"><Icon n="shield" /><h3 className="grow">Shop-safe check</h3>
        <span className={`badge ${s.status === "safe" ? "ok" : s.status === "risky" ? "fail" : "warn"}`}>
          {s.status === "safe" ? "Looks safe" : s.status === "risky" ? `${s.high} high-risk` : `${s.total} to review`}</span></div>
      {!view.compliance.length && <div className="small muted">No risky claims found in what you say or in on-screen text. Checks guarantees, medical/weight-loss claims, fake urgency, off-platform links, and price/discount vs your product profile. (Guidance, not legal advice.)</div>}
      {view.compliance.map((c: any, i: number) => (
        <div key={i} className={`note small ${SEV[c.severity] || ""}`}>
          <Icon n="warn" />
          <div className="grow">
            <b>{c.issue}</b> — “{c.match}” <span className="tiny faint">{c.where === "text" ? "on-screen text" : c.t0 != null ? `at ${c.t0.toFixed(1)}s` : ""}</span>
            <div className="muted">{c.why}</div>
            <div>Try: {c.suggestion}</div>
            <div className="row mt gap-s">
              {c.t0 != null && <button className="btn sm ghost" onClick={() => onSeek(c.t0)}>Play</button>}
              {c.where === "speech" && c.ref && <button className="btn sm danger" onClick={() => onPlan("remove_line", { unit_id: c.ref })}>Cut this line</button>}
              {c.where === "text" && c.ref && <button className="btn sm danger" onClick={() => onRemoveOverlay(c.ref)}>Remove text</button>}
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

export function Learned({ view }: { view: any }) {
  if (!view.learned?.length) return null;
  return (
    <section className="col gap-s">
      <div className="row between"><h3>From your results</h3><a className="tiny" style={{ color: "var(--mint)" }} href="#/analytics">All insights</a></div>
      {view.learned.map((l: any, i: number) => (
        <div key={i} className="note small"><Icon n="analytics" /><div className="grow">{l.text}{l.tip && <div className="muted">{l.tip}</div>}
          <div className="tiny faint">{l.confidence} confidence · correlation in your data, not a guarantee</div></div></div>
      ))}
    </section>
  );
}

export function TextHookSection({ view, addOps, onPlan }: any) {
  const [custom, setCustom] = useState("");
  const [dur, setDur] = useState(2.5);
  const current = view.overlays.find((o: any) => o.id === "hook");
  const apply = (text: string) => onPlan("add_text_hook", { text, dur });
  return (
    <section className="col">
      <div className="row between"><h3>Text hook</h3>{current && <button className="btn sm ghost" onClick={() => addOps([{ kind: "remove_overlay", params: { id: "hook" }, label: "Removed text hook" }], "Text hook")}>Remove</button>}</div>
      <div className="tiny faint">Bold on-screen line for the first seconds. Built only from your recorded hook and your product profile.</div>
      {current && <div className="note small"><Icon n="text" /><div className="grow"><b>On screen:</b> “{current.text}” · {(current.t1 - current.t0).toFixed(1)}s</div></div>}
      <div className="col gap-s">
        {(view.text_hook_ideas || []).map((i: any) => (
          <div key={i.text} className="row" style={{ cursor: "pointer" }} onClick={() => apply(i.text)}>
            <span className="grow" style={{ background: "#fff", color: "#111", fontWeight: 800, borderRadius: 8, padding: "6px 10px", fontFamily: "Poppins" }}>{i.text}</span>
            <span className="tiny faint" style={{ minWidth: 70, textAlign: "right" }}>{i.source}</span>
          </div>
        ))}
      </div>
      <div className="row">
        <input className="input" placeholder="Write your own…" value={custom} maxLength={80} onChange={(e) => setCustom(e.target.value)} />
        <button className="btn" disabled={!custom.trim()} onClick={() => apply(custom.trim())}>Use</button>
      </div>
      <div className="row between small"><span>Show for</span>
        <div className="seg">{[2, 2.5, 3.5, 5].map((d) => <button key={d} className={dur === d ? "on" : ""} onClick={() => setDur(d)}>{d}s</button>)}</div></div>
    </section>
  );
}

export function BatchAds({ view, onPlan }: any) {
  const [n, setN] = useState(6);
  const p = view.pieces || { hooks: [], ctas: [] };
  const combos = Math.max(1, p.hooks.length) * Math.max(1, p.ctas.length) * 4;
  return (
    <section className="card flat col">
      <h3>Build ads from your pieces</h3>
      <div className="small muted">Record several hooks and CTAs in one session — Rushline mixes them with different structures into separate ads.</div>
      <div className="row wrap gap-s">
        <span className="badge ember">{p.hooks.length} hook{p.hooks.length !== 1 ? "s" : ""}</span>
        <span className="badge ai">{p.ctas.length} CTA{p.ctas.length !== 1 ? "s" : ""}</span>
        <span className="badge">up to {combos} combos</span>
      </div>
      {p.hooks.length > 0 && <div className="tiny faint">Hooks: {p.hooks.slice(0, 4).map((h: any) => `“${h.text.slice(0, 32)}”`).join(" · ")}</div>}
      <div className="row wrap gap-s">{[4, 6, 10, 15].map((k) => <span key={k} className={`chip ${n === k ? "on" : ""}`} onClick={() => setN(k)}>{k} ads</span>)}</div>
      <button className="btn ai" onClick={() => onPlan("batch_ads", { count: n })}><Icon n="layers" />Plan {n} ads</button>
    </section>
  );
}
