/** Durable offline scan queue stored in IndexedDB via Dexie. Unresolved entries are never cleared. */
import Dexie, { Table } from "dexie";
import type { ScanOutcome } from "../api/types";
import { digestToken } from "./tokenState";
import { newUuid } from "./uuid";

export type QueueStatus = "pending" | ScanOutcome;
export type Direction = "IN" | "OUT";

export interface QueuedScan {
  id?: number;
  client_uuid: string;
  device_sequence: number;
  /** Secret QR token; removed once the server returns a terminal outcome. */
  token: string | null;
  /** SHA-256 digest of the normalised token (not secret); keys the token-state map. */
  token_digest?: string;
  captured_at: string;
  /** Fixed when the scan is captured (online = backend reachable at that moment), never inferred from retries. */
  capture_mode: "online" | "offline";
  /** Tablet-side guess shown as tentative only; the backend alone decides the direction. */
  tentative_direction?: Direction | null;
  status: QueueStatus;
  attempts: number;
  last_error?: string | null;
  reason?: string | null;
  direction?: Direction | null;
  employee_name?: string | null;
  direction_mismatch?: boolean;
  occurred_at?: string | null;
  local_time?: string | null;
  site_timezone?: string | null;
  duration_minutes?: number | null;
}

export interface Meta { key: string; value: number }
export interface TokenStateRow {
  digest: string;
  direction: Direction | null;
  confirmed: boolean;
  last_capture_at: string | null;
}
export interface TimingRow { id?: number; name: string; ms: number; at: string }

class QueueDb extends Dexie {
  scans!: Table<QueuedScan, number>;
  meta!: Table<Meta, string>;
  tokens!: Table<TokenStateRow, string>;
  perf!: Table<TimingRow, number>;
  constructor(name = "etms-scan-queue") {
    super(name);
    // Versioned schema: add new versions below, never edit an existing version.
    this.version(1).stores({ scans: "++id, client_uuid, device_sequence, status", meta: "key" });
    this.version(2)
      .stores({
        scans: "++id, client_uuid, device_sequence, status, token_digest",
        meta: "key",
        tokens: "digest",
        perf: "++id, name",
      })
      .upgrade((tx) =>
        // Keep every existing entry; only fill the capture mode that version 1 inferred from retries.
        tx.table("scans").toCollection().modify((row: QueuedScan) => {
          if (!row.capture_mode) row.capture_mode = row.attempts > 0 ? "offline" : "online";
        }),
      );
  }
}

export const queueDb = new QueueDb();

export interface EnqueueOptions {
  now?: Date;
  captureMode?: "online" | "offline";
  tentativeDirection?: Direction | null;
}

/** Persist a capture before any network use; allocates a monotonic device sequence. */
export async function enqueue(token: string, serverLastSequence = 0, opts: EnqueueOptions = {}): Promise<QueuedScan> {
  const now = opts.now ?? new Date();
  const digest = await digestToken(token);
  return queueDb.transaction("rw", queueDb.scans, queueDb.meta, queueDb.tokens, async () => {
    const stored = (await queueDb.meta.get("sequence"))?.value ?? 0;
    const sequence = Math.max(stored, serverLastSequence) + 1;
    await queueDb.meta.put({ key: "sequence", value: sequence });
    const entry: QueuedScan = {
      client_uuid: newUuid(),
      device_sequence: sequence,
      token: token.trim(),
      token_digest: digest,
      captured_at: now.toISOString(),
      capture_mode: opts.captureMode ?? "online",
      tentative_direction: opts.tentativeDirection ?? null,
      status: "pending",
      attempts: 0,
    };
    entry.id = await queueDb.scans.add(entry);
    const known = await queueDb.tokens.get(digest);
    await queueDb.tokens.put({
      digest,
      direction: known?.direction ?? null,
      confirmed: known?.confirmed ?? false,
      last_capture_at: now.toISOString(),
    });
    return entry;
  });
}

/** Pending entries, oldest sequence first. */
export async function pendingScans(): Promise<QueuedScan[]> {
  const rows = await queueDb.scans.where("status").equals("pending").toArray();
  return rows.sort((a, b) => a.device_sequence - b.device_sequence);
}

/** Most recent entries (any status) for diagnostics. */
export async function recentScans(limit = 20): Promise<QueuedScan[]> {
  return queueDb.scans.orderBy("device_sequence").reverse().limit(limit).toArray();
}

/** Pending and failed counts plus the oldest pending capture time, for the kiosk status and the heartbeat. */
export async function queueStats(): Promise<{ pending: number; failed: number; oldest_pending_at: string | null }> {
  const rows = await pendingScans();
  const oldest = rows.map((r) => r.captured_at).sort()[0] ?? null;
  return { pending: rows.length, failed: rows.filter((r) => r.attempts > 0 && !!r.last_error).length, oldest_pending_at: oldest };
}

export interface ResolveExtra {
  reason?: string | null;
  direction?: Direction | null;
  employee_name?: string | null;
  direction_mismatch?: boolean;
  occurred_at?: string | null;
  local_time?: string | null;
  site_timezone?: string | null;
  duration_minutes?: number | null;
}

/** Record a terminal outcome and drop the secret token. */
export async function resolveScan(id: number, outcome: ScanOutcome, extra: ResolveExtra = {}): Promise<void> {
  await queueDb.scans.update(id, { status: outcome, token: null, last_error: null, ...extra });
}

/** Count a failed attempt and keep the entry pending for an in-order retry. */
export async function markAttempt(ids: number[], error: string | null = null): Promise<void> {
  await queueDb.transaction("rw", queueDb.scans, async () => {
    for (const id of ids) {
      const row = await queueDb.scans.get(id);
      if (row) await queueDb.scans.update(id, { attempts: row.attempts + 1, last_error: error });
    }
  });
}

/** Give a pending entry a fresh device sequence after the server reported that its sequence was already used. */
export async function resequence(id: number, serverLastSequence: number): Promise<number> {
  return queueDb.transaction("rw", queueDb.scans, queueDb.meta, async () => {
    const stored = (await queueDb.meta.get("sequence"))?.value ?? 0;
    const next = Math.max(stored, serverLastSequence) + 1;
    await queueDb.meta.put({ key: "sequence", value: next });
    await queueDb.scans.update(id, { device_sequence: next });
    return next;
  });
}

/** Remove old resolved entries; pending (unresolved) entries are never touched. */
export async function pruneResolved(keep = 200): Promise<void> {
  const resolved = (await queueDb.scans.where("status").notEqual("pending").toArray())
    .sort((a, b) => a.device_sequence - b.device_sequence);
  const excess = resolved.slice(0, Math.max(0, resolved.length - keep));
  if (excess.length) await queueDb.scans.bulkDelete(excess.map((r) => r.id!));
}
