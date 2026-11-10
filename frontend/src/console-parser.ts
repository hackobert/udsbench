/** Konsolen-Parser: Eingabezeile → API-Operation (1:1) plus curl-Äquivalent. */
import type { Method } from "./api";
import { API_BASE } from "./api";

export type ConsoleCommand =
  | { kind: "api"; method: Method; path: string; body?: unknown; label?: string }
  | { kind: "help" }
  | { kind: "clear" }
  | { kind: "error"; message: string };

const METHODS: Method[] = ["GET", "POST", "PUT", "DELETE", "PATCH"];

const RUN_KINDS: Record<string, string> = {
  test: "tests",
  tests: "tests",
  suite: "testsuites",
  testsuite: "testsuites",
  sequence: "sequences",
  seq: "sequences",
};

/** Pfad relativ zu /api/v1 normalisieren ("info" → "/info"; "/api/health" bleibt absolut). */
export function normalizePath(p: string): string {
  let path = p.trim();
  if (!path.startsWith("/")) path = `/${path}`;
  if (path.startsWith(API_BASE + "/") || path === API_BASE) path = path.slice(API_BASE.length) || "/";
  return path;
}

/** Vollständiger URL-Pfad für fetch/curl. */
export function fullPath(path: string): string {
  return path.startsWith("/api/") ? path : API_BASE + path;
}

export function parseCommand(input: string): ConsoleCommand {
  const line = input.trim();
  if (!line) return { kind: "error", message: "Leere Eingabe" };
  const [head = "", ...rest] = line.split(/\s+/);
  const word = head.toLowerCase();

  if (word === "help" || word === "?" || word === "hilfe") return { kind: "help" };
  if (word === "clear" || word === "cls") return { kind: "clear" };

  const upper = head.toUpperCase() as Method;
  if (METHODS.includes(upper)) {
    const after = line.slice(head.length).trim();
    if (!after) return { kind: "error", message: `${upper}: Pfad fehlt (z. B. ${upper} /info)` };
    const m = /^(\S+)\s*([\s\S]*)$/.exec(after);
    const path = normalizePath(m?.[1] ?? "");
    const bodyText = (m?.[2] ?? "").trim();
    if (!bodyText) {
      return upper === "POST" || upper === "PUT" || upper === "PATCH"
        ? { kind: "api", method: upper, path, body: {} }
        : { kind: "api", method: upper, path };
    }
    try {
      return { kind: "api", method: upper, path, body: JSON.parse(bodyText) as unknown };
    } catch (exc) {
      return { kind: "error", message: `Ungültiger JSON-Body: ${(exc as Error).message}` };
    }
  }

  if (word === "uds") {
    const args = [...rest];
    let functional = false;
    for (const flag of ["--functional", "-f", "--func"]) {
      const i = args.indexOf(flag);
      if (i >= 0) {
        functional = true;
        args.splice(i, 1);
      }
    }
    const [ecu, ...hex] = args;
    if (!ecu || !hex.length) return { kind: "error", message: "Syntax: uds <ecu> <hex…> [--functional]" };
    const body: Record<string, unknown> = { ecu, payload: hex.join(" ").toUpperCase() };
    if (functional) body["functional"] = true;
    return { kind: "api", method: "POST", path: "/uds/request", body };
  }

  if (word === "send") {
    const [id] = rest;
    if (!id) return { kind: "error", message: "Syntax: send <message-id>" };
    return { kind: "api", method: "POST", path: `/messages/${encodeURIComponent(id)}/send`, body: {} };
  }

  if (word === "run") {
    const [kind = "", id] = rest;
    const coll = RUN_KINDS[kind.toLowerCase()];
    if (!coll || !id) return { kind: "error", message: "Syntax: run test|suite|sequence <id>" };
    return { kind: "api", method: "POST", path: `/${coll}/${encodeURIComponent(id)}/run`, body: {} };
  }

  return { kind: "error", message: `Unbekannter Befehl '${head}' – 'help' zeigt die Syntax` };
}

function shellQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

/** Äquivalentes curl-Kommando (Token als Umgebungsvariable statt Klartext). */
export function toCurl(
  cmd: { method: Method; path: string; body?: unknown },
  origin: string,
  withToken: boolean,
): string {
  const parts = ["curl -s"];
  if (cmd.method !== "GET") parts.push(`-X ${cmd.method}`);
  parts.push(shellQuote(origin.replace(/\/$/, "") + fullPath(cmd.path)));
  if (withToken) parts.push(`-H "Authorization: Bearer $UDSBENCH_TOKEN"`);
  if (cmd.body !== undefined) {
    parts.push(`-H 'Content-Type: application/json'`);
    parts.push(`-d ${shellQuote(JSON.stringify(cmd.body))}`);
  }
  return parts.join(" ");
}

export const CONSOLE_HELP = [
  "GET /info                                   – beliebige API-Operation (Pfad relativ zu /api/v1)",
  'POST /uds/request {"ecu":"ecu_a","payload":"22 F1 00"}',
  "uds <ecu> <hex…> [--functional]            – UDS-Request senden",
  "send <message-id>                           – vordefinierte Botschaft senden",
  "run test|suite|sequence <id>                – Lauf starten",
  "clear                                       – Ausgabe leeren",
  "help                                        – diese Hilfe",
  "↑/↓ blättert im Verlauf",
];
