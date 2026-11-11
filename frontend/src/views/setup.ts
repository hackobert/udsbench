/**
 * Einrichtungsassistent: führt Schritt für Schritt von „nichts eingerichtet“ zur ersten Antwort
 * eines echten Steuergeräts – oder startet die Demo. Auch für „Neues Gerät“ / „Gerät bearbeiten“.
 */
import { ApiError } from "../api";
import { toast, toastError } from "../components/toast";
import { badge, button, checkbox, field, numberInput, select, textInput } from "../components/ui";
import {
  applyPreset,
  DEFAULT_DEVICE,
  deviceToForm,
  diagnose,
  formToDevice,
  hex,
  parseId,
  slugify,
  syncFixed29,
  validateDevice,
  type BusActivity,
  type DeviceForm,
  type DeviceInfo,
  type Diagnosis,
  type PresetId,
} from "../device-model";
import { type Child, h, replace } from "../dom";
import { openHelpTopic } from "../help";
import { t, type MsgKey } from "../i18n";
import * as storage from "../storage";
import type { UdsResult } from "../types";
import type { AppCtx, View } from "../view";
import { channelForInterface } from "./connection";

// --- Einstiegspunkte von außen (Geräte-Ansicht, Banner, Erste Schritte) ---------------------------

export type SetupIntent = { mode: "full" } | { mode: "device"; ecu?: string } | { mode: "test"; ecu: string };

let pendingIntent: SetupIntent | null = null;

/** Beim nächsten Öffnen der Einrichtung mit diesem Ziel starten. */
export function requestSetup(intent: SetupIntent): void {
  pendingIntent = intent;
}

export interface SetupStatus {
  completed: boolean;
  demo: { available: boolean; active: boolean; packages: string[] };
  devices: { own: number; demo: number };
  saved_connections: { name: string; backend: string; options: Record<string, unknown> }[];
  config_connections: unknown[];
}

/** Häufige python-can-Interfaces mit verständlichen Namen (weitere folgen aus /interfaces). */
export const COMMON_INTERFACES: { value: string; label: string }[] = [
  { value: "pcan", label: "PCAN (PEAK-System)" },
  { value: "socketcan", label: "SocketCAN (Linux-Kerneltreiber)" },
  { value: "kvaser", label: "Kvaser" },
  { value: "vector", label: "Vector" },
  { value: "ixxat", label: "IXXAT (HMS)" },
  { value: "gs_usb", label: "gs_usb / candleLight" },
  { value: "slcan", label: "SLCAN (serielle Adapter)" },
];

const BITRATES = ["125000", "250000", "500000", "1000000"];

type StepId = "start" | "demoRun" | "demo" | "adapter" | "device" | "test" | "done";

const STEP_TITLES: Record<StepId, MsgKey> = {
  start: "setup.step.start",
  demoRun: "setup.step.demoRun",
  demo: "setup.step.demo",
  adapter: "setup.step.adapter",
  device: "setup.step.device",
  test: "setup.step.test",
  done: "setup.step.done",
};

interface AdapterForm {
  iface: string;
  channel: string;
  bitrate: string;
  customBitrate: string;
  fd: boolean;
  dataBitrate: string;
}

const DEFAULT_ADAPTER: AdapterForm = {
  iface: "pcan",
  channel: "PCAN_USBBUS1",
  bitrate: "500000",
  customBitrate: "",
  fd: false,
  dataBitrate: "2000000",
};

const CHANNEL = "default";

export function createSetupView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const el = h("div", { class: "setup" });

  let status: SetupStatus | null = null;
  let path: "demo" | "real" | "device" | "test" = "real";
  let steps: StepId[] = ["start"];
  let idx = 0;
  let hideDemo = true;
  const adapter: AdapterForm = {
    ...DEFAULT_ADAPTER,
    ...storage.load<Partial<AdapterForm>>("setup.adapter", {}),
  };
  let adapterState: "unknown" | "ok" | "skipped" = "unknown";
  let adapterInfo: Child = null;
  let device: DeviceForm = { ...DEFAULT_DEVICE };
  let editing: string | null = null; // ID eines bestehenden Geräts
  let idTouched = false;
  let savedDevice: string | null = null;
  let autoConnect = true;
  let interfaces: string[] = [];
  let lastTest: { diag: Diagnosis; vin?: string } | null = null;
  let lastSpec: Record<string, unknown> | null = null;

  const step = (): StepId => steps[idx] ?? "start";
  const connected = () =>
    // Echte Einrichtung ohne Adapter: nicht gegen eine noch verbundene Demo testen
    (path !== "real" || adapterState === "ok") &&
    store.connection.channels.some((c) => c.name === CHANNEL && c.connected);
  const connectedReal = () =>
    store.connection.channels.some((c) => c.name === CHANNEL && c.connected && c.backend === "python-can");

  const loadStatus = async () => {
    status = await api.get<SetupStatus>("/setup");
  };

  const reset = async (intent: SetupIntent) => {
    await Promise.all([loadStatus(), store.refreshConnection()]);
    idx = 0;
    lastTest = null;
    savedDevice = null;
    editing = null;
    idTouched = false;
    device = { ...DEFAULT_DEVICE };
    adapterState = connectedReal() ? "ok" : "unknown";
    adapterInfo = null;
    if (intent.mode === "full") {
      path = "real";
      steps = ["start"];
    } else {
      const ecu = intent.ecu;
      if (ecu) {
        const info = await api.get<DeviceInfo>(`/devices/${encodeURIComponent(ecu)}`);
        device = deviceToForm(info);
        editing = info.editable ? info.id : null;
        savedDevice = info.id;
        idTouched = true;
      }
      if (intent.mode === "device") {
        path = "device";
        steps = ["device", "test", "done"];
      } else {
        path = "test";
        steps = ["test", "done"];
      }
    }
    render();
  };

  const choosePath = (p: "demo" | "real") => {
    path = p;
    steps =
      p === "demo"
        ? ["start", "demoRun", "done"]
        : [
            "start",
            ...(status?.demo.active ? (["demo"] as StepId[]) : []),
            "adapter",
            "device",
            "test",
            "done",
          ];
    idx = 1;
    render();
  };

  const goto = (id: StepId) => {
    const i = steps.indexOf(id);
    if (i >= 0) {
      idx = i;
      render();
    }
  };

  // --- Aktionen ------------------------------------------------------------------------------------

  const bitrate = () => Number(adapter.bitrate === "custom" ? adapter.customBitrate : adapter.bitrate);

  const connectAdapter = async (): Promise<boolean> => {
    storage.save("setup.adapter", adapter);
    const options: Record<string, unknown> = {
      interface: adapter.iface,
      channel: adapter.channel.trim(),
      bitrate: bitrate(),
      fd: adapter.fd,
      ...(adapter.fd ? { data_bitrate: Number(adapter.dataBitrate) } : {}),
    };
    const spec = { name: CHANNEL, backend: "python-can", options, simulate: false };
    try {
      await api.post("/connection", spec, { replace: true });
      lastSpec = spec;
    } catch (exc) {
      adapterState = "unknown";
      adapterInfo = resultBox(
        "fail",
        t("setup.adapter.failed"),
        [errorText(exc)],
        [button(t("setup.adapter.help"), () => openHelpTopic("verbindung", "pcan"), { kind: "ghost" })],
      );
      await store.refreshConnection().catch(() => undefined);
      render();
      return false;
    }
    adapterState = "ok";
    await store.refreshConnection().catch(() => undefined);
    adapterInfo = resultBox("run", t("setup.adapter.listening"), []);
    render();
    const act = await api
      .get<BusActivity>("/setup/bus-activity", { channel: CHANNEL, seconds: 1 })
      .catch(() => null);
    adapterInfo = act
      ? act.error_frames > 0 && act.frames === 0
        ? resultBox("warn", t("setup.adapter.okErrors"), [t("setup.adapter.okErrorsText")])
        : act.frames > 0
          ? resultBox("ok", t("setup.adapter.okTraffic", { n: act.frames }), [
              t("setup.adapter.okTrafficText", {
                ids: act.ids
                  .slice(0, 8)
                  .map((i) => `0x${i.id_hex}`)
                  .join(", "),
              }),
            ])
          : resultBox("ok", t("setup.adapter.okQuiet"), [t("setup.adapter.okQuietText")])
      : resultBox("ok", t("setup.adapter.ok"), []);
    render();
    return true;
  };

  const saveDevice = async (): Promise<boolean> => {
    const taken = store.ecus.map((e) => e.id).filter((id) => id !== editing);
    const problems = validateDevice(device, taken);
    if (problems.length) {
      render(problems);
      return false;
    }
    const body = formToDevice(device);
    const r = editing
      ? await api.put<{ warnings: string[] }>(`/devices/${encodeURIComponent(editing)}`, body)
      : await api.post<{ warnings: string[] }>("/devices", body);
    for (const w of r.warnings ?? []) toast(w, "warning");
    editing = device.id;
    savedDevice = device.id;
    await store.refreshAll().catch(() => undefined);
    store.selectEcu(device.id);
    lastTest = null;
    return true;
  };

  const runTest = async () => {
    const ecu = savedDevice;
    if (!ecu) return;
    const info = await api.get<DeviceInfo>(`/devices/${encodeURIComponent(ecu)}`);
    const channel = info.profile.channel ?? CHANNEL;
    lastTest = null;
    renderTestBusy();
    const activity = api.get<BusActivity>("/setup/bus-activity", { channel, seconds: 1.5 }).catch(() => null);
    await new Promise((r) => setTimeout(r, 200));
    let res: UdsResult | null = null;
    try {
      res = await api.post<UdsResult>("/uds/request", { ecu, payload: "3E 00" });
    } catch (exc) {
      res = { error: errorText(exc), error_kind: "error" } as UdsResult;
    }
    const diag = diagnose(res, await activity, {
      tx_id: info.profile.tx_id,
      rx_id: info.profile.rx_id,
      extended_id: !!info.profile.extended_id,
    });
    let vin: string | undefined;
    if (diag.level === "ok") {
      const r = await api.post<UdsResult>("/uds/request", { ecu, payload: "22 F1 90" }).catch(() => null);
      if (r?.positive && r.response) vin = asciiFromResponse(r.response, 3);
    }
    lastTest = { diag, vin };
    render();
  };

  const useAsResponse = async (id: number, ext: boolean) => {
    device.rx_id = hex(id, ext ? 8 : 3);
    device.extended_id = ext;
    device.preset = "custom";
    if (await saveDevice()) await runTest();
  };

  /** Schritt verlassen: prüfen/speichern. false = bleiben. */
  const leave = async (): Promise<boolean> => {
    switch (step()) {
      case "demoRun": {
        await api.put("/setup/demo", { enabled: true });
        const spec = { name: CHANNEL, backend: "virtual", options: { bus: "vbus0" }, simulate: true };
        await api.post("/connection", spec, { replace: true });
        await api.put("/setup/connections", [spec]);
        await store.refreshAll().catch(() => undefined);
        return true;
      }
      case "demo":
        await api.put("/setup/demo", { enabled: !hideDemo });
        await store.refreshAll().catch(() => undefined);
        await loadStatus();
        return true;
      case "adapter":
        return adapterState !== "unknown" || (await connectAdapter());
      case "device":
        return saveDevice();
      default:
        return true;
    }
  };

  const next = async () => {
    if (!(await leave())) return;
    idx = Math.min(idx + 1, steps.length - 1);
    if (step() === "done") await enterDone();
    render();
    if (step() === "test" && !lastTest && connected()) void runTest().catch(toastError);
  };

  const back = () => {
    idx = Math.max(idx - 1, 0);
    render();
  };

  const enterDone = async () => {
    if (path === "demo" || path === "real") {
      await api.put("/setup/completed", { completed: true });
      if (path === "real") await saveConnection(autoConnect && adapterState === "ok");
      await loadStatus();
    }
  };

  const saveConnection = async (on: boolean) => {
    const ch = store.connection.channels.find((c) => c.name === CHANNEL && c.connected);
    const options = ch?.adapter?.["options"];
    const spec =
      lastSpec ??
      (ch && options ? { name: CHANNEL, backend: ch.backend, options, simulate: !!ch.simulate } : null);
    if (on && spec) {
      await api.put("/setup/connections", [spec]);
    } else {
      await api.put("/setup/connections", []);
    }
  };

  // --- Rendering -----------------------------------------------------------------------------------

  const stepper = () =>
    steps.length > 1
      ? h(
          "ol",
          { class: "setup-steps", "aria-label": t("setup.progress") },
          steps.map((s, i) =>
            h(
              "li",
              {
                class: [i < idx && "done", i === idx && "current"],
                "aria-current": i === idx ? "step" : undefined,
              },
              h("span", { class: "setup-step-no" }, i < idx ? "✓" : String(i + 1)),
              h("span", { class: "setup-step-label" }, t(STEP_TITLES[s])),
            ),
          ),
        )
      : null;

  const footer = (opts: { nextLabel?: string; extra?: Child; hideNext?: boolean } = {}) =>
    h(
      "div",
      { class: "setup-footer" },
      idx > 0 && step() !== "done" ? button(`← ${t("common.back")}`, back) : h("span"),
      h(
        "div",
        { class: "setup-footer-right" },
        opts.extra,
        opts.hideNext ? null : button(opts.nextLabel ?? `${t("setup.next")} →`, next, { kind: "primary" }),
      ),
    );

  const render = (problems: { field: string; msg: string }[] = []) => {
    const s = step();
    const body: Child =
      s === "start"
        ? renderStart()
        : s === "demoRun"
          ? renderDemoRun()
          : s === "demo"
            ? renderDemo()
            : s === "adapter"
              ? renderAdapter()
              : s === "device"
                ? renderDevice(problems)
                : s === "test"
                  ? renderTest()
                  : renderDone();
    replace(el, stepper(), h("section", { class: "card setup-card" }, body));
  };

  const renderStart = () => {
    const st = status;
    const conn = store.connection.channels.filter((c) => c.connected);
    return [
      h("h2", null, t("setup.start.title")),
      h("p", { class: "lead" }, t("setup.start.lead")),
      h(
        "div",
        { class: "setup-choices" },
        choice("🔌", t("setup.start.real"), t("setup.start.realText"), () => choosePath("real"), true),
        choice("🧪", t("setup.start.demo"), t("setup.start.demoText"), () => choosePath("demo")),
      ),
      h(
        "div",
        { class: "setup-current muted" },
        h("strong", null, t("setup.start.current")),
        " ",
        t("setup.start.currentText", {
          own: st?.devices.own ?? 0,
          demo: st?.demo.active ? (st?.devices.demo ?? 0) : 0,
          conn: conn.length ? conn.map((c) => `${c.name} · ${c.backend}`).join(", ") : t("setup.none"),
        }),
      ),
      st && !st.completed
        ? h(
            "div",
            { class: "setup-skip" },
            button(
              t("setup.start.skip"),
              async () => {
                await api.put("/setup/completed", { completed: true });
                await loadStatus();
                toast(t("setup.start.skipped"), "info");
                ctx.navigate("devices");
              },
              { kind: "ghost" },
            ),
          )
        : null,
    ];
  };

  const renderDemoRun = () => [
    h("h2", null, t("setup.demoRun.title")),
    h("p", null, t("setup.demoRun.text")),
    h(
      "ul",
      { class: "setup-list" },
      h("li", null, t("setup.demoRun.p1")),
      h("li", null, t("setup.demoRun.p2")),
      h("li", null, t("setup.demoRun.p3")),
    ),
    footer({ nextLabel: t("setup.demoRun.go") }),
  ];

  const renderDemo = () => {
    const box = checkbox(t("setup.demo.hide"), hideDemo, (v) => (hideDemo = v));
    return [
      h("h2", null, t("setup.demo.title")),
      h("p", null, t("setup.demo.text", { n: status?.devices.demo ?? 0 })),
      box.el,
      h("p", { class: "muted small" }, t("setup.demo.hint")),
      footer(),
    ];
  };

  const renderAdapter = () => {
    const ifaceSel = h("select");
    const known = new Set(COMMON_INTERFACES.map((i) => i.value));
    ifaceSel.append(
      h(
        "optgroup",
        { label: t("setup.adapter.common") },
        COMMON_INTERFACES.map((i) =>
          h("option", { value: i.value, selected: i.value === adapter.iface }, i.label),
        ),
      ),
    );
    const rest = interfaces.filter((i) => !known.has(i) && i !== "virtual");
    if (rest.length)
      ifaceSel.append(
        h(
          "optgroup",
          { label: t("setup.adapter.more") },
          rest.map((i) => h("option", { value: i, selected: i === adapter.iface }, i)),
        ),
      );
    const channelList = h("datalist", { id: "setup-channel-list" });
    const channelIn = textInput(adapter.channel, { list: "setup-channel-list" });
    ifaceSel.addEventListener("change", () => {
      adapter.iface = ifaceSel.value;
      channelIn.value = channelForInterface(adapter.iface, channelIn.value.trim());
      adapter.channel = channelIn.value;
      adapterState = "unknown";
      updateHint();
    });
    channelIn.addEventListener("input", () => {
      adapter.channel = channelIn.value;
      adapterState = "unknown";
    });
    const detect = async () => {
      const r = await api.get<{
        detected: { interface?: string; channel?: string | number }[];
        detect_error?: string;
      }>("/interfaces", { detect: true, interface: adapter.iface });
      const chans = r.detected
        .filter((d) => d.interface === adapter.iface && d.channel !== undefined)
        .map((d) => String(d.channel));
      replace(channelList, ...chans.map((c) => h("option", { value: c })));
      if (chans.length && !chans.includes(channelIn.value.trim())) {
        channelIn.value = chans[0]!;
        adapter.channel = chans[0]!;
      }
      toast(
        chans.length
          ? t("conn.detected", { n: chans.length, iface: adapter.iface })
          : t("conn.detectNone", { iface: adapter.iface }),
        chans.length ? "success" : "info",
      );
    };
    const brSel = select(
      [
        ...BITRATES.map((b) => ({ value: b, label: `${Number(b) / 1000} kBit/s` })),
        { value: "custom", label: t("setup.adapter.otherBitrate") },
      ],
      adapter.bitrate,
    );
    const brCustom = numberInput(adapter.customBitrate, {
      min: "10000",
      step: "1000",
      placeholder: "z. B. 83333",
    });
    const fdBox = checkbox("CAN FD", adapter.fd);
    const dataBr = numberInput(adapter.dataBitrate, { min: "100000", step: "1000" });
    const dataField = field(t("conn.dataBitrate"), dataBr);
    const hint = h("div", { class: "setup-hint" });
    const updateHint = () => {
      brCustom.hidden = brSel.value !== "custom";
      dataField.hidden = !fdBox.input.checked;
      replace(hint, ...ifaceHint(adapter.iface));
    };
    brSel.addEventListener("change", () => {
      adapter.bitrate = brSel.value;
      adapterState = "unknown";
      updateHint();
    });
    brCustom.addEventListener("input", () => (adapter.customBitrate = brCustom.value));
    fdBox.input.addEventListener("change", () => {
      adapter.fd = fdBox.input.checked;
      adapterState = "unknown";
      updateHint();
    });
    dataBr.addEventListener("input", () => (adapter.dataBitrate = dataBr.value));
    updateHint();
    return [
      h("h2", null, t("setup.adapter.title")),
      h("p", null, t("setup.adapter.lead")),
      h(
        "div",
        { class: "grid" },
        field(t("conn.interface"), ifaceSel, undefined, undefined, "connection.interface"),
        field(
          t("conn.channel"),
          h(
            "div",
            { class: "row" },
            channelIn,
            channelList,
            button(t("conn.detect"), detect, { kind: "ghost" }),
          ),
          undefined,
          undefined,
          "connection.channel",
        ),
        field(t("conn.bitrate"), h("div", { class: "row" }, brSel, brCustom), t("setup.adapter.bitrateHint")),
        h("div", { class: "field" }, fdBox.el, dataField),
      ),
      hint,
      h("div", { class: "row" }, button(t("setup.adapter.connect"), connectAdapter, { kind: "primary" })),
      adapterInfo,
      footer({
        extra: button(
          t("setup.adapter.skip"),
          () => {
            adapterState = "skipped";
            void next();
          },
          { kind: "ghost", title: t("setup.adapter.skipHint") },
        ),
      }),
    ];
  };

  const renderDevice = (problems: { field: string; msg: string }[]) => {
    const err = (key: string) => {
      const p = problems.find((x) => x.field === key);
      return p ? h("span", { class: "field-error", role: "alert" }, p.msg) : null;
    };
    const input = (key: keyof DeviceForm, attrs: Record<string, unknown> = {}) => {
      const i = textInput(String(device[key]), attrs);
      i.addEventListener("input", () => {
        (device[key] as string) = i.value;
        onChange(key);
      });
      return i;
    };
    const fld = (label: string, key: keyof DeviceForm, ctrl: HTMLElement, hint?: string) => {
      const f = field(label, ctrl, hint);
      const e = err(key);
      if (e) {
        f.classList.add("has-error");
        f.append(e);
      }
      return f;
    };

    const nameIn = input("name", { placeholder: t("setup.device.namePh") });
    const idIn = input("id", { placeholder: "mein_steuergeraet", readOnly: !!editing });
    idIn.addEventListener("input", () => (idTouched = true));
    const txIn = input("tx_id", { class: "mono" });
    const rxIn = input("rx_id", { class: "mono" });
    const fnIn = input("functional_id", { class: "mono", placeholder: t("common.optional") });
    const taIn = input("target_address", { class: "mono" });
    const saIn = input("tester_address", { class: "mono" });
    const ext = checkbox(t("setup.device.ext29"), device.extended_id, (v) => {
      device.extended_id = v;
      device.preset = "custom";
      onChange("extended_id");
    });
    const addrSel = select(
      [
        { value: "normal", label: t("setup.device.addr.normal") },
        { value: "extended", label: t("setup.device.addr.extended") },
        { value: "mixed", label: t("setup.device.addr.mixed") },
      ],
      device.addressing,
    );
    addrSel.addEventListener("change", () => {
      device.addressing = addrSel.value as DeviceForm["addressing"];
      onChange("addressing");
    });
    const txAe = input("tx_ae", { class: "mono", placeholder: "z. B. 2B" });
    const rxAe = input("rx_ae", { class: "mono", placeholder: t("common.optional") });
    const pad = checkbox(t("setup.device.padding"), device.padding, (v) => {
      device.padding = v;
      onChange("padding");
    });
    const padByte = input("padding_byte", { class: "mono" });
    const dlcSel = select(
      [
        { value: "fixed", label: t("setup.device.dlc.fixed") },
        { value: "minimal", label: t("setup.device.dlc.minimal") },
      ],
      device.dlc_mode,
    );
    dlcSel.addEventListener("change", () => (device.dlc_mode = dlcSel.value as DeviceForm["dlc_mode"]));
    const fd = checkbox(t("setup.device.canfd"), device.can_fd, (v) => (device.can_fd = v));
    const p2 = input("p2_ms", { placeholder: "50" });
    const p2s = input("p2_star_ms", { placeholder: "5000" });
    const desc = input("description", { placeholder: t("common.optional") });

    const presetBox = h(
      "div",
      { class: "setup-presets", role: "radiogroup", "aria-label": t("setup.device.preset") },
      (["std11", "fixed29", "custom"] as PresetId[]).map((p) =>
        h(
          "label",
          { class: ["setup-preset", device.preset === p && "selected"] },
          h("input", {
            type: "radio",
            name: "preset",
            value: p,
            checked: device.preset === p,
            onchange: () => {
              device = applyPreset(device, p);
              render();
            },
          }),
          h("strong", null, t(`setup.device.preset.${p}` as MsgKey)),
          h("span", { class: "muted small" }, t(`setup.device.preset.${p}.text` as MsgKey)),
        ),
      ),
    );

    const fixedBox = h(
      "div",
      { class: "grid" },
      fld(t("setup.device.ta"), "target_address", taIn, t("setup.device.taHint")),
      fld(t("setup.device.sa"), "tester_address", saIn, t("setup.device.saHint")),
    );
    const aeBox = h(
      "div",
      { class: "grid" },
      fld(t("setup.device.txAe"), "tx_ae", txAe, t("setup.device.txAeHint")),
      fld(t("setup.device.rxAe"), "rx_ae", rxAe, t("setup.device.rxAeHint")),
    );
    const summary = h("p", { class: "setup-summary" });

    const onChange = (key: keyof DeviceForm) => {
      if (key === "name" && !idTouched && !editing) {
        device.id = slugify(device.name);
        idIn.value = device.id;
      }
      if (device.preset === "fixed29" && (key === "target_address" || key === "tester_address")) {
        syncFixed29(device);
        txIn.value = device.tx_id;
        rxIn.value = device.rx_id;
        fnIn.value = device.functional_id;
      }
      if (key === "tx_id" || key === "rx_id" || key === "functional_id") {
        if (device.preset !== "custom") {
          device.preset = "custom";
          for (const l of presetBox.querySelectorAll("label")) l.classList.remove("selected");
          presetBox.querySelector<HTMLInputElement>('input[value="custom"]')!.checked = true;
          presetBox.lastElementChild?.classList.add("selected");
        }
      }
      update();
    };
    const update = () => {
      fixedBox.hidden = device.preset !== "fixed29";
      const ro = device.preset === "fixed29";
      txIn.readOnly = ro;
      rxIn.readOnly = ro;
      fnIn.readOnly = ro;
      ext.input.checked = device.extended_id;
      aeBox.hidden = device.addressing === "normal";
      padByte.disabled = !device.padding;
      const tx = parseId(device.tx_id);
      const rx = parseId(device.rx_id);
      const w = device.extended_id ? 8 : 3;
      replace(
        summary,
        tx !== null && rx !== null
          ? t("setup.device.summary", { tx: `0x${hex(tx, w)}`, rx: `0x${hex(rx, w)}` })
          : t("setup.device.summaryIncomplete"),
      );
    };
    update();

    return [
      h("h2", null, editing ? t("setup.device.editTitle", { id: editing }) : t("setup.device.title")),
      h("p", null, t("setup.device.lead")),
      h(
        "div",
        { class: "grid" },
        fld(t("setup.device.name"), "name", nameIn),
        fld(t("setup.device.id"), "id", idIn, t("setup.device.idHint")),
      ),
      h("h3", { class: "setup-sub" }, t("setup.device.preset")),
      presetBox,
      fixedBox,
      h(
        "div",
        { class: "grid" },
        fld(t("setup.device.tx"), "tx_id", txIn, t("setup.device.txHint")),
        fld(t("setup.device.rx"), "rx_id", rxIn, t("setup.device.rxHint")),
        fld(t("setup.device.func"), "functional_id", fnIn, t("setup.device.funcHint")),
        h("div", { class: "field" }, ext.el),
      ),
      summary,
      h(
        "details",
        {
          class: "setup-advanced",
          open: problems.some((p) => !["name", "id", "tx_id", "rx_id", "functional_id"].includes(p.field)),
        },
        h("summary", null, t("setup.device.advanced")),
        h("p", { class: "muted small" }, t("setup.device.advancedHint")),
        h(
          "div",
          { class: "grid" },
          field(t("setup.device.addressing"), addrSel, undefined, undefined, "isotp.addressing"),
          h("div", { class: "field" }, pad.el, fld(t("setup.device.paddingByte"), "padding_byte", padByte)),
          field(t("setup.device.dlc"), dlcSel),
          h("div", { class: "field" }, fd.el),
        ),
        aeBox,
        h(
          "div",
          { class: "grid" },
          fld("P2 (ms)", "p2_ms", p2, t("setup.device.p2Hint")),
          fld("P2* (ms)", "p2_star_ms", p2s, t("setup.device.p2sHint")),
          fld(t("setup.device.description"), "description", desc),
        ),
      ),
      footer({ nextLabel: `${t("setup.device.save")} →` }),
    ];
  };

  const testBox = h("div");
  const renderTestBusy = () =>
    replace(testBox, resultBox("run", t("setup.test.running"), [t("setup.test.runningText")]));

  const renderTest = () => {
    const ecu = savedDevice;
    const ecuState = store.ecus.find((e) => e.id === ecu);
    const isConn = connected();
    if (!isConn) {
      replace(
        testBox,
        resultBox(
          "warn",
          t("setup.test.noConn"),
          [t("setup.test.noConnText")],
          [
            steps.includes("adapter")
              ? button(t("setup.test.toAdapter"), () => goto("adapter"))
              : button(t("setup.test.toConnection"), () => ctx.navigate("connection")),
          ],
        ),
      );
    } else if (lastTest) {
      const d = lastTest.diag;
      replace(
        testBox,
        resultBox(
          d.level,
          d.title,
          [...d.text, ...(lastTest.vin ? [t("setup.test.vin", { vin: lastTest.vin })] : [])],
          d.candidates.length
            ? [
                h("div", { class: "setup-candidates" }, [
                  h("span", { class: "muted small" }, t("setup.test.seen")),
                  ...d.candidates
                    .slice(0, 10)
                    .map((c) =>
                      button(
                        `0x${hex(c.id, c.ext ? 8 : 3)} (${c.count}×)`,
                        () => useAsResponse(c.id, c.ext),
                        { title: t("setup.test.useAsRx") },
                      ),
                    ),
                ]),
              ]
            : [],
        ),
      );
    } else if (!testBox.firstChild) {
      replace(testBox, h("p", { class: "muted" }, t("setup.test.ready")));
    }
    const failed = lastTest && lastTest.diag.level !== "ok";
    return [
      h("h2", null, t("setup.test.title")),
      h("p", null, t("setup.test.lead")),
      ecuState
        ? h(
            "p",
            { class: "setup-summary" },
            h("strong", null, ecuState.name || ecuState.id),
            ` · 0x${hex(ecuState.tx_id, ecuState.tx_id > 0x7ff ? 8 : 3)} → 0x${hex(ecuState.rx_id, ecuState.rx_id > 0x7ff ? 8 : 3)}`,
          )
        : null,
      h(
        "div",
        { class: "row" },
        isConn
          ? button(lastTest ? t("setup.test.again") : t("setup.test.run"), runTest, { kind: "primary" })
          : null,
        steps.includes("device") ? button(t("setup.test.edit"), () => goto("device")) : null,
        button(t("setup.test.trace"), () => ctx.navigate("trace"), { kind: "ghost" }),
      ),
      testBox,
      footer({ nextLabel: failed ? t("setup.test.finishAnyway") : `${t("setup.next")} →` }),
    ];
  };

  const renderDone = () => {
    const demo = path === "demo";
    const items: Child[] = [];
    if (demo) {
      items.push(h("li", null, t("setup.done.demoReady")));
    } else {
      if (path === "real")
        items.push(
          h(
            "li",
            null,
            adapterState === "ok"
              ? t("setup.done.adapter", {
                  iface: adapter.iface,
                  channel: adapter.channel,
                  br: bitrate() / 1000,
                })
              : t("setup.done.noAdapter"),
          ),
        );
      if (savedDevice) items.push(h("li", null, t("setup.done.device", { id: savedDevice })));
      if (lastTest)
        items.push(
          h("li", null, lastTest.diag.level === "ok" ? t("setup.done.testOk") : t("setup.done.testFailed")),
        );
      if (status?.demo.available && !status.demo.active)
        items.push(h("li", null, t("setup.done.demoHidden")));
    }
    const auto =
      path === "real" && adapterState === "ok"
        ? checkbox(t("setup.done.autoConnect"), autoConnect, (v) => {
            autoConnect = v;
            void saveConnection(v)
              .then(() => toast(t(v ? "setup.done.autoOn" : "setup.done.autoOff"), "success"))
              .catch(toastError);
          })
        : null;
    return [
      h("h2", null, t("setup.done.title")),
      h("ul", { class: "setup-list setup-done" }, items),
      auto ? h("div", null, auto.el, h("p", { class: "muted small" }, t("setup.done.autoHint"))) : null,
      h("h3", { class: "setup-sub" }, t("setup.done.next")),
      h(
        "div",
        { class: "setup-choices small" },
        choice("📨", t("nav.uds"), t("setup.done.udsText"), () => ctx.navigate("uds")),
        choice("📈", t("nav.trace"), t("setup.done.traceText"), () => ctx.navigate("trace")),
        demo
          ? choice("✅", t("nav.tests"), t("setup.done.testsText"), () => ctx.navigate("tests"))
          : choice("🔢", t("nav.dids"), t("setup.done.didsText"), () => ctx.navigate("dids")),
        choice("➕", t("setup.done.another"), t("setup.done.anotherText"), () => {
          requestSetup({ mode: "device" });
          void reset({ mode: "device" }).catch(toastError);
        }),
        choice("🗂", t("nav.devices"), t("setup.done.devicesText"), () => ctx.navigate("devices")),
      ),
    ];
  };

  // --- Bausteine -------------------------------------------------------------------------------------

  function choice(sym: string, title: string, text: string, onClick: () => void, primary = false) {
    return h(
      "button",
      { type: "button", class: ["setup-choice", primary && "primary"], onclick: onClick },
      h("span", { class: "setup-choice-sym", "aria-hidden": "true" }, sym),
      h("strong", null, title),
      h("span", { class: "muted" }, text),
    );
  }

  function resultBox(
    level: "ok" | "warn" | "fail" | "run",
    title: string,
    text: string[],
    extra: Child[] = [],
  ) {
    return h(
      "div",
      { class: ["setup-result", `setup-result-${level}`], role: level === "fail" ? "alert" : "status" },
      h("strong", null, title),
      text.filter(Boolean).map((p) => h("p", null, p)),
      extra,
    );
  }

  function ifaceHint(iface: string): Child[] {
    const key = `setup.adapter.hint.${iface}` as MsgKey;
    const text = t(key);
    return text === key ? [] : [badge(iface), " ", text];
  }

  void api
    .get<{ python_can_interfaces: string[] }>("/interfaces")
    .then((r) => {
      interfaces = r.python_can_interfaces;
      if (step() === "adapter") render();
    })
    .catch(() => undefined);

  return {
    el,
    show: () => {
      const intent = pendingIntent;
      pendingIntent = null;
      if (intent || steps.length <= 1) void reset(intent ?? { mode: "full" }).catch(toastError);
    },
  };
}

function errorText(exc: unknown): string {
  if (exc instanceof ApiError) return exc.message;
  return exc instanceof Error ? exc.message : String(exc);
}

/** ASCII-Nutzdaten einer positiven Antwort ab Byte `skip` (z. B. 62 F1 90 …). */
export function asciiFromResponse(hexStr: string, skip: number): string {
  const bytes = hexStr
    .trim()
    .split(/\s+/)
    .slice(skip)
    .map((b) => parseInt(b, 16));
  return bytes
    .filter((b) => b >= 0x20 && b < 0x7f)
    .map((b) => String.fromCharCode(b))
    .join("")
    .trim();
}
