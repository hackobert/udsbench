import { describe, expect, it } from "vitest";
import { matchesSearch, relTime, toWsFilter, traceCells, traceRowClass } from "../src/trace-format";
import type { TraceFrame, TraceMessage } from "../src/types";

const frame = (over: Partial<TraceFrame>): TraceFrame => ({
  kind: "frame",
  seq: 1,
  ts: 100,
  channel: "default",
  dir: "tx",
  id: 0x700,
  id_hex: "700",
  dlc: 8,
  data: "02 10 03 CC CC CC CC CC",
  ascii: "........",
  pci: "SF",
  uds: "request",
  text: "DiagnosticSessionControl",
  ...over,
});

describe("trace row coloring", () => {
  it("classifies single frames by UDS semantics", () => {
    expect(traceRowClass(frame({}))).toContain("t-req");
    expect(traceRowClass(frame({ uds: "positive", dir: "rx" }))).toContain("t-pos");
    expect(traceRowClass(frame({ uds: "negative", dir: "rx" }))).toContain("t-neg");
    expect(traceRowClass(frame({ dir: "rx" }))).toContain("dir-rx");
  });

  it("classifies FF/CF/FC frames", () => {
    expect(traceRowClass(frame({ pci: "FF", uds: "segmented" }))).toContain("t-ff");
    expect(traceRowClass(frame({ pci: "CF", uds: null }))).toContain("t-cf");
    expect(traceRowClass(frame({ pci: "FC", uds: null }))).toContain("t-fc");
    expect(traceRowClass(frame({ pci: null, uds: null }))).toContain("t-other");
    expect(traceRowClass(frame({ err: true }))).toContain("t-err");
  });

  it("classifies reconstructed messages", () => {
    const m: TraceMessage = {
      kind: "message",
      seq: 2,
      ts: 101,
      channel: "default",
      dir: "rx",
      can_id: 0x708,
      frames: 3,
      payload: "62 F1 00 41",
      len: 4,
      uds: "positive",
    };
    const cls = traceRowClass(m);
    expect(cls).toContain("t-pos");
    expect(cls).toContain("t-multi");
    expect(traceRowClass({ ...m, uds: "negative" })).toContain("t-neg");
    expect(traceRowClass({ ...m, uds: "request" })).toContain("t-req");
    const c = traceCells(m, 100);
    expect(c.id).toBe("708");
    expect(c.ascii).toBe("b··A");
    expect(c.time).toBe("1.000");
  });

  it("formats relative time and search", () => {
    expect(relTime(10.5, 10)).toBe("0.500");
    expect(relTime(9, 10)).toBe("0.000");
    expect(matchesSearch(frame({}), "session")).toBe(true);
    expect(matchesSearch(frame({}), "zzz")).toBe(false);
  });

  it("builds the server-side WS filter", () => {
    expect(
      toWsFilter({
        ids: "700, 0x708",
        data_contains: " F1 00 ",
        direction: "rx",
        services: "22",
        only_uds: true,
      }),
    ).toEqual({
      ids: ["0x700", "0x708"],
      services: ["0x22"],
      direction: "rx",
      data_contains: "F1 00",
      only_uds: true,
    });
    expect(toWsFilter({ ids: "", data_contains: "", direction: "", services: "", only_uds: false })).toEqual(
      {},
    );
  });
});
