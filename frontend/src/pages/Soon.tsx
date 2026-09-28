import { ComingSoon } from "../ui";

const COPY: Record<string, { title: string; phase: string; items: string[] }> = {
  scripts: {
    title: "Scripts", phase: "Phase 2",
    items: ["AI script generator (problem/solution, review, storytime, price hook, listicle, “my honest experience”…) sized to your target length",
      "Script quality check: hook too long, product too late, unsupported claims, repeated points",
      "Hook generator — lines for YOU to record (never put in your mouth)",
      "Recording assistant with step-by-step sections, multiple takes and a teleprompter (speed, mirror, voice-follow)",
      "Script-to-footage matching and missed-line detection"],
  },
  templates: {
    title: "Templates & style profiles", phase: "Phase 2",
    items: ["Creator style profiles (pacing, cut frequency, captions, zooms, CTA style, target length) applied automatically",
      "Reference-video mode: learn the pacing/structure of a video you like and apply the rhythm to your own footage",
      "Split-screen comparison creator & before/after layouts"],
  },
  analytics: {
    title: "Analytics & performance learning", phase: "Phase 3",
    items: ["Enter or import (official APIs only) views, hold rates, CTR, orders and GMV",
      "Patterns from your own history (“price hooks drove more clicks in your data”) — clearly labelled as correlation",
      "Post-performance review comparing structure, hook, duration and product screen time",
      "Personalized recommendations you can always override"],
  },
};

export function SoonPage({ which }: { which: string }) {
  const c = COPY[which];
  return (
    <div>
      <div className="page-head"><h1>{c.title}</h1></div>
      <ComingSoon title={`Planned for ${c.phase}`}>
        <p>This area is designed but not built yet, so nothing here pretends to work. Planned:</p>
        <ul>{c.items.map((i) => <li key={i} style={{ marginBottom: 6 }}>{i}</li>)}</ul>
      </ComingSoon>
    </div>
  );
}
