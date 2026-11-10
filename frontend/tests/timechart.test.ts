import { describe, expect, it } from "vitest";
import { renderChartSvg } from "../src/components/timechart";
import {
  type Bucket,
  groupColor,
  niceMax,
  orderGroups,
  pixelToTime,
  scaleLinear,
  stackBuckets,
  ticks,
  timeTicks,
} from "../src/timechart-math";

const buckets: Bucket[] = [
  { t: 0, counts: { positive: 3, negative: 1 }, total: 4 },
  { t: 10, counts: {}, total: 0 },
  { t: 20, counts: { negative: 2, timeout: 1 }, total: 3, latency_avg_ms: 5 },
];

describe("timechart math", () => {
  it("stacks groups in order and skips hidden ones", () => {
    const s = stackBuckets(buckets, ["positive", "negative", "timeout"]);
    expect(s[0]?.segments).toEqual([
      { group: "positive", y0: 0, y1: 3, value: 3 },
      { group: "negative", y0: 3, y1: 4, value: 1 },
    ]);
    expect(s[1]?.segments).toEqual([]);
    expect(s[2]?.total).toBe(3);
    const hidden = stackBuckets(buckets, ["positive", "negative", "timeout"], new Set(["negative"]));
    expect(hidden[0]?.total).toBe(3);
    expect(hidden[2]?.segments).toEqual([{ group: "timeout", y0: 0, y1: 1, value: 1 }]);
  });

  it("orders groups (preferred first, then by count)", () => {
    expect(orderGroups({ b: 1, negative: 5, positive: 2, a: 7 }, ["positive", "negative"])).toEqual([
      "positive",
      "negative",
      "a",
      "b",
    ]);
  });

  it("computes nice scales", () => {
    expect(niceMax(0)).toBe(1);
    expect(niceMax(3)).toBe(5);
    expect(niceMax(7)).toBe(10);
    expect(niceMax(12)).toBe(20);
    expect(niceMax(450)).toBe(500);
    expect(ticks(10, 5)).toEqual([0, 2, 4, 6, 8, 10]);
    const x = scaleLinear(0, 100, 40, 240);
    expect(x(50)).toBe(140);
    expect(pixelToTime(140, 0, 100, 40, 200)).toBe(50);
    expect(pixelToTime(-10, 0, 100, 40, 200)).toBe(0);
    expect(timeTicks(0, 300, 6)).toEqual([0, 60, 120, 180, 240, 300]);
  });

  it("uses fixed colors for semantic groups", () => {
    expect(groupColor("positive")).toBe("var(--ok)");
    expect(groupColor("negative")).toBe("var(--err)");
    expect(groupColor("timeout")).toBe("var(--warn)");
    expect(groupColor("suppressed")).toBe("var(--text-3)");
    expect(groupColor("error")).toBe("var(--run)");
    expect(groupColor("request")).toBe("var(--info)");
    expect(groupColor("FC")).not.toBe(groupColor("FF"));
    expect(groupColor("something")).toMatch(/^var\(--series-\d\)$/);
  });

  it("renders stacked bars, latency line and event markers", () => {
    const svgEl = renderChartSvg(
      { from: 0, to: 30, bucket_s: 10, groups: { positive: 3, negative: 3, timeout: 1 }, total: 7, buckets },
      [
        { ts: 15, topic: "marker", text: "M" },
        { ts: 5, topic: "uds", type: "negative" },
      ],
      { width: 400, height: 200, hidden: new Set(), showLatency: true, showEvents: true },
    );
    const rects = svgEl.querySelectorAll("rect[data-bucket]");
    expect(rects).toHaveLength(4);
    expect(svgEl.querySelector('rect[data-group="timeout"]')?.getAttribute("style")).toBe("fill:var(--warn)");
    expect(svgEl.querySelector(".tc-latency")).not.toBeNull();
    expect(svgEl.querySelectorAll("[data-event]")).toHaveLength(2);
    expect(svgEl.querySelector(".tc-marker-line")).not.toBeNull();
  });
});
