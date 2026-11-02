/**
 * Token-state map keyed by a SHA-256 digest of the normalised token (the raw token is never a key).
 * It is seeded from server-confirmed directions and only yields a *tentative* direction; the backend
 * alone decides IN or OUT.
 */
import { queueDb } from "./queue";
import type { Direction } from "./queue";

const toHex = (buf: ArrayBuffer) => Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");

/** Non-cryptographic fallback for origins without SubtleCrypto (only used as a map key). */
function fallbackDigest(text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return `fx-${(h2 >>> 0).toString(16).padStart(8, "0")}${(h1 >>> 0).toString(16).padStart(8, "0")}`;
}

// PUBLIC_INTERFACE
/** SHA-256 hex digest of the trimmed token (falls back to a short hash where SubtleCrypto is missing). */
export async function digestToken(token: string): Promise<string> {
  const normalised = token.trim();
  const subtle = typeof crypto !== "undefined" ? crypto.subtle : undefined;
  if (subtle) {
    try {
      return toHex(await subtle.digest("SHA-256", new TextEncoder().encode(normalised)));
    } catch { /* fall back */ }
  }
  return fallbackDigest(normalised);
}

const opposite = (d: Direction): Direction => (d === "IN" ? "OUT" : "IN");

// PUBLIC_INTERFACE
/** Remember the direction the backend confirmed for a token. */
export async function recordConfirmed(digest: string | undefined, direction: Direction | null | undefined): Promise<void> {
  if (!digest || !direction) return;
  const known = await queueDb.tokens.get(digest);
  await queueDb.tokens.put({ digest, direction, confirmed: true, last_capture_at: known?.last_capture_at ?? null });
}

// PUBLIC_INTERFACE
/** Remember an unconfirmed (tentative) direction so the next offline capture of the token toggles. */
export async function recordTentative(digest: string, direction: Direction): Promise<void> {
  const known = await queueDb.tokens.get(digest);
  await queueDb.tokens.put({ digest, direction, confirmed: false, last_capture_at: known?.last_capture_at ?? null });
}

// PUBLIC_INTERFACE
/** The tentative direction for the next capture (opposite of the last known one) or null when unknown. */
export async function tentativeFor(digest: string): Promise<Direction | null> {
  const row = await queueDb.tokens.get(digest);
  return row?.direction ? opposite(row.direction) : null;
}

// PUBLIC_INTERFACE
/** True when the same token was captured inside the duplicate window (tablet clock), so it is not queued again. */
export async function recentCaptureWithin(digest: string, windowSeconds: number, now: Date = new Date()): Promise<boolean> {
  if (windowSeconds <= 0) return false;
  const row = await queueDb.tokens.get(digest);
  if (!row?.last_capture_at) return false;
  const age = now.getTime() - new Date(row.last_capture_at).getTime();
  return age >= 0 && age < windowSeconds * 1000;
}

// PUBLIC_INTERFACE
/** Forget the last capture time (used when a capture was rejected so a corrected retry is not suppressed). */
export async function clearCapture(digest: string | undefined): Promise<void> {
  if (!digest) return;
  const row = await queueDb.tokens.get(digest);
  if (row) await queueDb.tokens.put({ ...row, last_capture_at: null });
}
