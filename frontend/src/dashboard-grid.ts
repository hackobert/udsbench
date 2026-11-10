/** 12-Spalten-Raster der Dashboards: Begrenzung, Kollisionserkennung und -auflösung (rein, testbar). */

export interface GridRect {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export function clampRect<T extends GridRect>(r: T, cols = 12): T {
  const w = Math.min(cols, Math.max(1, Math.round(r.w)));
  const h = Math.min(24, Math.max(1, Math.round(r.h)));
  const x = Math.min(cols - w, Math.max(0, Math.round(r.x)));
  const y = Math.max(0, Math.round(r.y));
  return { ...r, x, y, w, h };
}

export function overlaps(a: GridRect, b: GridRect): boolean {
  return a.id !== b.id && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

export function hasCollisions(rects: GridRect[]): boolean {
  for (let i = 0; i < rects.length; i++)
    for (let j = i + 1; j < rects.length; j++)
      if (overlaps(rects[i] as GridRect, rects[j] as GridRect)) return true;
  return false;
}

/**
 * Layout nach dem Verschieben/Größenändern eines Panels kollisionsfrei machen:
 * Das bewegte Panel behält seine Position, alle anderen werden (in Lesereihenfolge) so weit nach
 * unten geschoben, bis sie nichts mehr überlappen.
 */
export function resolveLayout<T extends GridRect>(rects: T[], movedId: string | null, cols = 12): T[] {
  const clamped = rects.map((r) => clampRect(r, cols));
  const moved = clamped.find((r) => r.id === movedId);
  const others = clamped.filter((r) => r.id !== movedId).sort((a, b) => a.y - b.y || a.x - b.x);
  const placed: T[] = moved ? [moved] : [];
  for (const r of others) {
    const cur = { ...r };
    for (;;) {
      const hit = placed.find((p) => overlaps(cur, p));
      if (!hit) break;
      cur.y = hit.y + hit.h;
    }
    placed.push(cur);
  }
  // ursprüngliche Reihenfolge erhalten
  return rects.map((r) => placed.find((p) => p.id === r.id) as T);
}

/** Lücken nach oben schließen (ohne Reihenfolge zu ändern). */
export function compactLayout<T extends GridRect>(rects: T[], cols = 12): T[] {
  const sorted = rects.map((r) => clampRect(r, cols)).sort((a, b) => a.y - b.y || a.x - b.x);
  const placed: T[] = [];
  for (const r of sorted) {
    const cur = { ...r };
    while (cur.y > 0 && !placed.some((p) => overlaps({ ...cur, y: cur.y - 1 }, p))) cur.y--;
    placed.push(cur);
  }
  return rects.map((r) => placed.find((p) => p.id === r.id) as T);
}

/** Erste freie Position für ein neues Panel (unterhalb aller vorhandenen, linksbündig). */
export function nextFreeSpot(rects: GridRect[], w: number, h: number, cols = 12): { x: number; y: number } {
  for (let y = 0; y < 200; y++) {
    for (let x = 0; x + w <= cols; x++) {
      const probe = { id: "__new", x, y, w, h };
      if (!rects.some((r) => overlaps(probe, r))) return { x, y };
    }
  }
  return { x: 0, y: rects.reduce((m, r) => Math.max(m, r.y + r.h), 0) };
}

/** Pixel-Verschiebung → Rasterverschiebung. */
export function pixelDeltaToCells(
  dx: number,
  dy: number,
  colStep: number,
  rowStep: number,
): { dx: number; dy: number } {
  return { dx: Math.round(dx / (colStep || 1)), dy: Math.round(dy / (rowStep || 1)) };
}

/** Eindeutige ID mit Präfix. */
export function uniqueId(prefix: string, existing: string[]): string {
  let i = 1;
  while (existing.includes(`${prefix}${i}`)) i++;
  return `${prefix}${i}`;
}
