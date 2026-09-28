import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

// ---------------------------------------------------------------- icons (original, 24px stroke set)
const P: Record<string, string> = {
  home: "M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z",
  projects: "M4 5h7l2 2h7v12H4z",
  editor: "M4 5h16v10H4zM8 19h8M12 15v4",
  products: "M4 8l8-4 8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8",
  scripts: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5",
  templates: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  analytics: "M4 20V10M10 20V4M16 20v-8M22 20H2",
  media: "M3 6h18v12H3zM3 10h18M8 6v4M16 6v4",
  exports: "M12 3v12M7 10l5 5 5-5M4 19h16",
  account: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  bag: "M6 8h12l-1 12H7zM9 8V6a3 3 0 0 1 6 0v2",
  broom: "M14 4l6 6M4 20l7-7M9 11l4 4-5 5H4v-4z",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  play: "M7 4l13 8-13 8z",
  pause: "M7 4h4v16H7zM13 4h4v16h-4z",
  back: "M15 5l-7 7 7 7",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12l5 5 9-10",
  undo: "M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  redo: "M15 14l5-5-5-5M20 9H9a5 5 0 0 0 0 10h3",
  scissors: "M6 6a2 2 0 1 0 0 .1M6 18a2 2 0 1 0 0 .1M8 7l12 10M8 17L20 7",
  trash: "M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  copy: "M8 8h12v12H8zM4 16V4h12",
  left: "M14 6l-6 6 6 6", right: "M10 6l6 6-6 6",
  zoomin: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5M11 8v6M8 11h6",
  zoomout: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5M8 11h6",
  text: "M5 6h14M12 6v13M9 19h6",
  chat: "M4 5h16v11H9l-5 4z",
  history: "M4 12a8 8 0 1 0 2.3-5.7M4 4v4h4M12 8v4l3 2",
  style: "M12 3a9 9 0 1 0 0 18c1.5 0 2-1 2-2s-1-2 0-3 3 0 5-1 2-4 2-4a9 9 0 0 0-9-8zM7.5 11.5h.01M10 7.5h.01M15 7.5h.01",
  versions: "M7 4h13v13M4 7h13v13H4z",
  insights: "M12 3a6 6 0 0 0-3 11.2V17h6v-2.8A6 6 0 0 0 12 3zM9 21h6",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  warn: "M12 4l9 16H3zM12 10v4M12 17h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  hook: "M9 3v10a4 4 0 1 0 8 0v-1M17 12l-3-3",
  wand: "M4 20L16 8M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 11l.7 1.3L21 13l-1.3.7L19 15l-.7-1.3L17 13l1.3-.7z",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 9h4M4 15h4M16 9h4M16 15h4",
  vol: "M4 9h4l5-4v14l-5-4H4zM17 9a4 4 0 0 1 0 6",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  share: "M12 3v13M7 8l5-5 5 5M5 13v8h14v-8",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  menu: "M4 7h16M4 12h16M4 17h16",
  split: "M12 3v18M5 8l-3 4 3 4M19 8l3 4-3 4",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  download: "M12 3v12M7 10l5 5 5-5M4 19h16",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  more: "M5 12h.01M12 12h.01M19 12h.01",
};
export function Icon({ n, size, style }: { n: string; size?: number; style?: any }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} style={style} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={P[n] || P.info} />
    </svg>
  );
}
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} aria-label="Rushline">
      <rect x="3" y="8" width="19" height="7" rx="3.5" fill="#F2F3F5" />
      <rect x="10" y="18" width="19" height="7" rx="3.5" fill="#FF6A3D" />
      <path d="M17.5 5.5h2.4l-5.3 22h-2.4z" fill="#0B0C0F" />
    </svg>
  );
}

export const SECTION_COLORS: Record<string, string> = {
  hook: "#FF6A3D", problem: "#FF5470", pain_point: "#E0457B", product_intro: "#3DDBB0", solution: "#2FC5E0", feature: "#6AA8FF",
  benefit: "#8B7BFF", demonstration: "#3DDB6E", social_proof: "#FFB23F", price: "#F5D547", discount: "#F2A93B", urgency: "#FF8A5B",
  objection: "#B58BFF", comparison: "#5CC8FF", cta: "#FF3DA5", other: "#5B6270", broll: "#465062",
};
export const SECTION_LABELS: Record<string, string> = {
  hook: "Hook", problem: "Problem", pain_point: "Pain point", product_intro: "Product", solution: "Solution", feature: "Feature",
  benefit: "Benefit", demonstration: "Demo", social_proof: "Social proof", price: "Price", discount: "Discount", urgency: "Urgency",
  objection: "Objection", comparison: "Comparison", cta: "CTA", other: "Other", broll: "B-roll",
};

// ---------------------------------------------------------------- toasts
type Toast = { id: number; msg: string; err?: boolean };
const ToastCtx = createContext<(msg: string, err?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((msg: string, err?: boolean) => {
    const id = Math.random();
    setItems((x) => [...x.slice(-2), { id, msg, err }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), err ? 5200 : 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.err ? "err" : ""}`}><Icon n={t.err ? "warn" : "check"} size={17} />{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ---------------------------------------------------------------- sheet (modal on desktop, bottom sheet on iPhone)
export function Sheet({ title, onClose, children, footer, wide }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", k); document.body.style.overflow = prev; };
  }, [onClose]);
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`sheet ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">
        <div className="sheet-head"><h2 className="grow">{title}</h2><button className="btn ghost icon" onClick={onClose} aria-label="Close"><Icon n="close" /></button></div>
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="switch" aria-label={label}><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /><span /></label>
  );
}

export function Seg<T extends string | number>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg">{options.map(([v, l]) => <button key={String(v)} className={v === value ? "on" : ""} onClick={() => onChange(v)}>{l}</button>)}</div>
  );
}

export function Spinner() { return <div className="spinner" />; }

export function ComingSoon({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card"><div className="row mb"><h2 className="grow">{title}</h2><span className="badge soon">COMING SOON</span></div>
      <div className="muted">{children}</div></div>
  );
}

export function Empty({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return <div className="empty"><Icon n={icon} /><h3 style={{ color: "var(--text)" }}>{title}</h3><div className="small mt">{children}</div></div>;
}
