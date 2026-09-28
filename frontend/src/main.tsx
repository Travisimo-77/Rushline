import "./styles.css";
import { useEffect, useState } from "react";
import { go, useRoute, UserCtx, User, useUser } from "./app";
import { createRoot } from "react-dom/client";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { Icon, Logo, Sheet, ToastProvider } from "./ui";
import { AuthPage } from "./pages/Auth";
import { HomePage } from "./pages/Home";
import { ProjectsPage } from "./pages/Projects";
import { ProductsPage } from "./pages/Products";
import { MediaPage } from "./pages/Media";
import { ExportsPage } from "./pages/Exports";
import { AccountPage } from "./pages/Account";
import { SoonPage } from "./pages/Soon";
import { AnalyticsPage } from "./pages/Analytics";
import { Editor } from "./editor/Editor";
import { NewProjectSheet } from "./pages/NewProject";

const NAV_GROUPS: [string, [string, string, string][]][] = [
  ["Workspace", [["/", "home", "Home"], ["/projects", "projects", "Projects"], ["/products", "products", "Products"]]],
  ["Publish", [["/exports", "exports", "Exports"], ["/analytics", "analytics", "Analytics"]]],
  ["Library", [["/media", "media", "Media"]]],
];
const MORE = [["/products", "products", "Products"], ["/analytics", "analytics", "Analytics"], ["/media", "media", "Media library"],
  ["/account", "account", "Account"]];

function initials(u: User | null) {
  const s = (u?.name || u?.email || "?").trim();
  const p = s.split(/[\s@.]+/).filter(Boolean);
  return ((p[0]?.[0] || "") + (p[1]?.[0] || "")).toUpperCase() || "?";
}

function Shell() {
  const r = useRoute();
  const { user } = useUser();
  const [more, setMore] = useState(false);
  const [creating, setCreating] = useState(false);
  const top = "/" + (r.parts[0] || "");
  useEffect(() => setMore(false), [r.path]);
  if (r.parts[0] === "edit" && r.parts[1]) return <Editor projectId={r.parts[1]} versionParam={r.query.get("v")} />;
  let page;
  switch (top) {
    case "/": page = <HomePage />; break;
    case "/projects": page = <ProjectsPage />; break;
    case "/editor": page = <EditorLauncher />; break;
    case "/products": page = <ProductsPage id={r.parts[1]} />; break;
    case "/media": page = <MediaPage />; break;
    case "/exports": page = <ExportsPage />; break;
    case "/account": page = <AccountPage />; break;
    case "/analytics": page = <AnalyticsPage />; break;
    case "/scripts": case "/templates": page = <SoonPage which={top.slice(1)} />; break;
    default: page = <HomePage />;
  }
  const inMore = MORE.some(([to]) => to === top);
  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <a className="brand" href="#/"><Logo />Rushline</a>
        <button className="btn primary rail-new" onClick={() => setCreating(true)}><Icon n="plus" />New project</button>
        {NAV_GROUPS.map(([label, items]) => (
          <div key={label} className="nav-group">
            <div className="nav-label">{label}</div>
            {items.map(([to, ic, l]) => (
              <a key={to} href={`#${to}`} className={`nav-item ${top === to ? "active" : ""}`}><Icon n={ic} />{l}</a>
            ))}
          </div>
        ))}
        <span className="grow" />
        <a href="#/account" className={`user-card ${top === "/account" ? "active" : ""}`}>
          <span className="avatar">{initials(user)}</span>
          <span className="grow" style={{ minWidth: 0 }}><span className="ellipsis" style={{ display: "block", fontWeight: 650, fontSize: 13.5 }}>{user?.name || user?.email}</span>
            <span className="tiny faint" style={{ textTransform: "capitalize" }}>{user?.plan} plan</span></span>
          <Icon n="more" size={18} />
        </a>
      </nav>
      <div className="mobile-top">
        <a className="brand sm" href="#/"><Logo size={24} />Rushline</a>
        <a href="#/account" className="avatar" aria-label="Account">{initials(user)}</a>
      </div>
      <main className="main">{page}</main>
      <nav className="tabbar" aria-label="Tabs">
        <a href="#/" className={top === "/" ? "active" : ""}><Icon n="home" />Home</a>
        <a href="#/projects" className={top === "/projects" ? "active" : ""}><Icon n="projects" />Projects</a>
        <button className="tab-create" onClick={() => { setMore(false); setCreating(true); }} aria-label="New project"><Icon n="plus" /></button>
        <a href="#/exports" className={top === "/exports" ? "active" : ""}><Icon n="exports" />Exports</a>
        <button className={inMore || more ? "active" : ""} onClick={() => setMore(!more)}><Icon n="menu" />More</button>
      </nav>
      {creating && <NewProjectSheet kind="blank" onClose={() => setCreating(false)} />}
      {more && (
        <Sheet title="More" onClose={() => setMore(false)}>
          <div className="col gap-s">
            {MORE.map(([to, ic, l]) => (
              <a key={to} href={`#${to}`} className={`nav-item big ${top === to ? "active" : ""}`}><Icon n={ic} />{l}</a>
            ))}
          </div>
        </Sheet>
      )}
    </div>
  );
}

function EditorLauncher() {
  useEffect(() => {
    api("/projects").then((ps: any[]) => go(ps[0] ? `/edit/${ps[0].id}` : "/projects?new=1")).catch(() => go("/projects"));
  }, []);
  return <div className="empty">Opening your latest project…</div>;
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [meta, setMeta] = useState<any>(null);
  useEffect(() => {
    setUnauthorizedHandler(() => { setToken(null); setUser(null); });
    api("/meta").then(setMeta).catch(() => {});
    if (!getToken()) { setReady(true); return; }
    api<User>("/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setReady(true));
  }, []);
  if (!ready) return <div className="auth"><Logo size={48} /></div>;
  return (
    <UserCtx.Provider value={{ user, setUser, meta }}>
      {user ? <Shell /> : <AuthPage onAuthed={(u, t) => { setToken(t); setUser(u); }} />}
    </UserCtx.Provider>
  );
}

createRoot(document.getElementById("root")!).render(<ToastProvider><App /></ToastProvider>);

// PWA: service worker needs a secure context (https or localhost)
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
