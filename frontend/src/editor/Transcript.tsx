import { useMemo, useState } from "react";
import { Icon, SECTION_COLORS, SECTION_LABELS } from "../ui";

type Props = {
  view: any; time: number; onSeek: (t: number) => void; addOps: (ops: any[], label: string) => void; onPlan: (action: string, args?: any) => void;
  onOverrideSection: (sid: string, section: string) => void;
};

/** Edit video by editing text: deleting words removes that footage, restoring brings it back. Source order, nothing is lost. */
export function Transcript({ view, time, onSeek, addOps, onPlan, onOverrideSection }: Props) {
  const [sel, setSel] = useState<{ a: number; b: number } | null>(null);
  const [q, setQ] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const words = view.words as any[];
  const order = useMemo(() => {
    const mediaOrder: Record<string, number> = {};
    view.media.forEach((m: any, i: number) => (mediaOrder[m.id] = i));
    return [...words].sort((x, y) => mediaOrder[x.media_id] - mediaOrder[y.media_id] || x.s - y.s);
  }, [words]);
  const index = useMemo(() => Object.fromEntries(order.map((w, i) => [w.key, i])), [order]);
  const sentences = view.sentences.filter((s: any) => s.speech);
  const qn = q.trim().toLowerCase();
  const hits = qn ? order.filter((w) => w.t.toLowerCase().replace(/[^\w$%']/g, "").includes(qn.replace(/[^\w$%']/g, ""))) : [];
  const nowKey = useMemo(() => {
    let best: any = null;
    for (const w of order) if (w.kept && w.tl != null && w.tl <= time + 0.02) { if (!best || w.tl > best.tl) best = w; }
    return best?.key;
  }, [order, Math.round(time * 10)]);

  const click = (w: any, e: React.MouseEvent) => {
    const i = index[w.key];
    if (e.shiftKey && sel) { setSel({ a: Math.min(sel.a, i), b: Math.max(sel.a, i) }); return; }
    if (sel && sel.a === sel.b && sel.a !== i && Math.abs(sel.a - i) < 400) { setSel({ a: Math.min(sel.a, i), b: Math.max(sel.a, i) }); return; }
    setSel({ a: i, b: i });
    if (w.kept && w.tl != null) onSeek(w.tl);
  };

  const ranges = (ws: any[], pad: number) => {
    const out: any[] = [];
    let cur: any = null;
    for (const w of ws) {
      if (cur && cur[0] === w.media_id && w.s - cur[2] < 1.5) cur[2] = w.e + pad;
      else { cur = [w.media_id, Math.max(0, w.s - pad), w.e + pad]; out.push(cur); }
    }
    return out.map((r) => [r[0], +r[1].toFixed(3), +r[2].toFixed(3)]);
  };
  const selWords = sel ? order.slice(sel.a, sel.b + 1) : [];
  const del = () => { addOps([{ kind: "remove", params: { ranges: ranges(selWords.filter((w) => w.kept), 0.04), reason: "transcript" }, label: `Deleted “${selWords.map((w) => w.t).join(" ").slice(0, 40)}”` }], "Delete text"); setSel(null); };
  const restore = () => { addOps([{ kind: "restore", params: { ranges: ranges(selWords, 0.08) }, label: `Restored “${selWords.map((w) => w.t).join(" ").slice(0, 40)}”` }], "Restore text"); setSel(null); };

  const unitFor = (sid: string) => view.timeline.units.find((u: any) => u.origin === sid);
  const cutCount = words.filter((w) => !w.kept).length;
  const fillersLeft = words.filter((w) => w.kept && w.filler).length;

  if (!words.length) {
    const warn = view.media.find((m: any) => m.warning)?.warning;
    return <div className="pbody"><div className="empty small">{warn || "No speech transcribed yet."}</div></div>;
  }
  return (
    <div className="pbody transcript" style={{ paddingBottom: 0 }}>
      <div className="row mb">
        <div className="grow" style={{ position: "relative" }}>
          <input className="input" style={{ minHeight: 38, paddingLeft: 34 }} placeholder="Search transcript" value={q} onChange={(e) => setQ(e.target.value)} />
          <span style={{ position: "absolute", left: 10, top: 10, color: "var(--faint)" }}><Icon n="search" size={17} /></span>
        </div>
        {qn && <span className="small muted">{hits.length}</span>}
      </div>
      <div className="row wrap gap-s mb">
        <button className="chip ai" onClick={() => onPlan("remove_fillers")} disabled={!fillersLeft}><Icon n="broom" />Remove all fillers{fillersLeft ? ` (${fillersLeft})` : ""}</button>
        <span className="tiny faint">{cutCount} words cut · tap a word to jump · tap two words to select</span>
      </div>
      {sentences.map((s: any) => {
        const ws = order.filter((w) => w.media_id === s.media_id && w.s >= s.s - 0.001 && w.s < s.e);
        if (!ws.length) return null;
        const allCut = ws.every((w) => !w.kept);
        const u = unitFor(s.id);
        return (
          <div key={s.id} className="sent" style={{ borderLeftColor: SECTION_COLORS[s.section], opacity: allCut ? 0.6 : 1 }}>
            <div className="row gap-s" style={{ marginBottom: 2 }}>
              <button className="badge" style={{ background: "transparent", color: SECTION_COLORS[s.section], border: 0, padding: 0, cursor: "pointer" }}
                onClick={() => setMenu(menu === s.id ? null : s.id)}>{(SECTION_LABELS[s.section] || s.section).toUpperCase()} ▾</button>
              {s.hook_score >= 45 && <span className="badge ember">hook {s.hook_score}</span>}
              {s.visible && <span className="badge ok">product</span>}
              <span className="grow" />
              {allCut ? <button className="btn ghost sm" onClick={() => addOps([{ kind: "restore", params: { ranges: [[s.media_id, s.s, s.e]] }, label: "Restored line" }], "Restore line")}>Restore</button>
                : u && <button className="btn ghost sm" onClick={() => addOps([{ kind: "move", params: { unit_id: u.id, after: null }, label: "Moved line to start" }], "Move")}>Move to start</button>}
            </div>
            {menu === s.id && (
              <div className="row wrap gap-s mb">
                {Object.keys(SECTION_LABELS).filter((k) => k !== "broll").map((k) => (
                  <span key={k} className="chip" style={{ minHeight: 28, borderColor: SECTION_COLORS[k] }} onClick={() => { onOverrideSection(s.id, k); setMenu(null); }}>{SECTION_LABELS[k]}</span>
                ))}
              </div>
            )}
            <div>
              {ws.map((w) => {
                const i = index[w.key];
                const cls = ["w", !w.kept && "cut", w.filler && w.kept && "filler", sel && i >= sel.a && i <= sel.b && "sel", w.key === nowKey && "now",
                  qn && hits.includes(w) && "hit"].filter(Boolean).join(" ");
                return <span key={w.key} className={cls} onClick={(e) => click(w, e)} title={w.by ? `removed by ${w.by}` : undefined}>{w.t} </span>;
              })}
            </div>
          </div>
        );
      })}
      <div style={{ height: 70 }} />
      {sel && (
        <div className="sel-bar">
          <span className="small grow ellipsis">{selWords.length} word{selWords.length > 1 ? "s" : ""}</span>
          {selWords.some((w) => w.kept) && <button className="btn sm danger" onClick={del}><Icon n="trash" />Delete</button>}
          {selWords.some((w) => !w.kept) && <button className="btn sm" onClick={restore}><Icon n="undo" />Restore</button>}
          <button className="btn ghost sm icon" onClick={() => setSel(null)} aria-label="Clear"><Icon n="close" /></button>
        </div>
      )}
    </div>
  );
}
