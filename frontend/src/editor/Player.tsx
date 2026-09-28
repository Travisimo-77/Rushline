import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

export type Seg = { media_id: string; s: number; e: number; t0: number; t1: number; speed: number; props?: any; id?: string };
export type PlayerHandle = { play: () => void; pause: () => void; toggle: () => void; seek: (t: number) => void; playing: () => boolean };

type Props = {
  segs: Seg[]; media: Record<string, any>; useEnhanced: boolean; onTime: (t: number) => void; onPlaying: (p: boolean) => void;
  captions: any[]; style: any; overlays: any[]; color: any; aspect: string; showSafe: boolean; time: number; tag?: string; children?: any; soft?: boolean; brolls?: any[];
};

/**
 * EDL player: plays a list of source segments from lightweight H.264 proxies as one continuous video, without
 * rendering anything. Two <video> elements are double-buffered: while one plays, the other is already loaded and
 * parked on the first frame of the next cut, so cuts swap instantly instead of stalling on a seek.
 * (Both elements are unlocked on the first tap, which iPhone Safari requires for programmatic play.)
 */
export const Player = forwardRef<PlayerHandle, Props>(function Player(p, ref) {
  const va = useRef<HTMLVideoElement>(null);
  const vb = useRef<HTMLVideoElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const active = useRef(0); // 0 → va, 1 → vb
  const [shown, setShown] = useState(0);
  const segOf = useRef<(number | null)[]>([null, null]);
  const [, force] = useState(0);
  const idx = useRef(0);
  const playing = useRef(false);
  const unlocked = useRef(false);
  const raf = useRef(0);
  const segsRef = useRef(p.segs);
  const [fh, setFh] = useState(600);
  segsRef.current = p.segs;

  const el = (k: number) => (k === 0 ? va.current : vb.current);
  const srcFor = (mid: string) => {
    const m = p.media[mid];
    if (!m) return "";
    return (p.useEnhanced && m.enhanced_url) || m.proxy_url || "";
  };
  const contiguous = (a: Seg, b: Seg) => a.media_id === b.media_id && Math.abs(b.s - a.e) < 0.04 && a.speed === b.speed &&
    (a.props?.zoom || 1) === (b.props?.zoom || 1) && (a.props?.rotate || 0) === (b.props?.rotate || 0);

  /** Load segment i into element k at source time `local`. */
  const load = (k: number, i: number, local: number, then?: () => void) => {
    const v = el(k);
    const seg = segsRef.current[i];
    if (!v || !seg) return;
    segOf.current[k] = i;
    force((x) => x + 1);
    const src = srcFor(seg.media_id);
    const apply = () => {
      try { v.currentTime = Math.max(0, local); } catch { /* not ready yet */ }
      v.playbackRate = seg.speed || 1;
      then?.();
    };
    if (src && v.getAttribute("data-src") !== src) {
      v.setAttribute("data-src", src);
      v.src = src;
      v.addEventListener("loadedmetadata", apply, { once: true });
      v.load();
    } else apply();
  };

  /** Park the idle element on the next non-contiguous segment. */
  const preloadNext = () => {
    const segs = segsRef.current;
    const i = idx.current;
    const n = i + 1;
    if (n >= segs.length || contiguous(segs[i], segs[n])) return;
    const idle = 1 - active.current;
    if (segOf.current[idle] === n) return;
    load(idle, n, segs[n].s);
  };

  const show = (k: number) => { active.current = k; setShown(k); };

  const seek = (t: number) => {
    const segs = segsRef.current;
    if (!segs.length) return;
    let i = segs.findIndex((s) => t >= s.t0 && t < s.t1);
    if (i < 0) i = t <= 0 ? 0 : segs.length - 1;
    const s = segs[i];
    const tt = Math.min(Math.max(t, s.t0), s.t1 - 0.001);
    idx.current = i;
    load(active.current, i, s.s + (tt - s.t0) * s.speed, preloadNext);
    p.onTime(tt);
  };

  const advance = () => {
    const segs = segsRef.current;
    const cur = segs[idx.current];
    const nxt = idx.current + 1;
    if (nxt >= segs.length) { pause(); p.onTime(segs[segs.length - 1].t1); return false; }
    const n = segs[nxt];
    idx.current = nxt;
    if (contiguous(cur, n)) return true;
    const idle = 1 - active.current;
    const iv = el(idle);
    const old = el(active.current);
    if (iv && segOf.current[idle] === nxt && iv.readyState >= 2 && Math.abs(iv.currentTime - n.s) < 0.15) {
      // instant swap to the pre-loaded cut
      iv.playbackRate = n.speed || 1;
      iv.play().catch(() => {});
      show(idle);
      // soft cuts: let the outgoing shot fade out under the incoming one (matches the export's quick dissolve)
      if (p.soft) setTimeout(() => { if (el(active.current) !== old) old?.pause(); }, 160); else old?.pause();
    } else {
      load(active.current, nxt, n.s, () => { if (playing.current) old?.play().catch(() => {}); });
    }
    setTimeout(preloadNext, 30);
    return true;
  };

  const tick = () => {
    const v = el(active.current);
    const segs = segsRef.current;
    if (!v || !playing.current) return;
    const seg = segs[idx.current];
    if (seg) {
      const ct = v.currentTime;
      if (ct >= seg.e - 0.02 || v.ended) {
        if (!advance()) return;
      } else if (ct < seg.s - 0.25) {
        load(active.current, idx.current, seg.s);
      }
      const cur = segs[idx.current];
      const cv = el(active.current);
      if (cur && cv) p.onTime(cur.t0 + (Math.max(cv.currentTime, cur.s) - cur.s) / cur.speed);
    }
    raf.current = requestAnimationFrame(tick);
  };

  const play = () => {
    const segs = segsRef.current;
    const v = el(active.current);
    if (!v || !segs.length) return;
    if (!unlocked.current) {
      // iPhone: unlock the idle element inside this user gesture so later swaps can autoplay
      unlocked.current = true;
      const idle = el(1 - active.current);
      if (idle) { idle.muted = true; idle.play().then(() => { idle.pause(); idle.muted = false; }).catch(() => { idle.muted = false; }); }
    }
    const seg = segs[idx.current];
    if (seg && idx.current >= segs.length - 1 && v.currentTime >= seg.e - 0.04) seek(0);
    playing.current = true;
    p.onPlaying(true);
    el(active.current)!.play().catch(() => { playing.current = false; p.onPlaying(false); });
    preloadNext();
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(tick);
  };
  const pause = () => {
    playing.current = false;
    p.onPlaying(false);
    va.current?.pause(); vb.current?.pause();
    cancelAnimationFrame(raf.current);
  };
  useImperativeHandle(ref, () => ({ play, pause, seek, toggle: () => (playing.current ? pause() : play()), playing: () => playing.current }));

  // re-place when the edit changes (keeps the playhead at the same timeline time)
  const segKey = p.segs.map((s) => `${s.media_id}${s.s}${s.e}${s.speed}${s.props?.zoom || 1}`).join("|");
  useEffect(() => { if (!playing.current) { segOf.current = [null, null]; seek(Math.min(p.time, p.segs.length ? p.segs[p.segs.length - 1].t1 - 0.01 : 0)); } }, [segKey, p.useEnhanced]);
  useEffect(() => () => cancelAnimationFrame(raf.current), []);
  useLayoutEffect(() => {
    if (!frame.current) return;
    const ro = new ResizeObserver(() => setFh(frame.current!.clientHeight));
    ro.observe(frame.current);
    return () => ro.disconnect();
  }, []);

  // ---- captions (same layout the renderer burns in)
  const st = p.style || {};
  const line = st.enabled === false ? null : p.captions.find((l) => p.time >= l.t0 && p.time < l.t1);
  const px = (st.size || 6) / 100 * fh;
  const o = ((st.outline ?? 6) * fh) / 1920;
  const shadowParts: string[] = [];
  if (o > 0 && !st.background) for (let a = 0; a < 16; a++) shadowParts.push(`${(Math.cos((a * Math.PI) / 8) * o).toFixed(1)}px ${(Math.sin((a * Math.PI) / 8) * o).toFixed(1)}px 0 #000`);
  if (st.shadow) shadowParts.push(`0 ${((st.shadow * fh) / 1920 * 2).toFixed(1)}px ${((st.shadow * fh) / 1920 * 3).toFixed(1)}px rgba(0,0,0,.7)`);
  const vstyle = (k: number) => {
    const sg = segOf.current[k] != null ? p.segs[segOf.current[k] as number] : undefined;
    return { filter, transform: `scale(${sg?.props?.zoom || 1}) rotate(${sg?.props?.rotate || 0}deg)`, opacity: shown === k ? 1 : 0,
      transition: p.soft ? "opacity 0.14s linear" : undefined, zIndex: shown === k ? 1 : 0 };
  };
  const c = p.color || {};
  const filter = `brightness(${(1 + (c.brightness || 0) * 1.6).toFixed(3)}) contrast(${c.contrast ?? 1}) saturate(${c.saturation ?? 1})` +
    (c.temperature ? ` sepia(${Math.max(0, c.temperature) / 250}) hue-rotate(${Math.min(0, c.temperature) / 6}deg)` : "");
  const aspectCls = p.aspect === "1:1" ? "a11" : p.aspect === "16:9" ? "a169" : "";
  return (
    <div className={`frame ${aspectCls}`} ref={frame} onClick={() => (playing.current ? pause() : play())}>
      <video ref={va} playsInline preload="auto" style={vstyle(0)} {...({ "webkit-playsinline": "true" } as any)} />
      <video ref={vb} playsInline preload="auto" style={vstyle(1)} {...({ "webkit-playsinline": "true" } as any)} />
      {p.tag && <span className="badge mode-tag" style={{ background: "rgba(0,0,0,.6)", color: "#fff" }}>{p.tag}</span>}
      {line && (
        <div className="cap" style={{ top: `${st.y ?? 62}%`, fontSize: px, fontWeight: st.weight || 800, color: st.color || "#fff", textShadow: shadowParts.join(",") }}>
          <span style={st.background ? { background: hexA(st.bg_color || "#000000B0"), padding: `${px * 0.12}px ${px * 0.3}px`, borderRadius: px * 0.25, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" } : undefined}>
            {line.words.map((w: any, i: number) => {
              const active = st.mode === "karaoke" && p.time >= w.t0 && (i === line.words.length - 1 || p.time < line.words[i + 1].t0);
              const hi = active || w.emph;
              return <span key={i} className="w" style={{ color: hi ? st.highlight : undefined, transform: w.emph && !active ? `scale(${st.emph_scale || 1.12})` : undefined }}>{w.text}</span>;
            })}
          </span>
        </div>
      )}
      {(p.brolls || []).filter((b) => p.time >= b.t0 && p.time < b.t1).map((b) => (
        <div key={b.id} style={{ position: "absolute", inset: 0, zIndex: 2, background: `#000 center/cover no-repeat url(${b.thumb_url})` }}>
          <span className="badge" style={{ position: "absolute", right: 8, top: 8, background: "rgba(0,0,0,.6)", color: "#fff" }}>B-ROLL · {b.label}</span>
        </div>
      ))}
      {p.overlays.filter((ov) => p.time >= ov.t0 && p.time < ov.t1).map((ov) => ov.style === "hook" ? (
        <div key={ov.id} style={{ position: "absolute", left: "8%", right: "8%", top: `${ov.y ?? 16}%`, transform: "translateY(-50%)", textAlign: "center", zIndex: 4 }}>
          <span style={{ background: "#fff", color: "#111", fontFamily: "Poppins", fontWeight: 800, fontSize: fh * 0.036, lineHeight: 1.25,
            padding: `${fh * 0.006}px ${fh * 0.012}px`, borderRadius: fh * 0.008, boxDecorationBreak: "clone", WebkitBoxDecorationBreak: "clone" }}>{ov.text}</span>
        </div>
      ) : (
        <div key={ov.id} className="ovl" style={{ top: `${ov.y ?? 20}%`, fontSize: px * 0.8 }}>{ov.text}</div>
      ))}
      {p.showSafe && p.aspect === "9:16" && (
        <div className="safe">
          <div style={{ left: 0, right: 0, top: 0, height: "11%" }}>Top navigation</div>
          <div style={{ right: 0, top: "38%", width: "15%", height: "45%" }}>Like · Comment · Share</div>
          <div style={{ left: 0, right: "15%", bottom: 0, height: "22%" }}>Username · caption · Shop button</div>
        </div>
      )}
      {p.children}
    </div>
  );
});

function hexA(h: string) {
  const x = h.replace("#", "");
  const r = parseInt(x.slice(0, 2), 16), g = parseInt(x.slice(2, 4), 16), b = parseInt(x.slice(4, 6), 16);
  const a = x.length >= 8 ? parseInt(x.slice(6, 8), 16) / 255 : 1;
  return `rgba(${r},${g},${b},${a.toFixed(2)})`;
}
