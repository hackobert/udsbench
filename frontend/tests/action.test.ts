import { describe, expect, it } from "vitest";
import { actionToForm, buildAction, emptyForm, matchShortcut, parseShortcut } from "../src/action-model";
import { resultTone } from "../src/components/action-result";

describe("action editor → action JSON", () => {
  it("builds a message action with only relevant fields", () => {
    const f = { ...emptyForm("message"), ref: "read_identifier", payload: "ignored", can_id: "700" };
    expect(buildAction(f)).toEqual({ type: "message", ref: "read_identifier" });
  });

  it("builds uds/raw/unlock/session/step/report actions", () => {
    expect(
      buildAction({
        ...emptyForm("uds"),
        ecu: "ecu_a",
        payload: "22 F1 00",
        functional: true,
        vars: '{"a":1}',
      }),
    ).toEqual({
      type: "uds",
      ecu: "ecu_a",
      payload: "22 F1 00",
      functional: true,
      vars: { a: 1 },
    });
    expect(buildAction({ ...emptyForm("raw"), can_id: "7DF", payload: "02 3E 00", channel: "can1" })).toEqual(
      {
        type: "raw",
        can_id: "0x7DF",
        payload: "02 3E 00",
        channel: "can1",
      },
    );
    expect(buildAction({ ...emptyForm("unlock"), ref: "1", ecu: "ecu_a", confirm: true })).toEqual({
      type: "unlock",
      ref: 1,
      ecu: "ecu_a",
      confirm: true,
    });
    expect(buildAction({ ...emptyForm("session"), ref: "3" })).toEqual({ type: "session", ref: 3 });
    expect(buildAction({ ...emptyForm("step"), step: '{"read_did":"0xF100"}' })).toEqual({
      type: "step",
      step: { read_did: "0xF100" },
    });
    expect(buildAction({ ...emptyForm("report"), report: '{"title":"R","from":"-5m"}' })).toEqual({
      type: "report",
      report: { title: "R", from: "-5m" },
    });
    expect(buildAction({ ...emptyForm("record_stop") })).toEqual({ type: "record_stop" });
    expect(buildAction({ ...emptyForm("marker"), ref: "Start" })).toEqual({ type: "marker", ref: "Start" });
  });

  it("rejects incomplete actions", () => {
    expect(() => buildAction(emptyForm("message"))).toThrow(/ref/);
    expect(() => buildAction(emptyForm("uds"))).toThrow(/Nutzlast/);
    expect(() => buildAction({ ...emptyForm("raw"), payload: "00" })).toThrow(/CAN-ID/);
    expect(() => buildAction(emptyForm("step"))).toThrow(/Schritt/);
    expect(() => buildAction({ ...emptyForm("uds"), payload: "22", vars: "{x" })).toThrow(/vars/);
    expect(() => buildAction({ ...emptyForm("uds"), payload: "22", vars: "[1]" })).toThrow(/Objekt/);
  });

  it("round-trips action ↔ form", () => {
    const a = {
      type: "uds" as const,
      ecu: "ecu_b",
      payload: "10 03",
      functional: true,
      confirm: true,
      vars: { x: 2 },
    };
    expect(buildAction(actionToForm(a))).toEqual(a);
    expect(actionToForm(null).type).toBe("message");
  });

  it("parses and matches shortcuts", () => {
    const sc = parseShortcut("Ctrl+Shift+1")!;
    expect(sc).toEqual({ ctrl: true, alt: false, shift: true, meta: false, key: "1" });
    expect(
      matchShortcut(
        { key: "!", code: "Digit1", ctrlKey: true, shiftKey: true, altKey: false, metaKey: false },
        sc,
      ),
    ).toBe(true);
    expect(
      matchShortcut({ key: "1", ctrlKey: false, shiftKey: true, altKey: false, metaKey: false }, sc),
    ).toBe(false);
    expect(parseShortcut("")).toBeNull();
  });

  it("derives result tone", () => {
    expect(resultTone({ status: "passed", result: { positive: true, negative: false, error: null } })).toBe(
      "ok",
    );
    expect(resultTone({ status: "passed", result: { positive: false, negative: true, error: null } })).toBe(
      "fail",
    );
    expect(resultTone({ status: "started", run_id: "r" })).toBe("run");
    expect(resultTone({ status: "failed" })).toBe("fail");
  });
});
