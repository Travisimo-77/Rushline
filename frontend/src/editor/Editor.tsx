import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fmt } from "../api";
import { go } from "../app";
import { Icon, Sheet, Spinner, useToast } from "../ui";
import { ExportSheet } from "./ExportSheet";
import { AssistantPanel, HistoryPanel, InsightsPanel, StylePanel, VersionsPanel } from "./Panels";
import { Menu } from "./Menu";
import { PlanCard } from "./PlanCard";
import { Player, PlayerHandle, Seg } from "./Player";
import { Timeline } from "./Timeline";
import { Transcript } from "./Transcript";

type Q = [string, string, string, any?];
const QUICK_GROUPS: [string, string, Q[]][] = [
  ["Clean", "broom", [["remove_dead_space", "clock", "Remove dead space"], ["remove_retakes", "refresh", "Remove retakes"],
    ["remove_fillers", "broom", "Remove filler words"], ["improve_pacing", "zoomin", "Tighten pacing", { level: "fast" }]]],
  ["Structure", "hook", [["find_best_hook", "hook", "Find best hook"], ["tiktok_shop_optimize", "bag", "TikTok Shop optimize"],
    ["show_product_earlier", "eye", "Show product earlier", { within: 3 }], ["shorten_video", "scissors", "Shorten video"]]],
  ["Add", "plus", [["add_text_hook", "text", "Text hook"], ["add_broll", "film", "B-roll"], ["add_captions", "text", "Captions"]]],
  ["Generate", "layers", [["generate_variations", "layers", "Variations (3)", { count: 3 }], ["batch_ads", "layers", "Ads from pieces (6)", { count: 6 }]]],
  ["Enhance", "mic", [["enhance_video", "eye", "Auto color & sharpen"], ["enhance_audio", "mic", "Re-apply audio cleanup"]]],
];
const QUICK: Q[] = [["ai_edit", "spark", "AI Edit"], ...QUICK_GROUPS.flatMap((g) => g[2])];
const TABS = [["ai", "chat", "AI"], ["insights", "insights", "Insights"], ["style", "style", "Style"], ["versions", "versions", "Versions"]];

export function Editor({ projectId, versionParam }: { projectId: string; versionParam: string | null }) {
  const toast = useToast();
  const [project, setProject] = useState<any>(null);
  const [view, setView] = useState<any>(null);
  const [vid, setVid] = useState<string | null>(versionParam);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [original, setOriginal] = useState(false);
  const [final, setFinal] = useState(false); // play a real rendered preview of the edit (exactly like the export)
  const finalVid = useRef<HTMLVideoElement>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [tab, setTab] = useState("ai");
  const [mobile, setMobile] = useState<string | null>(null);
  const [plan, setPlan] = useState<any>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [showSafe, setShowSafe] = useState(false);
  const [audioAB, setAudioAB] = useState(false);
  const [chat, setChat] = useState<any[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const player = useRef<PlayerHandle>(null);
  const lastStatuses = useRef("");

  const loadProject = useCallback(async () => {
    const p = await api<any>(`/projects/${projectId}`);
    setProject(p);
    return p;
  }, [projectId]);
  const loadView = useCallback(async (v: string) => { const r = await api<any>(`/versions/${v}`); setView(r); return r; }, []);

  useEffect(() => {
    loadProject().then((p) => { const v = vid && p.versions.some((x: any) => x.id === vid) ? vid : p.active_version_id; setVid(v); return loadView(v); })
      .catch((e) => { toast(e.message, true); go("/projects"); });
  }, [projectId]);

  // poll while footage is processing / first pass running
  const processing = !!project && (project.jobs.length > 0 || project.status === "processing");
  useEffect(() => {
    if (!processing || !vid) return;
    const t = setInterval(async () => {
      const p = await loadProject().catch(() => null);
      if (!p) return;
      const key = JSON.stringify(p.jobs.map((j: any) => j.id)) + p.status + p.versions.length;
      if (key !== lastStatuses.current) { lastStatuses.current = key; loadView(vid); }
    }, 2000);
    return () => clearInterval(t);
  }, [processing, vid]);
  // refresh once more when enhanced-audio previews finish
  useEffect(() => {
    if (!view || !vid) return;
    if (view.settings.audio?.enhance && view.media.some((m: any) => m.has_audio && !m.enhanced_url)) {
      const t = setTimeout(() => loadView(vid), 4000);
      return () => clearTimeout(t);
    }
  }, [view]);

  // Final-cut preview: render (fast, 540p) whenever the edit changes while this mode is on, then play the file
  useEffect(() => {
    if (!final || !vid || !view) return;
    if (view.preview?.url) return;
    let stop = false;
    (async () => {
      try { if (!view.preview?.job) await api(`/versions/${vid}/preview`, { body: {} }); } catch (e: any) { toast(e.message, true); setFinal(false); return; }
      while (!stop) {
        await new Promise((r) => setTimeout(r, 1500));
        const v = await api<any>(`/versions/${vid}`).catch(() => null);
        if (stop || !v) return;
        setView(v);
        if (v.preview?.url) return;
        if (!v.preview?.job) { await api(`/versions/${vid}/preview`, { body: {} }).catch(() => {}); }
      }
    })();
    return () => { stop = true; };
  }, [final, vid, view?.preview?.hash, !!view?.preview?.url]);

  const switchVersion = async (v: string | null) => {
    const p = await loadProject();
    const nv = v || p.active_version_id;
    await api(`/projects/${projectId}`, { method: "PATCH", body: { active_version_id: nv } });
    setVid(nv); setSel(null); setTime(0); setChat([]);
    await loadView(nv);
    history.replaceState(null, "", `#/edit/${projectId}?v=${nv}`);
  };

  const addOps = async (ops: any[], label: string) => {
    if (!vid) return;
    setSaving(true);
    try { const r = await api<any>(`/versions/${vid}/ops`, { body: { ops, label } }); setView(r.view); }
    catch (e: any) { toast(e.message, true); } finally { setSaving(false); }
  };
  const runPlan = async (action: string, args: any = {}) => {
    if (!vid) return;
    setPlanBusy(true);
    setPlan({ loading: true, title: QUICK.find((q) => q[0] === action)?.[2] || action });
    try { setPlan(await api(`/versions/${vid}/plan`, { body: { action, args } })); }
    catch (e: any) { toast(e.message, true); setPlan(null); } finally { setPlanBusy(false); }
  };
  const applyPlan = async (steps: any[], variations: any[] | null) => {
    if (!vid) return;
    setPlanBusy(true);
    try {
      const r = await api<any>(`/versions/${vid}/apply`, { body: { steps, variations, title: plan.title } });
      setView(r.view);
      if (r.versions?.length) { await loadProject(); toast(`${r.versions.length} versions created`); setTab("versions"); setMobile((m) => (m ? "versions" : m)); }
      else toast(`Applied: ${plan.title}`);
      setPlan(null);
    } catch (e: any) { toast(e.message, true); } finally { setPlanBusy(false); }
  };
  const onApplied = (r: any) => { setView(r.view); if (r.versions?.length) loadProject(); };

  // ---------------------------------------------------------------- derived
  const media = useMemo(() => Object.fromEntries((view?.media || []).map((m: any) => [m.id, m])), [view]);
  const segs: Seg[] = useMemo(() => {
    if (!view) return [];
    if (!original) return view.timeline.clips;
    let t = 0;
    return view.media.filter((m: any) => m.status === "ready").map((m: any) => { const s = { media_id: m.id, s: 0, e: m.duration, t0: t, t1: t + m.duration, speed: 1 }; t += m.duration; return s; });
  }, [view, original]);
  const clip = view?.timeline.clips.find((c: any) => c.id === sel);
  const srcAt = (c: any) => c.s + (Math.min(Math.max(time, c.t0), c.t1) - c.t0) * c.speed;

  // ---------------------------------------------------------------- clip tools
  const snapToGap = (mid: string, t: number) => {
    // never split inside a word: snap to the nearest silence between words (within 0.4s)
    const ws = view.words.filter((w: any) => w.media_id === mid);
    const inside = ws.find((w: any) => t > w.s + 0.02 && t < w.e - 0.02);
    if (!inside) return t;
    const before = inside.s - 0.01, after = inside.e + 0.01;
    return Math.abs(t - before) < Math.abs(after - t) ? before : after;
  };
  const tools = clip ? (() => {
    const t = srcAt(clip);
    const units = view.timeline.clips.reduce((a: string[], c: any) => (a[a.length - 1] === c.unit_id ? a : [...a, c.unit_id]), []);
    const ui = units.indexOf(clip.unit_id);
    const isDup = clip.unit_id.includes("+");
    const P = clip.props || {};
    const del = () => { addOps([isDup ? { kind: "drop", params: { unit_id: clip.unit_id }, label: "Deleted clip copy" } : { kind: "remove", params: { ranges: [[clip.media_id, clip.s, clip.e]], reason: "manual" }, label: "Deleted clip" }], "Delete"); setSel(null); };
    return (<>
      <button className="btn sm" onClick={() => addOps([{ kind: "split", params: { media_id: clip.media_id, t: snapToGap(clip.media_id, t) }, label: "Split clip" }], "Split")}><Icon n="scissors" />Split</button>
      <button className="btn sm danger" onClick={del}><Icon n="trash" /></button>
      <button className="btn sm" onClick={() => addOps([{ kind: "duplicate", params: { unit_id: clip.unit_id }, label: "Duplicated clip" }], "Duplicate")} aria-label="Duplicate"><Icon n="copy" /></button>
      <button className="btn sm" disabled={ui <= 0} onClick={() => addOps([{ kind: "move", params: { unit_id: clip.unit_id, after: ui >= 2 ? units[ui - 2] : null }, label: "Moved clip" }], "Move")} aria-label="Move left"><Icon n="left" /></button>
      <button className="btn sm" disabled={ui >= units.length - 1} onClick={() => addOps([{ kind: "move", params: { unit_id: clip.unit_id, after: units[ui + 1] }, label: "Moved clip" }], "Move")} aria-label="Move right"><Icon n="right" /></button>
      <button className="btn sm" onClick={() => t - clip.s > 0.05 && addOps([{ kind: "remove", params: { ranges: [[clip.media_id, clip.s, snapToGap(clip.media_id, t)]], reason: "trim" }, label: "Trimmed start" }], "Trim")}>Trim start</button>
      <button className="btn sm" onClick={() => clip.e - t > 0.05 && addOps([{ kind: "remove", params: { ranges: [[clip.media_id, snapToGap(clip.media_id, t), clip.e]], reason: "trim" }, label: "Trimmed end" }], "Trim")}>Trim end</button>
      <select className="select" style={{ width: "auto", minHeight: 34, padding: "2px 6px" }} value={clip.speed} onChange={(e) => addOps([{ kind: "props", params: { unit_id: clip.unit_id, props: { speed: +e.target.value } }, label: `Speed ${e.target.value}×` }], "Speed")}>
        {[0.5, 0.75, 1, 1.25, 1.5, 2].map((s) => <option key={s} value={s}>{s}×</option>)}
      </select>
      <select className="select" style={{ width: "auto", minHeight: 34, padding: "2px 6px" }} value={P.zoom || 1} onChange={(e) => addOps([{ kind: "props", params: { unit_id: clip.unit_id, props: { zoom: +e.target.value } }, label: `Zoom ${e.target.value}×` }], "Zoom")}>
        {[1, 1.1, 1.2, 1.35, 1.5].map((s) => <option key={s} value={s}>Zoom {s}×</option>)}
      </select>
      <select className="select" style={{ width: "auto", minHeight: 34, padding: "2px 6px" }} value={P.mute ? 0 : P.volume ?? 1} onChange={(e) => addOps([{ kind: "props", params: { unit_id: clip.unit_id, props: { volume: +e.target.value, mute: +e.target.value === 0 } }, label: `Volume ${Math.round(+e.target.value * 100)}%` }], "Volume")}>
        {[0, 0.5, 0.75, 1, 1.25, 1.5].map((s) => <option key={s} value={s}>Vol {Math.round(s * 100)}%</option>)}
      </select>
      <button className="btn sm" onClick={() => addOps([{ kind: "props", params: { unit_id: clip.unit_id, props: { rotate: ((P.rotate || 0) + 90) % 360 } }, label: "Rotated clip" }], "Rotate")}>⟳</button>
      <button className="btn sm" onClick={() => addOps([{ kind: "product_tag", params: { media_id: clip.media_id, s: clip.s, e: clip.e, visible: true }, label: "Tagged product visible" }], "Tag")}><Icon n="eye" />Product</button>
      <button className="btn sm" onClick={() => addOps([{ kind: "restore", params: { ranges: [[clip.media_id, Math.max(0, clip.s - 5), clip.e + 5]] }, label: "Restored around clip" }], "Restore")}>Restore ±5s</button>
    </>);
  })() : <span className="tiny faint">Tap a clip to edit · drag a selected clip to move it</span>;

  // ---------------------------------------------------------------- keyboard (desktop)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input,textarea,select")) return;
      if (e.code === "Space") { e.preventDefault(); player.current?.toggle(); }
      else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && vid) {
        e.preventDefault();
        api<any>(`/versions/${vid}/${e.shiftKey ? "redo" : "undo"}`, { body: {} }).then((r) => { setView(r.view); toast(e.shiftKey ? "Redo" : "Undo"); });
      } else if (e.key === "ArrowLeft") player.current?.seek(Math.max(0, time - (e.shiftKey ? 1 : 1 / 30)));
      else if (e.key === "ArrowRight") player.current?.seek(time + (e.shiftKey ? 1 : 1 / 30));
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [vid, time]);

  if (!view || !project) return <div className="editor" style={{ alignItems: "center", justifyContent: "center" }}><Spinner /></div>;
  const ready = view.media.filter((m: any) => m.status === "ready").length;
  const versionName = project.versions.find((v: any) => v.id === vid)?.name;
  const panel = (t: string) => {
    switch (t) {
      case "ai": return <AssistantPanel versionId={vid!} onApplied={onApplied} chat={chat} setChat={setChat} />;
      case "insights": return <InsightsPanel view={view} project={project} onPlan={runPlan} onSeek={(x: number) => player.current?.seek(x)} addOps={addOps} />;
      case "style": return <StylePanel view={view} addOps={addOps} onPlan={runPlan} showSafe={showSafe} setShowSafe={setShowSafe} audioAB={audioAB} setAudioAB={setAudioAB} />;
      case "versions": return <VersionsPanel project={project} versionId={vid} onSwitch={switchVersion} onPlan={runPlan} reload={loadProject} view={view} />;
    }
  };
  const rightTab = mobile && mobile !== "transcript" ? mobile : tab;
  const overrideSection = async (sid: string, section: string) => {
    const s = project.settings || {};
    await api(`/projects/${projectId}`, { method: "PATCH", body: { settings: { section_overrides: { ...(s.section_overrides || {}), [sid]: section } } } });
    await loadProject(); await loadView(vid!);
  };

  return (
    <div className="editor">
      <header className="ed-top">
        <button className="btn ghost icon" onClick={() => go("/projects")} aria-label="Back"><Icon n="back" /></button>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="ed-title ellipsis">{project.name}</div>
          <div className="row gap-s" style={{ minWidth: 0, flexWrap: "nowrap" }}>
            <Menu className="ver-btn" button={<><Icon n="versions" size={14} /><span className="ellipsis">{versionName || "Version"}</span><span className="chev">▾</span></>}
              items={[{ section: "Versions" }, ...project.versions.map((v: any) => ({ label: v.name, on: v.id === vid, onClick: () => switchVersion(v.id) })),
                { label: "Manage versions…", icon: <Icon n="layers" />, onClick: () => { setTab("versions"); if (window.innerWidth <= 820) setMobile("versions"); } }]} />
            <span className="save-ind hide-mobile">{saving ? <><Spinner />Saving…</> : <><i />Saved</>}</span>
          </div>
        </div>
        <button className="btn ghost sm icon icon-btn" onClick={() => setHistoryOpen(true)} aria-label="Edit history" title="Edit history"><Icon n="history" /></button>
        <button className="btn ghost sm icon icon-btn hide-mobile" onClick={() => api<any>(`/versions/${vid}/undo`, { body: {} }).then((r) => setView(r.view))} aria-label="Undo" title="Undo (Ctrl+Z)"><Icon n="undo" /></button>
        <button className="btn ghost sm icon icon-btn hide-mobile" onClick={() => api<any>(`/versions/${vid}/redo`, { body: {} }).then((r) => setView(r.view))} aria-label="Redo" title="Redo (Ctrl+Shift+Z)"><Icon n="redo" /></button>
        <button className="btn primary sm" onClick={() => setExportOpen(true)} disabled={!view.timeline.clips.length}><Icon n="exports" />Export</button>
      </header>
      <div className="ed-body">
        <aside className={`ed-left ${mobile === "transcript" ? "open" : ""}`}>
          <div className="ptabs"><button className="on">Transcript</button><span className="grow" /><button className="sheet-close" onClick={() => setMobile(null)}><Icon n="close" size={18} /></button></div>
          <Transcript view={view} time={time} onSeek={(t) => player.current?.seek(t)} addOps={addOps} onPlan={runPlan} onOverrideSection={overrideSection} />
        </aside>
        <section className="ed-center">
          <div className="stage">
            {final && !original && (
              <div style={{ position: "absolute", inset: 0, zIndex: 8, display: "flex", alignItems: "center", justifyContent: "center", padding: "inherit", background: "#08090b" }}>
              <div className={`frame ${view.settings.output?.aspect === "1:1" ? "a11" : view.settings.output?.aspect === "16:9" ? "a169" : ""}`}>
                {view.preview?.url ? (
                  <video ref={finalVid} key={view.preview.url} src={view.preview.url} playsInline controls autoPlay
                    style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", background: "#000" }} />
                ) : (
                  <div className="processing"><div className="col" style={{ alignItems: "center" }}><Spinner /><b>Rendering your final cut…</b>
                    <div className="progress" style={{ width: 180 }}><div style={{ width: `${Math.round((view.preview?.job?.progress || 0) * 100)}%` }} /></div>
                    <div className="tiny faint" style={{ maxWidth: 240 }}>A quick preview render with every cut, caption and sound exactly as it will export.</div></div></div>
                )}
                <span className="badge mode-tag" style={{ background: "rgba(0,0,0,.6)", color: "#fff" }}>FINAL CUT PREVIEW</span>
              </div>
              </div>
            )}
            <Player ref={player} segs={segs} media={media} useEnhanced={audioAB} onTime={setTime} onPlaying={setPlaying} time={time}
              captions={original ? [] : view.captions} style={view.caption_style} overlays={original ? [] : view.overlays} color={original ? {} : view.settings.color}
              aspect={view.settings.output?.aspect || "9:16"} showSafe={showSafe} tag={original ? "ORIGINAL" : undefined}
              soft={!original && view.settings.video?.soft_cuts !== false} brolls={original ? [] : view.brolls}>
              {(processing || ready < view.media.length || !view.media.length) && (
                <div className="processing"><div className="col" style={{ alignItems: "center" }}>
                  {view.media.length ? <><Spinner /><b>AI is working on your footage</b>
                    <div className="small muted">{project.jobs[0]?.message || "Queued"} · {ready}/{view.media.length} clips ready</div>
                    <div className="progress" style={{ width: 200 }}><div style={{ width: `${Math.round((project.jobs[0]?.progress || 0) * 100)}%` }} /></div>
                    <div className="tiny faint" style={{ maxWidth: 260 }}>Proxy → transcript → dead space, retakes & fillers → hooks & structure. You can leave; it keeps going.</div></>
                    : <><b>No footage yet</b><button className="btn primary" onClick={() => go("/projects?new=1")}>Upload clips</button></>}
                  {view.media.filter((m: any) => m.status === "failed").map((m: any) => <div key={m.id} className="note fail small">{m.filename}: {m.error}</div>)}
                </div></div>
              )}
            </Player>
          </div>
          <div className="transport">
            <button className="btn icon" onClick={() => player.current?.toggle()} aria-label={playing ? "Pause" : "Play"}><Icon n={playing ? "pause" : "play"} /></button>
            <span className="time">{fmt(time)} / {fmt(segs.length ? segs[segs.length - 1].t1 : 0)}</span>
            <span className="grow" />
            <div className="seg">
              <button className={!original && !final ? "on" : ""} onClick={() => { setOriginal(false); setFinal(false); }}>Edit</button>
              <button className={final && !original ? "on" : ""} onClick={() => { player.current?.pause(); setOriginal(false); setFinal(true); }}>Final</button>
              <button className={original ? "on" : ""} onClick={() => { setFinal(false); setOriginal(true); }}>Original</button>
            </div>
            <button className={`btn sm icon ${showSafe ? "primary" : ""}`} onClick={() => setShowSafe(!showSafe)} aria-label="Safe zones" title="TikTok safe zones"><Icon n="target" /></button>
          </div>
          <div className="quickbar">
            <button className="qa-btn primary" onClick={() => runPlan("ai_edit")} disabled={!ready}><Icon n="spark" />AI Edit</button>
            <span className="qa-sep" />
            {QUICK_GROUPS.map(([g, gic, items]) => (
              <Menu key={g} disabled={!ready} button={<><Icon n={gic} />{g}<span className="chev">▾</span></>}
                items={items.map(([a, ic, label, args]) => ({ label, icon: <Icon n={ic} />, onClick: () => runPlan(a, args) }))} />
            ))}
          </div>
          {!original && <Timeline view={view} time={time} selected={sel} onSelect={setSel} onSeek={(t) => player.current?.seek(t)}
            onMoveUnit={(u, after) => addOps([{ kind: "move", params: { unit_id: u, after }, label: "Moved clip" }], "Move")} tools={tools}
            onRemoveBroll={(id) => confirm("Remove this B-roll shot?") && addOps([{ kind: "remove_broll", params: { id }, label: "Removed B-roll" }], "B-roll")}
            onRemoveOverlay={(id) => confirm("Remove this on-screen text?") && addOps([{ kind: "remove_overlay", params: { id }, label: "Removed text" }], "Text")} />}
          {original && <div className="tl" style={{ padding: 12 }}><div className="small muted">Viewing the untouched original footage ({fmt(segs.length ? segs[segs.length - 1].t1 : 0)}). <button className="btn sm" onClick={() => setOriginal(false)}>Back to AI edit</button></div></div>}
          <nav className="ed-mtabs">
            <button className={mobile === "transcript" ? "on" : ""} onClick={() => setMobile(mobile === "transcript" ? null : "transcript")}><Icon n="text" />Transcript</button>
            {TABS.map(([k, ic, l]) => <button key={k} className={mobile === k ? "on" : ""} onClick={() => setMobile(mobile === k ? null : k)}><Icon n={ic} />{l}</button>)}
          </nav>
        </section>
        <aside className={`ed-right ${mobile && mobile !== "transcript" ? "open" : ""}`}>
          <div className="ptabs">
            {TABS.map(([k, , l]) => <button key={k} className={rightTab === k ? "on" : ""} onClick={() => { setTab(k); if (mobile) setMobile(k); }}>{l}</button>)}
            <span className="grow" /><button className="sheet-close" onClick={() => setMobile(null)}><Icon n="close" size={18} /></button>
          </div>
          {panel(rightTab)}
        </aside>
      </div>
      {plan && (
        <Sheet title={plan.loading ? plan.title : "Review AI plan"} onClose={() => setPlan(null)}>
          {plan.loading ? <div className="row" style={{ padding: 20 }}><Spinner />Analyzing your footage…</div>
            : <PlanCard plan={plan} busy={planBusy} onApply={applyPlan} onCancel={() => setPlan(null)} />}
        </Sheet>
      )}
      {historyOpen && (
        <Sheet title="Edit history" onClose={() => setHistoryOpen(false)}>
          <HistoryPanel view={view} versionId={vid!} onView={setView} onCompare={() => { setOriginal(true); setHistoryOpen(false); setMobile(null); }} />
        </Sheet>
      )}
      {exportOpen && vid && <ExportSheet versionId={vid} versions={project.versions} onClose={() => setExportOpen(false)} onSeek={(t) => player.current?.seek(t)} shopSafe={view.shop_safe} />}
    </div>
  );
}
