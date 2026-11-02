import { DependencyList, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Site } from "../api/types";
import type { Feedback } from "../scanner/feedback";
import { fmtDuration, fmtZoned, zonedDate } from "../lib/time";
import { useI18n, type Key } from "../i18n";

/** Run an async loader and expose data, loading state, errors, and a reload callback. */
export function useLoad<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(() => {
    setLoading(true);
    return fn()
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((cause: Error) => setError(cause.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

// PUBLIC_INTERFACE
/** Poll a reload function without overlapping requests and pause background work on hidden pages. */
export function usePolling(reload: () => Promise<unknown>, intervalMs: number, enabled = true) {
  const busy = useRef(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let disposed = false;
    const poll = async () => {
      if (disposed || busy.current || document.visibilityState === "hidden") return;
      busy.current = true;
      try {
        await reload();
        if (!disposed) setLastUpdated(new Date());
      } finally {
        busy.current = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), intervalMs);
    const visibility = () => {
      if (document.visibilityState === "visible") void poll();
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [enabled, intervalMs, reload]);

  return lastUpdated;
}

export function ErrorBanner({ message }: { message: string | null }) {
  return message ? <p className="error" role="alert">{message}</p> : null;
}

/** Site dropdown with an optional “All” value. */
export function SiteSelect({ value, onChange, allowAll = true }: {
  value: string;
  onChange: (value: string) => void;
  allowAll?: boolean;
}) {
  const { t } = useI18n();
  const { data } = useLoad<Site[]>(() => api.sites(), []);
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} aria-label={t("common.site")}>
      {allowAll && <option value="">{t("common.all")}</option>}
      {(data ?? []).map((site) => <option key={site.id} value={site.id}>{site.code} – {site.name}</option>)}
    </select>
  );
}

/** Display a scanner outcome without exposing an identity for rejected scans. */
export function ResultPanel({ feedback, timezone }: { feedback: Feedback | null; timezone: string | null }) {
  const { t } = useI18n();
  if (!feedback) return <div className="result idle" aria-live="polite">{t("scanner.ready")}</div>;

  const reason = feedback.reason
    ? t(`reason.${feedback.reason}` as Key)
    : "";
  const direction = feedback.direction ? t(feedback.direction === "IN" ? "dir.IN" : "dir.OUT") : "";
  const tone = feedback.kind === "confirmed" ? "in" : feedback.kind === "pending" ? "pending"
    : feedback.kind === "already" ? "pending" : "bad";

  return (
    <div className={`result ${tone}`} aria-live="polite">
      {feedback.kind === "pending" && (
        <>
          <strong>{t("scanner.recordedLocally")}</strong>
          {feedback.tentative
            ? <span>{t("scanner.tentative").replace("{dir}", t(feedback.tentative === "IN" ? "dir.IN" : "dir.OUT"))}</span>
            : <span>{t("scanner.directionLater")}</span>}
        </>
      )}
      {feedback.kind === "already" && <><strong>{t("scanner.alreadyProcessed")}</strong>{reason && <span>{reason}</span>}</>}
      {feedback.kind === "rejected" && <><strong>{t("outcome.rejected")}</strong>{reason && <span>{reason}</span>}</>}
      {feedback.kind === "confirmed" && (
        <>
          <strong>{feedback.direction === "OUT" ? t("scanner.checkedOut") : t("scanner.checkedIn")}</strong>
          {feedback.name && <span>{feedback.name}</span>}
          <span>{t("scanner.at")} {feedback.time ?? fmtZoned(null, timezone)}</span>
          {feedback.durationMinutes !== null && feedback.durationMinutes !== undefined
            && <span>{t("scanner.duration")}: {fmtDuration(feedback.durationMinutes)}</span>}
          {feedback.mismatch && <span className="warning-text">{t("scanner.mismatch")}</span>}
        </>
      )}
    </div>
  );
}

export const fmtTime = (iso: string | null | undefined, timezone?: string | null, lang = "en") =>
  fmtZoned(iso, timezone, lang);

export const todayIso = (timezone?: string | null) => zonedDate(timezone);
