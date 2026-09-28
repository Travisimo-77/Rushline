import { useEffect, useState } from "react";
import { ago, api, fmtShort } from "../api";
import { go, useRoute } from "../app";
import { Empty, Icon, useToast } from "../ui";
import { NewProjectSheet } from "./NewProject";

export function ProjectsPage() {
  const r = useRoute();
  const toast = useToast();
  const [list, setList] = useState<any[] | null>(null);
  const [q, setQ] = useState("");
  const [sheet, setSheet] = useState<string | null>(r.query.get("new") ? "blank" : null);
  const load = () => api<any[]>("/projects").then(setList).catch((e) => toast(e.message, true));
  useEffect(() => { load(); }, [sheet]);
  const del = async (p: any) => {
    if (!confirm(`Delete “${p.name}”? Its edits, versions, exports and uploaded clips will be permanently deleted.`)) return;
    await api(`/projects/${p.id}`, { method: "DELETE" });
    toast("Project deleted"); load();
  };
  const shown = (list || []).filter((p) => p.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <div className="page-head"><h1>Projects</h1><button className="btn primary" onClick={() => setSheet("blank")}><Icon n="plus" />New project</button></div>
      <input className="input mb" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
      {list && !list.length && <Empty icon="projects" title="No projects yet">Upload raw footage to create your first project.</Empty>}
      <div className="grid cards">
        {shown.map((p) => (
          <div key={p.id} className="card click" style={{ padding: 0, overflow: "hidden" }} onClick={() => go(`/edit/${p.id}`)}>
            <div style={{ aspectRatio: "16/10", background: `var(--surface-2) center/cover ${p.thumb_url ? `url(${p.thumb_url})` : ""}` }} />
            <div style={{ padding: 12 }}>
              <div className="row"><b className="grow ellipsis">{p.name}</b>
                <button className="btn ghost sm icon" aria-label="Delete project" onClick={(e) => { e.stopPropagation(); del(p); }}><Icon n="trash" /></button></div>
              <div className="row wrap gap-s mt">
                <span className={`badge ${p.mode === "tiktok_shop" ? "ember" : ""}`}>{p.mode === "tiktok_shop" ? "TikTok Shop" : "Clean"}</span>
                {p.processing > 0 ? <span className="badge ai">Processing {p.processing}</span> : <span className="badge">{p.versions} version{p.versions !== 1 ? "s" : ""}</span>}
              </div>
              <div className="tiny muted mt">{p.media_count} clips · {fmtShort(p.raw_duration)} raw · {ago(p.updated_at)}</div>
            </div>
          </div>
        ))}
      </div>
      {sheet && <NewProjectSheet kind={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}
