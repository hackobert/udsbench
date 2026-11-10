import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, buildQuery, formatErrorDetails } from "../src/api";
import { viewIndexForKey } from "../src/app";
import { h } from "../src/dom";
import { t, setLang } from "../src/i18n";
import { reportBody, toLocalInput, fromLocalInput } from "../src/views/reports";
import { ReconnectingSocket } from "../src/ws";

afterEach(() => setLang("de"));

describe("dom & i18n", () => {
  it("creates elements with attrs, events and children", () => {
    const fn = vi.fn();
    const el = h(
      "button",
      { class: ["a", false, "b"], dataset: { x: "1" }, onclick: fn, disabled: false, title: "T" },
      "x",
      1,
      null,
      [h("span", null, "y")],
    );
    expect(el.className).toBe("a b");
    expect(el.dataset["x"]).toBe("1");
    expect(el.textContent).toBe("x1y");
    el.click();
    expect(fn).toHaveBeenCalled();
  });

  it("translates with placeholders and falls back to German", () => {
    expect(t("trace.dropped", { n: 5 })).toBe("verworfen: 5");
    setLang("en");
    expect(t("nav.uds")).toBe("Send UDS");
    expect(t("dtc.clearConfirm", { ecu: "A", group: "FF" })).toContain("A");
  });
});

describe("api client", () => {
  it("adds bearer token and maps error format", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: "not_found", message: "weg", details: { id: "x" } } }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
    );
    const api = new ApiClient(fetchMock as unknown as typeof fetch);
    api.setToken("abc");
    await expect(api.get("/ecus")).rejects.toMatchObject({ status: 404, code: "not_found", message: "weg" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/ecus");
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer abc");
    api.setToken(null);
  });

  it("calls onUnauthorized on 401 and adopts token from URL", async () => {
    const api = new ApiClient((async () => new Response("{}", { status: 401 })) as unknown as typeof fetch);
    const spy = vi.fn();
    api.onUnauthorized = spy;
    await expect(api.get("/info")).rejects.toBeInstanceOf(ApiError);
    expect(spy).toHaveBeenCalled();
    const replace = vi.fn();
    const ok = api.adoptTokenFromUrl(
      { hash: "#token=s3cr%3Dt&x=1", pathname: "/", search: "" } as Location,
      { replaceState: replace } as unknown as History,
    );
    expect(ok).toBe(true);
    expect(api.token).toBe("s3cr=t");
    expect(replace).toHaveBeenCalledWith(null, "", "/#x=1");
    expect(api.wsUrl("/ws/trace", undefined, { protocol: "https:", host: "h:1" } as Location)).toBe(
      "wss://h:1/ws/trace?token=s3cr%3Dt",
    );
    api.setToken(null);
  });

  it("formats queries and error details", () => {
    expect(buildQuery({ a: 1, b: "", c: undefined, d: "x y" })).toBe("?a=1&d=x%20y");
    expect(formatErrorDetails([{ loc: "body.x", msg: "bad" }])).toEqual(["body.x: bad"]);
    expect(formatErrorDetails({ k: "v" })).toEqual(["k: v"]);
  });
});

describe("ws reconnect", () => {
  it("reconnects with backoff after close", () => {
    vi.useFakeTimers();
    const instances: { onclose: ((e: { code: number }) => void) | null; onopen: (() => void) | null }[] = [];
    class FakeWs {
      onopen: (() => void) | null = null;
      onclose: ((e: { code: number }) => void) | null = null;
      onmessage = null;
      onerror = null;
      readyState = 0;
      constructor() {
        instances.push(this);
      }
      close() {}
      send() {}
    }
    const s = new ReconnectingSocket(
      () => "ws://x",
      { onMessage: () => undefined },
      { WebSocketImpl: FakeWs as unknown as typeof WebSocket, minDelayMs: 100 },
    );
    s.start();
    expect(instances).toHaveLength(1);
    instances[0]!.onclose?.({ code: 1006 });
    expect(s.state).toBe("closed");
    vi.advanceTimersByTime(100);
    expect(instances).toHaveLength(2);
    instances[1]!.onopen?.();
    expect(s.state).toBe("open");
    s.stop();
    vi.useRealTimers();
  });
});

describe("misc helpers", () => {
  it("maps Alt+digit to view index", () => {
    expect(viewIndexForKey("1")).toBe(0);
    expect(viewIndexForKey("0")).toBe(9);
    expect(viewIndexForKey("a")).toBeNull();
  });

  it("builds report request bodies", () => {
    const body = reportBody({
      title: "",
      from: 1000,
      to: 1300,
      ecu: "ecu_a",
      notes: "n",
      author: "me",
      include: {
        stats: true,
        events: true,
        runs: false,
        messages: true,
        frames: true,
        logs: false,
        recordings: true,
      },
      trace_formats: ["asc"],
      run_ids: [],
    });
    expect(body).toMatchObject({
      title: "Diagnose-Report",
      from: 1000,
      to: 1300,
      ecu: "ecu_a",
      trace_formats: ["asc"],
    });
    expect(body).not.toHaveProperty("run_ids");
    expect(() =>
      reportBody({
        title: "x",
        from: 5,
        to: 5,
        ecu: null,
        notes: "",
        author: "",
        include: {} as never,
        trace_formats: [],
        run_ids: [],
      }),
    ).toThrow();
    expect(Math.round(fromLocalInput(toLocalInput(1794318000)))).toBe(1794318000);
  });
});
