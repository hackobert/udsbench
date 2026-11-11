/** Schlichte Linien-Icons (24×24, stroke) als Inline-SVG – keine externen Ressourcen. */
import { svg } from "./dom";

const PATHS: Record<string, string> = {
  trace: "M3 6h18M3 12h12M3 18h16",
  chart: "M4 20V10M10 20V4M16 20v-7M21 20H3",
  send: "M4 12l16-8-6 16-2-6-8-2z",
  did: "M4 5h16v14H4zM4 10h16M10 10v9",
  dtc: "M12 3l9 16H3l9-16zM12 10v4M12 17v.5",
  routine: "M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3",
  message: "M3 6h18v12H3zM3 7l9 6 9-6",
  sequence: "M5 5h4v4H5zM15 15h4v4h-4zM9 7h4a2 2 0 0 1 2 2v6",
  test: "M5 12l4 4 10-10",
  dashboard: "M4 4h7v9H4zM13 4h7v5h-7zM13 11h7v9h-7zM4 15h7v5H4z",
  report: "M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5",
  record: "M12 12m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0M12 12m-8.5 0a8.5 8.5 0 1 0 17 0a8.5 8.5 0 1 0-17 0",
  logs: "M5 4h14v16H5zM8 8h8M8 12h8M8 16h5",
  plug: "M9 3v5M15 3v5M7 8h10v4a5 5 0 0 1-10 0zM12 17v4",
  layers: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5",
  package: "M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10",
  terminal: "M4 5h16v14H4zM7 9l3 3-3 3M12 15h5",
  help: "M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17v.5",
  search: "M11 11m-6 0a6 6 0 1 0 12 0a6 6 0 1 0-12 0M20 20l-4.5-4.5",
  sun: "M12 12m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5",
  moon: "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
  key: "M8 15m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0M11 12l9-9M17 6l3 3",
  menu: "M4 6h16M4 12h16M4 18h16",
  collapse: "M15 6l-6 6 6 6",
  expand: "M9 6l6 6-6 6",
  wizard: "M4 20l10-10M14 10l2-2M15 4v2M19 8h2M18 5l1.5-1.5M12 6l1 1M17 11l1 1",
  device: "M5 7h14v10H5zM8 17v3M16 17v3M8 4v3M16 4v3M9 11h6M9 14h3",
};

export function icon(name: string, size = 18): SVGSVGElement {
  return svg(
    "svg",
    {
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 1.7,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
      class: "icon",
    },
    svg("path", { d: PATHS[name] ?? PATHS["layers"] }),
  );
}
