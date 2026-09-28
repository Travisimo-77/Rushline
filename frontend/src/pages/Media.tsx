import { useEffect, useState } from "react";
import { ago, api, fmtShort } from "../api";
import { Empty, Icon, useToast } from "../ui";

export function MediaPage() {
  const toast = useToast();
  const [list, setList] = useState<any[] | null>(null);
  const load = () => api<any[]>("/media").then(setList).catch((e) => toast(e.message, true));
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);
  const del = async (m: any) => {
    if (!confirm(`Permanently delete “${m.filename}” (original + proxies)? Any edit using it will lose this clip.`)) return;
    await api(`/media/${m.id}`, { method: "DELETE" }); toast("Media deleted"); load();
  };
  const retry = async (m: any) => { await api(`/media/${m.id}/retry`, { body: {} }); toast("Re-processing"); load(); };
  const total = (list || []).reduce((a, m) => a + (m.size || 0), 0);
  return (
    <div>
      <div className="page-head"><div><h1>Media library</h1><div className="small muted">{list?.length || 0} files · {(total / 1e9).toFixed(2)} GB · originals are never modified</div></div></div>
      <div className="note mb small"><Icon n="search" /><div>Semantic footage search (“find the close-up of the packaging”) is <span className="badge soon">COMING SOON</span></div></div>
      {list && !list.length && <Empty icon="media" title="No media yet">Uploads from all projects appear here.</Empty>}
      <div className="card" style={{ paddingTop: 4, paddingBottom: 4 }}>
        {(list || []).map((m) => (
          <div key={m.id} className="list-item">
            <div className="thumb" style={{ backgroundImage: m.thumb_url ? `url(${m.thumb_url})` : undefined }} />
            <div className="grow" style={{ minWidth: 0 }}>
              <div className="ellipsis" style={{ fontWeight: 650 }}>{m.filename}</div>
              <div className="tiny muted">{m.duration ? fmtShort(m.duration) : "–"} · {m.width ? `${m.width}×${m.height}` : ""} · {m.size ? `${(m.size / 1e6).toFixed(0)} MB` : ""} · {ago(m.created_at)}</div>
              <div className="tiny faint ellipsis">{m.project_name ? <a href={`#/edit/${m.project_id}`}>{m.project_name}</a> : "Unassigned"}</div>
              {m.error && <div className="tiny" style={{ color: "var(--danger)" }}>{m.error}</div>}
            </div>
            <span className={`badge ${m.status === "ready" ? "ok" : m.status === "failed" ? "fail" : "ai"}`}>{m.status}</span>
            {m.status === "failed" && <button className="btn sm" onClick={() => retry(m)}><Icon n="refresh" /></button>}
            <button className="btn ghost sm icon" onClick={() => del(m)} aria-label="Delete"><Icon n="trash" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
