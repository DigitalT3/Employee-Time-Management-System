/**
 * Staff top bar regression checks in real Chromium (production preview build, synthetic data):
 *
 * 1. The language selector and the log-out button must be readable. They were reported as plain white
 *    boxes because the dark top bar sets white text while the global form-control rule gives a white
 *    background and inherits the text colour (white on white). The check measures the computed
 *    colours instead of relying on axe, which does not flag this case.
 * 2. A saved language must set `<html lang>` when the page loads, not only when the switch is used.
 * 3. The "no access" message follows the selected language.
 *
 * CONDITIONS: headless Chromium, production preview build, seed accounts. Visual judgement on a real
 * tablet or desktop browser remains a manual observation.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { BASE_URL, requirePassword } from "./support";

/** WCAG 2 minimum contrast for normal text. */
const MIN_CONTRAST = 4.5;

/** Computed text colour, the nearest painted background and the resulting contrast ratio. */
async function measure(locator: Locator): Promise<{ color: string; background: string; contrast: number }> {
  return locator.evaluate((element) => {
    const parse = (value: string): number[] => (value.match(/[\d.]+/g) ?? []).map(Number);
    const luminance = ([r, g, b]: number[]): number => {
      const channel = (v: number) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    };
    const style = getComputedStyle(element);
    // Walk up until a non-transparent background is found (the control itself is normally painted).
    let background = style.backgroundColor;
    let node: Element | null = element;
    while (node && parse(background).length >= 4 && parse(background)[3] === 0) {
      node = node.parentElement;
      background = node ? getComputedStyle(node).backgroundColor : "rgb(255, 255, 255)";
    }
    const fg = luminance(parse(style.color));
    const bg = luminance(parse(background));
    const [hi, lo] = fg > bg ? [fg, bg] : [bg, fg];
    return { color: style.color, background, contrast: (hi + 0.05) / (lo + 0.05) };
  });
}

/**
 * Save a language in localStorage before the application starts. This happens only on the first load
 * of the tab, so a later reload sees whatever the application itself saved.
 */
async function seedLanguage(page: Page, lang: "en" | "nl"): Promise<void> {
  await page.addInitScript((value) => {
    if (sessionStorage.getItem("test.langSeeded")) return;
    sessionStorage.setItem("test.langSeeded", "1");
    localStorage.setItem("etms.lang", value);
  }, lang);
}

/** Sign in through the real form with the language saved beforehand. */
async function signIn(page: Page, lang: "en" | "nl", username: string, passwordVariable: string): Promise<void> {
  await seedLanguage(page, lang);
  await page.goto("/login");
  const [userLabel, passwordLabel, buttonName] = lang === "nl"
    ? ["Gebruikersnaam", "Wachtwoord", "Inloggen"]
    : ["Username", "Password", "Log in"];
  await page.getByLabel(userLabel).fill(username);
  await page.getByLabel(passwordLabel).fill(requirePassword(passwordVariable));
  await page.getByRole("button", { name: buttonName }).click();
}

for (const lang of ["en", "nl"] as const) {
  test(`top bar language select and log-out button are readable (${lang})`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
    const page = await context.newPage();
    await signIn(page, lang, "admin", "SEED_ADMIN_PASSWORD");
    const header = page.locator("header.topbar");
    await expect(header).toBeVisible();

    const select = header.getByRole("combobox", { name: lang === "nl" ? "Taal" : "Language" });
    const logout = header.getByRole("button", { name: lang === "nl" ? "Uitloggen" : "Log out" });
    await expect(select).toBeVisible();
    await expect(logout).toBeVisible();

    const selectStyle = await measure(select);
    const logoutStyle = await measure(logout);
    await testInfo.attach(`topbar-${lang}.png`, { body: await header.screenshot(), contentType: "image/png" });

    expect(selectStyle.contrast, `language select ${selectStyle.color} on ${selectStyle.background}`).toBeGreaterThanOrEqual(MIN_CONTRAST);
    expect(logoutStyle.contrast, `log-out button ${logoutStyle.color} on ${logoutStyle.background}`).toBeGreaterThanOrEqual(MIN_CONTRAST);

    // The controls must also stand out from the dark bar, so they are not mistaken for blank boxes.
    await expect(select).toHaveCSS("border-top-style", "solid");
    await context.close();
  });
}

test("a saved language sets the document language when the page loads", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  const page = await context.newPage();
  await seedLanguage(page, "nl");
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Inloggen medewerkers" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "nl");

  // Switching back updates the attribute and the choice survives a reload.
  await page.getByRole("combobox", { name: "Taal" }).selectOption("en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await context.close();
});

test("the no-access message is shown in the selected language", async ({ browser }) => {
  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  const page = await context.newPage();
  // HR never holds permissions.manage under the default matrix.
  await signIn(page, "nl", "hr", "SEED_HR_PASSWORD");
  await expect(page.getByRole("heading", { name: "Dashboard leidinggevende" })).toBeVisible();
  await page.goto("/permissions");
  await expect(page.getByRole("alert")).toHaveText("Uw rol heeft geen toegang tot deze pagina.");

  await page.getByRole("combobox", { name: "Taal" }).selectOption("en");
  await expect(page.getByRole("alert")).toHaveText("Your role does not have access to this page.");
  await context.close();
});
