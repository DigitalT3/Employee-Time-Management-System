import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const DEVICE_TOKEN_KEY = "etms.deviceToken";

async function openScanner(page: Parameters<typeof test>[0] extends never ? never : any) {
  await page.addInitScript((key) => {
    localStorage.setItem(key, "virtual-browser-test-device");
  }, DEVICE_TOKEN_KEY);
  await page.goto("/scanner");
  await expect(page.getByRole("heading", { name: "Scanner" })).toBeVisible();
}

test("production scanner shell reloads while the network is unavailable", async ({ page, context }) => {
  await openScanner(page);
  await page.waitForFunction(async () => {
    const registration = await navigator.serviceWorker.ready;
    return Boolean(registration.active);
  });
  // A newly installed worker controls subsequent pages, not the page that
  // registered it. Reload once online before asserting an offline reload.
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null);

  await context.setOffline(true);
  await page.reload({ waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Scanner" })).toBeVisible();
  await expect(page.getByText("Waiting to sync:")).toBeVisible();
});

test("login and kiosk have no critical axe violations", async ({ page }) => {
  await page.goto("/login");
  const loginResults = await new AxeBuilder({ page })
    .disableRules(["color-contrast"])
    .analyze();
  expect(loginResults.violations.filter((violation) => violation.impact === "critical")).toEqual([]);

  await openScanner(page);
  const kioskResults = await new AxeBuilder({ page })
    .disableRules(["color-contrast"])
    .analyze();
  expect(kioskResults.violations.filter((violation) => violation.impact === "critical")).toEqual([]);
});
