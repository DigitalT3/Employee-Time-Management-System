/**
 * Demonstrations A to G (specification section 19) in real Chromium against the production
 * preview build and the live synthetic backend.
 *
 * CONDITIONS: the tablet camera is a *virtual* Chromium camera that plays a Y4M video of the QR
 * issued during Demonstration A (the real ZXing decode path runs). Headless "restart" means closing
 * and relaunching a persistent Chromium profile. None of this is evidence for a physical camera,
 * physical tablet, lighting, or Excel; Demonstration G only checks the CSV file, not Excel.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  chromium, expect, request, test,
  type APIRequestContext, type Browser, type BrowserContext, type Page,
} from "@playwright/test";
import {
  BASE_URL, CHROMIUM_EXECUTABLE, DEVICE_TOKEN_KEY, DIRECT_API_URL, OUTAGE_CONTROL_URL, REPO_ROOT, parseCsv,
  requirePassword, setNetwork, uiLogin, virtualCameraArgs,
} from "./support";

const DUPLICATE_WINDOW_SECONDS = 4;
const run = Date.now().toString(36).toUpperCase();
const fullName = "Alex Morgan";
const employeeNumber = `E2E-${run}`;

interface SiteInfo { id: string; code: string; name: string }
const state: {
  api?: APIRequestContext; site?: SiteInfo; deviceToken?: string; employeeId?: string;
  fixture?: string; virtualBrowser?: Browser; kioskContext?: BrowserContext; kiosk?: Page;
  admin?: Page; adminContext?: BrowserContext; profileDir?: string;
  timings: Record<string, number | string>;
} = { timings: {} };

const api = () => state.api!;

/** Stored events for the demonstration employee, oldest first. */
async function storedEvents(): Promise<Array<Record<string, any>>> {
  const response = await api().get(`/api/attendance/events?employee_id=${state.employeeId}`);
  expect(response.ok()).toBeTruthy();
  return ((await response.json()).items as Array<Record<string, any>>).slice().reverse();
}

/** Stop the camera if it runs, then start it again (a fresh decode latch, same virtual feed). */
async function restartCamera(page: Page): Promise<void> {
  const stop = page.getByRole("button", { name: "Stop camera" });
  if (await stop.isVisible()) {
    await stop.click();
    await expect(page.getByText("Camera off")).toBeVisible();
  }
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.getByText("Camera active")).toBeVisible({ timeout: 15_000 });
}

const connectionBadge = (page: Page) => page.locator(".kiosk-header .badge").first();
const pendingCount = (page: Page) => page.locator(".scanner-status");

test.describe.configure({ mode: "serial", timeout: 150_000 });

test.beforeAll(async ({ browser }) => {
  // Verification calls go straight to the backend so they keep working during a simulated outage.
  state.api = await request.newContext({ baseURL: DIRECT_API_URL });
  const login = await api().post("/api/auth/login", {
    data: { username: "admin", password: requirePassword("SEED_ADMIN_PASSWORD") },
  });
  expect(login.ok()).toBeTruthy();
  const sites = (await (await api().get("/api/sites")).json()) as SiteInfo[];
  state.site = sites[0];
  const settings = await api().put(`/api/sites/${state.site.id}/settings`, {
    data: { duplicate_window_seconds: DUPLICATE_WINDOW_SECONDS, missing_out_cutoff_time: "06:00:00" },
  });
  expect(settings.ok()).toBeTruthy();
  const gate = await api().post(`/api/sites/${state.site.id}/gates`, { data: { name: `Browser Gate ${run}` } });
  const device = await api().post("/api/devices", {
    data: { name: `Browser Tablet ${run}`, gate_id: (await gate.json()).id },
  });
  expect(device.status()).toBe(201);
  state.deviceToken = (await device.json()).device_token;

  state.adminContext = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  state.admin = await state.adminContext.newPage();
});

test.afterAll(async () => {
  fs.mkdirSync(path.join(process.cwd(), "test-results"), { recursive: true });
  // Never leave the outage proxy cut for the next spec.
  await fetch(`${OUTAGE_CONTROL_URL}/up`, { method: "POST" }).catch(() => undefined);
  fs.writeFileSync(
    path.join(process.cwd(), "test-results", "browser-timings.json"),
    JSON.stringify({
      conditions: "virtual Chromium camera, headless, production preview build, loopback network, synthetic data; not a physical device",
      duplicate_window_seconds: DUPLICATE_WINDOW_SECONDS,
      ...state.timings,
    }, null, 2),
  );
  await state.kioskContext?.close();
  await state.virtualBrowser?.close();
  await state.adminContext?.close();
  await state.api?.dispose();
  if (state.fixture) fs.rmSync(state.fixture, { force: true });
  if (state.profileDir) fs.rmSync(state.profileDir, { recursive: true, force: true });
});

test("A: administrator registers an employee and the permanent QR is retained", async () => {
  const page = state.admin!;
  await uiLogin(page, "admin", requirePassword("SEED_ADMIN_PASSWORD"));
  await page.goto("/employees/new");
  await page.getByLabel("Employee number").fill(employeeNumber);
  await page.getByLabel("First name").fill("Alex");
  await page.getByLabel("Last name").fill("Morgan");
  await page.getByRole("checkbox", { name: `${state.site!.code} – ${state.site!.name}` }).check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(/\/employees\/[0-9a-f-]{36}$/);
  state.employeeId = page.url().split("/").pop();

  const qr = page.getByRole("img", { name: `QR ${employeeNumber}` });
  await expect(qr).toBeVisible();
  await expect.poll(() => qr.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

  const issued = await (await api().get(`/api/employees/${state.employeeId}/qr.png`)).body();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download PNG" }).click();
  const download = await downloadPromise;
  expect(Buffer.compare(fs.readFileSync((await download.path())!), issued)).toBe(0);

  // Reopen the employee: the same permanent credential image is served.
  await page.goto("/employees");
  await page.goto(`/employees/${state.employeeId}`);
  await expect(page.getByRole("img", { name: `QR ${employeeNumber}` })).toBeVisible();
  const reopened = await (await api().get(`/api/employees/${state.employeeId}/qr.png`)).body();
  expect(Buffer.compare(issued, reopened)).toBe(0);

  // Build the virtual camera feed from the credential that was just issued.
  state.fixture = path.join(os.tmpdir(), `etms-qr-${run}.y4m`);
  execFileSync(
    path.join(REPO_ROOT, "backend", ".venv", "bin", "python"),
    [path.join(REPO_ROOT, "scripts", "make_fake_camera.py"), "--employee-id", state.employeeId!, "--output", state.fixture],
    { cwd: REPO_ROOT, stdio: "pipe" },
  );
  state.virtualBrowser = await chromium.launch({
    executablePath: CHROMIUM_EXECUTABLE,
    args: virtualCameraArgs(state.fixture),
  });
  state.kioskContext = await state.virtualBrowser.newContext({
    baseURL: BASE_URL, locale: "en-US", permissions: ["camera"],
  });
  await state.kioskContext.addInitScript(
    ([key, value]) => localStorage.setItem(key, value),
    [DEVICE_TOKEN_KEY, state.deviceToken!],
  );
  state.kiosk = await state.kioskContext.newPage();
  await state.kiosk.goto("/scanner");
  await expect(connectionBadge(state.kiosk)).toHaveText("Online", { timeout: 15_000 });
  // Let the service worker take control so later offline reloads are served from the shell.
  await state.kiosk.waitForFunction(async () => Boolean((await navigator.serviceWorker.ready).active));
  await state.kiosk.reload({ waitUntil: "domcontentloaded" });
  await state.kiosk.waitForFunction(() => navigator.serviceWorker.controller !== null);
  await expect(connectionBadge(state.kiosk)).toHaveText("Online", { timeout: 15_000 });
});

test("B and D: the virtual camera reads the QR, IN is confirmed, a repeat is suppressed, the dashboard shows the employee", async () => {
  const kiosk = state.kiosk!;
  const staff = state.admin!;
  await staff.goto("/");
  await expect(staff.getByRole("heading", { name: "Supervisor dashboard" })).toBeVisible();

  const started = Date.now();
  await restartCamera(kiosk);
  const result = kiosk.locator(".result");
  await expect(result).toContainText("Checked IN", { timeout: 15_000 });
  state.timings.camera_start_click_to_green_in_ms = Date.now() - started;
  await expect(result).toContainText(fullName);
  await expect(kiosk.locator(".result.in")).toBeVisible();
  const confirmedAt = Date.now();

  // Demonstration D (tablet side): the same code presented again inside the window is not re-sent.
  await restartCamera(kiosk);
  await expect(result).toContainText("Already processed", { timeout: 10_000 });
  expect(await storedEvents()).toHaveLength(1);

  await expect(staff.getByRole("link", { name: fullName })).toBeVisible({ timeout: 12_000 });
  state.timings.green_in_to_dashboard_row_ms = Date.now() - confirmedAt;
  expect(Number(state.timings.green_in_to_dashboard_row_ms)).toBeLessThan(10_000);
});

test("C: the same QR after the duplicate window records OUT with a duration and the dashboard updates", async () => {
  const kiosk = state.kiosk!;
  await kiosk.waitForTimeout((DUPLICATE_WINDOW_SECONDS + 2) * 1000);
  await restartCamera(kiosk);
  const result = kiosk.locator(".result");
  await expect(result).toContainText("Checked OUT", { timeout: 15_000 });
  await expect(result).toContainText("Attendance duration");
  const confirmedAt = Date.now();
  await expect(state.admin!.getByRole("link", { name: fullName })).toBeHidden({ timeout: 12_000 });
  state.timings.green_out_to_dashboard_update_ms = Date.now() - confirmedAt;
  const events = await storedEvents();
  expect(events.map((event) => event.direction)).toEqual(["IN", "OUT"]);
});

test("E: offline captures stay pending across a reload and synchronise once, in order, after reconnect", async () => {
  const kiosk = state.kiosk!;
  const context = state.kioskContext!;
  await setNetwork(context, false);
  await expect(connectionBadge(kiosk)).toContainText("Offline", { timeout: 20_000 });

  await restartCamera(kiosk);
  await expect(kiosk.locator(".result")).toContainText("Recorded on this tablet", { timeout: 15_000 });
  await expect(pendingCount(kiosk)).toContainText(/Waiting to sync:\s*1/);
  await kiosk.waitForTimeout((DUPLICATE_WINDOW_SECONDS + 2) * 1000);
  await restartCamera(kiosk);
  await expect(pendingCount(kiosk)).toContainText(/Waiting to sync:\s*2/, { timeout: 15_000 });

  // Refresh while offline: the application shell loads from the service worker and the queue remains.
  await kiosk.reload({ waitUntil: "domcontentloaded" });
  await expect(kiosk.getByRole("heading", { name: "Scanner" })).toBeVisible();
  await expect(pendingCount(kiosk)).toContainText(/Waiting to sync:\s*2/);
  expect(await storedEvents()).toHaveLength(2);

  const reconnected = Date.now();
  await setNetwork(context, true);
  await expect(pendingCount(kiosk)).toContainText(/Waiting to sync:\s*0/, { timeout: 40_000 });
  state.timings.reconnect_to_queue_drained_ms = Date.now() - reconnected;

  const events = await storedEvents();
  expect(events.map((event) => event.direction)).toEqual(["IN", "OUT", "IN", "OUT"]);
  expect(new Set(events.map((event) => event.id)).size).toBe(4);
  expect(events.slice(2).map((event) => event.capture_mode)).toEqual(["offline", "offline"]);
});

test("E (restart): a pending offline capture survives closing and relaunching a persistent Chromium profile", async () => {
  state.profileDir = fs.mkdtempSync(path.join(os.tmpdir(), "etms-profile-"));
  const launch = () => chromium.launchPersistentContext(state.profileDir!, {
    executablePath: CHROMIUM_EXECUTABLE,
    args: virtualCameraArgs(state.fixture!),
    baseURL: BASE_URL, locale: "en-US", permissions: ["camera"],
  });
  await new Promise((resolve) => setTimeout(resolve, (DUPLICATE_WINDOW_SECONDS + 2) * 1000));

  const first = await launch();
  await first.addInitScript(([key, value]) => localStorage.setItem(key, value), [DEVICE_TOKEN_KEY, state.deviceToken!]);
  const firstPage = first.pages()[0] ?? await first.newPage();
  await firstPage.goto("/scanner");
  await expect(connectionBadge(firstPage)).toHaveText("Online", { timeout: 15_000 });
  await firstPage.waitForFunction(async () => Boolean((await navigator.serviceWorker.ready).active));
  await firstPage.reload({ waitUntil: "domcontentloaded" });
  await firstPage.waitForFunction(() => navigator.serviceWorker.controller !== null);
  await setNetwork(first, false);
  await expect(connectionBadge(firstPage)).toContainText("Offline", { timeout: 20_000 });
  await restartCamera(firstPage);
  await expect(pendingCount(firstPage)).toContainText(/Waiting to sync:\s*1/, { timeout: 15_000 });
  await first.close();

  const second = await launch();
  await setNetwork(second, false);
  const secondPage = second.pages()[0] ?? await second.newPage();
  await secondPage.goto("/scanner");
  await expect(secondPage.getByRole("heading", { name: "Scanner" })).toBeVisible();
  await expect(pendingCount(secondPage)).toContainText(/Waiting to sync:\s*1/);
  await setNetwork(second, true);
  await expect(pendingCount(secondPage)).toContainText(/Waiting to sync:\s*0/, { timeout: 40_000 });
  await second.close();

  const events = await storedEvents();
  expect(events).toHaveLength(5);
  expect(events[4].direction).toBe("IN");
  expect(events[4].capture_mode).toBe("offline");
});

test("F: a supervisor adds the missing OUT with a reason and the original and the audit entry stay visible", async ({ browser }) => {
  const events = await storedEvents();
  const last = events[events.length - 1];
  // datetime-local has minute precision: use the first whole minute after the IN, once it has passed.
  const target = Math.floor(new Date(last.occurred_at).getTime() / 60_000) * 60_000 + 60_000;
  const waitMs = target + 1_000 - Date.now();
  if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
  const inLocal = String(last.local_time).slice(0, 16);
  const outLocal = new Date(`${inLocal}:00Z`.replace("T", "T")).getTime() + 60_000;
  const outValue = new Date(outLocal).toISOString().slice(0, 16);

  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  const page = await context.newPage();
  await uiLogin(page, "supervisor", requirePassword("SEED_SUPERVISOR_PASSWORD"));
  await page.getByRole("link", { name: fullName }).first().click();
  await expect(page.getByRole("heading", { name: /Session detail/ })).toBeVisible();
  await page.getByLabel("New time").fill(outValue);
  await page.getByLabel("Reason (required)").fill(`E2E ${run}: employee forgot to scan out`);
  await page.getByRole("button", { name: "Apply correction" }).click();

  await expect(page.getByRole("cell", { name: `E2E ${run}: employee forgot to scan out` })).toBeVisible();
  await expect(page.getByText("By supervisor")).toBeVisible();
  // The immutable original IN event is still listed; no original OUT exists for this session.
  await expect(page.getByRole("heading", { name: "Original events" })).toBeVisible();
  await page.goto("/corrections");
  await expect(page.getByRole("cell", { name: new RegExp(`E2E ${run}`) })).toBeVisible();
  await context.close();
});

test("G: the attendance report previews the session and the CSV export contains it", async () => {
  const page = state.admin!;
  const events = await storedEvents();
  const day = String(events[events.length - 1].local_time).slice(0, 10);
  await page.goto("/reports");
  await page.getByLabel("Date").fill(day);
  await expect(page.getByRole("cell", { name: new RegExp(employeeNumber) }).first()).toBeVisible({ timeout: 15_000 });

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export attendance CSV" }).click();
  const download = await downloadPromise;
  const raw = fs.readFileSync((await download.path())!);
  expect(raw.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf]))).toBeTruthy(); // BOM for Excel
  const rows = parseCsv(raw.toString("utf-8").replace(/^\uFEFF/, ""));
  const header = rows[0];
  const mine = rows.filter((row) => row[header.indexOf("employee_number")] === employeeNumber);
  expect(mine.length).toBeGreaterThanOrEqual(3); // one row per session: two complete and one corrected
  expect(header).toEqual(expect.arrayContaining(["employee_number", "site_name", "hours", "corrected"]));
  expect(mine.some((row) => row[header.indexOf("corrected")] === "yes")).toBeTruthy();
  expect(mine.every((row) => row[header.indexOf("site_name")] === state.site!.name)).toBeTruthy();
});
