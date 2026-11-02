/** Timing samples (scan-to-confirmation and similar) kept in IndexedDB for later measurement reports. */
import { queueDb } from "./queue";

const MAX_SAMPLES = 500;

// PUBLIC_INTERFACE
/** Store one timing sample in milliseconds. Never throws. */
export async function recordTiming(name: string, ms: number): Promise<void> {
  try {
    await queueDb.perf.add({ name, ms: Math.round(ms * 10) / 10, at: new Date().toISOString() });
    const count = await queueDb.perf.count();
    if (count > MAX_SAMPLES) {
      const old = await queueDb.perf.orderBy("id").limit(count - MAX_SAMPLES).primaryKeys();
      await queueDb.perf.bulkDelete(old);
    }
  } catch { /* measurement must never affect scanning */ }
}

// PUBLIC_INTERFACE
/** Read all stored samples for a name (oldest first). */
export async function getTimings(name?: string) {
  const rows = await queueDb.perf.orderBy("id").toArray();
  return name ? rows.filter((r) => r.name === name) : rows;
}

// PUBLIC_INTERFACE
/** Median and 95th percentile of a list of samples. */
export function summarize(values: number[]): { n: number; median: number; p95: number } {
  if (!values.length) return { n: 0, median: 0, p95: 0 };
  const s = [...values].sort((a, b) => a - b);
  const pick = (q: number) => s[Math.min(s.length - 1, Math.ceil(q * s.length) - 1)];
  return { n: s.length, median: pick(0.5), p95: pick(0.95) };
}

if (typeof window !== "undefined") {
  // Handy for the browser harness: `await window.__etmsTimings("scan_to_confirmation_ms")`.
  (window as unknown as { __etmsTimings?: typeof getTimings }).__etmsTimings = getTimings;
}
