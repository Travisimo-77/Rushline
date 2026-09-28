import { useState } from "react";
import { api } from "../api";
import { go, useUser } from "../app";
import { Icon, Seg, Sheet, useToast } from "../ui";

export function ExportSheet({ versionId, versions, onClose, onSeek, shopSafe }: { versionId: string; versions: any[]; onClose: () => void; onSeek: (t: number) => void; shopSafe?: any }) {
  const { user } = useUser();
  const toast = useToast();
  const maxH = user?.limits?.max_height || 1080;
  const [s, setS] = useState<any>({ aspect: "9:16", resolution: "1080p", fps: 30, quality: "balanced" });
  const [qc, setQc] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => { setS({ ...s, [k]: v }); setQc(null); };
  const check = async () => { setBusy(true); try { setQc(await api(`/versions/${versionId}/qc`, { body: { settings: s } })); } finally { setBusy(false); } };
  const queue = async (ids: string[]) => {
    setBusy(true);
    try {
      for (const id of ids) await api(`/versions/${id}/exports`, { body: { settings: s } });
      toast(ids.length > 1 ? `${ids.length} exports queued` : "Export queued — you'll be notified when it's ready");
      onClose(); go("/exports");
    } catch (e: any) { toast(e.message, true); } finally { setBusy(false); }
  };
  const resOpts: [string, string][] = [["720p", "720p"], ["1080p", "1080p"], ["1440p", "1440p"], ["4k", "4K"]];
  const shortSide: Record<string, number> = { "720p": 720, "1080p": 1080, "1440p": 1440, "4k": 2160 };
  return (
    <Sheet title="Export" onClose={onClose}
      footer={<>
        {versions.length > 1 && <button className="btn" disabled={busy || qc?.status === "fail"} onClick={() => queue(versions.map((v) => v.id))}>Export all {versions.length}</button>}
        {!qc ? <button className="btn primary grow" onClick={check} disabled={busy}><Icon n="shield" />{busy ? "Checking…" : "Run quality check"}</button>
          : <button className="btn primary grow" disabled={busy || qc.status === "fail"} onClick={() => queue([versionId])}><Icon n="exports" />Export this version</button>}
      </>}>
      <div className="col gap-l">
        {shopSafe && (
          <div className={`note small ${shopSafe.status === "risky" ? "fail" : shopSafe.status === "review" ? "warn" : ""}`}>
            <Icon n="shield" /><div className="grow"><b>Shop-safe check:</b> {shopSafe.status === "safe" ? "no risky claims found." :
              `${shopSafe.total} item${shopSafe.total > 1 ? "s" : ""} to review${shopSafe.high ? ` (${shopSafe.high} high-risk)` : ""} — see Insights before posting.`}</div>
          </div>
        )}
        <div className="field"><span>Aspect ratio</span><Seg value={s.aspect} onChange={(v) => set("aspect", v)} options={[["9:16", "9:16"], ["1:1", "1:1"], ["16:9", "16:9"]]} /></div>
        <div className="field"><span>Resolution</span>
          <div className="row wrap gap-s">{resOpts.map(([v, l]) => {
            const locked = shortSide[v] > maxH;
            return <span key={v} className={`chip ${s.resolution === v ? "on" : ""}`} style={{ opacity: locked ? 0.5 : 1 }} onClick={() => (locked ? toast(`${l} needs the Pro plan`, true) : set("resolution", v))}>{locked && <Icon n="lock" />}{l}</span>;
          })}</div>
        </div>
        <div className="field"><span>Frame rate</span><Seg value={s.fps} onChange={(v) => set("fps", v)} options={[[24, "24"], [30, "30"], [60, "60"], ["source", "Original"]]} /></div>
        <div className="field"><span>Quality</span><Seg value={s.quality} onChange={(v) => set("quality", v)} options={[["high", "High"], ["balanced", "Balanced"], ["small", "Small file"]]} /></div>
        {qc && (
          <div className="card flat col">
            <div className="row"><b className="grow">Quality check</b><span className={`badge ${qc.status === "pass" ? "ok" : qc.status}`}>{qc.status.toUpperCase()}</span></div>
            {!qc.items.length && <div className="small muted">No issues found: audio sync, clip ranges, captions, safe zones, resolution, claims all OK.</div>}
            {qc.items.map((i: any, n: number) => (
              <div key={n} className={`note small ${i.level}`} onClick={() => i.t != null && (onSeek(i.t), onClose())} style={{ cursor: i.t != null ? "pointer" : undefined }}>
                <Icon n={i.level === "info" ? "info" : "warn"} /><div className="grow">{i.message}</div>{i.t != null && <span className="tiny faint">{i.t.toFixed(1)}s</span>}
              </div>
            ))}
            <div className="tiny faint">After rendering, the file is verified again (duration, A/V sync, black/frozen frames, loudness) before it's delivered.</div>
          </div>
        )}
        <div className="row small muted"><Icon n="share" size={16} />Publishing directly to TikTok <span className="badge soon">COMING SOON</span></div>
      </div>
    </Sheet>
  );
}
