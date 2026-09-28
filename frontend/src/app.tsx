import { createContext, useContext, useEffect, useState } from "react";

// ---------------------------------------------------------------- hash router (works from Home Screen / offline shell)
export function useRoute() {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const f = () => setHash(location.hash || "#/");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  const [path, qs] = hash.slice(1).split("?");
  return { path: path || "/", parts: (path || "/").split("/").filter(Boolean), query: new URLSearchParams(qs || "") };
}
export const go = (to: string) => { location.hash = to; };

export type User = { id: string; email: string; name: string; plan: string; limits: any };
export const UserCtx = createContext<{ user: User | null; setUser: (u: User | null) => void; meta: any }>({ user: null, setUser: () => {}, meta: null });
export const useUser = () => useContext(UserCtx);

