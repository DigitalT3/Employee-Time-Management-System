/// <reference types="vitest" />
import basicSsl from "@vitejs/plugin-basic-ssl";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Single-origin development: the browser talks to :3000 (dev) or :4173 (preview) and /api is proxied to FastAPI.
const defaultBackend = "http://127.0.0.1:8000"; // FastAPI dev server

/**
 * `vite --mode https` / `vite preview --mode https` serve a self-signed certificate so that
 * camera access and the service worker also work from a tablet that opens the LAN address.
 * The service worker only exists in the production build (DEC-06); the dev server cannot work offline.
 */
export default defineConfig(({ mode }) => {
  // ETMS_API_URL (environment or .env) overrides the proxy target; the browser harness uses it to
  // route through a controllable outage proxy. loadEnv also reads ETMS_* process environment variables.
  const backend = loadEnv(mode, ".", "ETMS_").ETMS_API_URL ?? defaultBackend;
  const proxy = { "/api": backend };

  return {
    plugins: [
      react(),
      ...(mode === "https" ? [basicSsl()] : []),
      ...(mode === "test"
        ? []
        : [
            VitePWA({
              // Registered explicitly (and only) by the scanner route, see src/pwa.ts.
              injectRegister: false,
              registerType: "autoUpdate",
              manifest: {
                name: "Time Management Scanner",
                short_name: "Scanner",
                start_url: "/scanner",
                scope: "/",
                display: "fullscreen",
                background_color: "#12355b",
                theme_color: "#12355b",
              },
              workbox: {
                globPatterns: ["**/*.{js,css,html,svg,webmanifest}"],
                // Any navigation (including /scanner) is answered with the cached application shell.
                navigateFallback: "/index.html",
                navigateFallbackDenylist: [/^\/api\//],
                // The API is never cached: attendance data must come from the server only.
                runtimeCaching: [{ urlPattern: ({ url }) => url.pathname.startsWith("/api/"), handler: "NetworkOnly" }],
                cleanupOutdatedCaches: true,
                clientsClaim: true,
                skipWaiting: true,
              },
            }),
          ]),
    ],
    server: { port: 3000, host: "0.0.0.0", proxy },
    preview: { port: 4173, host: "0.0.0.0", proxy },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
      globals: false,
      // Playwright owns browser specs; loading them in jsdom makes Vitest invoke a
      // second test runner and fail before component assertions can run.
      exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
    },
  };
});
