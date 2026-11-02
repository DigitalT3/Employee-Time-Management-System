/**
 * Automated axe-core scan of the staff screens in Chromium (VAL-14). Violations are written to
 * test-results/axe-staff.json so they are recorded even when the run passes; the assertion only
 * fails on critical or serious findings. An automated scan is not a full accessibility audit:
 * screen-reader, keyboard-only and touch-target checks remain manual observations.
 */
import fs from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { requirePassword, uiLogin } from "./support";

const ROUTES = ["/", "/employees", "/employees/new", "/sites", "/attendance", "/corrections", "/reports", "/permissions"];

test("staff screens have no critical or serious axe violations", async ({ page }) => {
  test.setTimeout(120_000);
  await uiLogin(page, "admin", requirePassword("SEED_ADMIN_PASSWORD"));
  const recorded: Array<{ route: string; id: string; impact: string | null | undefined; nodes: number; help: string; targets: string[] }> = [];

  for (const route of ROUTES) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    for (const violation of results.violations) {
      recorded.push({
        route, id: violation.id, impact: violation.impact, nodes: violation.nodes.length, help: violation.help,
        // Selector plus axe's measured/required contrast summary make each finding actionable.
        targets: violation.nodes.map((node) => `${node.target.join(" ")} :: ${node.any[0]?.message ?? node.failureSummary ?? ""}`),
      });
    }
  }

  fs.mkdirSync(path.join(process.cwd(), "test-results"), { recursive: true });
  fs.writeFileSync(path.join(process.cwd(), "test-results", "axe-staff.json"), JSON.stringify({ routes: ROUTES, violations: recorded }, null, 2));
  expect(recorded.filter((entry) => entry.impact === "critical" || entry.impact === "serious")).toEqual([]);
});
