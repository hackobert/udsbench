import { toast, toastError } from "../components/toast";
import {
  badge,
  button,
  card,
  checkbox,
  field,
  jsonView,
  numberInput,
  row,
  select,
  table,
  textInput,
  confirmDialog,
} from "../components/ui";
import { formatDateTime, h, readFileText, replace } from "../dom";
import { t } from "../i18n";
import type { RecordingInfo, ReplayInfo } from "../types";
import type { AppCtx, View } from "../view";

interface RecordingsResponse {
  recordings: RecordingInfo[];
  replays: ReplayInfo[];
  formats: string[];
}

export function createRecordingsView(ctx: AppCtx): View {
  const { api, store } = ctx;
  let data: RecordingsResponse = { recordings: [], replays: [], formats: ["jsonl", "csv", "asc", "candump"] };
  let active: { id: string; name: string } | null = null;
  const nameIn = textInput("", { placeholder: t("rec.namePlaceholder") });
  const stateBox = h("div");
  const listBox = h("div");
  const replaysBox = h("div");
  const importBox = h("div");
  const modeSel = select(
    [
      { value: "bus", label: t("rec.modeBus") },
      { value: "trace", label: t("rec.modeTrace") },
    ],
    "trace",
  );
  const speedIn = numberInput("1", { min: "0.01", step: "0.1", class: "w-xs" });
  const loopIn = numberInput("1", { min: "1", max: "1000", class: "w-xs" });
  const dirTx = checkbox("TX", true);
  const dirRx = checkbox("RX", true);
  const fileIn = h("input", { type: "file", accept: ".jsonl,.csv,.asc,.log,.txt,.candump" });
  const importName = textInput("", { placeholder: t("rec.importName") });

  const load = async () => {
    data = await api.get<RecordingsResponse>("/recordings");
    const info = await api.get<{ recording: { id: string; name: string } | null }>("/info");
    active = info.recording ?? null;
    render();
  };

  const render = () => {
    replace(
      stateBox,
      active
        ? h(
            "div",
            { class: "result-head" },
            badge(t("rec.recording"), "run"),
            ` ${active.name} (${active.id})`,
          )
        : h("span", { class: "muted" }, t("rec.idle")),
    );
    replace(
      listBox,
      table<RecordingInfo>(
        [
          { key: "name", label: t("common.name"), render: (r) => h("strong", null, r.name) },
          { key: "id", label: "ID", render: (r) => h("code", null, r.id) },
          { key: "frames", label: t("rec.frames"), render: (r) => String(r.frames) },
          { key: "started", label: t("rec.started"), render: (r) => formatDateTime(r.started) },
          {
            key: "size",
            label: t("rec.size"),
            render: (r) => (r.size !== undefined ? `${Math.round(r.size / 102.4) / 10} KiB` : "–"),
          },
          {
            key: "export",
            label: t("rec.export"),
            render: (r) =>
              h(
                "span",
                { class: "inline" },
                data.formats.map((f) =>
                  button(
                    f,
                    () =>
                      api.download(`/recordings/${encodeURIComponent(r.id)}`, { format: f }, `${r.id}.${f}`),
                    { kind: "ghost" },
                  ),
                ),
              ),
          },
          {
            key: "act",
            label: "",
            render: (r) =>
              h(
                "span",
                { class: "inline" },
                button(t("rec.replay"), () => replay(r.id), { kind: "primary" }),
                button(
                  t("common.delete"),
                  async () => {
                    if (!(await confirmDialog(t("rec.deleteConfirm", { name: r.name })))) return;
                    await api.del(`/recordings/${encodeURIComponent(r.id)}`);
                    await load();
                  },
                  { kind: "danger" },
                ),
              ),
          },
        ],
        data.recordings,
      ),
    );
    replace(
      replaysBox,
      data.replays.length
        ? table<ReplayInfo>(
            [
              { key: "id", label: "ID", render: (r) => h("code", null, r.id) },
              { key: "rec", label: t("rec.recordingCol"), render: (r) => String(r.recording ?? "–") },
              { key: "state", label: t("common.status"), render: (r) => badge(String(r.state ?? "–")) },
              { key: "mode", label: t("rec.mode"), render: (r) => String(r.mode ?? "–") },
              {
                key: "prog",
                label: t("test.progress"),
                render: (r) => (r.total ? `${r.sent ?? 0}/${r.total}` : String(r.sent ?? "–")),
              },
              {
                key: "x",
                label: "",
                render: (r) =>
                  r.state === "running"
                    ? button(
                        t("common.cancel"),
                        async () => {
                          await api.post(`/replays/${encodeURIComponent(r.id)}/cancel`);
                          await load();
                        },
                        { kind: "danger" },
                      )
                    : null,
              },
            ],
            data.replays,
          )
        : h("div", { class: "empty" }, t("rec.noReplays")),
    );
  };

  const startRec = async () => {
    const r = await api.post<{ id: string; name: string }>(
      "/recordings",
      nameIn.value.trim() ? { name: nameIn.value.trim() } : {},
    );
    toast(t("rec.startedToast", { name: r.name }), "success");
    await load();
  };
  const stopRec = async () => {
    const r = await api.post<{ id: string; frames: number }>("/recordings/stop");
    toast(t("rec.stoppedToast", { n: r.frames }), "success");
    await load();
  };
  const replay = async (id: string) => {
    const directions = [dirTx.input.checked ? "tx" : null, dirRx.input.checked ? "rx" : null].filter(Boolean);
    const r = await api.post<ReplayInfo>(`/recordings/${encodeURIComponent(id)}/replay`, {
      mode: modeSel.value,
      speed: Number(speedIn.value) || 1,
      loop: Number(loopIn.value) || 1,
      directions: directions.length === 2 ? null : directions,
    });
    toast(t("rec.replayStarted", { id: r.id ?? id }), "info");
    await load();
  };
  const doImport = async () => {
    const file = fileIn.files?.[0];
    if (!file) {
      toast(t("rec.noFile"), "warning");
      return;
    }
    const content = await readFileText(file);
    try {
      const r = await api.post<Record<string, unknown>>("/recordings/import", {
        content,
        filename: file.name,
        name: importName.value.trim() || file.name,
      });
      replace(importBox, jsonView(r));
      toast(t("rec.imported"), "success");
      await load();
    } catch (exc) {
      toastError(exc);
    }
  };

  const el = h(
    "div",
    { class: "view-grid" },
    card(
      t("rec.title"),
      stateBox,
      row(
        field(t("common.name"), nameIn),
        button(t("rec.start"), startRec, { kind: "primary" }),
        button(t("rec.stop"), stopRec, { kind: "danger" }),
      ),
    ),
    card(
      h("span", null, t("rec.list"), " ", button(t("common.reload"), load, { kind: "ghost" })),
      h(
        "div",
        { class: "grid" },
        field(t("rec.mode"), modeSel, t("rec.modeHint"), undefined, "recordings.mode"),
        field(t("rec.speed"), speedIn, undefined, undefined, "recordings.speed"),
        field(t("rec.loop"), loopIn),
        h("div", { class: "inline" }, dirTx.el, dirRx.el),
      ),
      listBox,
    ),
    card(t("rec.replays"), replaysBox),
    card(
      t("rec.import"),
      row(fileIn, importName, button(t("rec.importBtn"), doImport, { kind: "primary" })),
      h("p", { class: "muted small" }, t("rec.importHint")),
      importBox,
    ),
  );

  const offs = [
    store.on("recording", () => void load().catch(() => undefined)),
    store.on("replay", () => void load().catch(() => undefined)),
  ];
  return { el, show: () => void load().catch(toastError), destroy: () => offs.forEach((o) => o()) };
}
