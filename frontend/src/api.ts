// API client: JSON calls with bearer token + resumable-friendly raw uploads with progress (works on iPhone Safari).
const TOKEN_KEY = "rl_token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
export function setToken(t: string | null) {
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) { super(msg); this.status = status; }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

export async function api<T = any>(path: string, opts: { method?: string; body?: any; retries?: number } = {}): Promise<T> {
  const method = opts.method || (opts.body !== undefined ? "POST" : "GET");
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let lastErr: any;
  // retry transient network failures (flaky mobile connections) for idempotent-safe calls
  const retries = opts.retries ?? (method === "GET" ? 2 : 1);
  for (let i = 0; i <= retries; i++) {
    try {
      const r = await fetch(`/api/v1${path}`, { method, headers, body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
      const data = await r.json().catch(() => ({}));
      if (r.status === 401) { onUnauthorized(); throw new ApiError(401, data.error || "Please sign in."); }
      if (!r.ok) throw new ApiError(r.status, data.error || `Request failed (${r.status})`);
      return data as T;
    } catch (e: any) {
      lastErr = e;
      if (e instanceof ApiError) throw e;
      await new Promise((res) => setTimeout(res, 600 * (i + 1)));
    }
  }
  throw new ApiError(0, "Network error — check your connection.");
}

export function upload(path: string, file: File | Blob, filename: string, onProgress: (p: number) => void): { promise: Promise<any>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<any>((resolve, reject) => {
    xhr.open("POST", `/api/v1${path}${path.includes("?") ? "&" : "?"}filename=${encodeURIComponent(filename)}`);
    const t = getToken();
    if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data: any = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* */ }
      xhr.status >= 200 && xhr.status < 300 ? resolve(data) : reject(new ApiError(xhr.status, data.error || "Upload failed"));
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed — connection lost."));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}

export const fmt = (t: number | null | undefined) => {
  if (t == null || isNaN(t)) return "–";
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
};
export const fmtShort = (t: number) => (t >= 60 ? `${Math.floor(t / 60)}m ${Math.round(t % 60)}s` : `${t.toFixed(t < 10 ? 1 : 0)}s`);
export const ago = (ts: number) => {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
};
export const isIOS = () => /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
export const isStandalone = () => (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || (navigator as any).standalone === true;
