import { infoIcon } from "../help";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  kv,
  numberInput,
  row,
  select,
  table,
  textInput,
} from "../components/ui";
import { toast } from "../components/toast";
import { formatDateTime, h, replace } from "../dom";
import { toHexId } from "../hex";
import { t } from "../i18n";
import * as storage from "../storage";
import type { EcuState, SimState, ChannelStatus } from "../types";
import type { AppCtx, View } from "../view";

interface ConnForm {
  name: string;
  backend: "virtual" | "python-can";
  bus: string;
  interface: string;
  channel: string;
  bitrate: string;
  fd: boolean;
  data_bitrate: string;
  simulate: boolean;
}

/** Übliche Kanalnamen je python-can-Interface (Vorbelegung beim Wechsel des Interfaces). */
export const DEFAULT_CHANNELS: Record<string, string> = {
  socketcan: "can0",
  pcan: "PCAN_USBBUS1",
  kvaser: "0",
  vector: "0",
  ixxat: "0",
  virtual: "vbus0",
};

/** Neuen Kanal beim Interface-Wechsel: nur ersetzen, wenn leer oder Vorgabe eines anderen Interfaces. */
export function channelForInterface(iface: string, current: string): string {
  const def = DEFAULT_CHANNELS[iface];
  if (def === undefined) return current;
  const isDefault = current === "" || Object.values(DEFAULT_CHANNELS).includes(current);
  return isDefault ? def : current;
}

interface DetectedConfig {
  interface?: string;
  channel?: string | number;
}

const DEFAULT_FORM: ConnForm = {
  name: "default",
  backend: "virtual",
  bus: "vbus0",
  interface: "socketcan",
  channel: "can0",
  bitrate: "500000",
  fd: false,
  data_bitrate: "2000000",
  simulate: true,
};

export function createConnectionView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const form: ConnForm = { ...DEFAULT_FORM, ...storage.load<Partial<ConnForm>>("connForm", {}) };
  const persist = () => storage.save("connForm", form);

  const nameIn = textInput(form.name);
  const backendSel = select(
    [
      { value: "virtual", label: t("conn.backend.virtual") },
      { value: "python-can", label: "python-can" },
    ],
    form.backend,
  );
  const busIn = textInput(form.bus);
  const ifaceSel = h("select");
  const channelList = h("datalist", { id: "conn-channel-list" });
  const channelIn = textInput(form.channel, { list: "conn-channel-list" });
  const bitrateIn = numberInput(form.bitrate, { min: "1000", step: "1000" });
  const fdBox = checkbox("CAN FD", form.fd, undefined, undefined, "connection.fd");
  const dataBitrateIn = numberInput(form.data_bitrate, { min: "1000", step: "1000" });
  const simBox = checkbox(
    t("conn.simulate"),
    form.simulate,
    undefined,
    t("conn.simulateHint"),
    "connection.simulate",
  );

  const virtualOpts = h(
    "div",
    { class: "grid" },
    field(t("conn.bus"), busIn, t("conn.busHint"), undefined, "connection.bus"),
  );
  const pcanOpts = h(
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
        button(t("conn.detect"), () => detect(), { kind: "ghost", title: t("conn.detectHint") }),
      ),
      undefined,
      undefined,
      "connection.channel",
    ),
    field(t("conn.bitrate"), bitrateIn, undefined, undefined, "connection.bitrate"),
    field(t("conn.dataBitrate"), dataBitrateIn, undefined, undefined, "connection.data_bitrate"),
    fdBox.el,
  );

  const updateVisibility = () => {
    const isVirtual = backendSel.value === "virtual";
    virtualOpts.hidden = !isVirtual;
    pcanOpts.hidden = isVirtual;
    dataBitrateIn.disabled = !fdBox.input.checked;
  };
  backendSel.addEventListener("change", updateVisibility);
  ifaceSel.addEventListener("change", () => {
    channelIn.value = channelForInterface(ifaceSel.value, channelIn.value.trim());
  });
  fdBox.input.addEventListener("change", updateVisibility);

  const readForm = (): ConnForm => {
    Object.assign(form, {
      name: nameIn.value.trim() || "default",
      backend: backendSel.value as ConnForm["backend"],
      bus: busIn.value.trim(),
      interface: ifaceSel.value,
      channel: channelIn.value.trim(),
      bitrate: bitrateIn.value,
      fd: fdBox.input.checked,
      data_bitrate: dataBitrateIn.value,
      simulate: simBox.input.checked,
    });
    persist();
    return form;
  };

  const connect = async () => {
    const f = readForm();
    const options: Record<string, unknown> =
      f.backend === "virtual"
        ? { bus: f.bus || "vbus0" }
        : {
            interface: f.interface,
            channel: f.channel,
            bitrate: Number(f.bitrate),
            fd: f.fd,
            ...(f.fd ? { data_bitrate: Number(f.data_bitrate) } : {}),
          };
    // Bereits verbundenen Kanal gleichen Namens umstellen (z. B. --demo: virtuell → PCAN)
    await api.post(
      "/connection",
      { name: f.name, backend: f.backend, options, simulate: f.simulate },
      { replace: true },
    );
    toast(t("conn.connected", { name: f.name }), "success");
    await refresh();
  };
  const disconnect = async () => {
    const f = readForm();
    await api.del("/connection", { name: f.name });
    toast(t("conn.disconnected", { name: f.name }), "info");
    await refresh();
  };
  const reset = async () => {
    const f = readForm();
    await api.post(`/connection/${encodeURIComponent(f.name)}/reset`);
    toast(t("conn.resetDone"), "success");
    await refresh();
  };

  const statusBox = h("div");
  const ecuBox = h("div");
  const simBox2 = h("div");

  const renderStatus = () => {
    const ch = store.connection.channels;
    replace(
      statusBox,
      ch.length
        ? table<ChannelStatus>(
            [
              { key: "name", label: t("common.name"), render: (c) => c.name },
              { key: "backend", label: t("conn.backend"), render: (c) => c.backend },
              {
                key: "state",
                label: t("common.status"),
                render: (c) =>
                  badge(
                    c.connected ? t("conn.state.connected") : t("conn.state.disconnected"),
                    c.connected ? "ok" : "fail",
                  ),
              },
              { key: "adapter", label: t("conn.adapter"), render: (c) => String(c.adapter?.state ?? "–") },
              { key: "tx", label: "TX", render: (c) => String(c.tx) },
              { key: "rx", label: "RX", render: (c) => String(c.rx) },
              { key: "err", label: t("conn.errors"), render: (c) => String(c.tx_errors) },
              { key: "since", label: t("conn.since"), render: (c) => formatDateTime(c.connected_at ?? null) },
              { key: "sim", label: t("conn.simShort"), render: (c) => (c.simulate ? "✔" : "") },
            ],
            ch,
          )
        : h("div", { class: "empty" }, t("conn.none")),
    );
  };

  const renderEcus = () => {
    replace(
      ecuBox,
      table<EcuState>(
        [
          { key: "id", label: "ECU", render: (e) => h("strong", null, e.id) },
          { key: "name", label: t("common.name"), render: (e) => e.name },
          { key: "prof", label: t("conn.profile"), render: (e) => e.isotp_profile },
          {
            key: "ids",
            label: "TX/RX",
            render: (e) => h("code", null, `${toHexId(e.tx_id)} / ${toHexId(e.rx_id)}`),
          },
          {
            key: "sess",
            label: t("header.session"),
            render: (e) => `${e.session_name} (0x${e.session.toString(16).toUpperCase().padStart(2, "0")})`,
          },
          {
            key: "unl",
            label: t("header.unlocked"),
            render: (e) =>
              e.unlocked_levels.length
                ? e.unlocked_levels.map((l) => badge(`L${l}`, "ok"))
                : h("span", { class: "muted" }, t("header.locked")),
          },
          {
            key: "tp",
            label: "TesterPresent",
            render: (e) => {
              const c = checkbox(t("common.on"), e.tester_present.enabled, async (v) => {
                try {
                  await api.put(`/ecus/${encodeURIComponent(e.id)}/tester-present`, { enabled: v });
                  await store.refreshEcus();
                } catch (exc) {
                  c.input.checked = !v;
                  throw exc;
                }
              });
              return c.el;
            },
          },
          {
            key: "act",
            label: "",
            render: (e) => button(t("common.select"), () => store.selectEcu(e.id), { kind: "ghost" }),
          },
        ],
        store.ecus,
        { rowClass: (e) => (e.id === store.selectedEcu ? "row-selected" : "") },
      ),
    );
  };

  const renderSim = (sims: SimState[]) => {
    replace(
      simBox2,
      sims.length
        ? table<SimState>(
            [
              { key: "ecu", label: "ECU", render: (s) => s.ecu },
              {
                key: "sess",
                label: t("header.session"),
                render: (s) => `0x${s.session.toString(16).toUpperCase().padStart(2, "0")}`,
              },
              {
                key: "unl",
                label: t("header.unlocked"),
                render: (s) => (s.unlocked.length ? s.unlocked.map((l) => badge(`L${l}`, "ok")) : "–"),
              },
              { key: "req", label: t("conn.requests"), render: (s) => String(s.requests) },
              { key: "dids", label: "DIDs", render: (s) => String(Object.keys(s.dids).length) },
              {
                key: "dtcs",
                label: "DTCs",
                render: (s) =>
                  Object.entries(s.dtcs).map(([c, st]) => h("code", { class: "mr" }, `${c}:${st}`)),
              },
              {
                key: "x",
                label: "",
                render: (s) =>
                  button(
                    t("conn.simReset"),
                    async () => {
                      await api.post(`/simulation/${encodeURIComponent(s.ecu)}/reset`);
                      await loadSim();
                    },
                    { kind: "ghost" },
                  ),
              },
            ],
            sims,
          )
        : h("div", { class: "empty" }, t("conn.simNone")),
    );
  };

  const loadSim = async () => renderSim(await api.get<SimState[]>("/simulation"));

  const refresh = async () => {
    await Promise.all([store.refreshConnection(), store.refreshEcus(), loadSim()]);
  };

  const loadInterfaces = async () => {
    const r = await api.get<{ backends: string[]; python_can_interfaces: string[]; detected: unknown[] }>(
      "/interfaces",
    );
    replace(
      ifaceSel,
      ...r.python_can_interfaces.map((i) => h("option", { value: i, selected: i === form.interface }, i)),
    );
  };

  const detect = async () => {
    const r = await api.get<{ detected: DetectedConfig[]; detect_error?: string }>("/interfaces", {
      detect: true,
      interface: ifaceSel.value,
    });
    if (r.detect_error) toast(r.detect_error, "error");
    const channels = r.detected
      .filter((d) => d.interface === ifaceSel.value && d.channel !== undefined)
      .map((d) => String(d.channel));
    replace(channelList, ...channels.map((c) => h("option", { value: c })));
    if (channels.length && !channels.includes(channelIn.value.trim())) channelIn.value = channels[0]!;
    toast(
      channels.length
        ? t("conn.detected", { n: channels.length, iface: ifaceSel.value })
        : t("conn.detectNone", { iface: ifaceSel.value }),
      channels.length ? "success" : "info",
    );
  };

  const offs = [
    store.changed.on((k) => {
      if (k === "connection") renderStatus();
      if (k === "ecus" || k === "selectedEcu") renderEcus();
    }),
    store.on("connection", () => void refresh().catch(() => undefined)),
    store.on("simulation", () => void loadSim().catch(() => undefined)),
  ];

  const el = h(
    "div",
    { class: "view-grid" },
    card(
      t("conn.title"),
      h(
        "div",
        { class: "grid" },
        field(t("common.name"), nameIn, undefined, undefined, "connection.name"),
        field(t("conn.backend"), backendSel, undefined, undefined, "connection.backend"),
      ),
      virtualOpts,
      pcanOpts,
      simBox.el,
      row(
        button(t("conn.connect"), connect, { kind: "primary" }),
        button(t("conn.disconnect"), disconnect),
        button(t("conn.reset"), reset, { title: t("conn.resetHint") }),
        infoIcon("connection.reset"),
      ),
    ),
    card(
      t("conn.status"),
      statusBox,
      kv([[t("conn.events"), h("span", { class: "events-state" }, store.eventsState)]]),
    ),
    card(h("span", null, t("conn.ecus"), infoIcon("connection.tester_present")), ecuBox),
    card(
      h(
        "span",
        null,
        t("conn.simulation"),
        " ",
        button(
          t("conn.simRestart"),
          async () => {
            await api.post("/simulation/restart");
            await loadSim();
          },
          { kind: "ghost" },
        ),
      ),
      simBox2,
    ),
  );

  updateVisibility();
  renderStatus();
  renderEcus();
  void loadInterfaces().catch(() => undefined);

  return {
    el,
    show: () => void refresh().catch(() => undefined),
    destroy: () => offs.forEach((o) => o()),
  };
}
