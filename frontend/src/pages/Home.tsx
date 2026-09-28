import { useEffect, useState } from "react";
import { ago, api, fmtShort, isIOS, isStandalone } from "../api";
import { go, useUser } from "../app";
import { Icon } from "../ui";
import { NewProjectSheet } from "./NewProject";

export function HomePage() {
  const { user } = useUser();
  const [data, setData] = useState<any>(null);
  const [sheet, setSheet] = useState<string | null>(null);
  const [hideInstall, setHideInstall] = useState(() => { try { return !!localStorage.getItem("rl_hide_install"); } catch { return false; } });
  useEffect(() => { api("/home").then(setData).catch(() => {}); }, [sheet]);
  const hour = new Date().getHours();
  const hi = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const QA = [
    ["tiktok_shop", "bag", "TikTok Shop Edit", "Product-aware ad cut", true],
    ["clean", "broom", "Clean Raw Footage", "Remove pauses, retakes, fillers", false],
    ["variations", "layers", "Generate Ad Variations", "Many ads, one filming session", false],
    ["blank", "plus", "New Project", "Start from scratch", false],
  ] as const;
  return (
    <div>
      <div className="page-head">
        <div><div className="muted small">{hi}{user?.name ? `, ${user.name.split(" ")[0]}` : ""}</div><h1>What are we making?</h1></div>
        <button className="btn primary hide-mobile" onClick={() => setSheet("blank")}><Icon n="upload" />Upload raw footage</button>
      </div>
      {isIOS() && !isStandalone() && !hideInstall && (
        <div className="note mb" style={{ alignItems: "center" }}>
          <Icon n="share" /><div className="grow small"><b>Install Rushline on your iPhone:</b> tap <b>Share</b> in Safari, then <b>Add to Home Screen</b>.</div>
          <button className="btn ghost sm icon" aria-label="Dismiss" onClick={() => { try { localStorage.setItem("rl_hide_install", "1"); } catch { /**/ } setHideInstall(true); }}><Icon n="close" /></button>
        </div>
      )}
      <div className="quick">
        {QA.map(([k, ic, t, s, hero]) => (
          <div key={k} className={`qa ${hero ? "hero" : ""}`} onClick={() => setSheet(k)} role="button" tabIndex={0}>
            <div className="qa-ico"><Icon n={ic} /></div>
            <div><b>{t}</b><small>{s}</small></div>
          </div>
        ))}
      </div>

      <div className="row between mt-l mb"><h2>Recent projects</h2><a className="small muted" href="#/projects">See all</a></div>
      {data && !data.projects.length && <div className="card muted small">No projects yet — upload a messy filming session and let the AI do the first cut.</div>}
      <div className="hscroll">
        {(data?.projects || []).map((p: any) => (
          <div key={p.id} className="pcard" onClick={() => go(`/edit/${p.id}`)} style={{ cursor: "pointer" }}>
            <div className="poster" style={{ backgroundImage: p.thumb_url ? `url(${p.thumb_url})` : undefined }}>
              {p.processing > 0 ? <span className="badge ai">Processing</span> : <span className="badge">{p.versions} version{p.versions !== 1 ? "s" : ""}</span>}
            </div>
            <div className="meta"><div className="ellipsis" style={{ fontWeight: 650 }}>{p.name}</div>
              <div className="tiny muted">{p.media_count} clip{p.media_count !== 1 ? "s" : ""} · {fmtShort(p.raw_duration)} raw · {ago(p.updated_at)}</div></div>
          </div>
        ))}
      </div>

      <div className="grid two mt-l">
        <div className="card">
          <div className="row between mb"><h2>Saved products</h2><a className="small muted" href="#/products/new">+ New</a></div>
          {(data?.products || []).length === 0 && <div className="small muted">Save a product once — Rushline reuses its features, claims and CTA in every project.</div>}
          {(data?.products || []).map((p: any) => (
            <a key={p.id} className="list-item" href={`#/products/${p.id}`}>
              <div className="thumb" style={{ width: 44, height: 44, backgroundImage: p.photos[0] ? `url(${p.photos[0].url})` : undefined }} />
              <div className="grow"><div style={{ fontWeight: 650 }}>{p.name}</div><div className="tiny muted">{[p.category, p.price && `$${String(p.price).replace("$", "")}`].filter(Boolean).join(" · ")}</div></div>
            </a>
          ))}
        </div>
        <div className="card">
          <div className="row between mb"><h2>Recent exports</h2><a className="small muted" href="#/exports">All</a></div>
          {(data?.exports || []).length === 0 && <div className="small muted">Finished videos show up here.</div>}
          {(data?.exports || []).map((e: any) => (
            <div key={e.id} className="list-item">
              <Icon n="film" /><div className="grow"><div className="ellipsis" style={{ fontWeight: 600 }}>{e.name}</div><div className="tiny muted">{e.project_name} · {ago(e.created_at)}</div></div>
              {e.download_url ? <a className="btn sm" href={e.download_url}><Icon n="download" /></a> : <span className="badge">{e.status}</span>}
            </div>
          ))}
        </div>
      </div>
      {data?.limits && (
        <div className="card mt-l">
          <div className="row between"><b>Monthly processing</b><span className="small muted">{data.limits.used_minutes} / {data.limits.minutes} min · {data.limits.plan} plan</span></div>
          <div className="progress mt"><div style={{ width: `${Math.min(100, (100 * data.limits.used_minutes) / data.limits.minutes)}%` }} /></div>
        </div>
      )}
      {sheet && <NewProjectSheet kind={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}
