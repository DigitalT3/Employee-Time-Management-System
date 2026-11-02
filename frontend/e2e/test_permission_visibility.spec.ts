/**
 * Permission visibility (FR-13, section 5.5) in real Chromium: what each role sees in the navigation
 * and on an employee record, that restricted pages and API calls are refused, and that an
 * administrator's change to the matrix reaches another user on the next page load.
 *
 * The matrix is forced to the specification defaults first and restored to what it was afterwards.
 * CONDITIONS: headless Chromium, production preview build, synthetic data and seed accounts.
 */
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { BASE_URL, requirePassword, uiLogin } from "./support";
import { createEmployee, directApi, firstSite } from "./test_fixtures";

const run = Date.now().toString(36).toUpperCase();
const ROLES = [
  { username: "admin", passwordVariable: "SEED_ADMIN_PASSWORD" },
  { username: "supervisor", passwordVariable: "SEED_SUPERVISOR_PASSWORD" },
  { username: "hr", passwordVariable: "SEED_HR_PASSWORD" },
] as const;
type RoleName = (typeof ROLES)[number]["username"];

/** Navigation entries and the permission that reveals each one. */
const NAV: Array<{ name: string; permission: string }> = [
  { name: "Dashboard", permission: "dashboard.view" },
  { name: "Employees", permission: "employees.view" },
  { name: "Sites & devices", permission: "sites.manage" },
  { name: "Attendance", permission: "attendance.view" },
  { name: "Corrections", permission: "corrections.view" },
  { name: "Reports", permission: "reports.export" },
  { name: "Permissions", permission: "permissions.manage" },
];

/** Specification section 5.5 defaults (as implemented in backend/app/permissions.py). */
const DEFAULT_ALLOWED: Record<RoleName, string[]> = {
  admin: [
    "dashboard.view", "attendance.view", "employees.view", "employees.manage", "credentials.manage",
    "credentials.download", "attendance.correct", "corrections.view", "reports.export", "sites.manage",
    "scanlog.view", "permissions.manage",
  ],
  supervisor: [
    "dashboard.view", "attendance.view", "employees.view", "attendance.correct", "corrections.view",
    "reports.export", "scanlog.view",
  ],
  hr: ["dashboard.view", "attendance.view", "employees.view", "corrections.view", "reports.export"],
};
const ALL_PERMISSIONS = DEFAULT_ALLOWED.admin;
const defaultMatrix = Object.fromEntries(
  (Object.keys(DEFAULT_ALLOWED) as RoleName[]).map((role) => [
    role, Object.fromEntries(ALL_PERMISSIONS.map((key) => [key, DEFAULT_ALLOWED[role].includes(key)])),
  ]),
);

test.describe.configure({ mode: "serial", timeout: 90_000 });

let admin: APIRequestContext;
let originalMatrix: Record<string, Record<string, boolean>>;
let employeeId = "";
const contexts: BrowserContext[] = [];

/** Open a new signed-in staff page for a seed role. */
async function signIn(browser: Browser, role: RoleName): Promise<Page> {
  const entry = ROLES.find((item) => item.username === role)!;
  const context = await browser.newContext({ baseURL: BASE_URL, locale: "en-US" });
  contexts.push(context);
  const page = await context.newPage();
  await uiLogin(page, entry.username, requirePassword(entry.passwordVariable));
  return page;
}

const mainNav = (page: Page) => page.getByRole("navigation", { name: "Main navigation" });

test.beforeAll(async () => {
  admin = await directApi("admin", "SEED_ADMIN_PASSWORD");
  const current = await admin.get("/api/admin/permissions");
  expect(current.ok()).toBeTruthy();
  originalMatrix = (await current.json()).matrix;
  const forced = await admin.put("/api/admin/permissions", { data: { matrix: defaultMatrix } });
  expect(forced.ok()).toBeTruthy();
  employeeId = await createEmployee(admin, await firstSite(admin), `PERM-${run}`, "Permission", "Subject");
});

test.afterAll(async () => {
  // Leave the matrix exactly as it was found, whatever happened in the tests.
  await admin.put("/api/admin/permissions", { data: { matrix: originalMatrix } });
  await Promise.all(contexts.map((context) => context.close()));
  await admin.dispose();
});

for (const { username } of ROLES) {
  test(`navigation for ${username} shows exactly the entries its permissions allow`, async ({ browser }) => {
    const page = await signIn(browser, username);
    for (const entry of NAV) {
      const link = mainNav(page).getByRole("link", { name: entry.name, exact: true });
      if (DEFAULT_ALLOWED[username].includes(entry.permission)) await expect(link).toBeVisible();
      else await expect(link).toHaveCount(0);
    }
  });
}

test("HR sees employees read-only, restricted pages say so and the server refuses the same actions", async ({ browser }) => {
  const page = await signIn(browser, "hr");

  // Employee list and record: no creation, edit or credential controls.
  await page.goto("/employees");
  await expect(page.getByRole("heading", { name: "Employees", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "New employee" })).toHaveCount(0);
  await page.goto(`/employees/${employeeId}`);
  await expect(page.getByRole("heading", { name: "Permission Subject" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Edit", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Credential controls" })).toHaveCount(0);
  await expect(page.getByRole("img", { name: `QR PERM-${run}` })).toHaveCount(0);

  // Restricted routes render the access message instead of the page.
  for (const route of ["/permissions", "/sites", "/employees/new"]) {
    await page.goto(route);
    await expect(page.getByRole("alert")).toHaveText("Your role does not have access to this page.");
  }

  // The server enforces the same rules independently of the screen (session cookie of the HR page).
  const sites = await (await page.request.get("/api/sites")).json();
  expect((await page.request.get("/api/admin/permissions")).status()).toBe(403);
  expect((await page.request.put("/api/admin/permissions", { data: { matrix: {} } })).status()).toBe(403);
  const create = await page.request.post("/api/employees", {
    data: { employee_number: `DENY-${run}`, first_name: "No", last_name: "Access", site_ids: [sites[0].id] },
  });
  expect(create.status()).toBe(403);
  expect((await page.request.get(`/api/employees/${employeeId}/qr.png`)).status()).toBe(403);
});

test("the administrator sees the management controls that HR does not", async ({ browser }) => {
  const page = await signIn(browser, "admin");
  await page.goto("/employees");
  await expect(page.getByRole("link", { name: "New employee" })).toBeVisible();
  await page.goto(`/employees/${employeeId}`);
  await expect(page.getByRole("heading", { name: "Permission Subject" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Edit", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Credential controls" })).toBeVisible();
  await expect(page.getByRole("img", { name: `QR PERM-${run}` })).toBeVisible();

  // The administrator's own right to change the matrix is locked in the editor.
  await page.goto("/permissions");
  await expect(page.getByRole("checkbox", { name: "admin permissions.manage" })).toBeDisabled();
});

test("removing a permission in the editor hides the entry for HR on the next load and the server refuses it", async ({ browser }) => {
  const adminPage = await signIn(browser, "admin");
  const hrPage = await signIn(browser, "hr");
  await expect(mainNav(hrPage).getByRole("link", { name: "Reports", exact: true })).toBeVisible();

  try {
    await adminPage.goto("/permissions");
    const box = adminPage.getByRole("checkbox", { name: "hr reports.export" });
    await expect(box).toBeChecked();
    await box.uncheck();
    await adminPage.getByRole("button", { name: "Save permissions" }).click();
    await expect(adminPage.getByText("Permissions saved")).toBeVisible();

    await hrPage.goto("/");
    await expect(hrPage.getByRole("heading", { name: "Supervisor dashboard" })).toBeVisible();
    await expect(mainNav(hrPage).getByRole("link", { name: "Reports", exact: true })).toHaveCount(0);
    await hrPage.goto("/reports");
    await expect(hrPage.getByRole("alert")).toHaveText("Your role does not have access to this page.");
    expect((await hrPage.request.get("/api/reports/daily?date=2026-01-01")).status()).toBe(403);
  } finally {
    const restored = await admin.put("/api/admin/permissions", { data: { matrix: { hr: { "reports.export": true } } } });
    expect(restored.ok()).toBeTruthy();
  }

  await hrPage.goto("/");
  await expect(mainNav(hrPage).getByRole("link", { name: "Reports", exact: true })).toBeVisible();
});
