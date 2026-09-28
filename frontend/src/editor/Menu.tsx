import { ReactNode, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type MenuItem = { label: string; icon?: ReactNode; onClick: () => void; hint?: string; on?: boolean } | { section: string };

/** Button + dropdown. Uses fixed positioning so it isn't clipped by scrolling bars. */
export function Menu({ button, items, className = "qa-btn", align = "left", disabled, title }: {
  button: ReactNode; items: MenuItem[]; className?: string; align?: "left" | "right"; disabled?: boolean; title?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number }>({ top: 0 });
  const btn = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      const t = e.target as Node;
      if (box.current?.contains(t) || btn.current?.contains(t)) return;
      setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    window.addEventListener("resize", () => setOpen(false), { once: true });
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const toggle = () => {
    const r = btn.current!.getBoundingClientRect();
    const below = r.bottom + 6;
    const tooLow = below + 320 > window.innerHeight;
    setPos(align === "right"
      ? { top: tooLow ? Math.max(8, r.top - 6 - 320) : below, right: window.innerWidth - r.right }
      : { top: tooLow ? Math.max(8, r.top - 6 - 320) : below, left: Math.min(r.left, window.innerWidth - 250) });
    setOpen(!open);
  };
  return (
    <>
      <button ref={btn} className={`${className} ${open ? "open" : ""}`} onClick={toggle} disabled={disabled} title={title} aria-haspopup="menu" aria-expanded={open}>{button}</button>
      {open && createPortal(
        <div ref={box} className="menu" role="menu" style={{ position: "fixed", top: pos.top, left: pos.left, right: pos.right }}>
          {items.map((it, i) => "section" in it
            ? <div key={i} className="menu-label">{it.section}</div>
            : <button key={i} role="menuitem" className={it.on ? "on" : ""} onClick={() => { setOpen(false); it.onClick(); }}>
                {it.icon}<span className="grow" style={{ textAlign: "left" }}>{it.label}</span>{it.hint && <span className="tiny faint">{it.hint}</span>}
              </button>)}
        </div>, document.body
      )}
    </>
  );
}
