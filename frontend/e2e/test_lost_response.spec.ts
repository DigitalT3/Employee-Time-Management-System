/**
 * Lost response after commit (browser level). The kiosk sends a scan, the backend commits it, and
 * the answer never reaches the tablet. The tablet must keep the capture pending, retry it with the
 * same client UUID and show the stored result, and the backend must hold exactly one event.
 *
 * CONDITIONS: headless Chromium against the production preview build and the live synthetic backend.
 * The loss is injected at the browser network layer with `page.route` (the real request is forwarded
 * with `route.fetch()` so it commits, then the page's request is aborted). Playwright routing does
 * not see service-worker traffic, so this context blocks the service worker; the worker only passes
 * /api through (NetworkOnly) and is covered by the offline specs. Not evidence for a physical tablet.
 */
import { expect, test } from "@playwright/test";
import { BASE_URL, DEVICE_TOKEN_KEY } from "./support";
import { createEmployee, createKioskDevice, directApi, firstSite, issuedToken } from "./test_fixtures";

const run = Date.now().toString(36).toUpperCase();

test("a committed scan whose response is lost is retried once and leaves exactly one event", async ({ browser }) => {
  test.setTimeout(90_000);
  test.info().annotations.push({
    type: "test-condition",
    description: "Response loss injected with page.route after the server committed; service worker blocked; virtual run only.",
  });
  const api = await directApi("admin", "SEED_ADMIN_PASSWORD");
  const site = await firstSite(api);
  const deviceToken = await createKioskDevice(api, site, `Lost ${run}`);
  const employeeId = await createEmployee(api, site, `LOST-${run}`, "Lost", "Response");
  const code = issuedToken(employeeId);

  const storedEvents = async (): Promise<Array<Record<string, any>>> => {
    const response = await api.get(`/api/attendance/events?employee_id=${employeeId}`);
    expect(response.ok()).toBeTruthy();
    return (await response.json()).items as Array<Record<string, any>>;
  };

  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US", serviceWorkers: "block" });
  await context.addInitScript(([key, value]) => localStorage.setItem(key, value), [DEVICE_TOKEN_KEY, deviceToken]);
  const page = await context.newPage();

  // First scan request: forward it (the backend commits), then drop the answer. Retries wait until
  // the test has inspected the in-between state, then pass through.
  let scanRequests = 0;
  let committedStatus = 0;
  let release!: () => void;
  const retryGate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/attendance/scan", async (route) => {
    scanRequests += 1;
    if (scanRequests === 1) {
      const upstream = await route.fetch();
      committedStatus = upstream.status();
      await route.abort("connectionreset");
      return;
    }
    await retryGate;
    await route.continue();
  });

  try {
    await page.goto("/scanner");
    await expect(page.locator(".kiosk-header .badge").first()).toHaveText("Online", { timeout: 15_000 });

    await page.getByLabel("Manual code entry").fill(code);
    await page.getByRole("button", { name: "Submit" }).click();

    // The server committed the IN event although the tablet never saw the answer.
    await expect.poll(async () => (await storedEvents()).length, { timeout: 15_000 }).toBe(1);
    expect(committedStatus).toBeGreaterThanOrEqual(200);
    expect(committedStatus).toBeLessThan(300);
    // The capture is kept on the tablet and is not reported as confirmed.
    await expect(page.locator(".scanner-status")).toContainText(/Waiting to sync:\s*1/);
    await expect(page.locator(".result")).not.toContainText("Checked IN");

    // Let the retry through: same client UUID, so the stored result is returned and nothing is added.
    release();
    await expect(page.locator(".result")).toContainText("Checked IN", { timeout: 20_000 });
    await expect(page.locator(".result")).toContainText("Lost Response");
    await expect(page.locator(".scanner-status")).toContainText(/Waiting to sync:\s*0/, { timeout: 15_000 });
    expect(scanRequests).toBeGreaterThanOrEqual(2);

    const events = await storedEvents();
    expect(events).toHaveLength(1);
    expect(events[0].direction).toBe("IN");
    expect(events[0].capture_mode).toBe("online");
  } finally {
    release();
    await context.close();
    await api.dispose();
  }
});
