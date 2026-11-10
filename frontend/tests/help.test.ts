import { describe, expect, it, vi } from "vitest";
import { helpBus, infoIcon, setTooltips, splitTopicRef, usedHelpKeys } from "../src/help";
import { stepTarget } from "../src/app";
import { VIEWS } from "../src/views";

describe("field help (ⓘ)", () => {
  it("shows tooltip text via aria-describedby and opens the linked section on click", () => {
    setTooltips({ "uds.sprm": { text: "Unterdrückt die positive Antwort.", topic: "uds-senden#dienst" } });
    const el = infoIcon("uds.sprm");
    document.body.appendChild(el);
    const btn = el.querySelector("button")!;
    const tip = document.getElementById(btn.getAttribute("aria-describedby")!)!;
    expect(tip.getAttribute("role")).toBe("tooltip");
    expect(tip.textContent).toContain("Unterdrückt die positive Antwort.");
    const spy = vi.fn();
    const off = helpBus.on(spy);
    btn.click();
    expect(spy).toHaveBeenCalledWith({ kind: "topic", topic: "uds-senden", anchor: "dienst" });
    off();
    expect(usedHelpKeys.has("uds.sprm")).toBe(true);
  });

  it("hides the icon for unknown keys once tooltips are loaded", () => {
    expect(infoIcon("gibt.esnicht").hidden).toBe(true);
  });

  it("splits topic references", () => {
    expect(splitTopicRef("verbindung#backend")).toEqual({ topic: "verbindung", anchor: "backend" });
    expect(splitTopicRef("tests")).toEqual({ topic: "tests", anchor: null });
  });
});

describe("navigation & onboarding", () => {
  it("uses the help API context names as view ids", () => {
    const ctx = [
      "connection",
      "trace",
      "uds",
      "isotp",
      "dids",
      "dtcs",
      "routines",
      "messages",
      "sequences",
      "security",
      "tests",
      "recordings",
      "reports",
      "timechart",
      "dashboards",
      "packages",
      "logs",
      "console",
    ];
    expect(VIEWS.map((v) => v.id).sort()).toEqual([...ctx].sort());
    expect(new Set(VIEWS.map((v) => v.group))).toEqual(
      new Set(["observe", "diagnose", "automate", "evaluate", "system"]),
    );
  });

  it("maps onboarding steps to views", () => {
    expect(stepTarget("Verbinden")).toBe("connection");
    expect(stepTarget("Live-Trace ansehen")).toBe("trace");
    expect(stepTarget("Anfrage senden")).toBe("uds");
    expect(stepTarget("Test ausführen")).toBe("tests");
    expect(stepTarget("Kaffee")).toBeNull();
  });
});
