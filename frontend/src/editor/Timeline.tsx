import { useEffect, useMemo, useRef, useState } from "react";
import { fmt } from "../api";
import { Icon, SECTION_COLORS, SECTION_LABELS } from "../ui";

type Props = {
  view: any; time: number; selected: string | null; onSelect: (clipId: string | null) => void; onSeek: (t: number) => void;
  onMoveUnit: (unitId: string, afterUnitId: string | null) => void; tools: any;
  onRemoveBroll?: (id: string) => void; onRemoveOverlay?: (id: string) => void;
};

export function Timeline({ view, time, selected, onSelect, onSeek, onMoveUnit, tools, onRemoveBroll, onRemoveOverlay }: Props) {
  const clips = view.timeline.clips as any[];
  const D = Math.max(view.timeline.duration, 0.1);
  const scroll = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const [pps, setPps] = useState<number | null>(null);
  const [drag, setDrag] = useState<{ unit: string; x: number; drop: number | null } | null>(null);
  const down = useRef<any>(null);

  useEffect(() => {
    if (pps == null && scroll.current) setPps(Math.min(160, Math.max(14, (scroll.current.clientWidth - 30) / D)));
  }, [D, pps]);
  const k = pps ?? 30;
  const W = D * k;

  // keep playhead visible while playing
  useEffect(() => {
    const el = scroll.current;
    if (!el) return;
    const x = time * k;
    if (x < el.scrollLeft + 20 || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = Math.max(0, x - el.clientWidth / 3);
  }, [Math.floor(time * k / 60)]);

  const units = useMemo(() => {
    const out: { id: string; t0: number; t1: number }[] = [];
    for (const c of clips) {
      const last = out[out.length - 1];
      if (last && last.id === c.unit_id) last.t1 = c.t1; else out.push({ id: c.unit_id, t0: c.t0, t1: c.t1 });
    }
    return out;
  }, [clips]);

  const xToT = (clientX: number) => {
    const r = inner.current!.getBoundingClientRect();
    return Math.max(0, Math.min(D, (clientX - r.left) / k));
  };
  const dropIndex = (t: number, unit: string) => {
    const others = units.filter((u) => u.id !== unit);
    let i = 0;
    while (i < others.length && (others[i].t0 + others[i].t1) / 2 < t) i++;
    return i;
  };

  const onDown = (e: React.PointerEvent, c: any) => {
    down.current = { x: e.clientX, y: e.clientY, clip: c, id: e.pointerId, touch: e.pointerType === "touch", selected: selected === c.id };
  };
  const onMove = (e: React.PointerEvent) => {
    const d = down.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    if (!drag && Math.abs(dx) > 10 && (!d.touch || d.selected)) {
      (e.target as HTMLElement).setPointerCapture?.(d.id);
      setDrag({ unit: d.clip.unit_id, x: e.clientX, drop: null });
    }
    if (drag) setDrag({ ...drag, x: e.clientX, drop: dropIndex(xToT(e.clientX), drag.unit) });
  };
  const onUp = (e: React.PointerEvent) => {
    const d = down.current;
    down.current = null;
    if (drag) {
      if (drag.drop != null) {
        const others = units.filter((u) => u.id !== drag.unit);
        const after = drag.drop === 0 ? null : others[drag.drop - 1].id;
        const curIdx = units.findIndex((u) => u.id === drag.unit);
        const curAfter = curIdx > 0 ? units[curIdx - 1].id : null;
        if (after !== curAfter) onMoveUnit(drag.unit, after);
      }
      setDrag(null);
      return;
    }
    if (d && Math.abs(e.clientX - d.x) < 10 && Math.abs(e.clientY - d.y) < 10) {
      onSelect(d.clip.id);
      onSeek(Math.max(d.clip.t0, Math.min(xToT(e.clientX), d.clip.t1 - 0.01)));
    }
  };

  const env = (c: any) => {
    const m = view.media.find((m: any) => m.id === c.media_id);
    const e: number[] = m?.envelope || [];
    if (!e.length) return null;
    const a = Math.floor(c.s * 10), b = Math.max(a + 1, Math.ceil(c.e * 10));
    const pts = e.slice(a, b);
    if (pts.length < 2) return null;
    const d = pts.map((v, i) => `${(i / (pts.length - 1)) * 100},${22 - v * 20}`).join(" ");
    return <svg className="wave" viewBox="0 0 100 22" preserveAspectRatio="none"><polyline points={d} fill="none" stroke="#fff" strokeWidth="1" vectorEffect="non-scaling-stroke" /></svg>;
  };

  const step = k > 80 ? 1 : k > 30 ? 2 : k > 12 ? 5 : 10;
  const ticks = [];
  for (let t = 0; t <= D; t += step) ticks.push(t);
  const dropX = drag?.drop != null ? (() => {
    const others = units.filter((u) => u.id !== drag.unit);
    return drag.drop === 0 ? 0 : others[drag.drop - 1].t1 * k;
  })() : null;

  return (
    <div className="tl">
      <div className="tl-tools">
        <span className="small mono" style={{ minWidth: 88 }}>{fmt(time)} / {fmt(D)}</span>
        <button className="btn ghost sm icon" onClick={() => setPps(Math.max(6, k / 1.5))} aria-label="Zoom out"><Icon n="zoomout" /></button>
        <button className="btn ghost sm icon" onClick={() => setPps(Math.min(400, k * 1.5))} aria-label="Zoom in"><Icon n="zoomin" /></button>
        <span style={{ width: 1, height: 22, background: "var(--border)" }} />
        {tools}
      </div>
      <div className="tl-scroll" ref={scroll}>
        <div className="tl-inner" ref={inner} style={{ width: W + 24 }} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={() => { setDrag(null); down.current = null; }}>
          <div className="tl-ruler" onClick={(e) => onSeek(xToT(e.clientX))}>
            {ticks.map((t) => <span key={t} style={{ left: t * k }}>{t >= 60 ? `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}` : `${t}s`}</span>)}
          </div>
          <div className="tl-row tl-sec">
            {view.sections.map((s: any, i: number) => (
              <div key={i} style={{ left: s.t0 * k, width: Math.max(2, (s.t1 - s.t0) * k - 2), background: SECTION_COLORS[s.section] }} title={`${s.label} ${fmt(s.t0)}–${fmt(s.t1)}`}>
                {(s.t1 - s.t0) * k > 34 ? SECTION_LABELS[s.section] || s.label : ""}
              </div>
            ))}
          </div>
          <div className="tl-row tl-clips">
            {clips.map((c) => {
              const fx = [c.speed !== 1 && `${c.speed}×`, c.props?.zoom > 1 && "Z", c.props?.mute && "M", c.props?.rotate && "R"].filter(Boolean).join(" ");
              return (
                <div key={c.id} className={`clip ${selected === c.id ? "sel" : ""} ${drag?.unit === c.unit_id ? "dragging" : ""}`}
                  style={{ left: c.t0 * k, width: Math.max(3, (c.t1 - c.t0) * k - 2) }} onPointerDown={(e) => onDown(e, c)}>
                  <div className="bar" style={{ background: SECTION_COLORS[c.section] }} />
                  {(c.t1 - c.t0) * k > 40 && <div className="txt">{clipText(view, c)}</div>}
                  {env(c)}
                  {fx && <span className="fx">{fx}</span>}
                </div>
              );
            })}
            {dropX != null && <div className="drop-ind" style={{ left: dropX - 1 }} />}
          </div>
          {(view.brolls?.length > 0 || view.overlays?.length > 0) && (
            <div className="tl-row" style={{ height: 18 }}>
              {(view.brolls || []).map((b: any) => (
                <div key={b.id} title={`B-roll: ${b.label} — tap to remove`} onClick={() => onRemoveBroll?.(b.id)}
                  style={{ position: "absolute", top: 1, left: b.t0 * k, width: Math.max(4, (b.t1 - b.t0) * k), height: 16, borderRadius: 5, cursor: "pointer",
                    background: "rgba(61,219,110,.85)", color: "#062", fontSize: 9, fontWeight: 800, padding: "1px 4px", overflow: "hidden", whiteSpace: "nowrap" }}>B-ROLL</div>
              ))}
              {(view.overlays || []).map((o: any) => (
                <div key={o.id} title={`Text: ${o.text} — tap to remove`} onClick={() => onRemoveOverlay?.(o.id)}
                  style={{ position: "absolute", top: 1, left: o.t0 * k, width: Math.max(4, (o.t1 - o.t0) * k), height: 16, borderRadius: 5, cursor: "pointer",
                    background: "#fff", color: "#111", fontSize: 9, fontWeight: 800, padding: "1px 4px", overflow: "hidden", whiteSpace: "nowrap" }}>T {o.text}</div>
              ))}
            </div>
          )}
          <div className="tl-row tl-caps">{view.settings.captions?.enabled !== false && view.captions.map((l: any, i: number) => <div key={i} style={{ left: l.t0 * k, width: Math.max(2, (l.t1 - l.t0) * k - 1) }} />)}</div>
          <div className="tl-row tl-prod" title="Product on screen">{view.visibility.segments.map(([a, b]: number[], i: number) => <div key={i} style={{ left: a * k, width: Math.max(2, (b - a) * k) }} />)}</div>
          <div className="playhead" style={{ left: time * k }} />
        </div>
      </div>
    </div>
  );
}

function clipText(view: any, c: any) {
  const ws = view.words.filter((w: any) => w.media_id === c.media_id && w.kept && (w.s + w.e) / 2 >= c.s && (w.s + w.e) / 2 < c.e);
  if (!ws.length) return <i className="faint">no speech</i>;
  return ws.map((w: any) => w.t).join(" ");
}
