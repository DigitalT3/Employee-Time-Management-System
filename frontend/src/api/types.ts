/** Types mirroring the FastAPI backend responses. */
export type Role = "admin" | "supervisor" | "hr";

export interface User { id: string; username: string; role: Role; permissions: string[] }

export interface SiteRef { id: string; code: string; name: string }

export interface Employee {
  id: string;
  employee_number: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  site_ids: string[];
  sites: SiteRef[];
  credential_id: string | null;
  /** active, blocked, revoked or null (never issued). */
  credential_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface Credential {
  id: string; employee_id: string; status: string; is_current: boolean;
  issued_at: string; blocked_at: string | null; revoked_at: string | null;
}
export interface QrInfo extends Credential { png_url: string | null; pdf_url: string | null }

export interface Site { id: string; code: string; name: string; timezone: string; is_active: boolean }
export interface SiteSettings { duplicate_window_seconds: number; missing_out_cutoff_time: string }
export interface Gate { id: string; site_id: string; name: string; is_active: boolean }
export interface Device {
  id: string; name: string; site_id: string; gate_id: string; last_sequence: number; is_active: boolean;
}
export interface DeviceCreated extends Device { device_token: string }

export type SessionStatus = "open" | "missing_out" | "complete";

export interface SessionRow {
  id: string;
  employee_id: string;
  employee_number: string;
  employee_name: string;
  site_id: string;
  site_code: string | null;
  site_name: string | null;
  site_timezone: string;
  effective_in: string;
  effective_out: string | null;
  local_in: string | null;
  local_out: string | null;
  shift_date: string;
  version: number;
  corrected: boolean;
  hours: number | null;
  duration_minutes: number | null;
  missing_out: boolean;
  status: SessionStatus;
  /** missing_out, corrected, offline_capture, out_after_cutoff */
  flags: string[];
}

export interface OnSiteItem extends SessionRow { latest_direction: "IN"; latest_in: string }
export interface OnSite { as_of: string; count: number; items: OnSiteItem[] }
export interface DailyEmployee {
  employee_id: string; employee_number: string; employee_name: string;
  total_hours: number; open: boolean; missing_out: boolean; sessions: SessionRow[];
}
export interface Daily { date: string; site_id: string | null; employees: DailyEmployee[] }

export interface Paged<T> { total: number; limit: number; offset: number; items: T[] }

export interface EventRow {
  id: string;
  direction: "IN" | "OUT";
  occurred_at: string;
  received_at: string;
  capture_mode: string;
  employee_id?: string;
  employee_number?: string;
  employee_name?: string;
  gate_name?: string;
  device_name?: string;
  local_time?: string;
  site_timezone?: string;
}
export interface Correction {
  id: string; session_id: string; field: string; old_value: string | null; new_value: string; reason: string;
  actor: string; created_at: string;
  site_timezone?: string; old_value_local?: string | null; new_value_local?: string | null;
  created_at_local?: string | null;
  employee_id?: string; employee_number?: string; employee_name?: string; site_id?: string; site_code?: string;
}
export interface SessionDetail extends SessionRow {
  in_event: EventRow | null; out_event: EventRow | null; corrections: Correction[];
}

export interface ActivityItem {
  id: string; employee_id: string; employee_number: string; employee_name: string; site_id: string;
  gate_name: string; device_name: string; direction: "IN" | "OUT"; capture_mode: string;
  occurred_at: string; local_time: string; site_timezone: string;
}
export interface ScanLogItem {
  id: string; outcome: string; reason: string | null; device_id: string; device_name: string; site_id: string;
  capture_mode: string | null; device_sequence: number | null; received_at: string; local_time: string;
  site_timezone: string; employee: { employee_number: string; name: string } | null;
}
export interface SyncStatusItem {
  device_id: string; device_name: string; site_id: string; is_active: boolean;
  connection: "online" | "offline" | "never_seen"; state: "synced" | "pending" | "failed";
  last_seen_at: string | null; last_seen_local: string | null; pending: number; failed: number;
  oldest_pending_at: string | null; last_sequence: number;
}
export interface Dashboard {
  as_of: string; site_id: string | null; date: string | null; label: string;
  counts: { on_site: number; off_site: number; incomplete: number };
  on_site: OnSiteItem[]; recent_activity: ActivityItem[]; exceptions: SessionRow[];
  scan_problems: ScanLogItem[]; device_sync: SyncStatusItem[];
}

export interface ReportRow {
  employee_number: string; first_name: string; last_name: string; site_code: string; site_name: string;
  shift_date: string; in_local: string; out_local: string; hours: string; duration_minutes: number | null;
  duration_hhmm: string; corrected: string; missing_out: string; status: string; flags: string[];
  offline: string; session_id: string;
}
export interface ReportPreview {
  period: string; from: string; to: string; duration_label: string;
  summary: { sessions: number; completed_minutes: number; completed_hours: number; incomplete: number; missing_out: number };
  rows: ReportRow[];
}

export interface PermissionMatrix {
  roles: string[];
  permissions: { key: string; description: string }[];
  matrix: Record<string, Record<string, boolean>>;
  locked: { role: string; permission: string }[];
}

export type ScanOutcome = "accepted" | "duplicate" | "rejected" | "replay" | "conflict" | "error" | "skipped";
/** Terminal outcomes stored on a resolved queue entry. */
export type ResolvedOutcome = "accepted" | "duplicate" | "rejected" | "conflict";

/** Token-safe scan result: the employee object carries the name only and only on accepted/duplicate. */
export interface ScanResult {
  client_uuid: string;
  device_sequence: number;
  status?: number;
  outcome: ScanOutcome;
  retryable?: boolean;
  reason?: string | null;
  direction?: "IN" | "OUT" | null;
  employee?: { name: string } | null;
  original_outcome?: ScanOutcome;
  occurred_at?: string | null;
  local_time?: string | null;
  site_timezone?: string | null;
  duration_minutes?: number | null;
  last_sequence?: number | null;
  direction_mismatch?: boolean;
}

export interface ScannerContext {
  device: { id: string; name: string; last_sequence: number };
  site: { id: string; code: string; name: string; timezone: string };
  gate: { id: string; name: string };
  duplicate_window_seconds: number;
  server_time?: string;
  offline_max_age_hours?: number;
}

export interface Ping { ok: boolean; server_time: string; last_sequence: number; device: { id: string; name: string } }
