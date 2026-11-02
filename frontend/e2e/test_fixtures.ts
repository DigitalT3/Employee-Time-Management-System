/**
 * Fixtures shared by the browser regression specs that need their own synthetic data: an
 * authenticated API context that talks straight to the backend (bypassing the outage proxy), plus
 * helpers that create a kiosk device and an employee and read the issued QR payload.
 *
 * Everything created here is synthetic. Re-run `bash scripts/reset_demo.sh` after a browser run.
 * No credential literal lives in this file; seed passwords come from backend/.env or the environment.
 */
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import path from "node:path";
import { expect, request, type APIRequestContext } from "@playwright/test";
import { DIRECT_API_URL, REPO_ROOT, requirePassword } from "./support";

export interface SiteInfo { id: string; code: string; name: string }

/** Log in through the API (cookie session) and return a context bound to the backend directly. */
export async function directApi(username: string, passwordVariable: string): Promise<APIRequestContext> {
  const api = await request.newContext({ baseURL: DIRECT_API_URL });
  const login = await api.post("/api/auth/login", { data: { username, password: requirePassword(passwordVariable) } });
  expect(login.ok(), `login of ${username} through the API`).toBeTruthy();
  return api;
}

/** Return the first configured site. */
export async function firstSite(api: APIRequestContext): Promise<SiteInfo> {
  const response = await api.get("/api/sites");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as SiteInfo[])[0];
}

/** Register a new gate and scanner device for a site and return the one-time device token. */
export async function createKioskDevice(api: APIRequestContext, site: SiteInfo, label: string): Promise<string> {
  const gate = await api.post(`/api/sites/${site.id}/gates`, { data: { name: `${label} Gate` } });
  expect(gate.ok()).toBeTruthy();
  const device = await api.post("/api/devices", { data: { name: `${label} Tablet`, gate_id: (await gate.json()).id } });
  expect(device.status()).toBe(201);
  return (await device.json()).device_token as string;
}

/** Create an employee assigned to a site (a permanent QR credential is issued at the same time). */
export async function createEmployee(
  api: APIRequestContext, site: SiteInfo, employeeNumber: string, firstName: string, lastName: string,
): Promise<string> {
  const response = await api.post("/api/employees", {
    data: { employee_number: employeeNumber, first_name: firstName, last_name: lastName, site_ids: [site.id] },
  });
  expect(response.status()).toBe(201);
  return (await response.json()).id as string;
}

/**
 * Read the opaque QR payload that the tablet would submit for an employee, using the same helper as
 * scripts/make_fake_camera.py. The value stays in memory and is never logged.
 */
export function issuedToken(employeeId: string): string {
  const script = "import sys; sys.path.insert(0, 'scripts'); import make_fake_camera as m; sys.stdout.write(m._issued_payload(sys.argv[1]))";
  return execFileSync(
    path.join(REPO_ROOT, "backend", ".venv", "bin", "python"),
    ["-c", script, employeeId],
    { cwd: REPO_ROOT, encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();
}

/** A random opaque code that no credential matches (43 URL-safe characters, like a real payload). */
export function unknownCode(): string {
  return crypto.randomBytes(32).toString("base64url");
}
