/** Typed fetch wrapper for the ETMS backend (cookie session; same origin via Vite proxy). */
import type {
  Correction, Credential, Daily, Dashboard, Device, DeviceCreated, Employee, Gate, OnSite, Paged, PermissionMatrix,
  Ping, QrInfo, ReportPreview, ScannerContext, ScanLogItem, ScanResult, SessionDetail, SessionRow, Site,
  SiteSettings, SyncStatusItem, User,
} from "./types";

export const API_BASE = "/api";

/** Error carrying the backend's {code, message} envelope. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter?: number) {
    super(message);
  }
}

/** True for failures that should be retried later (offline, timeouts, throttling, 5xx). */
export function isRetryable(e: unknown): boolean {
  return !(e instanceof ApiError) || e.status >= 500 || e.status === 429 || e.status === 408;
}

async function toError(res: Response): Promise<ApiError> {
  let code = "http_error";
  let message = `HTTP ${res.status}`;
  let retryAfter: number | undefined;
  const header = Number(res.headers?.get?.("Retry-After"));
  if (Number.isFinite(header) && header > 0) retryAfter = header;
  try {
    const body = await res.json();
    code = body.code ?? code;
    if (typeof body.retry_after_seconds === "number") retryAfter = body.retry_after_seconds;
    if (typeof body.message === "string") message = body.message;
    else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch { /* non-JSON body */ }
  return new ApiError(res.status, code, message, retryAfter);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.body) headers["Content-Type"] = "application/json";
  const res = await fetch(API_BASE + path, { credentials: "include", ...init, headers });
  if (!res.ok) throw await toError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const body = (data: unknown) => JSON.stringify(data);
const qs = (p: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") s.set(k, String(v)); });
  const out = s.toString();
  return out ? `?${out}` : "";
};

export interface EmployeeInput {
  employee_number: string; first_name: string; last_name: string; site_ids: string[];
}

/**
 * Device-authenticated request. Returns the status and JSON for scan outcomes (including 409 conflicts) and
 * throws an ApiError for authentication problems, other 4xx rejections and server failures. An optional
 * timeout aborts hung requests so the connectivity probe cannot block.
 */
export async function deviceRequest<T>(
  path: string, deviceToken: string, data?: unknown, timeoutMs?: number,
): Promise<{ status: number; json: T }> {
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = controller && timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  try {
    const res = await fetch(API_BASE + path, {
      method: data === undefined ? "GET" : "POST",
      headers: { "X-Device-Token": deviceToken, ...(data === undefined ? {} : { "Content-Type": "application/json" }) },
      body: data === undefined ? undefined : body(data),
      cache: "no-store",
      signal: controller?.signal,
    });
    if (!res.ok && res.status !== 409) throw await toError(res);
    return { status: res.status, json: (await res.json()) as T };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export interface ScanBody {
  client_uuid: string; device_sequence: number; token: string; captured_at: string;
  capture_mode: "online" | "offline"; tentative_direction?: "IN" | "OUT";
}

export interface HistoryParams {
  employee_id?: string; site_id?: string; from?: string; to?: string; status?: string; limit?: number; offset?: number;
}
export interface ReportParams {
  period?: "daily" | "weekly"; date?: string; from?: string; to?: string; site_id?: string; employee_id?: string;
  delimiter?: string;
}

export const api = {
  login: (username: string, password: string) =>
    request<User>("/auth/login", { method: "POST", body: body({ username, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),

  employees: (p: { search?: string; active?: boolean; site_id?: string } = {}) =>
    request<Employee[]>(`/employees${qs(p)}`),
  employee: (id: string) => request<Employee>(`/employees/${id}`),
  createEmployee: (d: EmployeeInput) => request<Employee>("/employees", { method: "POST", body: body(d) }),
  updateEmployee: (id: string, d: Partial<EmployeeInput>) =>
    request<Employee>(`/employees/${id}`, { method: "PUT", body: body(d) }),
  setEmployeeActive: (id: string, is_active: boolean) =>
    request<Employee>(`/employees/${id}/status`, { method: "PATCH", body: body({ is_active }) }),
  qrPngUrl: (id: string) => `${API_BASE}/employees/${id}/qr.png`,
  qrPdfUrl: (id: string) => `${API_BASE}/employees/${id}/qr.pdf`,
  qrInfo: (id: string) => request<QrInfo>(`/employees/${id}/qr`),
  qrReprint: (id: string) => request<QrInfo>(`/employees/${id}/qr/reprint`, { method: "POST" }),
  credentials: (id: string) => request<Credential[]>(`/employees/${id}/credentials`),
  credentialAction: (credentialId: string, action: "block" | "unblock" | "revoke", reason?: string) =>
    request<Credential>(`/qr-credentials/${credentialId}/${action}`, { method: "PATCH", body: body({ reason: reason || null }) }),
  reissueCredential: (employeeId: string, reason?: string) =>
    request<QrInfo>(`/employees/${employeeId}/qr/reissue`, { method: "POST", body: body({ reason: reason || null }) }),

  sites: () => request<Site[]>("/sites"),
  createSite: (d: { code: string; name: string; timezone?: string }) =>
    request<Site>("/sites", { method: "POST", body: body(d) }),
  updateSite: (id: string, d: Partial<Pick<Site, "name" | "timezone" | "is_active">>) =>
    request<Site>(`/sites/${id}`, { method: "PATCH", body: body(d) }),
  siteSettings: (id: string) => request<SiteSettings>(`/sites/${id}/settings`),
  saveSiteSettings: (id: string, d: SiteSettings) =>
    request<SiteSettings>(`/sites/${id}/settings`, { method: "PUT", body: body(d) }),
  gates: (siteId: string) => request<Gate[]>(`/sites/${siteId}/gates`),
  createGate: (siteId: string, name: string) =>
    request<Gate>(`/sites/${siteId}/gates`, { method: "POST", body: body({ name }) }),
  updateGate: (id: string, d: Partial<Pick<Gate, "name" | "is_active">>) =>
    request<Gate>(`/gates/${id}`, { method: "PATCH", body: body(d) }),
  devices: () => request<Device[]>("/devices"),
  createDevice: (name: string, gate_id: string) =>
    request<DeviceCreated>("/devices", { method: "POST", body: body({ name, gate_id }) }),
  setDeviceActive: (id: string, is_active: boolean) =>
    request<Device>(`/devices/${id}`, { method: "PATCH", body: body({ is_active }) }),

  dashboard: (p: { site_id?: string; date?: string } = {}) => request<Dashboard>(`/attendance/dashboard${qs(p)}`),
  onSite: (site_id?: string) => request<OnSite>(`/attendance/current${qs({ site_id })}`),
  daily: (p: { site_id?: string; date?: string }) => request<Daily>(`/attendance/daily${qs(p)}`),
  history: (p: HistoryParams = {}) => request<Paged<SessionRow>>(`/attendance/history${qs({ ...p })}`),
  exceptions: (p: { site_id?: string; date?: string } = {}) =>
    request<{ items: SessionRow[] }>(`/attendance/exceptions${qs(p)}`),
  events: (p: { employee_id?: string; site_id?: string; from?: string; to?: string; limit?: number } = {}) =>
    request<{ items: import("./types").EventRow[] }>(`/attendance/events${qs(p)}`),
  scanLog: (p: { site_id?: string; outcome?: string; limit?: number; offset?: number } = {}) =>
    request<Paged<ScanLogItem>>(`/attendance/scan-log${qs(p)}`),
  syncStatus: (site_id?: string) =>
    request<{ as_of: string; items: SyncStatusItem[] }>(`/attendance/sync/status${qs({ site_id })}`),
  session: (id: string) => request<SessionDetail>(`/attendance/sessions/${id}`),
  correct: (id: string, d: { field: "in" | "out"; new_value: string; reason: string; expected_version: number }) =>
    request<SessionDetail>(`/attendance/sessions/${id}/corrections`, { method: "POST", body: body(d) }),
  corrections: (p: {
    employee_id?: string; site_id?: string; from?: string; to?: string; limit?: number; offset?: number;
  } = {}) => request<Paged<Correction>>(`/attendance/corrections${qs(p)}`),

  reportPreview: (kind: "daily" | "weekly", p: { date?: string; site_id?: string; employee_id?: string }) =>
    request<ReportPreview>(`/reports/${kind}${qs({ ...p })}`),
  exportUrl: (p: ReportParams) => `${API_BASE}/reports/export${qs({ ...p })}`,

  permissions: () => request<PermissionMatrix>("/admin/permissions"),
  savePermissions: (matrix: Record<string, Record<string, boolean>>) =>
    request<PermissionMatrix>("/admin/permissions", { method: "PUT", body: body({ matrix }) }),

  scannerContext: async (deviceToken: string) =>
    (await deviceRequest<ScannerContext>("/scanner/context", deviceToken)).json,
  ping: (deviceToken: string, timeoutMs = 3000) =>
    deviceRequest<Ping>("/scanner/ping", deviceToken, undefined, timeoutMs),
  scannerStatus: (deviceToken: string, d: { pending: number; failed: number; oldest_pending_at: string | null }) =>
    deviceRequest<{ ok?: boolean }>("/scanner/status", deviceToken, d, 5000),
  scan: (deviceToken: string, d: ScanBody) => deviceRequest<ScanResult>("/attendance/scan", deviceToken, d),
  sync: (deviceToken: string, items: ScanBody[]) =>
    deviceRequest<{ results: ScanResult[] }>("/attendance/sync", deviceToken, { items }),
};
