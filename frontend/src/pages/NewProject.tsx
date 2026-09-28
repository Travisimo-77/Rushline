import { useEffect, useRef, useState } from "react";
import { api, upload } from "../api";
import { go } from "../app";
import { Icon, Seg, Sheet, Switch, useToast } from "../ui";

const LENGTHS = [10, 15, 20, 25, 30, 45, 60];

type Preset = { mode: "tiktok_shop" | "clean"; generate?: boolean; title: string };
export const PRESETS: Record<string, Preset> = {
  tiktok_shop: { mode: "tiktok_shop", generate: true, title: "TikTok Shop edit" },
  clean: { mode: "clean", title: "Clean raw footage" },
  variations: { mode: "tiktok_shop", generate: true, title: "Generate ad variations" },
  blank: { mode: "tiktok_shop", title: "New project" },
};

export function NewProjectSheet({ kind, onClose }: { kind: string; onClose: () => void }) {
  const preset = PRESETS[kind] || PRESETS.blank;
  const toast = useToast();
  const [products, setProducts] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [mode, setMode] = useState(preset.mode);
  const [productId, setProductId] = useState("");
  const [length, setLength] = useState<number | null>(preset.mode === "tiktok_shop" ? 25 : null);
  const [custom, setCustom] = useState("");
  const [strength, setStrength] = useState<"clean" | "fast" | "viral">(preset.mode === "clean" ? "clean" : "fast");
  const [generate, setGenerate] = useState(!!preset.generate);
  const [adCount, setAdCount] = useState(3);
  const [adv, setAdv] = useState(false);
  const [sens, setSens] = useState<any>({});
  const [files, setFiles] = useState<File[]>([]);
  const [progress, setProgress] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api<any[]>("/products").then((p) => { setProducts(p); if (p[0] && preset.mode === "tiktok_shop") setProductId(p[0].id); }).catch(() => {}); }, []);

  const start = async () => {
    if (!files.length) { toast("Add at least one clip", true); return; }
    setBusy(true);
    try {
      const target = custom ? parseFloat(custom) : length;
      const p = await api<any>("/projects", {
        body: {
          name: name || files[0].name.replace(/\.[^.]+$/, "") || "Untitled", mode, product_id: productId || null, target_duration: target || null,
          strength, generate_ads: generate, ad_count: adCount, sensitivity: sens,
        },
      });
      setProgress(files.map(() => 0));
      // sequential uploads are gentler on mobile connections and keep clip order stable
      for (let i = 0; i < files.length; i++) {
        let attempt = 0;
        for (;;) {
          try {
            await upload(`/projects/${p.id}/upload`, files[i], files[i].name || `clip${i + 1}.mov`, (x) =>
              setProgress((pr) => pr.map((v, j) => (j === i ? x : v)))).promise;
            break;
          } catch (e: any) {
            if (++attempt >= 3 || e.status >= 400) throw e;
          }
        }
      }
      toast("Uploaded — AI is processing your footage");
      onClose();
      go(`/edit/${p.id}`);
    } catch (e: any) {
      toast(e.message, true);
    } finally { setBusy(false); }
  };

  const total = files.reduce((a, f) => a + f.size, 0);
  return (
    <Sheet title={preset.title} onClose={busy ? () => {} : onClose} wide
      footer={<><button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn primary grow" onClick={start} disabled={busy || !files.length}>
          <Icon n="spark" />{busy ? "Uploading…" : generate ? "Upload & generate ads" : "Upload & clean"}</button></>}>
      <div className="col gap-l">
        <div className="card flat col" onClick={() => !busy && input.current?.click()} style={{ cursor: "pointer", borderStyle: "dashed", alignItems: "center", textAlign: "center" }}>
          <Icon n="upload" size={28} />
          <b>{files.length ? `${files.length} clip${files.length > 1 ? "s" : ""} · ${(total / 1e6).toFixed(0)} MB` : "Add raw footage"}</b>
          <span className="small muted">From Photos, Files or Camera. Multiple clips, long takes and 4K are fine — originals stay untouched.</span>
          <input ref={input} type="file" accept="video/*,.mov,.mp4,.m4v" multiple hidden
            onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])])} />
        </div>
        {files.length > 0 && (
          <div className="col gap-s">
            {files.map((f, i) => (
              <div key={i} className="row small">
                <Icon n="film" size={16} /><span className="grow ellipsis">{f.name}</span><span className="faint">{(f.size / 1e6).toFixed(0)} MB</span>
                {progress.length ? <div className="progress" style={{ width: 80 }}><div style={{ width: `${(progress[i] || 0) * 100}%` }} /></div>
                  : <button className="btn ghost sm icon" onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label="Remove"><Icon n="close" /></button>}
              </div>
            ))}
          </div>
        )}
        <label className="field"><span>Project name</span><input className="input" value={name} placeholder="e.g. Hair clay — batch 1" onChange={(e) => setName(e.target.value)} /></label>
        <div className="field"><span>Mode</span><Seg value={mode} onChange={setMode as any} options={[["tiktok_shop", "TikTok Shop"], ["clean", "Clean edit only"]]} /></div>
        {mode === "tiktok_shop" && (
          <label className="field"><span>Product</span>
            <select className="select" value={productId} onChange={(e) => setProductId(e.target.value)}>
              <option value="">No product (generic)</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            {!products.length && <a className="small" style={{ color: "var(--ember)" }} href="#/products/new" onClick={onClose}>+ Create a product profile first (recommended)</a>}
          </label>
        )}
        <div className="field"><span>Target length</span>
          <div className="row wrap gap-s">
            <span className={`chip ${!length && !custom ? "on" : ""}`} onClick={() => { setLength(null); setCustom(""); }}>Any</span>
            {LENGTHS.map((l) => <span key={l} className={`chip ${length === l && !custom ? "on" : ""}`} onClick={() => { setLength(l); setCustom(""); }}>{l}s</span>)}
            <input className="input" style={{ width: 96, minHeight: 34 }} inputMode="numeric" placeholder="Custom" value={custom} onChange={(e) => setCustom(e.target.value.replace(/[^0-9.]/g, ""))} />
          </div>
        </div>
        <div className="field"><span>Cleanup strength</span>
          <Seg value={strength} onChange={setStrength as any} options={[["clean", "Clean"], ["fast", "Fast"], ["viral", "Viral"]]} />
          <span className="tiny faint">{strength === "clean" ? "Removes mistakes, pauses, fillers & retakes; keeps natural pacing." :
            strength === "fast" ? "Clean + tighter social-media pacing." : "Aggressive retention pacing with punch-in zooms and bold captions."}</span>
        </div>
        {mode === "tiktok_shop" && (
          <div className="row between">
            <div><b>Generate ad versions</b><div className="small muted">Builds different hook × structure ads from the same footage.</div></div>
            <div className="row">{generate && <select className="select" style={{ width: 72, minHeight: 34, padding: "4px 8px" }} value={adCount} onChange={(e) => setAdCount(+e.target.value)}>
              {[2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select>}<Switch checked={generate} onChange={setGenerate} /></div>
          </div>
        )}
        <button className="btn ghost sm" style={{ alignSelf: "flex-start" }} onClick={() => setAdv(!adv)}>{adv ? "Hide" : "Show"} smart-cut sensitivity</button>
        {adv && <Sensitivity value={sens} onChange={setSens} />}
      </div>
    </Sheet>
  );
}

function SRow({ k, label, min, max, step, def, unit, value, set }: any) {
  return (
    <label className="field"><span className="row between"><span>{label}</span><span className="mono">{value[k] ?? def}{unit}</span></span>
      <input className="range" type="range" min={min} max={max} step={step} value={value[k] ?? def} onChange={(e) => set(k, parseFloat(e.target.value))} /></label>
  );
}

export function Sensitivity({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const set = (k: string, v: any) => onChange({ ...value, [k]: v });
  return (
    <div className="card flat col">
      <SRow value={value} set={set} k="min_pause" label="Pause length that counts as dead space" min={0.2} max={1.5} step={0.05} def={0.4} unit="s" />
      <SRow value={value} set={set} k="keep_pause" label="Pause kept between phrases" min={0.05} max={0.6} step={0.01} def={0.16} unit="s" />
      <SRow value={value} set={set} k="min_clip" label="Minimum gap between cuts" min={0.1} max={1.5} step={0.05} def={0.35} unit="s" />
      <SRow value={value} set={set} k="retake_sensitivity" label="Retake sensitivity" min={0} max={1} step={0.05} def={0.55} unit="" />
      <SRow value={value} set={set} k="zoom_every" label="Zoom frequency (0 = off)" min={0} max={8} step={0.5} def={0} unit="s" />
      <div className="row between"><span>Remove filler words</span><Switch checked={value.fillers ?? true} onChange={(v) => set("fillers", v)} /></div>
      <div className="row between"><span>Remove filler “like”</span><Switch checked={value.like ?? true} onChange={(v) => set("like", v)} /></div>
      <div className="row between"><span>Remove retakes</span><Switch checked={value.retakes ?? true} onChange={(v) => set("retakes", v)} /></div>
      <div className="row between"><span>B-roll frequency</span><span className="badge soon">COMING SOON</span></div>
    </div>
  );
}
