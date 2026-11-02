# API Reference

The generated OpenAPI document at `http://localhost:8000/openapi.json` (interactive docs at `/docs`) is the machine-readable contract. This page summarises the routes as implemented in `backend/app/api/`. All routes are mounted under `/api`. Staff routes use the HttpOnly session cookie set by login; scanner routes use the `X-Device-Token` header. Every response carries `X-Request-ID` and `X-Process-Time-Ms`, plus security headers.

## Conventions

Errors use a common envelope `{code, message, request_id}` (validation errors add `details` without the submitted values, so tokens and passwords are never echoed). Permissions are checked on the server with `require_permission`; the default role grants below come from `backend/app/permissions.py` and an administrator can change them at `PUT /api/admin/permissions`, except that `permissions.manage` cannot be removed from the admin role. Dashboard fields `scan_problems` and `device_sync` are empty for users without `scanlog.view`. Login responses and `GET /api/auth/me` include the user's permission list. Repeated failed logins return 429 `login_locked` with a `Retry-After` header.

## Permissions and default roles

| Permission | Default roles | Meaning |
| --- | --- | --- |
| `dashboard.view` | admin, supervisor, hr | Dashboard |
| `attendance.view` | admin, supervisor, hr | Attendance, sites, gates |
| `employees.view` | admin, supervisor, hr | Employee list and detail |
| `employees.manage` | admin | Register, edit, activate employees |
| `credentials.manage` | admin | Block, unblock, revoke, re-issue, credential history |
| `credentials.download` | admin | QR metadata, reprint, PNG and PDF downloads |
| `attendance.correct` | admin, supervisor | Create corrections |
| `corrections.view` | admin, supervisor, hr | Correction history and audit |
| `reports.export` | admin, supervisor, hr | Report previews and CSV |
| `sites.manage` | admin | Sites, gates, devices, attendance settings |
| `scanlog.view` | admin, supervisor | Scan log, sync status, devices list |
| `permissions.manage` | admin | Permission matrix |

## Endpoints

### Health and authentication

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/health` | none | Liveness |
| `POST /api/auth/login` | none | Sets the session cookie; throttled |
| `POST /api/auth/logout` | session | 204 |
| `GET /api/auth/me` | session | User and permission list |

### Employees and QR credentials

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/employees`, `GET /api/employees/{id}` | `employees.view` | Output includes `credential_id`, site names and credential status |
| `POST /api/employees` | `employees.manage` | Creates employee, site assignments, credential and audit entry in one commit |
| `PUT` or `PATCH /api/employees/{id}` | `employees.manage` | `PUT` is an alias of `PATCH` |
| `PATCH /api/employees/{id}/status` | `employees.manage` | Body sets `is_active` |
| `POST /api/employees/{id}/activate`, `/deactivate` | `employees.manage` | Older routes, kept |
| `GET /api/employees/{id}/qr` | `credentials.download` | Metadata (credential id, status, issued time, download links); never the token |
| `POST /api/employees/{id}/qr/reprint` | `credentials.download` | Returns the existing credential and audits `credential.reprint`; 409 for revoked |
| `GET /api/employees/{id}/qr.png`, `/qr.pdf` | `credentials.download` | Image and A6 badge PDF; 409 `credential_revoked` without a current credential; no-store |
| `POST /api/employees/{id}/qr/reissue` | `credentials.manage` | 201; only when no current credential exists |
| `GET /api/employees/{id}/credentials` | `credentials.manage` | Credential history |
| `PATCH /api/qr-credentials/{id}/block`, `/unblock`, `/revoke` | `credentials.manage` | Optional reason in the body; audited |

### Sites, gates, devices and scanner

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/sites`, `POST /api/sites`, `PATCH /api/sites/{id}` | `attendance.view` and `sites.manage` | Create and update need `sites.manage` |
| `GET /api/sites/{id}/settings`, `PUT /api/sites/{id}/settings` | view and `sites.manage` | `duplicate_window_seconds` (0 to 3600) and `missing_out_cutoff_time` |
| `GET` and `POST /api/sites/{id}/gates`, `PATCH /api/gates/{id}` | view and `sites.manage` | Per-site gates |
| `GET /api/gates`, `POST /api/gates` | view and `sites.manage` | Flat routes with optional `site_id` filter and `site_id` in the create body |
| `GET /api/devices`, `POST /api/devices`, `PATCH /api/devices/{id}` | `scanlog.view` and `sites.manage` | Pairing returns the device token once |
| `GET /api/scanner/context` | device token | Site, gate, time zone, `server_time`, `offline_max_age_hours`, `last_sequence` |
| `GET /api/scanner/ping` | device token | Connectivity probe; updates `last_seen_at`, returns server time and last sequence |
| `POST /api/scanner/status` | device token | Body `{pending, failed, oldest_pending_at}` heartbeat |

### Scanning and offline synchronisation

| Method and path | Auth | Notes |
| --- | --- | --- |
| `POST /api/attendance/scan` | device token | Body: `client_uuid`, `device_sequence`, `token`, optional `captured_at`, `capture_mode` (`online` or `offline`), optional `tentative_direction`. 201 accepted; 200 duplicate, rejection or exact replay; 409 conflict (reused client UUID, reused device sequence with `last_sequence`, concurrent conflict) |
| `POST /api/attendance/sync` | device token | Body `{items: [...]}` of one to 500 scans; returns `{results: [...]}`. Stops at the first retryable failure: that item is `error` and the rest are `skipped`, both retryable. Replays return stored results |

The scan result shape and reason vocabulary are described in `docs/ARCHITECTURE.md`.

### Attendance and corrections

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/attendance/dashboard` | `dashboard.view` | Query `site_id`, `date`; one-request dashboard |
| `GET /api/attendance/on-site` and `/current` | `attendance.view` | Recorded on-site sessions including missing-OUT with a status; `/current` is the specification name |
| `GET /api/attendance/daily` | `attendance.view` | Query `site_id`, `date` |
| `GET /api/attendance/history` | `attendance.view` | Query `employee_id`, `site_id`, `from`, `to`, `status` (`open`, `missing_out`, `complete`, `corrected`), `limit` (1 to 200), `offset` |
| `GET /api/attendance/exceptions` | `attendance.view` | Missing-OUT exceptions; query `site_id`, `date` |
| `GET /api/attendance/events` | `attendance.view` | Raw events; query `employee_id`, `site_id`, `from`, `to`, `limit` |
| `GET /api/attendance/sessions/{id}` | `attendance.view` | Session with `site_timezone`, local times, duration, status and flags |
| `GET /api/attendance/scan-log` | `scanlog.view` | Rejected, duplicate, conflict and error submissions; query `site_id`, `outcome`, `limit`, `offset` |
| `GET /api/attendance/sync/status` | `scanlog.view` | Per-device pending and failed summary from heartbeats |
| `POST /api/attendance/corrections` | `attendance.correct` | Body: `session_id`, `field` (`in` or `out`), `new_value`, `reason`, `expected_version` |
| `GET /api/attendance/corrections`, `GET /api/attendance/corrections/{id}` | `corrections.view` | Global audit; query `from`, `to`, `limit`, `offset` |
| `POST` and `GET /api/attendance/sessions/{id}/corrections` | `attendance.correct` and `corrections.view` | Per-session routes, kept |

Correction errors include 409 for a stale version, 422 `future_time`, `invalid_order`, `overlap`, `nonexistent_local_time` and `ambiguous_local_time`, and 422 for a missing reason.

### Reports

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/reports/daily`, `/weekly` | `reports.export` | JSON preview; query `site_id`, `employee_id`, `date` (weekly is the ISO week, Monday to Sunday) |
| `GET /api/reports/export` | `reports.export` | CSV; `period` (`daily` or `weekly`), `date`, or explicit `from` and `to`, plus `site_id`, `employee_id`, `delimiter` (comma, semicolon or tab). UTF-8 with a byte-order mark |
| `GET /api/reports/attendance.csv` | `reports.export` | Older route, `from` and `to` required |

CSV columns keep the original order and append `site_name`, `duration_hhmm`, `status`, `flags` and `offline`. Open sessions have blank OUT and duration.

### Administration

| Method and path | Permission | Notes |
| --- | --- | --- |
| `GET /api/admin/permissions`, `PUT /api/admin/permissions` | `permissions.manage` | Role permission matrix |

## Mapping from specification names

| Specification endpoint | Implemented route |
| --- | --- |
| `PUT /api/employees/{id}` | `PUT` and `PATCH /api/employees/{id}` |
| `PATCH /api/employees/{id}/status` | Same, plus the older activate and deactivate routes |
| `GET /api/employees/{id}/qr` | Metadata route; images at `/qr.png` and `/qr.pdf` |
| `POST /api/employees/{id}/qr/reprint` | Same |
| `PATCH /api/qr-credentials/{id}/block`, `/unblock` | Same, plus `/revoke` |
| `GET /api/attendance/current` | `/current`, alias of `/on-site` |
| `GET /api/attendance/history`, `/sync/status` | Same |
| `POST` and `GET /api/attendance/corrections`, `GET .../{id}` | Same, plus the per-session routes |
| `GET /api/reports/daily`, `/weekly`, `/export` | Same, plus the older `/attendance.csv` |
| `GET` and `POST /api/gates` | Same, plus the per-site gate routes |

Routes not in the specification: `GET /api/attendance/dashboard`, `GET /api/attendance/scan-log`, `GET /api/scanner/ping`, `POST /api/scanner/status`, `GET` and `PUT /api/admin/permissions`, credential history and re-issue.
