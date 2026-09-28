import { useState } from "react";
import { fmtShort } from "../api";
import { Icon } from "../ui";

/** AI PLAN → APPLY / EDIT PLAN / CANCEL. Nothing changes until Apply. */
export function PlanCard({ plan, onApply, onCancel, busy }: { plan: any; onApply: (steps: any[], variations: any[] | null) => void; onCancel: () => void; busy?: boolean }) {
  const [on, setOn] = useState<boolean[]>(() => plan.steps.map(() => true));
  const [vOn, setVOn] = useState<boolean[]>(() => (plan.variations || []).map(() => true));
  const [edit, setEdit] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const steps = plan.steps.filter((_: any, i: number) => on[i]);
  const vars = (plan.variations || []).filter((_: any, i: number) => vOn[i]);
  const s = plan.summary;
  const nothing = !plan.steps.length && !(plan.variations || []).length;
  return (
    <div className="plan">
      <div className="row mb"><span className="badge ai"><Icon n="spark" size={12} />AI PLAN</span><b className="grow">{plan.title}</b></div>
      {plan.interpreted && <div className="tiny faint mb">Understood: {plan.interpreted.map((a: string) => a.replace(/_/g, " ")).join(" · ")}</div>}
      {plan.steps.map((st: any, i: number) => (
        <div key={i} className="step">
          {edit ? <input type="checkbox" checked={on[i]} onChange={(e) => setOn(on.map((v, j) => (j === i ? e.target.checked : v)))} /> : <Icon n="check" size={18} style={{ color: "var(--mint)", flexShrink: 0 }} />}
          <div className="grow" style={{ opacity: on[i] ? 1 : 0.45 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }} onClick={() => setOpen(open === i ? null : i)}>{st.label}{st.detail && <span className="faint"> {open === i ? "▴" : "▾"}</span>}</div>
            {open === i && st.detail && <div className="detail">{Array.isArray(st.detail) ? st.detail.join("\n") : st.detail}</div>}
          </div>
        </div>
      ))}
      {(plan.variations || []).map((v: any, i: number) => (
        <div key={i} className="step">
          <input type="checkbox" checked={vOn[i]} onChange={(e) => setVOn(vOn.map((x, j) => (j === i ? e.target.checked : x)))} />
          <div className="grow"><div style={{ fontWeight: 600, fontSize: 14 }}>Version {String.fromCharCode(65 + i)} · {v.label}</div>
            <div className="detail">{v.hook_text ? `Hook: “${v.hook_text}” (${v.hook_categories.join(", ")})` : "Best available opening"}{v.target ? ` · target ${v.target}s` : ""}</div></div>
        </div>
      ))}
      {plan.notes?.map((n: string, i: number) => <div key={i} className="note small mt"><Icon n="info" />{n}</div>)}
      {!nothing && plan.steps.length > 0 && (
        <div className="row small muted mt"><Icon n="clock" size={15} />{fmtShort(s.before)} → <b style={{ color: "var(--text)" }}>{fmtShort(s.after)}</b>{s.removed > 0.05 && <span>({fmtShort(s.removed)} removed)</span>}</div>
      )}
      {!nothing && <div className="tiny faint mt">Reversible: a checkpoint is saved first and every step can be undone individually.</div>}
      <div className="row mt">
        {!nothing && <button className="btn ai grow" disabled={busy || (!steps.length && !vars.length)} onClick={() => onApply(steps, vars.length ? vars : null)}><Icon n="check" />{busy ? "Applying…" : "Apply"}</button>}
        {plan.steps.length > 1 && <button className="btn sm" onClick={() => setEdit(!edit)}>{edit ? "Done" : "Edit plan"}</button>}
        <button className="btn ghost sm" onClick={onCancel}>{nothing ? "OK" : "Cancel"}</button>
      </div>
    </div>
  );
}
