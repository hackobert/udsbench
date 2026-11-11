import { describe, expect, it } from "vitest";
import {
  applyPreset,
  DEFAULT_DEVICE,
  deviceToForm,
  diagnose,
  formToDevice,
  normalFixedIds,
  parseId,
  slugify,
  validateDevice,
  type DeviceForm,
} from "../src/device-model";
import { asciiFromResponse } from "../src/views/setup";
import type { UdsResult } from "../src/types";

const form = (o: Partial<DeviceForm> = {}): DeviceForm => ({
  ...DEFAULT_DEVICE,
  id: "ecu",
  name: "ECU",
  ...o,
});

describe("device model", () => {
  it("parses hex ids and slugs", () => {
    expect(parseId("7E0")).toBe(0x7e0);
    expect(parseId("0x18DA10F1")).toBe(0x18da10f1);
    expect(parseId("18 DA 10 F1")).toBe(0x18da10f1);
    expect(parseId("xyz")).toBeNull();
    expect(slugify("Motorsteuergerät Nr. 1")).toBe("motorsteuergeraet_nr_1");
  });

  it("derives normal fixed 29-bit ids", () => {
    expect(normalFixedIds(0x10, 0xf1)).toEqual({ tx: 0x18da10f1, rx: 0x18daf110, func: 0x18db33f1 });
    const f = applyPreset(form({ target_address: "10", tester_address: "F1" }), "fixed29");
    expect(f.extended_id).toBe(true);
    expect([f.tx_id, f.rx_id, f.functional_id]).toEqual(["18DA10F1", "18DAF110", "18DB33F1"]);
  });

  it("validates input", () => {
    expect(validateDevice(form())).toEqual([]);
    const fields = (f: DeviceForm, taken: string[] = []) => validateDevice(f, taken).map((p) => p.field);
    expect(fields(form({ name: "" }))).toContain("name");
    expect(fields(form(), ["ecu"])).toContain("id");
    expect(fields(form({ tx_id: "800" }))).toContain("tx_id"); // > 11 Bit
    expect(fields(form({ tx_id: "800", extended_id: true }))).not.toContain("tx_id");
    expect(fields(form({ rx_id: "7E0" }))).toContain("rx_id"); // gleich wie tx
    expect(fields(form({ addressing: "extended" }))).toContain("tx_ae");
    expect(fields(form({ padding_byte: "100" }))).toContain("padding_byte");
  });

  it("round-trips form ↔ device definition", () => {
    const f = form({ addressing: "extended", tx_ae: "2B", rx_ae: "F1", padding_byte: "FF", p2_ms: "80" });
    const dev = formToDevice(f) as { isotp: Record<string, unknown>; timing: Record<string, number> };
    expect(dev.isotp).toMatchObject({
      tx_id: 0x7e0,
      rx_id: 0x7e8,
      functional_id: 0x7df,
      addressing: "extended",
      tx_address_extension: 0x2b,
      rx_address_extension: 0xf1,
      padding: { enabled: true, byte: 0xff },
    });
    expect(dev.timing).toEqual({ p2_ms: 80 });
    const back = deviceToForm({
      id: "ecu",
      name: "ECU",
      description: "",
      package: "workspace",
      editable: true,
      demo: false,
      connected: false,
      profile: dev.isotp as never,
      definition: { timing: { p2_ms: 80 } },
    });
    expect(back).toMatchObject({
      tx_id: "7E0",
      rx_id: "7E8",
      tx_ae: "2B",
      rx_ae: "F1",
      padding_byte: "FF",
      p2_ms: "80",
    });
  });
});

describe("diagnose", () => {
  const dev = { tx_id: 0x7e0, rx_id: 0x7e8, extended_id: false };
  const res = (o: Partial<UdsResult>) => ({ positive: false, negative: false, ...o }) as UdsResult;
  const timeout = res({ error_kind: "timeout", error: "Timeout" });

  it("accepts positive and negative responses", () => {
    expect(diagnose(res({ positive: true, elapsed_ms: 3 }), null, dev).level).toBe("ok");
    expect(
      diagnose(res({ negative: true, nrc: 0x11, nrc_name: "serviceNotSupported" }), null, dev).level,
    ).toBe("ok");
  });

  it("explains timeouts using bus activity", () => {
    expect(diagnose(timeout, { frames: 0, error_frames: 0, ids: [] }, dev).title).toMatch(/nichts zu hören/);
    expect(diagnose(timeout, { frames: 0, error_frames: 5, ids: [] }, dev).title).toMatch(/Fehlerframes/);
    const busy = diagnose(
      timeout,
      {
        frames: 12,
        error_frames: 0,
        ids: [
          { id: 0x7e0, id_hex: "7E0", ext: false, count: 1 },
          { id: 0x7e9, id_hex: "7E9", ext: false, count: 1 },
          { id: 0x100, id_hex: "100", ext: false, count: 10 },
        ],
      },
      dev,
    );
    expect(busy.level).toBe("warn");
    expect(busy.candidates.map((c) => c.id)).toEqual([0x7e9, 0x100]); // eigene Anfrage ausgeblendet
    const onRx = diagnose(
      timeout,
      { frames: 2, error_frames: 0, ids: [{ id: 0x7e8, id_hex: "7E8", ext: false, count: 2 }] },
      dev,
    );
    expect(onRx.title).toMatch(/Antwort-ID kommen Daten/);
    expect(onRx.candidates).toEqual([]);
  });

  it("extracts ascii from a response", () => {
    expect(asciiFromResponse("62 F1 90 57 30 4C 30", 3)).toBe("W0L0");
  });
});
