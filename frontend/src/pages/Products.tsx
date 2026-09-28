import { useEffect, useRef, useState } from "react";
import { api, upload } from "../api";
import { go } from "../app";
import { Empty, Icon, useToast } from "../ui";

const LISTS = [
  ["features", "Features", "One per line — e.g. matte finish"],
  ["benefits", "Benefits", "Why it matters — e.g. adds texture without shine"],
  ["approved_claims", "Approved claims", "Claims the brand has documented"],
  ["avoid_claims", "Claims to avoid", "Rushline flags these before export"],
] as const;

export function ProductsPage({ id }: { id?: string }) {
  const [list, setList] = useState<any[] | null>(null);
  useEffect(() => { if (!id) api<any[]>("/products").then(setList).catch(() => setList([])); }, [id]);
  if (id) return <ProductEditor id={id} />;
  return (
    <div>
      <div className="page-head"><div><h1>Products</h1><div className="muted small">Saved once, reused by the AI in every project.</div></div>
        <a className="btn primary" href="#/products/new"><Icon n="plus" />New product</a></div>
      {list && !list.length && <Empty icon="products" title="No products yet">Add name, price, features, benefits, claims and photos — photos enable product-visibility tracking.</Empty>}
      <div className="grid cards">
        {(list || []).map((p) => (
          <a key={p.id} className="card click" href={`#/products/${p.id}`} style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ aspectRatio: "1/1", background: `var(--surface-2) center/cover ${p.photos[0] ? `url(${p.photos[0].url})` : ""}` }} />
            <div style={{ padding: 12 }}><b className="ellipsis" style={{ display: "block" }}>{p.name}</b>
              <div className="tiny muted">{[p.category, p.price && `$${String(p.price).replace("$", "")}`, `${p.project_count} projects`].filter(Boolean).join(" · ")}</div></div>
          </a>
        ))}
      </div>
    </div>
  );
}

function ProductEditor({ id }: { id: string }) {
  const toast = useToast();
  const isNew = id === "new";
  const [p, setP] = useState<any>(isNew ? { name: "", photos: [] } : null);
  const [saving, setSaving] = useState(false);
  const [up, setUp] = useState<number | null>(null);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!isNew) api(`/products/${id}`).then(setP).catch((e) => toast(e.message, true)); }, [id]);
  if (!p) return <div className="empty">Loading…</div>;
  const set = (k: string, v: any) => setP({ ...p, [k]: v });
  const save = async () => {
    if (!p.name?.trim()) { toast("Name is required", true); return; }
    setSaving(true);
    try {
      const body = { ...p };
      delete body.photos;
      const r = isNew ? await api("/products", { body }) : await api(`/products/${id}`, { method: "PATCH", body });
      toast("Product saved");
      if (isNew) go(`/products/${(r as any).id}`); else setP(r);
    } catch (e: any) { toast(e.message, true); } finally { setSaving(false); }
  };
  const addPhotos = async (files: FileList | null) => {
    if (!files || isNew) return;
    for (const f of Array.from(files)) {
      setUp(0);
      try {
        const r = await upload(`/products/${id}/photos`, f, f.name || "photo.jpg", setUp).promise;
        setP((cur: any) => ({ ...cur, photos: r.photos }));
      } catch (e: any) { toast(e.message, true); }
    }
    setUp(null);
    toast("Photos added — footage will be re-scanned for the product");
  };
  const delPhoto = async (path: string) => {
    const r = await api<any>(`/products/${id}/photos?path=${encodeURIComponent(path)}`, { method: "DELETE" });
    setP({ ...p, photos: r.photos });
  };
  const del = async () => {
    if (!confirm("Delete this product? Projects using it will keep their footage.")) return;
    await api(`/products/${id}`, { method: "DELETE" }); go("/products");
  };
  const listVal = (k: string) => (Array.isArray(p[k]) ? p[k].join("\n") : p[k] || "");
  return (
    <div>
      <div className="page-head">
        <div className="row"><a className="btn ghost icon" href="#/products" aria-label="Back"><Icon n="back" /></a><h1>{isNew ? "New product" : p.name}</h1></div>
        <div className="row">{!isNew && <button className="btn danger sm" onClick={del}><Icon n="trash" />Delete</button>}
          <button className="btn primary" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button></div>
      </div>
      <div className="grid two">
        <div className="col gap-l">
          <div className="card col">
            <h3>Basics</h3>
            <label className="field"><span>Product name *</span><input className="input" value={p.name} onChange={(e) => set("name", e.target.value)} /></label>
            <div className="grid two">
              <label className="field"><span>Category</span><input className="input" value={p.category || ""} onChange={(e) => set("category", e.target.value)} /></label>
              <label className="field"><span>Price</span><input className="input" inputMode="decimal" value={p.price || ""} onChange={(e) => set("price", e.target.value)} /></label>
              <label className="field"><span>Discount</span><input className="input" value={p.discount || ""} placeholder="20% off" onChange={(e) => set("discount", e.target.value)} /></label>
              <label className="field"><span>Shipping</span><input className="input" value={p.shipping || ""} placeholder="Free 2-day" onChange={(e) => set("shipping", e.target.value)} /></label>
            </div>
            <label className="field"><span>Product URL</span><input className="input" inputMode="url" value={p.url || ""} onChange={(e) => set("url", e.target.value)} /></label>
            <label className="field"><span>Description</span><textarea className="textarea" value={p.description || ""} onChange={(e) => set("description", e.target.value)} /></label>
          </div>
          <div className="card col">
            <div className="row between"><h3>Photos & product videos</h3>{up !== null && <span className="small muted">{Math.round(up * 100)}%</span>}</div>
            <p className="small muted" style={{ margin: 0 }}>Clear photos of the product/packaging let Rushline detect when the product is on screen.</p>
            <div className="row wrap gap-s">
              {p.photos.map((ph: any) => (
                <div key={ph.path} className="thumb" style={{ width: 84, height: 84, backgroundImage: `url(${ph.url})`, position: "relative" }}>
                  <button className="btn sm icon" style={{ position: "absolute", right: 4, top: 4, minHeight: 26, width: 26 }} onClick={() => delPhoto(ph.path)} aria-label="Remove photo"><Icon n="close" /></button>
                </div>
              ))}
              <button className="btn" style={{ width: 84, height: 84 }} onClick={() => (isNew ? toast("Save the product first", true) : file.current?.click())}><Icon n="plus" /></button>
              <input ref={file} type="file" accept="image/*" multiple hidden onChange={(e) => addPhotos(e.target.files)} />
            </div>
          </div>
          <BrollLibrary p={p} setP={setP} isNew={isNew} />
        </div>
        <div className="col gap-l">
          <div className="card col">
            <h3>Selling points</h3>
            {LISTS.slice(0, 2).map(([k, l, ph]) => (
              <label key={k} className="field"><span>{l}</span><textarea className="textarea" placeholder={ph} value={listVal(k)} onChange={(e) => set(k, e.target.value.split("\n"))} /></label>
            ))}
            <label className="field"><span>Target audience</span><input className="input" value={p.audience || ""} onChange={(e) => set("audience", e.target.value)} /></label>
          </div>
          <div className="card col">
            <div className="row"><Icon n="shield" /><h3>Claims & compliance</h3></div>
            {LISTS.slice(2).map(([k, l, ph]) => (
              <label key={k} className="field"><span>{l}</span><textarea className="textarea" placeholder={ph} value={listVal(k)} onChange={(e) => set(k, e.target.value.split("\n"))} /></label>
            ))}
            <label className="field"><span>Brand requirements</span><textarea className="textarea" value={p.brand_requirements || ""} onChange={(e) => set("brand_requirements", e.target.value)} /></label>
          </div>
          <div className="card col">
            <h3>Video preferences</h3>
            <label className="field"><span>Desired CTA</span><input className="input" value={p.cta || ""} placeholder="Tap the orange cart" onChange={(e) => set("cta", e.target.value)} /></label>
            <label className="field"><span>Desired video length (s)</span><input className="input" inputMode="numeric" value={p.desired_length || ""} onChange={(e) => set("desired_length", e.target.value)} /></label>
            <label className="field"><span>Creator notes</span><textarea className="textarea" value={p.notes || ""} onChange={(e) => set("notes", e.target.value)} /></label>
          </div>
        </div>
      </div>
    </div>
  );
}


function BrollLibrary({ p, setP, isNew }: any) {
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const [up, setUp] = useState<number | null>(null);
  const reload = () => api(`/products/${p.id}`).then(setP);
  useEffect(() => {
    if (!(p.broll || []).some((b: any) => b.status !== "ready" && b.status !== "failed")) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [p.broll]);
  const add = async (files: FileList | null) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      setUp(0);
      try {
        const q = label.trim() ? `?label=${encodeURIComponent(label.trim())}` : "";
        const r = await upload(`/products/${p.id}/broll${q}`, f, f.name || "broll.mov", setUp).promise;
        setP(r);
      } catch (e: any) { toast(e.message, true); }
    }
    setUp(null); setLabel("");
    toast("B-roll added — Rushline will cut to it when you mention what it shows");
  };
  const rename = async (b: any) => {
    const n = prompt("What does this clip show? (e.g. packaging close-up, fabric texture, before/after)", b.label);
    if (n != null) { await api(`/media/${b.id}/label`, { method: "PATCH", body: { label: n } }); reload(); }
  };
  const del = async (b: any) => { if (!confirm("Delete this B-roll clip?")) return; await api(`/media/${b.id}`, { method: "DELETE" }); reload(); };
  return (
    <div className="card col">
      <div className="row between"><h3>B-roll library</h3>{up !== null && <span className="small muted">{Math.round(up * 100)}%</span>}</div>
      <p className="small muted" style={{ margin: 0 }}>Short product shots (close-ups, packaging, texture, results). Label each one — when you say those words, Rushline cuts to it. Product photos above are used too.</p>
      {(p.broll || []).map((b: any) => (
        <div key={b.id} className="list-item">
          <div className="thumb" style={{ width: 44, height: 60, backgroundImage: b.thumb_url ? `url(${b.thumb_url})` : undefined }} />
          <div className="grow" style={{ minWidth: 0 }}><div className="ellipsis" style={{ fontWeight: 600 }}>{b.label}</div>
            <div className="tiny muted">{b.status === "ready" ? `${(b.duration || 0).toFixed(1)}s` : b.status}{b.error ? ` · ${b.error}` : ""}</div></div>
          <button className="btn ghost sm" onClick={() => rename(b)}>Label</button>
          <button className="btn ghost sm icon" onClick={() => del(b)} aria-label="Delete"><Icon n="trash" /></button>
        </div>
      ))}
      <div className="row">
        <input className="input" placeholder="Label for next clip (e.g. jar close-up)" value={label} onChange={(e) => setLabel(e.target.value)} />
        <button className="btn" onClick={() => (isNew ? toast("Save the product first", true) : file.current?.click())}><Icon n="plus" />Clip</button>
      </div>
      <input ref={file} type="file" accept="video/*,.mov,.mp4" multiple hidden onChange={(e) => add(e.target.files)} />
    </div>
  );
}
