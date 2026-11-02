import { defineConfig } from "@playwright/test";

const chromiumExecutablePath = process.env.ETMS_CHROMIUM_EXECUTABLE
  ?? "/ms-playwright/chromium-1234/chrome-linux64/chrome";
const virtualCameraFile = process.env.ETMS_VIRTUAL_CAMERA_FILE;
const virtualCameraArgs = virtualCameraFile
  ? [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      `--use-file-for-fake-video-capture=${virtualCameraFile}`,
    ]
  : [];
const outageProxyPort = process.env.ETMS_OUTAGE_PROXY_PORT ?? "8100";

/**
 * Chromium browser harness for the production Vite preview build.
 * The app shell is intentionally never tested against the Vite dev server because
 * service workers and offline reload evidence require the production build.
 *
 * The preview server reaches FastAPI through e2e/outage-proxy.mjs so that specs can cut the API
 * for real (page-level offline emulation does not reach service-worker requests).
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "test_*.spec.ts",
  timeout: 30_000,
  expect: { timeout: 8_000 },
  forbidOnly: !!process.env.CI,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: {
      executablePath: chromiumExecutablePath,
      args: virtualCameraArgs,
    },
  },
  webServer: [
    {
      command: "node e2e/outage-proxy.mjs",
      url: `http://127.0.0.1:${outageProxyPort}/__control/status`,
      reuseExistingServer: !process.env.CI,
      timeout: 15_000,
      env: { ETMS_OUTAGE_PROXY_PORT: outageProxyPort },
    },
    {
      command: "npm run preview -- --host 127.0.0.1",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      env: { ETMS_API_URL: `http://127.0.0.1:${outageProxyPort}` },
    },
  ],
});
