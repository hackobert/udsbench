import { describe, expect, it } from "vitest";
import { channelForInterface } from "../src/views/connection";

describe("channelForInterface", () => {
  it("ersetzt Vorgaben anderer Interfaces durch die passende", () => {
    expect(channelForInterface("pcan", "can0")).toBe("PCAN_USBBUS1");
    expect(channelForInterface("socketcan", "PCAN_USBBUS1")).toBe("can0");
    expect(channelForInterface("pcan", "")).toBe("PCAN_USBBUS1");
  });
  it("lässt eigene Eingaben und unbekannte Interfaces unverändert", () => {
    expect(channelForInterface("pcan", "PCAN_USBBUS2")).toBe("PCAN_USBBUS2");
    expect(channelForInterface("slcan", "COM5")).toBe("COM5");
  });
});
