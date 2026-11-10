/** Reine Rechenfunktionen der Timechart (Skalierung, Stapelung, Farben) – ohne DOM, testbar. */

export interface Bucket {
  t: number;
  counts: Record<string, number>;
  total: number;
  latency_avg_ms?: number | null;
  latency_max_ms?: number | null;
}

export interface Timeseries {
  metric?: string;
  from: number;
  to: number;
  bucket_s: number;
  group_by?: string;
  groups: Record<string, number>;
  total: number;
  buckets: Bucket[];
}

export interface Segment {
  group: string;
  y0: number;
  y1: number;
  value: number;
}

export interface StackedBucket {
  t: number;
  total: number;
  segments: Segment[];
}

/** Gruppen nach Gesamtanzahl absteigend sortiert (stabile Reihenfolge der Stapel). */
export function orderGroups(groups: Record<string, number>, preferred: string[] = []): string[] {
  const names = Object.keys(groups);
  return names.sort((a, b) => {
    const pa = preferred.indexOf(a);
    const pb = preferred.indexOf(b);
    if (pa !== -1 || pb !== -1) return (pa === -1 ? 999 : pa) - (pb === -1 ? 999 : pb);
    return (groups[b] ?? 0) - (groups[a] ?? 0) || a.localeCompare(b);
  });
}

/** Buckets stapeln; ausgeblendete Gruppen werden weggelassen (Summe nur sichtbarer Gruppen). */
export function stackBuckets(
  buckets: Bucket[],
  groups: string[],
  hidden: Set<string> = new Set(),
): StackedBucket[] {
  return buckets.map((b) => {
    let y = 0;
    const segments: Segment[] = [];
    for (const g of groups) {
      if (hidden.has(g)) continue;
      const v = b.counts[g] ?? 0;
      if (v <= 0) continue;
      segments.push({ group: g, y0: y, y1: y + v, value: v });
      y += v;
    }
    return { t: b.t, total: y, segments };
  });
}

/** "Schöne" Obergrenze der Y-Achse (1, 2, 5 × 10^n), mindestens 1. */
export function niceMax(v: number): number {
  if (!Number.isFinite(v) || v <= 0) return 1;
  const exp = Math.floor(Math.log10(v));
  const base = 10 ** exp;
  for (const m of [1, 2, 5, 10]) {
    if (v <= m * base) return m * base;
  }
  return 10 * base;
}

/** Gleichmäßige Achsenstriche von 0 bis max (inklusive). */
export function ticks(max: number, count = 4): number[] {
  const step = max / count;
  const out: number[] = [];
  for (let i = 0; i <= count; i++) out.push(Math.round(step * i * 1000) / 1000);
  return out;
}

/** Lineare Skala d0..d1 → r0..r1. */
export function scaleLinear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Pixel → Zeit (Umkehrung der X-Skala), auf den Bereich begrenzt. */
export function pixelToTime(x: number, t0: number, t1: number, x0: number, width: number): number {
  const f = Math.min(1, Math.max(0, (x - x0) / (width || 1)));
  return t0 + f * (t1 - t0);
}

/* Diagrammfarben als CSS-Tokens (siehe styles.css: --ok/--err/… und --series-1 … --series-8). */
const FIXED: Record<string, string> = {
  // UDS-Antworttypen
  positive: "var(--ok)",
  negative: "var(--err)",
  timeout: "var(--warn)",
  suppressed: "var(--text-3)",
  error: "var(--run)",
  // Frames
  request: "var(--info)",
  FF: "var(--series-6)",
  CF: "var(--series-9)",
  FC: "var(--series-7)",
  SF: "var(--series-1)",
  segmented: "var(--series-6)",
  // Richtungen
  tx: "var(--info)",
  rx: "var(--ok)",
};

const PALETTE = [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `var(--series-${n})`);

/** Farbe einer Gruppe: feste Farben für bekannte Typen, sonst Palette per Hash. */
export function groupColor(group: string): string {
  const fixed = FIXED[group];
  if (fixed) return fixed;
  let hash = 0;
  for (let i = 0; i < group.length; i++) hash = (hash * 31 + group.charCodeAt(i)) >>> 0;
  return PALETTE[hash % PALETTE.length] ?? "var(--text-3)";
}

const TOPIC_COLORS: Record<string, string> = {
  uds: "var(--info)",
  session: "var(--series-6)",
  security: "var(--series-7)",
  run: "var(--run)",
  connection: "var(--ok)",
  isotp: "var(--warn)",
  log: "var(--err)",
  marker: "var(--series-8)",
};

export function topicColor(topic: string): string {
  return TOPIC_COLORS[topic] ?? groupColor(topic);
}

/** Zeitachsenbeschriftung hh:mm:ss. */
export function timeLabel(ts: number): string {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** Zeit-Ticks in "runden" Schritten. */
export function timeTicks(t0: number, t1: number, maxTicks = 6): number[] {
  const span = Math.max(1, t1 - t0);
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 21600, 43200, 86400];
  const step = steps.find((s) => span / s <= maxTicks) ?? 86400;
  const out: number[] = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push(t);
  return out;
}
