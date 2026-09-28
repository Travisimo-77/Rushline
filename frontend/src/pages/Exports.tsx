import { useEffect, useRef, useState } from "react";
import { ago, api } from "../api";
import { Empty, Icon, useToast } from "../ui";
import { ResultsSheet } from "./Analytics";

export async function shareOrDownload(url: string, name: string, toast: (m: string, e?: boolean) => void) {
  // iPhone: share sheet → "Save Video" to Photos, or post directly. Falls back to download.
  try {
    const nav: any = navigator;
    if (nav.share && nav.canShare) {
      toast("Preparing video…");
      const blob = await (await fetch(url)).blob();
      const file = new File([blob], `${name.replace(/[^\w .-]+/g, "").slice(0, 60) || "rushline"}.mp4`, { type: "video/mp4" });
      if (nav.canShare({ files: [file] })) { await nav.share({ files: [file], title: name }); return; }
    }
  } catch (e: any) { if (e?.name === "AbortError") return; }
  const a = document.createElement("a");
  a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
}

export function ExportsPage() {
  const toast = useToast();
  const [list, setList] = useState<any[] | null>(null);
  const prev = useRef<Record<string, string>>({});
  const load = () => api<any[]>("/exports").then((l) => {
    for (const e of l) {
      if (prev.current[e.id] && prev.current[e.id] !== "done" && e.status === "done") toast(`“${e.name}” is ready`);
      prev.current[e.id] = e.status;
    }
    setList(l);
  }).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 2500); return () => clearInterval(t); }, []);
  const del = async (e: any) => { if (!confirm("Delete this export file?")) return; await api(`/exports/${e.id}`, { method: "DELETE" }); load(); };
  const [resultsFor, setResultsFor] = useState<any>(null);
  return (
    <div>
      <div className="page-head"><div><h1>Exports</h1><div className="small muted">Queue several versions — you'll see them here as they finish.</div></div></div>
      {list && !list.length && <Empty icon="exports" title="Nothing exported yet">Open a project and tap Export.</Empty>}
      <div className="col">
        {(list || []).map((e) => {
          const active = e.status === "queued" || e.status === "rendering";
          const post = e.qc?.post; const pre = e.qc?.pre;
          const warns = [...(pre?.items || []), ...(post?.items || [])].filter((i: any) => i.level === "warn" || i.level === "fail");
          return (
            <div key={e.id} className="card">
              <div className="row">
                <Icon n="film" />
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="ellipsis" style={{ fontWeight: 650 }}>{e.name}</div>
                  <div className="tiny muted">{e.project_name} · {e.settings.aspect} · {e.settings.resolution} · {e.settings.fps}fps · {e.settings.quality} · {ago(e.created_at)}</div>
                </div>
                <span className={`badge ${e.status === "done" ? "ok" : e.status === "failed" ? "fail" : "ai"}`}>{e.status === "queued" ? "waiting" : e.status}</span>
              </div>
              {active && <div className="progress mt"><div style={{ width: `${Math.max(3, e.progress * 100)}%` }} /></div>}
              {e.status === "failed" && <div className="note fail small mt"><Icon n="warn" />{e.error || "Export failed"} — your project is safe; fix the flagged issue and export again.</div>}
              {e.status === "done" && (
                <div className="row wrap mt">
                  <button className="btn primary sm" onClick={() => shareOrDownload(e.download_url, e.name, toast)}><Icon n="share" />Save / Share</button>
                  <a className="btn sm" href={e.download_url}><Icon n="download" />Download</a>
                  <a className="btn sm ghost" href={`#/edit/${e.project_id}?v=${e.version_id}`}>Open edit</a>
                  <button className="btn sm ghost" onClick={() => setResultsFor(e)}><Icon n="analytics" />Add results</button>
                  <span className="grow" />
                  <span className="small muted">{post?.items?.find((i: any) => i.code === "av_sync")?.message}</span>
                  <button className="btn ghost sm icon" onClick={() => del(e)} aria-label="Delete export"><Icon n="trash" /></button>
                </div>
              )}
              {e.status === "done" && warns.length > 0 && <details className="small muted mt"><summary>{warns.length} quality note{warns.length > 1 ? "s" : ""}</summary>
                {warns.map((w: any, i: number) => <div key={i}>• {w.message}</div>)}</details>}
            </div>
          );
        })}
      </div>
      {resultsFor && <ResultsSheet exportItem={resultsFor} onClose={() => setResultsFor(null)} />}
    </div>
  );
}
