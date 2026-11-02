/** Drains the IndexedDB queue oldest-first; error and skipped results stay pending and are re-sent in order. */
import { api, ApiError, isRetryable, ScanBody } from "../api/client";
import type { ScanResult } from "../api/types";
import { markAttempt, pendingScans, pruneResolved, QueuedScan, queueStats, resequence, resolveScan } from "./queue";
import { clearCapture, recordConfirmed } from "./tokenState";

export const CHUNK_SIZE = 100;
const MAX_ROUNDS = 50;

export interface Resolved { row: QueuedScan; result: ScanResult }

export interface DrainResult {
  /** Entries resolved by the server during this run, in processing order. */
  resolved: Resolved[];
  /** True if a retryable failure stopped the run; the entries remain pending. */
  retryLater: boolean;
  /** Set for non-retryable failures such as an invalid device token. */
  fatal?: string;
  /** Number of entries given a new device sequence after a sequence conflict. */
  resequenced: number;
}

function toBody(row: QueuedScan): ScanBody {
  return {
    client_uuid: row.client_uuid,
    device_sequence: row.device_sequence,
    token: row.token ?? "",
    captured_at: row.captured_at,
    capture_mode: row.capture_mode ?? "offline",
    ...(row.tentative_direction ? { tentative_direction: row.tentative_direction } : {}),
  };
}

/** Exponential backoff delay in ms for the given consecutive failure count. */
export function backoffMs(failures: number, base = 1000, max = 60000): number {
  return Math.min(max, base * 2 ** Math.max(0, failures - 1));
}

const isRetryableResult = (r: ScanResult) => !!r.retryable || r.outcome === "error" || r.outcome === "skipped";

/** Resolve one queue entry from a terminal server result and update the token-state map. */
async function applyResult(row: QueuedScan, result: ScanResult, out: DrainResult): Promise<void> {
  const outcome = result.outcome === "replay" ? (result.original_outcome ?? "accepted") : result.outcome;
  await resolveScan(row.id!, outcome, {
    reason: result.reason, direction: result.direction, employee_name: result.employee?.name,
    direction_mismatch: !!result.direction_mismatch, occurred_at: result.occurred_at, local_time: result.local_time,
    site_timezone: result.site_timezone, duration_minutes: result.duration_minutes,
  });
  if ((outcome === "accepted" || outcome === "duplicate") && result.direction) {
    await recordConfirmed(row.token_digest, result.direction);
  }
  if (outcome === "rejected" || outcome === "conflict") await clearCapture(row.token_digest);
  out.resolved.push({ row, result });
}

/** Send one chunk. Returns true when the run may continue with the next chunk. */
async function sendChunk(deviceToken: string, batch: QueuedScan[], out: DrainResult): Promise<boolean> {
  const ids = batch.map((r) => r.id!);
  let results: ScanResult[];
  try {
    results = batch.length > 1
      ? (await api.sync(deviceToken, batch.map(toBody))).json.results
      : [(await api.scan(deviceToken, toBody(batch[0]))).json];
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      // The server refused the payload itself. Isolate the entry instead of blocking the whole queue.
      if (batch.length > 1) {
        for (const row of batch) if (!(await sendChunk(deviceToken, [row], out))) return false;
        return true;
      }
      await applyResult(batch[0], { client_uuid: batch[0].client_uuid, device_sequence: batch[0].device_sequence,
        outcome: "rejected", reason: "invalid_code" }, out);
      return true;
    }
    if (isRetryable(e)) {
      await markAttempt(ids, e instanceof Error ? e.message : "network");
      out.retryLater = true;
    } else {
      out.fatal = e instanceof Error ? e.message : String(e);
    }
    return false;
  }

  const retryIds: number[] = [];
  let progressed = false;
  for (const result of results) {
    const row = batch.find((r) => r.client_uuid === result.client_uuid);
    if (!row) continue;
    if (isRetryableResult(result)) {
      retryIds.push(row.id!);
    } else if (result.outcome === "conflict" && result.reason === "device_sequence_reused" && result.last_sequence != null) {
      await resequence(row.id!, result.last_sequence);
      out.resequenced += 1;
      progressed = true;
    } else {
      await applyResult(row, result, out);
      progressed = true;
    }
  }
  if (retryIds.length) {
    await markAttempt(retryIds, "retry_later");
    out.retryLater = true;
    return false;
  }
  // Entries the server did not answer stay pending; stop instead of looping on them.
  return progressed;
}

// PUBLIC_INTERFACE
/**
 * Send all pending scans in sequence order, at most {@link CHUNK_SIZE} per request. Retryable failures keep
 * the failed and every later entry pending (no scan is ever dropped); a reused device sequence is repaired
 * by re-sequencing the same client UUID and sending again.
 */
export async function drainQueue(deviceToken: string): Promise<DrainResult> {
  const out: DrainResult = { resolved: [], retryLater: false, resequenced: 0 };
  for (let round = 0; round < MAX_ROUNDS; round++) {
    const rows = (await pendingScans()).filter((r) => r.token);
    if (!rows.length) break;
    if (!(await sendChunk(deviceToken, rows.slice(0, CHUNK_SIZE), out))) break;
  }
  if (out.resolved.length) await pruneResolved();
  return out;
}

// PUBLIC_INTERFACE
/** Report pending and failed counts to the backend for the supervisor sync view. Best effort, never throws. */
export async function sendHeartbeat(deviceToken: string): Promise<void> {
  try {
    await api.scannerStatus(deviceToken, await queueStats());
  } catch { /* the heartbeat is informational only */ }
}
