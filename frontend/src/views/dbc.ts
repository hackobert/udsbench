/**
 * DBC-Bereich: DBC-Dateien hochladen, je CAN-Kanal zuordnen, Signale live ansehen und Botschaften
 * aus Signalwerten kodieren/senden. Die Dekodierung im Trace geschieht im Backend automatisch.
 */
import { toast, toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  checkbox,
  confirmDialog,
  field,
  hexAscii,
  modal,
  numberInput,
  select,
  table,
  textInput,
} from "../components/ui";
import {
  decodeDbcBytes,
  filterLive,
  formatCanId,
  formatSignal,
  parseSignalInput,
  signalActive,
  signalLayout,
  type DbcMessage,
  type DbcOverview,
  type DbcSignal,
  type LiveMessage,
} from "../dbc-model";
import { type Child, h, replace } from "../dom";
import { t } from "../i18n";
import * as storage from "../storage";
import type { AppCtx, View } from "../view";

const POLL_MS = 500;

export function createDbcView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let data: DbcOverview = { files: [], assignments: {}, channels: [], conflicts: {} };
  const extraChannels = new Set<string>(storage.load<string[]>("dbc.extraChannels", []));
  let liveChannel = storage.load<string>("dbc.liveChannel", "default");
  let paused = false;
  let timer: ReturnType<typeof setInterval> | null = null;
  let visible = false;

  const channelsBox = h("div");
  const filesBox = h("div");
  const liveBox = h("div");
  const liveInfo = h("span", { class: "muted small" });
  const sendBox = h("div");

  const allChannels = (): { name: string; connected: boolean }[] => {
    const list = [...data.channels];
    for (const n of extraChannels)
      if (!list.some((c) => c.name === n)) list.push({ name: n, connected: false });
    return list.sort((a, b) => a.name.localeCompare(b.name));
  };

  const load = async () => {
    data = await api.get<DbcOverview>("/dbc");
    renderChannels();
    renderFiles();
    renderLiveControls();
    void renderSend();
  };

  // --- Kanäle --------------------------------------------------------------------------------------
  const setAssignment = async (channel: string, ids: string[]) => {
    const r = await api.put<{ conflicts: string[] }>(`/dbc/channels/${encodeURIComponent(channel)}`, {
      files: ids,
    });
    for (const c of r.conflicts) toast(c, "warning");
    toast(t("dbc.assigned", { channel, n: ids.length }), "success");
    await load();
  };

  const renderChannels = () => {
    const chans = allChannels();
    const newIn = textInput("", { placeholder: t("dbc.newChannelPh") });
    const addChannel = () => {
      const n = newIn.value.trim();
      if (!n) return;
      extraChannels.add(n);
      storage.save("dbc.extraChannels", [...extraChannels]);
      renderChannels();
    };
    newIn.addEventListener("keydown", (ev) => ev.key === "Enter" && addChannel());
    replace(
      channelsBox,
      data.files.length
        ? table(
            [
              {
                key: "ch",
                label: t("dbc.channel"),
                render: (c: { name: string; connected: boolean }) =>
                  h(
                    "span",
                    { class: "inline" },
                    h("strong", null, c.name),
                    c.connected
                      ? badge(t("conn.state.connected"), "ok")
                      : badge(t("conn.state.disconnected"), "muted"),
                  ),
              },
              {
                key: "files",
                label: t("dbc.activeFiles"),
                render: (c: { name: string; connected: boolean }) => {
                  const assigned = data.assignments[c.name] ?? [];
                  return h(
                    "div",
                    { class: "dbc-assign" },
                    data.files.map(
                      (f) =>
                        checkbox(f.name, assigned.includes(f.id), (on) => {
                          const next = on ? [...assigned, f.id] : assigned.filter((x) => x !== f.id);
                          void setAssignment(c.name, next).catch(toastError);
                        }).el,
                    ),
                    (data.conflicts[c.name] ?? []).length
                      ? h(
                          "ul",
                          { class: "validation" },
                          data.conflicts[c.name]!.map((x) => h("li", { class: "v-warning" }, `⚠ ${x}`)),
                        )
                      : null,
                  );
                },
              },
            ],
            chans,
          )
        : h("div", { class: "empty" }, t("dbc.noFilesYet")),
      h(
        "div",
        { class: "row" },
        newIn,
        button(t("dbc.addChannel"), addChannel, { kind: "ghost", title: t("dbc.addChannelHint") }),
      ),
    );
  };

  // --- Dateien -------------------------------------------------------------------------------------
  const fileIn = h("input", { type: "file", accept: ".dbc", multiple: true });
  const uploadChannel = h("select");
  const overwrite = checkbox(t("pkg.overwrite"), false);

  const upload = async () => {
    const files = Array.from(fileIn.files ?? []);
    if (!files.length) {
      toast(t("dbc.chooseFile"), "info");
      return;
    }
    const channels = uploadChannel.value ? [uploadChannel.value] : [];
    for (const file of files) {
      const content = decodeDbcBytes(new Uint8Array(await file.arrayBuffer()));
      try {
        const r = await api.post<{ file: { name: string; messages: number; signals: number } }>("/dbc", {
          filename: file.name,
          content,
          overwrite: overwrite.input.checked,
          channels,
        });
        toast(t("dbc.uploaded", { name: r.file.name, m: r.file.messages, s: r.file.signals }), "success");
      } catch (exc) {
        toastError(exc);
      }
    }
    fileIn.value = "";
    await load();
  };

  const remove = async (id: string, name: string) => {
    if (!(await confirmDialog(t("dbc.deleteConfirm", { name }), { title: t("dbc.deleteTitle") }))) return;
    await api.del(`/dbc/files/${encodeURIComponent(id)}`);
    toast(t("dbc.deleted", { name }), "success");
    await load();
  };

  const renderFiles = () => {
    replace(
      uploadChannel,
      h("option", { value: "" }, t("dbc.noAssign")),
      allChannels().map((c) =>
        h(
          "option",
          { value: c.name, selected: c.name === (store.connection.channels[0]?.name ?? "default") },
          c.name,
        ),
      ),
    );
    replace(
      filesBox,
      data.files.length
        ? table(
            [
              {
                key: "name",
                label: t("common.name"),
                render: (f: DbcOverview["files"][number]) =>
                  h("div", null, h("strong", null, f.name), h("div", { class: "muted small" }, f.id)),
              },
              {
                key: "m",
                label: t("dbc.messages"),
                render: (f: DbcOverview["files"][number]) => String(f.messages),
              },
              {
                key: "s",
                label: t("dbc.signals"),
                render: (f: DbcOverview["files"][number]) => String(f.signals),
              },
              {
                key: "ch",
                label: t("dbc.channels"),
                render: (f: DbcOverview["files"][number]) =>
                  f.channels.length
                    ? f.channels.map((c) => badge(c, "on"))
                    : h("span", { class: "muted" }, "–"),
              },
              {
                key: "x",
                label: "",
                render: (f: DbcOverview["files"][number]) =>
                  h(
                    "span",
                    { class: "inline" },
                    button(t("dbc.browse"), () => browse(f.id)),
                    button(t("common.delete"), () => remove(f.id, f.name), { kind: "danger" }),
                  ),
              },
            ],
            data.files,
          )
        : h("div", { class: "empty" }, t("dbc.noFiles")),
    );
  };

  // --- Inhalt einer DBC ----------------------------------------------------------------------------
  const browse = async (id: string) => {
    const d = await api.get<{ name: string; nodes: string[]; messages: DbcMessage[] }>(
      `/dbc/files/${encodeURIComponent(id)}`,
    );
    const filter = textInput("", { placeholder: t("dbc.filterPh") });
    const list = h("div", { class: "dbc-browser" });
    const render = () => {
      const n = filter.value.trim().toLowerCase();
      const msgs = d.messages.filter(
        (m) =>
          !n ||
          m.name.toLowerCase().includes(n) ||
          m.id_hex.toLowerCase().includes(n.replace(/^0x/, "")) ||
          m.signals.some((s) => s.name.toLowerCase().includes(n)),
      );
      replace(list, msgs.slice(0, 300).map(messageDetails));
    };
    filter.addEventListener("input", render);
    render();
    modal(
      `${d.name} – ${t("dbc.messagesN", { n: d.messages.length })}`,
      h(
        "div",
        { class: "dbc-modal" },
        d.nodes.length ? h("p", { class: "muted small" }, `${t("dbc.nodes")}: ${d.nodes.join(", ")}`) : null,
        filter,
        list,
      ),
    );
  };

  const messageDetails = (m: DbcMessage): HTMLElement =>
    h(
      "details",
      { class: "dbc-msg" },
      h(
        "summary",
        null,
        h("code", null, formatCanId(m.id, m.extended)),
        " ",
        h("strong", null, m.name),
        h(
          "span",
          { class: "muted small" },
          ` · ${m.length} Byte · ${m.signals.length} ${t("dbc.signals")}${m.cycle_time ? ` · ${m.cycle_time} ms` : ""}${m.fd ? " · FD" : ""}`,
        ),
      ),
      m.comment ? h("p", { class: "muted small" }, m.comment) : null,
      table(
        [
          {
            key: "n",
            label: t("dbc.signal"),
            render: (s: DbcSignal) =>
              h(
                "div",
                null,
                h("strong", null, s.name),
                s.multiplexer ? badge("MUX", "warn") : null,
                s.multiplexer_ids
                  ? h("span", { class: "muted small" }, ` (Mux ${s.multiplexer_ids.join(", ")})`)
                  : null,
                s.comment ? h("div", { class: "muted small" }, s.comment) : null,
              ),
          },
          {
            key: "l",
            label: t("dbc.layout"),
            render: (s: DbcSignal) => h("span", { class: "small" }, signalLayout(s)),
          },
          { key: "f", label: t("dbc.factorOffset"), render: (s: DbcSignal) => `${s.scale} / ${s.offset}` },
          {
            key: "r",
            label: t("dbc.range"),
            render: (s: DbcSignal) => `${s.minimum ?? "–"} … ${s.maximum ?? "–"} ${s.unit}`,
          },
          {
            key: "c",
            label: t("dbc.choices"),
            render: (s: DbcSignal) =>
              s.choices
                ? h(
                    "span",
                    { class: "small" },
                    Object.entries(s.choices)
                      .slice(0, 12)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(", "),
                  )
                : "",
          },
        ],
        m.signals,
      ),
    );

  // --- Live ----------------------------------------------------------------------------------------
  const liveSel = h("select");
  const liveFilter = textInput(storage.load<string>("dbc.liveFilter", ""), {
    placeholder: t("dbc.filterPh"),
  });
  liveFilter.addEventListener("input", () => {
    storage.save("dbc.liveFilter", liveFilter.value);
    void poll();
  });
  liveSel.addEventListener("change", () => {
    liveChannel = liveSel.value;
    storage.save("dbc.liveChannel", liveChannel);
    void poll();
    void renderSend();
  });
  const pauseBox = checkbox(t("dbc.pause"), false, (v) => (paused = v));

  const renderLiveControls = () => {
    const chans = allChannels();
    if (!chans.some((c) => c.name === liveChannel) && chans[0]) liveChannel = chans[0].name;
    replace(
      liveSel,
      chans.map((c) =>
        h(
          "option",
          { value: c.name, selected: c.name === liveChannel },
          `${c.name}${(data.assignments[c.name] ?? []).length ? "" : ` (${t("dbc.noDbc")})`}`,
        ),
      ),
    );
  };

  const poll = async () => {
    if (paused || !visible) return;
    const r = await api.get<{ messages: LiveMessage[] }>("/dbc/live", { channel: liveChannel });
    renderLive(r.messages);
  };

  const renderLive = (items: LiveMessage[]) => {
    const shown = filterLive(items, liveFilter.value);
    replace(
      liveInfo,
      (data.assignments[liveChannel] ?? []).length
        ? t("dbc.liveInfo", { n: items.length, shown: shown.length })
        : t("dbc.liveNoDbc", { channel: liveChannel }),
    );
    replace(
      liveBox,
      shown.length
        ? table(
            [
              {
                key: "id",
                label: "ID",
                render: (m: LiveMessage) => h("code", null, formatCanId(m.id, m.extended)),
              },
              {
                key: "msg",
                label: t("dbc.message"),
                render: (m: LiveMessage) =>
                  h("div", null, h("strong", null, m.message), h("div", { class: "muted small" }, m.dbc)),
              },
              {
                key: "sig",
                label: t("dbc.signals"),
                render: (m: LiveMessage) =>
                  h(
                    "div",
                    { class: "dbc-sigs" },
                    Object.entries(m.signals).map(([k, v]) =>
                      h(
                        "span",
                        { class: "dbc-sig" },
                        h("span", { class: "dbc-sig-name" }, k),
                        h("span", { class: "dbc-sig-val" }, formatSignal(v, m.units[k])),
                      ),
                    ),
                  ),
              },
              { key: "data", label: t("dbc.data"), render: (m: LiveMessage) => hexAscii(m.data) },
              {
                key: "cyc",
                label: t("dbc.cycle"),
                render: (m: LiveMessage) => (m.period_ms !== null ? `${m.period_ms} ms` : "–"),
              },
              { key: "n", label: t("dbc.count"), render: (m: LiveMessage) => String(m.count) },
              {
                key: "age",
                label: t("dbc.age"),
                render: (m: LiveMessage) =>
                  h("span", { class: m.age_s > 2 ? "muted" : "" }, `${m.age_s.toFixed(1)} s`),
              },
            ],
            shown,
          )
        : h(
            "div",
            { class: "empty" },
            t((data.assignments[liveChannel] ?? []).length ? "dbc.liveEmpty" : "dbc.liveEmptyNoDbc"),
          ),
    );
  };

  // --- Senden --------------------------------------------------------------------------------------
  let sendMessages: DbcMessage[] = [];
  let sendSel = storage.load<string>("dbc.sendMessage", "");

  const renderSend = async () => {
    const ch = liveChannel;
    if (!(data.assignments[ch] ?? []).length) {
      replace(sendBox, h("div", { class: "empty" }, t("dbc.sendNoDbc", { channel: ch })));
      return;
    }
    sendMessages = await api.get<DbcMessage[]>(`/dbc/channels/${encodeURIComponent(ch)}/messages`);
    const msgSel = select(
      sendMessages.map((m) => ({
        value: `${m.dbc}:${m.name}`,
        label: `${formatCanId(m.id, m.extended)}  ${m.name}`,
      })),
      sendSel,
    );
    const form = h("div", { class: "grid" });
    const out = h("div");
    const inputs = new Map<string, HTMLInputElement | HTMLSelectElement>();
    const current = () => sendMessages.find((m) => `${m.dbc}:${m.name}` === msgSel.value) ?? sendMessages[0];

    const buildForm = () => {
      const m = current();
      inputs.clear();
      replace(out);
      if (!m) return replace(form);
      const muxSig = m.signals.find((s) => s.multiplexer);
      const muxValue = () => {
        const el = muxSig ? inputs.get(muxSig.name) : undefined;
        const n = el ? Number(el.value) : NaN;
        return Number.isNaN(n) ? null : n;
      };
      const fields: Child[] = m.signals.map((s) => {
        let ctrl: HTMLInputElement | HTMLSelectElement;
        if (s.choices) {
          ctrl = select([
            { value: "", label: t("dbc.initial") },
            ...Object.entries(s.choices).map(([, v]) => ({ value: v, label: v })),
          ]);
        } else {
          ctrl = numberInput("", {
            step: "any",
            placeholder: `${s.minimum ?? ""}…${s.maximum ?? ""}`,
            ...(s.minimum !== null ? { min: String(s.minimum) } : {}),
            ...(s.maximum !== null ? { max: String(s.maximum) } : {}),
          });
        }
        inputs.set(s.name, ctrl);
        const f = field(
          `${s.name}${s.unit ? ` [${s.unit}]` : ""}`,
          ctrl,
          s.multiplexer_ids
            ? t("dbc.onlyMux", { ids: s.multiplexer_ids.join(", ") })
            : (s.comment ?? undefined),
        );
        f.dataset["signal"] = s.name;
        return f;
      });
      replace(form, fields);
      const updateMux = () => {
        const mv = muxValue();
        for (const s of m.signals) {
          const el = form.querySelector<HTMLElement>(`[data-signal="${CSS.escape(s.name)}"]`);
          if (el) el.classList.toggle("dbc-inactive", !signalActive(s, mv));
        }
      };
      if (muxSig) inputs.get(muxSig.name)?.addEventListener("input", updateMux);
      updateMux();
    };
    msgSel.addEventListener("change", () => {
      sendSel = msgSel.value;
      storage.save("dbc.sendMessage", sendSel);
      buildForm();
    });

    const run = async (send: boolean) => {
      const m = current();
      if (!m) return;
      const signals: Record<string, number | string> = {};
      const muxSig = m.signals.find((s) => s.multiplexer);
      const mv = muxSig ? Number(inputs.get(muxSig.name)?.value || NaN) : NaN;
      for (const s of m.signals) {
        if (!signalActive(s, Number.isNaN(mv) ? null : mv)) continue;
        const v = parseSignalInput(inputs.get(s.name)?.value ?? "", s);
        if (v !== null) signals[s.name] = v;
      }
      const r = await api.post<{ id: number; extended: boolean; data: string; sent: boolean }>(
        "/dbc/encode",
        {
          channel: ch,
          dbc: m.dbc,
          message: m.name,
          signals,
          send,
        },
      );
      replace(
        out,
        h(
          "div",
          { class: ["result", r.sent ? "result-ok" : "result-muted"] },
          h(
            "div",
            { class: "result-head" },
            badge(r.sent ? t("dbc.sent") : t("dbc.encoded"), r.sent ? "ok" : "muted"),
            h("code", null, ` ${formatCanId(r.id, r.extended)}`),
          ),
          hexAscii(r.data),
        ),
      );
      if (r.sent) toast(t("dbc.sentToast", { name: m.name, channel: ch }), "success");
    };

    buildForm();
    replace(
      sendBox,
      h("div", { class: "row" }, field(t("dbc.message"), msgSel)),
      form,
      h(
        "div",
        { class: "row" },
        button(t("dbc.encode"), () => run(false)),
        button(t("dbc.send"), () => run(true), { kind: "primary" }),
        h("span", { class: "muted small" }, t("dbc.sendHint")),
      ),
      out,
    );
  };

  // --- Layout --------------------------------------------------------------------------------------
  const el = h(
    "div",
    { class: "view-grid dbc-view" },
    card(
      t("dbc.liveTitle"),
      h(
        "div",
        { class: "row" },
        field(t("dbc.channel"), liveSel),
        field(t("common.filter"), liveFilter),
        pauseBox.el,
        button(
          t("dbc.resetLive"),
          async () => {
            await api.del("/dbc/live", { channel: liveChannel });
            await poll();
          },
          { kind: "ghost" },
        ),
        liveInfo,
      ),
      liveBox,
    ),
    card(t("dbc.channelsTitle"), h("p", { class: "muted" }, t("dbc.channelsText")), channelsBox),
    card(
      t("dbc.filesTitle"),
      h("p", { class: "muted" }, t("dbc.filesText")),
      h(
        "div",
        { class: "row" },
        fileIn,
        field(t("dbc.assignTo"), uploadChannel),
        overwrite.el,
        button(t("dbc.upload"), upload, { kind: "primary" }),
      ),
      filesBox,
    ),
    card(t("dbc.sendTitle"), sendBox),
  );

  const off = store.on("connection", () => void load().catch(() => undefined));
  return {
    el,
    show: () => {
      visible = true;
      void load().then(poll).catch(toastError);
      if (!timer) timer = setInterval(() => void poll().catch(() => undefined), POLL_MS);
    },
    hide: () => {
      visible = false;
      if (timer) clearInterval(timer);
      timer = null;
    },
    destroy: () => {
      visible = false;
      if (timer) clearInterval(timer);
      off();
    },
  };
}
