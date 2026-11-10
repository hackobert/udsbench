/** Zentraler REST-Client für /api/v1 (Bearer-Token, einheitliches Fehlerformat). */
import * as storage from "./storage";
import type { ApiErrorDetail } from "./types";

export const API_BASE = "/api/v1";
const TOKEN_KEY = "token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Fehlerdetails (z. B. Pydantic-Validierung) als lesbare Zeilen. */
export function formatErrorDetails(details: unknown): string[] {
  if (details === null || details === undefined) return [];
  if (typeof details === "string") return [details];
  if (Array.isArray(details)) {
    return details.map((d) => {
      if (d && typeof d === "object") {
        const e = d as ApiErrorDetail;
        if (e.msg !== undefined) return e.loc ? `${e.loc}: ${e.msg}` : String(e.msg);
        return JSON.stringify(d);
      }
      return String(d);
    });
  }
  if (typeof details === "object") {
    return Object.entries(details as Record<string, unknown>).map(
      ([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`,
    );
  }
  return [String(details)];
}

export type Method = "GET" | "POST" | "PUT" | "DELETE" | "PATCH";

export type Query = Record<string, string | number | boolean | null | undefined>;

export function buildQuery(query?: Query): string {
  if (!query) return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

export class ApiClient {
  token: string | null;
  /** Wird bei HTTP 401 aufgerufen (Token-Dialog). */
  onUnauthorized: (() => void) | null = null;
  private fetchImpl: typeof fetch;

  constructor(fetchImpl?: typeof fetch) {
    this.fetchImpl = fetchImpl ?? ((...args: Parameters<typeof fetch>) => fetch(...args));
    this.token = storage.load<string | null>(TOKEN_KEY, null);
  }

  setToken(token: string | null): void {
    this.token = token && token.trim() ? token.trim() : null;
    if (this.token) storage.save(TOKEN_KEY, this.token);
    else storage.remove(TOKEN_KEY);
  }

  /** Token aus dem URL-Fragment (#token=…) übernehmen und aus der Adresse entfernen. */
  adoptTokenFromUrl(loc: Location = window.location, hist: History = window.history): boolean {
    const m = /(?:^#|&)token=([^&]+)/.exec(loc.hash);
    if (!m || !m[1]) return false;
    this.setToken(decodeURIComponent(m[1]));
    const rest = loc.hash
      .replace(/^#/, "")
      .split("&")
      .filter((p) => !p.startsWith("token="))
      .join("&");
    try {
      hist.replaceState(null, "", loc.pathname + loc.search + (rest ? `#${rest}` : ""));
    } catch {
      /* ignorieren */
    }
    return true;
  }

  headers(json: boolean): Record<string, string> {
    const h: Record<string, string> = { Accept: "application/json" };
    if (json) h["Content-Type"] = "application/json";
    if (this.token) h["Authorization"] = `Bearer ${this.token}`;
    return h;
  }

  url(path: string, query?: Query): string {
    const p = path.startsWith("/api/") ? path : API_BASE + (path.startsWith("/") ? path : `/${path}`);
    return p + buildQuery(query);
  }

  async raw(method: Method, path: string, body?: unknown, query?: Query): Promise<Response> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.url(path, query), {
        method,
        headers: this.headers(body !== undefined),
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (exc) {
      throw new ApiError(0, "network_error", `Backend nicht erreichbar (${(exc as Error).message})`);
    }
    if (!res.ok) {
      let code = "http_error";
      let message = `HTTP ${res.status}`;
      let details: unknown;
      try {
        const data = (await res.json()) as { error?: { code?: string; message?: string; details?: unknown } };
        if (data?.error) {
          code = data.error.code ?? code;
          message = data.error.message ?? message;
          details = data.error.details;
        }
      } catch {
        /* kein JSON */
      }
      if (res.status === 401 && this.onUnauthorized) this.onUnauthorized();
      throw new ApiError(res.status, code, message, details);
    }
    return res;
  }

  async request<T>(method: Method, path: string, body?: unknown, query?: Query): Promise<T> {
    const res = await this.raw(method, path, body, query);
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/json")) return (await res.json()) as T;
    return (await res.text()) as unknown as T;
  }

  get<T>(path: string, query?: Query): Promise<T> {
    return this.request<T>("GET", path, undefined, query);
  }

  post<T>(path: string, body: unknown = {}, query?: Query): Promise<T> {
    return this.request<T>("POST", path, body, query);
  }

  put<T>(path: string, body: unknown, query?: Query): Promise<T> {
    return this.request<T>("PUT", path, body, query);
  }

  del<T>(path: string, query?: Query): Promise<T> {
    return this.request<T>("DELETE", path, undefined, query);
  }

  async text(path: string, query?: Query): Promise<string> {
    const res = await this.raw("GET", path, undefined, query);
    return res.text();
  }

  /** Datei-Download über fetch (Token im Header statt in der URL). */
  async download(path: string, query: Query | undefined, fallbackName: string): Promise<void> {
    const res = await this.raw("GET", path, undefined, query);
    const cd = res.headers.get("content-disposition") ?? "";
    const m = /filename="?([^";]+)"?/.exec(cd);
    const name = m?.[1] ?? fallbackName;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /**
   * Antwort (z. B. HTML-Report) per fetch mit Token laden und als Object-URL in einem neuen Tab öffnen.
   * Das Fenster wird synchron geöffnet, damit Popup-Blocker nicht greifen.
   */
  async openInTab(path: string, query?: Query): Promise<void> {
    const w = window.open("", "_blank");
    try {
      const res = await this.raw("GET", path, undefined, query);
      const type = res.headers.get("content-type") ?? "text/html";
      const blob = new Blob([await res.arrayBuffer()], { type });
      const url = URL.createObjectURL(blob);
      if (w) w.location.href = url;
      else window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 120000);
    } catch (exc) {
      w?.close();
      throw exc;
    }
  }

  /** WebSocket-URL inkl. Token als Query-Parameter. */
  wsUrl(path: string, query?: Query, loc: Location = window.location): string {
    const proto = loc.protocol === "https:" ? "wss:" : "ws:";
    const q: Query = { ...(query ?? {}) };
    if (this.token) q["token"] = this.token;
    return `${proto}//${loc.host}${path}${buildQuery(q)}`;
  }

  health(): Promise<{ status: string; version: string; auth_required: boolean }> {
    return this.request("GET", "/api/health");
  }
}

export const api = new ApiClient();
