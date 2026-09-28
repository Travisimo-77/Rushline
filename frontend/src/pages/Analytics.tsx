import { useEffect, useRef, useState } from "react";
import { ago, api, getToken } from "../api";
import { Empty, Icon, Sheet, useToast } from "../ui";

const FIELDS: [string, string, string][] = [
  ["views", "Views", ""], ["avg_watch_time", "Avg watch time", "s"], ["completion_rate", "Completion rate", "%"], ["hold_2s", "2-sec hold", "%"],
  ["likes", "Likes", ""], ["comments", "Comments", ""], ["shares", "Shares", ""], ["ctr", "Click-through rate", "%"],
  ["product_clicks", "Product clicks", ""], ["orders", "Orders", ""], ["gmv", "GMV / revenue", "$"],
];

export function ResultsSheet({ exportItem, onClose, onSaved }: { exportItem?: any; onClose: () => void; onSaved?: () => void }) {
  const toast = useToast();
  const [m, setM] = useState<Record<string, string>>({});
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState(exportItem?.name || "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api("/performance", { body: { export_id: exportItem?.id, title, url, metrics: m } });
      toast("Results saved — Rushline will learn from them"); onSaved?.(); onClose();
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  return (
    <Sheet title="Add results" onClose={onClose} footer={<><button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn primary grow" onClick={save} disabled={busy || !Object.values(m).some((v) => v.trim())}>Save results</button></>}>
      <div className="col">
        <div className="small muted">Copy the numbers from TikTok / TikTok Shop analytics after the video has run a few days. Fill in what you have.</div>
        {!exportItem && <label className="field"><span>Video name</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></label>}
        <label className="field"><span>Video link (optional)</span><input className="input" inputMode="url" value={url} onChange={(e) => setUrl(e.target.value)} /></label>
        <div className="grid two">
          {FIELDS.map(([k, l, u]) => (
            <label key={k} className="field"><span>{l}{u ? ` (${u})` : ""}</span>
              <input className="input" inputMode="decimal" value={m[k] || ""} onChange={(e) => setM({ ...m, [k]: e.target.value })} /></label>
          ))}
        </div>
      </div>
    </Sheet>
  );
}

export function AnalyticsPage() {
  const toast = useToast();
  const [data, setData] = useState<any>(null);
  const [adding, setAdding] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const load = () => api("/performance").then(setData).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, []);
  const importCsv = async (f: File | undefined) => {
    if (!f) return;
    const r = await fetch("/api/v1/performance/import", { method: "POST", headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "text/csv" }, body: await f.text() });
    const j = await r.json();
    r.ok ? toast(`Imported ${j.imported} videos`) : toast(j.error || "Import failed", true);
    load();
  };
  const del = async (id: string) => { await api(`/performance/${id}`, { method: "DELETE" }); load(); };
  const entries = data?.entries || [];
  const linked = entries.filter((e: any) => e.features && Object.keys(e.features).length).length;
  return (
    <div>
      <div className="page-head"><div><h1>Analytics</h1><div className="small muted">What works for <b>your</b> audience, learned from your own results.</div></div>
        <div className="row"><button className="btn" onClick={() => file.current?.click()}><Icon n="upload" />Import CSV</button>
          <button className="btn primary" onClick={() => setAdding(true)}><Icon n="plus" />Add results</button></div></div>
      <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => importCsv(e.target.files?.[0])} />
      <div className="card mb">
        <div className="row between mb"><h2>Insights</h2><span className="tiny faint">{linked} videos linked to edits</span></div>
        {!data?.insights?.length && (
          <div className="small muted">Add results for at least 3 exported videos (Exports → Add results). Rushline compares what the edits had in common —
            hook type, length, product timing, text hook, B-roll, pacing — against views, clicks and sales.</div>
        )}
        <div className="col gap-s">
          {(data?.insights || []).map((i: any, n: number) => (
            <div key={n} className="note small"><Icon n="analytics" /><div className="grow"><b>{i.factor}:</b> {i.text}
              {i.tip && <div className="muted">{i.tip}</div>}
              <div className="tiny faint">{i.confidence} confidence · a pattern in your data, not proof of cause</div></div></div>
          ))}
        </div>
      </div>
      <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {data && !entries.length && <Empty icon="analytics" title="No results yet">After posting, add each video's numbers here or from the Exports page.</Empty>}
        {entries.map((e: any) => (
          <div key={e.id} className="list-item">
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="ellipsis" style={{ fontWeight: 650 }}>{e.title}</div>
              <div className="tiny muted">{Object.entries(e.metrics).slice(0, 5).map(([k, v]: any) => `${data.metrics[k] || k}: ${Number(v).toLocaleString()}`).join(" · ")}</div>
              <div className="tiny faint">{e.features?.hook_type ? `${e.features.hook_type} hook · ${e.features.duration}s · ${e.features.template}` : "not linked to an edit"} · {ago(e.created_at)}</div>
            </div>
            <button className="btn ghost sm icon" onClick={() => del(e.id)} aria-label="Delete"><Icon n="trash" /></button>
          </div>
        ))}
      </div>
      <div className="tiny faint mt">Direct TikTok import will use TikTok's official API once connected — COMING SOON. CSV exports from TikTok Studio / Shop analytics work today.</div>
      {adding && <ResultsSheet onClose={() => setAdding(false)} onSaved={load} />}
    </div>
  );
}
