import { useEffect, useRef, useState } from "react";
import { ago, api, fmt, fmtShort } from "../api";
import { useUser } from "../app";
import { Icon, SECTION_COLORS, SECTION_LABELS, Switch, useToast } from "../ui";
import { PlanCard } from "./PlanCard";
import { BatchAds, Learned, RetentionMap, ShopSafe, TextHookSection } from "./Growth";

// ---------------------------------------------------------------- Assistant
const SUGGEST = ["Remove all the dead space", "Make this faster", "Turn this into a 25-second TikTok Shop ad", "Use my strongest hook",
  "Show the product within the first 3 seconds", "Take out the repetitive parts", "Make the CTA shorter", "Make three completely different versions",
  "Make one version focused on price", "Add captions", "Make this more natural"];

export function AssistantPanel({ versionId, onApplied, chat, setChat }: { versionId: string; onApplied: (r: any) => void; chat: any[]; setChat: (f: (c: any[]) => any[]) => void }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [chat.length]);
  const send = async (t: string) => {
    if (!t.trim()) return;
    setText("");
    setChat((c) => [...c, { me: true, text: t }]);
    setBusy(true);
    try {
      const plan = await api(`/versions/${versionId}/plan`, { body: { action: "assistant", text: t } });
      setChat((c) => [...c, { plan, id: Math.random() }]);
    } catch (e: any) { setChat((c) => [...c, { text: e.message }]); } finally { setBusy(false); }
  };
  const apply = async (id: number, plan: any, steps: any[], variations: any[] | null) => {
    setBusy(true);
    try {
      const r = await api<any>(`/versions/${versionId}/apply`, { body: { steps, variations, title: plan.title, from_assistant: true } });
      onApplied(r);
      setChat((c) => c.map((m) => (m.id === id ? { text: `Done — ${steps.length} change${steps.length !== 1 ? "s" : ""} applied${r.versions?.length ? `, ${r.versions.length} versions created` : ""}. Undo any of it from History.` } : m)));
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  return (
    <>
      <div className="pbody">
        <div className="chat">
          {!chat.length && (
            <div className="msg ai">Tell me what to change — I turn requests into real timeline edits and show you the plan first. I never invent words you didn't say.</div>
          )}
          {chat.map((m, i) => m.plan ? (
            <PlanCard key={m.id} plan={m.plan} busy={busy} onApply={(s, v) => apply(m.id, m.plan, s, v)} onCancel={() => setChat((c) => c.map((x) => (x.id === m.id ? { text: "Cancelled — nothing changed." } : x)))} />
          ) : <div key={i} className={`msg ${m.me ? "me" : "ai"}`}>{m.text}</div>)}
          {busy && <div className="msg ai row"><div className="spinner" />Thinking…</div>}
          <div ref={end} />
        </div>
        {!chat.length && <div className="row wrap gap-s mt">{SUGGEST.map((s) => <span key={s} className="chip" onClick={() => send(s)}>{s}</span>)}</div>}
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input className="input" placeholder="e.g. make this a 20s ad with the price hook" value={text} onChange={(e) => setText(e.target.value)} enterKeyHint="send" />
        <button className="btn ai icon" disabled={busy || !text.trim()} aria-label="Send"><Icon n="spark" /></button>
      </form>
    </>
  );
}

// ---------------------------------------------------------------- Insights (structure, hooks, product, retention heuristics, compliance)
export function InsightsPanel({ view, project, onPlan, onSeek, addOps }: { view: any; project: any; onPlan: (a: string, args?: any) => void; onSeek: (t: number) => void; addOps: (ops: any[], label: string) => void }) {
  const vis = view.visibility;
  const D = view.timeline.duration;
  const scores = heuristics(view);
  return (
    <div className="pbody col gap-l">
      <RetentionMap view={view} onPlan={onPlan} onSeek={onSeek} />
      <Learned view={view} />
      <section>
        <div className="row between mb"><h3>Ad structure</h3><button className="btn sm" onClick={() => onPlan("restructure", { template: "problem_solution" })}><Icon n="wand" />Restructure</button></div>
        <div style={{ display: "flex", height: 10, borderRadius: 6, overflow: "hidden", marginBottom: 10 }}>
          {view.sections.map((s: any, i: number) => <div key={i} style={{ flex: s.t1 - s.t0, background: SECTION_COLORS[s.section] }} />)}
        </div>
        {view.sections.map((s: any, i: number) => (
          <div key={i} className="kv" style={{ cursor: "pointer" }} onClick={() => onSeek(s.t0)}>
            <span className="row gap-s"><i className="sec-dot" style={{ background: SECTION_COLORS[s.section] }} />{s.label}</span><span className="mono muted">{fmt(s.t0)}–{fmt(s.t1)}</span>
          </div>
        ))}
        {view.missing_sections.length > 0 && <div className="small muted mt">Not detected: {view.missing_sections.map((s: string) => SECTION_LABELS[s]).join(", ")}</div>}
      </section>
      {view.diagnostics.length > 0 && (
        <section className="col gap-s">
          <h3>Recommendations</h3>
          {view.diagnostics.map((d: any, i: number) => (
            <div key={i} className={`note ${d.level}`}><Icon n={d.level === "warn" ? "warn" : "info"} /><div className="grow">{d.message}</div>
              {d.fix && <button className="btn sm ai" onClick={() => onPlan(d.fix, d.fix === "fit_duration" ? { seconds: project?.target_duration } : {})}>Fix</button>}</div>
          ))}
        </section>
      )}
      <section className="col gap-s">
        <div className="row between"><h3>Hooks you recorded</h3><span className="tiny faint">{view.hooks.length} found</span></div>
        {!view.hooks.length && <div className="small muted">No strong hook lines detected. Try the hook ideas in Scripts (coming soon) and record one.</div>}
        {view.hooks.map((h: any, i: number) => (
          <div key={h.id} className={`hook ${h.in_use ? "use" : ""}`}>
            <div className="row"><span className="score">{h.score}</span><div className="grow">
              <div className="meter"><i style={{ width: `${h.score}%` }} /></div>
              <div className="tiny muted mt" style={{ marginTop: 4 }}>{h.categories.join(" · ")} · {h.duration}s{h.in_use ? " · opening now" : ""}{!h.kept ? " · currently cut" : ""}</div>
            </div></div>
            <div className="mt" style={{ fontWeight: 600 }}>“{h.text}”</div>
            <div className="row mt">
              {!h.in_use && <button className="btn sm" onClick={() => onPlan("find_best_hook", { hook_id: h.id })}>Use as opening</button>}
              <button className="btn sm ghost" onClick={() => onPlan("generate_variations", { count: 1 })} hidden={i > 0}>Hook A/B versions</button>
            </div>
          </div>
        ))}
      </section>
      <section>
        <div className="row between mb"><h3>Product visibility</h3>{!vis.tracked && <span className="badge warn">needs photos</span>}</div>
        {vis.tracked ? (<>
          <div className="kv"><span>First appearance</span><b>{vis.first != null ? `${vis.first.toFixed(1)}s` : "never"}</b></div>
          <div className="kv"><span>Screen time</span><span>{vis.total.toFixed(1)}s ({vis.percent}%)</span></div>
          <div className="kv"><span>Longest stretch without product</span><span>{vis.longest_gap.toFixed(1)}s</span></div>
          <div className="kv"><span>Close-ups</span><span>{vis.closeups}</span></div>
        </>) : <div className="small muted">Add product photos to the product profile (or tag clips as “product visible”) to track when it's on screen.</div>}
        {vis.mentions.length > 0 && <div className="kv"><span>Product named at</span><span>{vis.mentions.map((m: number) => `${m.toFixed(0)}s`).join(", ")}</span></div>}
        {(vis.first == null || vis.first > 3) && <button className="btn sm ai mt" onClick={() => onPlan("show_product_earlier", { within: 3 })}><Icon n="eye" />Show product earlier</button>}
      </section>
      <section>
        <div className="row between mb"><h3>Retention checklist</h3><span className="tiny faint">editing heuristic</span></div>
        {scores.map(([label, v, note]) => (
          <div key={label as string} className="mb">
            <div className="row between small"><span>{label}</span><span className="muted">{note}</span></div>
            <div className="meter" style={{ height: 6 }}><i style={{ width: `${v}%`, background: (v as number) >= 70 ? "var(--ok)" : (v as number) >= 45 ? "var(--warn)" : "var(--danger)" }} /></div>
          </div>
        ))}
        <div className="tiny faint">These are editing heuristics, not a prediction of views or sales.</div>
      </section>
      <ShopSafe view={view} onPlan={onPlan} onSeek={onSeek}
        onRemoveOverlay={(id: string) => addOps([{ kind: "remove_overlay", params: { id }, label: "Removed flagged text" }], "Shop-safe")} />
      <div className="small faint">Length: {fmtShort(D)}{project?.target_duration ? ` · target ${project.target_duration}s` : ""}</div>
    </div>
  );
}

function heuristics(view: any): [string, number, string][] {
  const D = Math.max(view.timeline.duration, 0.1);
  const clips = view.timeline.clips;
  const first = view.sections[0];
  const hookLen = first ? first.t1 - first.t0 : D;
  const cutsPer10 = (clips.length / D) * 10;
  const kept = view.words.filter((w: any) => w.kept);
  const wps = kept.length / D;
  const fillers = kept.filter((w: any) => w.filler).length;
  const secs = new Set(view.sections.map((s: any) => s.section));
  const pct = view.visibility.tracked ? view.visibility.percent : null;
  const clamp = (x: number) => Math.max(5, Math.min(100, Math.round(x)));
  return [
    ["Opening speed", clamp(first?.section === "hook" ? 100 - Math.max(0, hookLen - 2) * 18 : 30), first?.section === "hook" ? `hook ${hookLen.toFixed(1)}s` : "no clear hook"],
    ["Pacing", clamp(100 - Math.abs(wps - 3.0) * 35), `${wps.toFixed(1)} words/s`],
    ["Visual variety", clamp(cutsPer10 * 22 + clips.filter((c: any) => c.props?.zoom > 1).length * 5), `${cutsPer10.toFixed(1)} cuts / 10s`],
    ["Product visibility", pct == null ? 40 : clamp(pct * 2.2), pct == null ? "not tracked" : `${pct}% on screen`],
    ["Clarity", clamp(100 - fillers * 12), `${fillers} filler${fillers !== 1 ? "s" : ""} left`],
    ["CTA", secs.has("cta") ? 100 : 10, secs.has("cta") ? "present" : "missing"],
    ["Demonstration", secs.has("demonstration") || view.visibility.total > 2 ? 100 : 20, secs.has("demonstration") ? "present" : "missing"],
  ];
}

// ---------------------------------------------------------------- History
export function HistoryPanel({ view, versionId, onView, onCompare }: { view: any; versionId: string; onView: (v: any) => void; onCompare: () => void }) {
  const toast = useToast();
  const call = async (p: Promise<any>, msg?: string) => { try { const r = await p; onView(r.view); if (msg) toast(msg); } catch (e: any) { toast(e.message, true); } };
  const ops = [...view.history].reverse();
  return (
    <div className="pbody col gap-l">
      <div className="row wrap gap-s">
        <button className="btn sm" onClick={() => call(api(`/versions/${versionId}/undo`, { body: {} }), "Undone")}><Icon n="undo" />Undo</button>
        <button className="btn sm" onClick={() => call(api(`/versions/${versionId}/redo`, { body: {} }), "Redone")}><Icon n="redo" />Redo</button>
        <button className="btn sm" onClick={onCompare}><Icon n="eye" />View original</button>
        <button className="btn sm danger" onClick={() => confirm("Turn off every AI edit? (Your manual edits stay. You can restore from a checkpoint.)") && call(api(`/versions/${versionId}/reset`, { body: {} }), "AI edits reset")}>Reset AI edit</button>
      </div>
      <section>
        <h3 className="mb">Edit history</h3>
        {!ops.length && <div className="small muted">No edits yet.</div>}
        {ops.map((o: any) => (
          <label key={o.id} className="list-item" style={{ opacity: o.enabled ? 1 : 0.5, cursor: "pointer" }}>
            <input type="checkbox" checked={!!o.enabled} style={{ width: 20, height: 20, accentColor: "var(--mint)" }}
              onChange={(e) => call(api(`/versions/${versionId}/ops/${o.id}`, { method: "PATCH", body: { enabled: e.target.checked } }))} />
            <div className="grow"><div style={{ fontWeight: 600, fontSize: 14, textDecoration: o.enabled ? undefined : "line-through" }}>{o.label}</div>
              <div className="tiny muted">{o.source === "user" ? "You" : o.source === "assistant" ? "Assistant" : "AI"} · {ago(o.created_at)}{view.skipped_ops.includes(o.id) ? " · no longer applies" : ""}</div></div>
            <span className={`badge ${o.source === "user" ? "" : "ai"}`}>{o.kind}</span>
          </label>
        ))}
      </section>
      <section>
        <h3 className="mb">Checkpoints</h3>
        <div className="tiny faint mb">Saved automatically before every AI action. Restoring never deletes anything.</div>
        {view.checkpoints.map((c: any) => (
          <div key={c.id} className="list-item"><Icon n="history" /><div className="grow"><div style={{ fontWeight: 600, fontSize: 14 }}>{c.label}</div><div className="tiny muted">{ago(c.created_at)}</div></div>
            <button className="btn sm" onClick={() => call(api(`/versions/${versionId}/checkpoints/${c.id}/restore`, { body: {} }), "Checkpoint restored")}>Restore</button></div>
        ))}
        <button className="btn sm mt" onClick={() => api(`/versions/${versionId}/checkpoints`, { body: { label: "Manual checkpoint" } }).then(() => api(`/versions/${versionId}`)).then(onView)}>Save checkpoint now</button>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- Style (captions, audio, color)
export function StylePanel({ view, addOps, onPlan, showSafe, setShowSafe, audioAB, setAudioAB }: any) {
  const { meta } = useUser();
  const presets = meta?.caption_presets || {};
  const cap = view.settings.captions || {};
  const st = view.caption_style;
  const col = view.settings.color || {};
  const aud = view.settings.audio || {};
  const pending = useRef<any>({});
  const timer = useRef<any>(0);
  // sliders are debounced into a single settings op
  const patch = (p: any, label: string) => {
    pending.current = deepMerge(pending.current, p);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { const x = pending.current; pending.current = {}; addOps([{ kind: "settings", params: { patch: x }, label }], label); }, 450);
  };
  const [local, setLocal] = useState<any>({});
  useEffect(() => setLocal({}), [view]);
  const v = (path: string, def: any) => local[path] ?? path.split(".").reduce((o: any, k) => (o ? o[k] : undefined), { cap: { ...st }, col, aud }) ?? def;
  const slide = (path: string, val: number, p: any, label: string) => { setLocal({ ...local, [path]: val }); patch(p, label); };
  const enhancedReady = view.media.some((m: any) => m.enhanced_url);
  return (
    <div className="pbody col gap-l">
      <TextHookSection view={view} addOps={addOps} onPlan={onPlan} />
      <section className="col">
        <div className="row between"><h3>Captions</h3><Switch checked={cap.enabled !== false} onChange={(on) => addOps([{ kind: "settings", params: { patch: { captions: { enabled: on } } }, label: on ? "Captions on" : "Captions off" }], "Captions")} /></div>
        <div className="grid" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 8 }}>
          {Object.entries(presets).map(([k, p]: any) => (
            <div key={k} className={`preset ${cap.preset === k ? "on" : ""}`} onClick={() => addOps([{ kind: "settings", params: { patch: { captions: { preset: k, custom: {} } } }, label: `Caption style: ${p.label}` }], "Caption style")}>
              <b style={{ color: p.emphasis ? p.highlight : p.color, textTransform: p.uppercase ? "uppercase" : undefined, fontWeight: p.weight,
                background: p.background ? p.bg_color?.slice(0, 7) : undefined, borderRadius: 4, padding: p.background ? "0 4px" : undefined,
                WebkitTextStroke: p.outline > 4 ? "0.6px #000" : undefined }}>Aa</b>
              <span className="tiny">{p.label}</span>
            </div>
          ))}
        </div>
        <label className="field"><span className="row between"><span>Size</span><span className="mono">{(+v("cap.size", 6)).toFixed(1)}</span></span>
          <input className="range" type="range" min={3} max={11} step={0.1} value={v("cap.size", 6)} onChange={(e) => slide("cap.size", +e.target.value, { captions: { custom: { size: +e.target.value } } }, "Caption size")} /></label>
        <label className="field"><span className="row between"><span>Position</span><span className="mono">{Math.round(v("cap.y", 62))}%</span></span>
          <input className="range" type="range" min={10} max={90} step={1} value={v("cap.y", 62)} onChange={(e) => slide("cap.y", +e.target.value, { captions: { y: +e.target.value } }, "Caption position")} /></label>
        <label className="field"><span className="row between"><span>Outline</span><span className="mono">{v("cap.outline", 6)}</span></span>
          <input className="range" type="range" min={0} max={14} step={1} value={v("cap.outline", 6)} onChange={(e) => slide("cap.outline", +e.target.value, { captions: { custom: { outline: +e.target.value } } }, "Caption outline")} /></label>
        <label className="field"><span className="row between"><span>Words per line</span><span className="mono">{v("cap.words_per_line", 3)}</span></span>
          <input className="range" type="range" min={1} max={7} step={1} value={v("cap.words_per_line", 3)} onChange={(e) => slide("cap.words_per_line", +e.target.value, { captions: { custom: { words_per_line: +e.target.value } } }, "Caption line length")} /></label>
        <div className="row wrap gap-s">
          <label className="row small">Text <input type="color" value={(st.color || "#ffffff").slice(0, 7)} onChange={(e) => patch({ captions: { custom: { color: e.target.value } } }, "Caption color")} /></label>
          <label className="row small">Highlight <input type="color" value={(st.highlight || "#ffd84d").slice(0, 7)} onChange={(e) => patch({ captions: { custom: { highlight: e.target.value } } }, "Highlight color")} /></label>
          <span className={`chip ${st.uppercase ? "on" : ""}`} onClick={() => addOps([{ kind: "settings", params: { patch: { captions: { custom: { uppercase: !st.uppercase } } } }, label: "Caption case" }], "Case")}>ABC</span>
          <span className={`chip ${st.background ? "on" : ""}`} onClick={() => addOps([{ kind: "settings", params: { patch: { captions: { custom: { background: !st.background } } } }, label: "Caption background" }], "Bg")}>Box</span>
          <span className={`chip ${st.emphasis ? "on" : ""}`} onClick={() => addOps([{ kind: "settings", params: { patch: { captions: { custom: { emphasis: !st.emphasis } } } }, label: "Keyword emphasis" }], "Emph")}>Emphasis</span>
          <select className="select" style={{ width: "auto", minHeight: 34, padding: "4px 8px" }} value={st.mode} onChange={(e) => addOps([{ kind: "settings", params: { patch: { captions: { custom: { mode: e.target.value } } } }, label: "Caption mode" }], "Mode")}>
            <option value="phrase">Phrase</option><option value="word">Word-by-word</option><option value="karaoke">Karaoke</option>
          </select>
        </div>
        <div className="row between"><span className="small">Show TikTok safe zones</span><Switch checked={showSafe} onChange={setShowSafe} /></div>
        <div className="tiny faint">Emphasis skips words inside lines flagged by the compliance check.</div>
      </section>
      <section className="col">
        <h3>Cuts</h3>
        <div className="row between"><div><div className="small">Soft cuts</div><div className="tiny faint">A quick, invisible dissolve at each jump cut so it flows instead of snapping</div></div>
          <Switch checked={view.settings.video?.soft_cuts !== false} onChange={(on) => addOps([{ kind: "settings", params: { patch: { video: { soft_cuts: on } } }, label: on ? "Soft cuts on" : "Soft cuts off" }], "Cuts")} /></div>
        <div className="row between"><div><div className="small">Punch-in on jump cuts</div><div className="tiny faint">Alternates an 8% zoom where a retake was removed</div></div>
          <Switch checked={!!view.settings.video?.smooth_cuts} onChange={(on) => addOps([{ kind: "settings", params: { patch: { video: { smooth_cuts: on } } }, label: on ? "Punch-ins on" : "Punch-ins off" }], "Cuts")} /></div>
        <div className="row wrap gap-s">
          <button className="btn sm" onClick={() => onPlan("make_natural")}>More natural pauses</button>
          <button className="btn sm" onClick={() => onPlan("improve_pacing", { level: "fast" })}>Tighter pacing</button>
        </div>
      </section>
      <section className="col">
        <div className="row between"><h3>Audio</h3><Switch checked={!!aud.enhance} onChange={(on) => addOps([{ kind: "settings", params: { patch: { audio: { enhance: on } } }, label: on ? "Audio enhanced" : "Audio enhance off" }], "Audio")} /></div>
        <div className="small muted">Noise reduction · voice EQ · compression · loudness normalize (−14 LUFS) · clipping protection</div>
        <label className="field"><span className="row between"><span>Noise reduction</span><span className="mono">{Math.round(v("aud.denoise", 0.6) * 100)}%</span></span>
          <input className="range" type="range" min={0} max={1} step={0.05} value={v("aud.denoise", 0.6)} onChange={(e) => slide("aud.denoise", +e.target.value, { audio: { denoise: +e.target.value } }, "Noise reduction")} /></label>
        <div className="row between"><span className="small">Preview</span>
          <div className="seg"><button className={!audioAB ? "on" : ""} onClick={() => setAudioAB(false)}>Original</button>
            <button className={audioAB ? "on" : ""} onClick={() => setAudioAB(true)} disabled={!enhancedReady}>Enhanced</button></div></div>
        {aud.enhance && !enhancedReady && <div className="tiny faint row"><div className="spinner" style={{ width: 12, height: 12 }} />Preparing enhanced preview…</div>}
        <div className="row between small"><span>Background music & auto-ducking</span><span className="badge soon">COMING SOON</span></div>
      </section>
      <section className="col">
        <div className="row between"><h3>Color</h3><button className="btn sm ai" onClick={() => onPlan("enhance_video")}><Icon n="wand" />Enhance video</button></div>
        {([["brightness", -0.3, 0.3, 0.01, 0], ["contrast", 0.6, 1.6, 0.01, 1], ["saturation", 0, 2, 0.01, 1], ["temperature", -100, 100, 1, 0], ["sharpen", 0, 1.5, 0.05, 0]] as const).map(([k, mn, mx, stp, d]) => (
          <label key={k} className="field"><span className="row between"><span style={{ textTransform: "capitalize" }}>{k}</span><span className="mono">{(+v(`col.${k}`, d)).toFixed(2)}</span></span>
            <input className="range" type="range" min={mn} max={mx} step={stp} value={v(`col.${k}`, d)} onChange={(e) => slide(`col.${k}`, +e.target.value, { color: { [k]: +e.target.value } }, `Color: ${k}`)} /></label>
        ))}
        <button className="btn sm" onClick={() => addOps([{ kind: "settings", params: { patch: { color: { brightness: 0, contrast: 1, saturation: 1, temperature: 0, sharpen: 0 } } }, label: "Reset color" }], "Color")}>Reset color</button>
        <div className="row between small"><span>Highlights / shadows / skin-tone protection</span><span className="badge soon">COMING SOON</span></div>
      </section>
    </div>
  );
}

function deepMerge(a: any, b: any): any {
  const o = { ...a };
  for (const k of Object.keys(b)) o[k] = b[k] && typeof b[k] === "object" && !Array.isArray(b[k]) ? deepMerge(a[k] || {}, b[k]) : b[k];
  return o;
}

// ---------------------------------------------------------------- Versions
export function VersionsPanel({ project, versionId, onSwitch, onPlan, reload, view }: any) {
  const toast = useToast();
  const [count, setCount] = useState(3);
  const [focus, setFocus] = useState("");
  const rename = async (v: any) => {
    const n = prompt("Rename version", v.name);
    if (n) { await api(`/versions/${v.id}`, { method: "PATCH", body: { name: n } }); reload(); }
  };
  const dup = async (v: any) => { const r = await api<any>(`/versions/${v.id}/duplicate`, { body: {} }); toast("Duplicated"); await reload(); onSwitch(r.id); };
  const del = async (v: any) => {
    if (!confirm(`Delete “${v.name}”? (Source footage is not affected.)`)) return;
    try { await api(`/versions/${v.id}`, { method: "DELETE" }); await reload(); if (v.id === versionId) onSwitch(null); } catch (e: any) { toast(e.message, true); }
  };
  return (
    <div className="pbody col gap-l">
      {view && <BatchAds view={view} onPlan={onPlan} />}
      <section className="card flat col">
        <h3>Generate ad variations</h3>
        <div className="small muted">Different hooks × structures from the same footage. Each becomes its own editable version.</div>
        <div className="row wrap gap-s">
          {[2, 3, 4, 5].map((n) => <span key={n} className={`chip ${count === n ? "on" : ""}`} onClick={() => setCount(n)}>{n}</span>)}
          <select className="select" style={{ width: "auto", minHeight: 34, padding: "4px 8px" }} value={focus} onChange={(e) => setFocus(e.target.value)}>
            <option value="">Mixed</option><option value="price">Price-focused</option><option value="problem">Problem-focused</option>
            <option value="demo">Demo-focused</option><option value="story">Storytime</option><option value="benefit">Benefit-heavy</option>
          </select>
        </div>
        <button className="btn ai" onClick={() => onPlan("generate_variations", { count, focus: focus || null })}><Icon n="layers" />Plan {count} versions</button>

      </section>
      <section>
        <h3 className="mb">Versions</h3>
        {project.versions.map((v: any) => (
          <div key={v.id} className="list-item">
            <button className={`btn sm ${v.id === versionId ? "primary" : ""}`} onClick={() => onSwitch(v.id)}>{v.id === versionId ? "Editing" : "Open"}</button>
            <div className="grow" style={{ minWidth: 0 }}><div className="ellipsis" style={{ fontWeight: 600 }}>{v.name}</div>
              {v.meta?.hook_text && <div className="tiny muted ellipsis">Hook: “{v.meta.hook_text}”</div>}</div>
            <button className="btn ghost sm icon" onClick={() => rename(v)} aria-label="Rename"><Icon n="text" /></button>
            <button className="btn ghost sm icon" onClick={() => dup(v)} aria-label="Duplicate"><Icon n="copy" /></button>
            <button className="btn ghost sm icon" onClick={() => del(v)} aria-label="Delete"><Icon n="trash" /></button>
          </div>
        ))}
      </section>
    </div>
  );
}
