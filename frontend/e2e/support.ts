/**
 * Shared helpers for the Chromium harness. Seed passwords are read from the generated
 * (git-ignored) backend/.env or the environment; no credential literal lives in source.
 *
 * Every browser run that uses these helpers is a *virtual* Chromium run. It is not evidence
 * for a physical tablet camera, a physical browser restart, lighting, or Excel.
 */
import fs from "node:fs";
import path from "node:path";
import { expect, type BrowserContext, type Page } from "@playwright/test";

/** Specs run from frontend/ (npm scripts), so the repository root is its parent. */
export const REPO_ROOT = path.resolve(process.cwd(), "..");
export const BASE_URL = process.env.ETMS_E2E_BASE_URL ?? "http://127.0.0.1:4173";
export const DEVICE_TOKEN_KEY = "etms.deviceToken";
export const CHROMIUM_EXECUTABLE =
  process.env.ETMS_CHROMIUM_EXECUTABLE ?? "/ms-playwright/chromium-1234/chrome-linux64/chrome";
/** Backend reached directly (bypassing the outage proxy) for test-side verification calls. */
export const DIRECT_API_URL = process.env.ETMS_E2E_DIRECT_API_URL ?? "http://127.0.0.1:8000";
/** Control endpoint of e2e/outage-proxy.mjs, started by playwright.config.ts. */
export const OUTAGE_CONTROL_URL = process.env.ETMS_E2E_OUTAGE_URL ?? "http://127.0.0.1:8100/__control";

/**
 * Take the browser's network up or down. The backend is cut through the outage proxy (this is what
 * the service worker's /api requests see) and the page-level emulation is switched as well.
 */
export async function setNetwork(context: BrowserContext, online: boolean): Promise<void> {
  const response = await fetch(`${OUTAGE_CONTROL_URL}/${online ? "up" : "down"}`, { method: "POST" });
  if (!response.ok) throw new Error(`outage proxy control failed with HTTP ${response.status}`);
  await context.setOffline(!online);
}

/** Read one value from the environment or backend/.env (quotes stripped); undefined when absent. */
export function backendEnv(name: string): string | undefined {
  if (process.env[name]) return process.env[name];
  const file = path.join(REPO_ROOT, "backend", ".env");
  if (!fs.existsSync(file)) return undefined;
  for (const line of fs.readFileSync(file, "utf-8").split(/\r?\n/)) {
    const index = line.indexOf("=");
    if (index > 0 && line.slice(0, index).trim() === name) {
      return line.slice(index + 1).trim().replace(/^["']|["']$/g, "");
    }
  }
  return undefined;
}

/** Return a required seed password or throw a clear, non-secret error. */
export function requirePassword(name: string): string {
  const value = backendEnv(name);
  if (!value) throw new Error(`${name} is missing; run bash scripts/gen_env.sh or export it.`);
  return value;
}

/** Chromium flags that feed a Y4M file to getUserMedia (virtual camera only). */
export function virtualCameraArgs(file: string): string[] {
  return [
    "--use-fake-device-for-media-stream",
    "--use-fake-ui-for-media-stream",
    `--use-file-for-fake-video-capture=${file}`,
  ];
}

/** Sign in through the real login form and wait for the dashboard. */
export async function uiLogin(page: Page, username: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Supervisor dashboard" })).toBeVisible();
}

/** Minimal RFC 4180 parser (quoted fields, doubled quotes) for the exported CSV. */
export function parseCsv(text: string, delimiter = ","): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === delimiter) { row.push(field); field = ""; }
    else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += char;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows.filter((entry) => entry.some((value) => value !== ""));
}
