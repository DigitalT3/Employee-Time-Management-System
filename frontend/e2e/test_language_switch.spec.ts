/**
 * Dutch/English switching in real Chromium (FR-14): login, staff screens and the tablet kiosk,
 * including a translated scan rejection reason. Raw dictionary keys must never be visible.
 *
 * The document `lang` attribute must follow the saved language after a reload (also covered by
 * test_topbar_controls.spec.ts).
 *
 * CONDITIONS: headless Chromium, production preview build, synthetic data. Not a native-speaker
 * review of the Dutch wording.
 */
import { expect, test, type Page } from "@playwright/test";
import { BASE_URL, DEVICE_TOKEN_KEY, requirePassword } from "./support";
import { createKioskDevice, directApi, firstSite, unknownCode } from "./test_fixtures";

const run = Date.now().toString(36).toUpperCase();
/** Anything that looks like an untranslated dictionary key, e.g. "nav.reports" or "reason.blocked". */
const RAW_KEY = /\b(?:nav|common|login|dashboard|reports|permissions|perm|scanner|reason|outcome|role|employees|credential)\.[A-Za-z_]+/;

test.describe.configure({ mode: "serial", timeout: 60_000 });

let deviceToken = "";

test.beforeAll(async () => {
  const api = await directApi("admin", "SEED_ADMIN_PASSWORD");
  deviceToken = await createKioskDevice(api, await firstSite(api), `Lang ${run}`);
  await api.dispose();
});

const languageSelect = (page: Page, label: "Language" | "Taal") => page.getByRole("combobox", { name: label });

test("login switches to Dutch, shows Dutch errors and keeps the choice after a reload", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  const page = await context.newPage();
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Staff login" })).toBeVisible();

  await languageSelect(page, "Language").selectOption("nl");
  await expect(page.getByRole("heading", { name: "Inloggen medewerkers" })).toBeVisible();
  await expect(page.getByLabel("Gebruikersnaam")).toBeVisible();
  await expect(page.getByLabel("Wachtwoord")).toBeVisible();
  await expect(page.getByRole("button", { name: "Inloggen" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  expect(await page.evaluate(() => localStorage.getItem("etms.lang"))).toBe("nl");

  // A failed login is reported in Dutch (a user name that does not exist, so no real account is throttled).
  await page.getByLabel("Gebruikersnaam").fill(`nobody-${run.toLowerCase()}`);
  await page.getByLabel("Wachtwoord").fill("not-a-real-password");
  await page.getByRole("button", { name: "Inloggen" }).click();
  await expect(page.getByRole("alert")).toContainText("Inloggen mislukt");

  // The saved language survives a reload.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Inloggen medewerkers" })).toBeVisible();
  // The document language follows the saved language on load, not only when the switch is used.
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");
  await context.close();
});

test("staff screens switch between Dutch and English without raw dictionary keys", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  const page = await context.newPage();
  await page.addInitScript(() => localStorage.setItem("etms.lang", "nl"));
  await page.goto("/login");
  await page.getByLabel("Gebruikersnaam").fill("admin");
  await page.getByLabel("Wachtwoord").fill(requirePassword("SEED_ADMIN_PASSWORD"));
  await page.getByRole("button", { name: "Inloggen" }).click();

  const nav = page.getByRole("navigation", { name: "Hoofdnavigatie" });
  await expect(page.getByRole("heading", { name: "Dashboard leidinggevende" })).toBeVisible();
  for (const name of ["Medewerkers", "Aanwezigheid", "Correcties", "Rapporten", "Rechten"]) {
    await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Uitloggen" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(RAW_KEY);

  await page.getByRole("link", { name: "Rapporten", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Rapporten" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Aanwezigheid exporteren (CSV)" })).toBeVisible();

  await page.getByRole("link", { name: "Rechten", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Rechten per rol" })).toBeVisible();
  await expect(page.locator("th", { hasText: "Beheerder" })).toBeVisible();
  await expect(page.locator("td", { hasText: "Dashboard bekijken" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(RAW_KEY);

  // Switch back: the same screens are now English, still on the same page.
  await languageSelect(page, "Taal").selectOption("en");
  await expect(page.getByRole("heading", { name: "Role permissions" })).toBeVisible();
  await expect(page.locator("th", { hasText: "Administrator" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Reports", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText(RAW_KEY);
  await context.close();
});

test("the tablet kiosk shows Dutch and English labels and a translated rejection reason", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  await context.addInitScript(([key, value]) => localStorage.setItem(key, value), [DEVICE_TOKEN_KEY, deviceToken]);
  const page = await context.newPage();
  await page.goto("/scanner");
  await expect(page.locator(".kiosk-header .badge").first()).toHaveText("Online", { timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Start camera" })).toBeVisible();

  await languageSelect(page, "Language").selectOption("nl");
  await expect(page.getByRole("button", { name: "Camera starten" })).toBeVisible();
  await expect(page.getByText("Camera uit")).toBeVisible();
  await expect(page.locator(".scanner-status")).toContainText("Wacht op synchronisatie");
  await expect(page.locator(".result")).toContainText("Klaar om te scannen");

  // An unknown code is rejected by the server; the reason is shown in Dutch and carries no identity.
  await page.getByLabel("Handmatige code-invoer").fill(unknownCode());
  await page.getByRole("button", { name: "Verzenden" }).click();
  await expect(page.locator(".result")).toContainText("Geweigerd", { timeout: 15_000 });
  await expect(page.locator(".result")).toContainText("Onbekende QR-code");
  await expect(page.locator("body")).not.toContainText(RAW_KEY);

  await languageSelect(page, "Taal").selectOption("en");
  await expect(page.getByRole("button", { name: "Start camera" })).toBeVisible();
  await page.getByLabel("Manual code entry").fill(unknownCode());
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.locator(".result")).toContainText("Rejected", { timeout: 15_000 });
  await expect(page.locator(".result")).toContainText("Unknown QR code");
  await expect(page.locator("body")).not.toContainText(RAW_KEY);
  await context.close();
});
