import { describe, expect, it } from "vitest";
import {
  clampRect,
  compactLayout,
  hasCollisions,
  nextFreeSpot,
  overlaps,
  pixelDeltaToCells,
  resolveLayout,
  uniqueId,
} from "../src/dashboard-grid";
import { dashboardPayload } from "../src/views/dashboards";

const r = (id: string, x: number, y: number, w: number, h: number) => ({ id, x, y, w, h });

describe("dashboard grid layout", () => {
  it("clamps panels into the 12-column grid", () => {
    expect(clampRect(r("a", 10, -2, 6, 0))).toEqual(r("a", 6, 0, 6, 1));
    expect(clampRect(r("a", -3, 1, 20, 2))).toEqual(r("a", 0, 1, 12, 2));
  });

  it("detects overlaps", () => {
    expect(overlaps(r("a", 0, 0, 4, 3), r("b", 3, 2, 4, 3))).toBe(true);
    expect(overlaps(r("a", 0, 0, 4, 3), r("b", 4, 0, 4, 3))).toBe(false);
    expect(overlaps(r("a", 0, 0, 4, 3), r("b", 0, 3, 4, 3))).toBe(false);
  });

  it("resolves collisions after a move by pushing others down", () => {
    const layout = [r("a", 0, 0, 4, 3), r("b", 4, 0, 8, 3), r("c", 0, 3, 4, 3), r("d", 4, 3, 8, 3)];
    // a wird auf die Position von d gezogen
    const moved = layout.map((p) => (p.id === "a" ? { ...p, x: 6, y: 3 } : p));
    const out = resolveLayout(moved, "a");
    expect(hasCollisions(out)).toBe(false);
    expect(out.find((p) => p.id === "a")).toEqual(r("a", 6, 3, 4, 3));
    expect(out.find((p) => p.id === "b")).toEqual(r("b", 4, 0, 8, 3));
    expect(out.find((p) => p.id === "d")!.y).toBeGreaterThanOrEqual(6);
    expect(out.map((p) => p.id)).toEqual(["a", "b", "c", "d"]);
  });

  it("stays collision-free for many random moves/resizes", () => {
    let layout = Array.from({ length: 8 }, (_, i) => r(`p${i}`, (i % 3) * 4, Math.floor(i / 3) * 3, 4, 3));
    let seed = 42;
    const rnd = (n: number) => {
      seed = (seed * 1103515245 + 12345) % 2 ** 31;
      return seed % n;
    };
    for (let k = 0; k < 200; k++) {
      const p = layout[rnd(layout.length)]!;
      const cand = { ...p, x: rnd(14) - 1, y: rnd(10), w: 1 + rnd(12), h: 1 + rnd(5) };
      layout = resolveLayout(
        layout.map((x) => (x.id === p.id ? cand : x)),
        p.id,
      );
      expect(hasCollisions(layout)).toBe(false);
      for (const q of layout) expect(q.x + q.w).toBeLessThanOrEqual(12);
    }
    expect(hasCollisions(compactLayout(layout))).toBe(false);
  });

  it("compacts gaps upwards", () => {
    expect(compactLayout([r("a", 0, 5, 4, 2), r("b", 0, 9, 4, 2)])).toEqual([
      r("a", 0, 0, 4, 2),
      r("b", 0, 2, 4, 2),
    ]);
  });

  it("finds a free spot for new panels", () => {
    expect(nextFreeSpot([r("a", 0, 0, 4, 3), r("b", 4, 0, 8, 3)], 4, 3)).toEqual({ x: 0, y: 3 });
    expect(nextFreeSpot([r("a", 0, 0, 4, 3)], 4, 3)).toEqual({ x: 4, y: 0 });
  });

  it("converts pixel deltas and generates ids", () => {
    expect(pixelDeltaToCells(130, -95, 60, 90)).toEqual({ dx: 2, dy: -1 });
    expect(uniqueId("buttons_", ["buttons_1", "buttons_2"])).toBe("buttons_3");
  });

  it("serializes dashboards without server-only fields", () => {
    const d = dashboardPayload({
      id: "x",
      name: "X",
      description: "",
      columns: 12,
      source: "user",
      editable: true,
      panels: [
        { id: "p", title: "", type: "note", x: 0, y: 0, w: 4, h: 2, buttons: [], config: { text: "hi" } },
      ],
    });
    expect(d).not.toHaveProperty("source");
    expect(d).not.toHaveProperty("editable");
    expect(d.panels[0]?.config).toEqual({ text: "hi" });
  });
});
