/** Geräteverwaltung: eigene Geräte anlegen/bearbeiten/testen/löschen, Demo-Geräte ein-/ausblenden. */
import { toast, toastError } from "../components/toast";
import { badge, button, card, confirmDialog, table } from "../components/ui";
import { describeIds, type DeviceInfo } from "../device-model";
import { h, replace } from "../dom";
import { t } from "../i18n";
import type { AppCtx, View } from "../view";
import { requestSetup, type SetupStatus } from "./setup";

export function createDevicesView(ctx: AppCtx): View {
  const { api, store } = ctx;
  const ownBox = h("div");
  const demoBox = h("div");
  const otherBox = h("div");
  let devices: DeviceInfo[] = [];
  let status: SetupStatus | null = null;

  const openWizard = (intent: Parameters<typeof requestSetup>[0]) => {
    requestSetup(intent);
    ctx.navigate("setup");
  };

  const load = async () => {
    [devices, status] = await Promise.all([
      api.get<DeviceInfo[]>("/devices"),
      api.get<SetupStatus>("/setup"),
    ]);
    render();
  };

  const setDemo = async (enabled: boolean) => {
    await api.put("/setup/demo", { enabled });
    toast(t(enabled ? "dev.demoShown" : "dev.demoHidden"), "success");
    await Promise.all([load(), store.refreshAll()]);
  };

  const remove = async (d: DeviceInfo) => {
    const ok = await confirmDialog(t("dev.deleteConfirm", { name: d.name || d.id }), {
      title: t("dev.deleteTitle"),
    });
    if (!ok) return;
    await api.del(`/devices/${encodeURIComponent(d.id)}`);
    toast(t("dev.deleted", { name: d.name || d.id }), "success");
    await Promise.all([load(), store.refreshAll()]);
  };

  const cols = (actions: (d: DeviceInfo) => HTMLElement | null) => [
    {
      key: "name",
      label: t("common.name"),
      render: (d: DeviceInfo) =>
        h(
          "div",
          null,
          h("strong", null, d.name || d.id),
          h("div", { class: "muted small" }, d.id, d.description ? ` · ${d.description}` : ""),
        ),
    },
    { key: "ids", label: t("dev.ids"), render: (d: DeviceInfo) => h("code", null, describeIds(d.profile)) },
    { key: "ch", label: t("dev.channel"), render: (d: DeviceInfo) => d.profile.channel ?? "default" },
    {
      key: "st",
      label: t("common.status"),
      render: (d: DeviceInfo) =>
        d.connected ? badge(t("dev.reachable"), "ok") : badge(t("dev.notConnected"), "muted"),
    },
    { key: "x", label: "", render: actions },
  ];

  const render = () => {
    const own = devices.filter((d) => d.editable);
    const demo = devices.filter((d) => d.demo);
    const other = devices.filter((d) => !d.editable && !d.demo);

    replace(
      ownBox,
      own.length
        ? table<DeviceInfo>(
            cols((d) =>
              h(
                "span",
                { class: "inline" },
                button(t("dev.test"), () => openWizard({ mode: "test", ecu: d.id })),
                button(t("dev.edit"), () => openWizard({ mode: "device", ecu: d.id }), { kind: "ghost" }),
                button(t("common.delete"), () => remove(d), { kind: "danger" }),
              ),
            ),
            own,
            { rowClass: (d) => (d.id === store.selectedEcu ? "row-selected" : "") },
          )
        : h(
            "div",
            { class: "empty setup-empty" },
            h("p", null, t("dev.noneOwn")),
            button(`+ ${t("dev.add")}`, () => openWizard({ mode: "device" }), { kind: "primary" }),
            " ",
            button(t("dev.wizard"), () => openWizard({ mode: "full" })),
          ),
    );

    const demoActive = status?.demo.active ?? false;
    replace(
      demoBox,
      h("p", { class: "muted" }, t(demoActive ? "dev.demoActiveText" : "dev.demoInactiveText")),
      demoActive && demo.length
        ? table<DeviceInfo>(
            cols(() => null),
            demo,
          )
        : null,
      status?.demo.available
        ? h(
            "div",
            { class: "row" },
            demoActive
              ? button(t("dev.hideDemo"), () => setDemo(false), { kind: "primary" })
              : button(t("dev.showDemo"), () => setDemo(true)),
          )
        : null,
    );

    otherBox.hidden = !other.length;
    replace(
      otherBox,
      card(
        t("dev.otherTitle"),
        h("p", { class: "muted" }, t("dev.otherText")),
        table<DeviceInfo>(
          cols((d) =>
            h(
              "span",
              { class: "inline" },
              badge(d.package),
              button(t("dev.test"), () => openWizard({ mode: "test", ecu: d.id }), { kind: "ghost" }),
            ),
          ),
          other,
        ),
        h(
          "div",
          { class: "row" },
          button(t("dev.toPackages"), () => ctx.navigate("packages"), { kind: "ghost" }),
        ),
      ),
    );
  };

  const el = h(
    "div",
    { class: "view-grid" },
    card(
      h(
        "span",
        { class: "card-title-row" },
        t("dev.ownTitle"),
        h(
          "span",
          { class: "inline" },
          button(`+ ${t("dev.add")}`, () => openWizard({ mode: "device" }), { kind: "primary" }),
          button(t("dev.wizard"), () => openWizard({ mode: "full" }), { kind: "ghost" }),
        ),
      ),
      h("p", { class: "muted" }, t("dev.ownText")),
      ownBox,
    ),
    card(t("dev.demoTitle"), demoBox),
    otherBox,
  );

  const off = store.on("packages", () => void load().catch(() => undefined));
  return {
    el,
    show: () => void load().catch(toastError),
    destroy: off,
  };
}
