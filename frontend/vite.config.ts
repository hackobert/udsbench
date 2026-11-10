import { defineConfig } from "vitest/config";

// Backend-Adresse des Dev-Servers (optional über UDSBENCH_BACKEND überschreibbar)
const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const backend = env["UDSBENCH_BACKEND"] ?? "http://127.0.0.1:8765";

export default defineConfig({
  base: "/",
  build: {
    outDir: "../backend/udsbench/static",
    emptyOutDir: true,
    assetsDir: "assets",
    target: "es2022",
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend, ws: true, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
