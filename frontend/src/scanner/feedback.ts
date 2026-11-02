/** Kiosk feedback state machine: one visible result at a time, returning to ready automatically. */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ScanResult } from "../api/types";
import { fmtZonedTime } from "../lib/time";

export type FeedbackKind = "confirmed" | "pending" | "already" | "rejected";

export interface Feedback {
  kind: FeedbackKind;
  direction?: "IN" | "OUT" | null;
  name?: string | null;
  /** Site-local wall-clock time of the accepted scan. */
  time?: string | null;
  durationMinutes?: number | null;
  reason?: string | null;
  tentative?: "IN" | "OUT" | null;
  mismatch?: boolean;
  uuid?: string;
}

/** How long a confirmation stays visible before the kiosk returns to ready (rejections stay a little longer). */
export const HOLD_MS: Record<FeedbackKind, number> = { confirmed: 4000, pending: 4000, already: 4000, rejected: 5000 };

// PUBLIC_INTERFACE
/** Map a terminal (or retryable) server result to what the kiosk shows; null for results that need no display. */
export function feedbackFromResult(result: ScanResult, fallbackTz: string | null, lang: string): Feedback | null {
  const outcome = result.outcome === "replay" ? (result.original_outcome ?? "accepted") : result.outcome;
  const tz = result.site_timezone ?? fallbackTz;
  const time = result.occurred_at ? fmtZonedTime(result.occurred_at, tz, lang) : null;
  if (outcome === "accepted") {
    return {
      kind: "confirmed", direction: result.direction ?? null, name: result.employee?.name ?? null, time,
      durationMinutes: result.direction === "OUT" ? (result.duration_minutes ?? null) : null,
      mismatch: !!result.direction_mismatch, uuid: result.client_uuid,
    };
  }
  if (outcome === "duplicate") {
    return { kind: "already", direction: result.direction ?? null, name: result.employee?.name ?? null, time, reason: result.reason, uuid: result.client_uuid };
  }
  if (outcome === "rejected" || outcome === "conflict") {
    return { kind: "rejected", reason: result.reason ?? "rejected", uuid: result.client_uuid };
  }
  return null;
}

// PUBLIC_INTERFACE
/** Hook exposing the current feedback; every `show` call replaces it and restarts the single auto-return timer. */
export function useFeedback() {
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const show = useCallback((fb: Feedback) => {
    clearTimeout(timer.current);
    setFeedback(fb);
    timer.current = setTimeout(() => setFeedback(null), HOLD_MS[fb.kind]);
  }, []);
  const clear = useCallback(() => { clearTimeout(timer.current); setFeedback(null); }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  return { feedback, show, clear };
}
