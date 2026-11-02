/**
 * Site time zone formatting (DEC-07). All staff and tablet displays go through these helpers so that
 * the browser's own zone is never used for attendance times.
 */

export const FALLBACK_TZ = "Europe/Amsterdam";

const localeOf = (lang: string) => (lang === "nl" ? "nl-NL" : "en-GB");

// PUBLIC_INTERFACE
/** Format an instant as date and time in the given IANA zone, e.g. "02/11/2026, 08:05:09". */
export function fmtZoned(iso: string | null | undefined, tz: string | null | undefined, lang = "en"): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(localeOf(lang), {
    timeZone: tz || FALLBACK_TZ, dateStyle: "short", timeStyle: "medium",
  }).format(d);
}

// PUBLIC_INTERFACE
/** Format only the wall-clock time in the given zone, e.g. "08:05:09". */
export function fmtZonedTime(iso: string | null | undefined, tz: string | null | undefined, lang = "en"): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(localeOf(lang), { timeZone: tz || FALLBACK_TZ, timeStyle: "medium" }).format(d);
}

// PUBLIC_INTERFACE
/** The calendar date (YYYY-MM-DD) of an instant in the given zone. */
export function zonedDate(tz: string | null | undefined, now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz || FALLBACK_TZ }).format(now);
}

const parts = (d: Date, tz: string) => {
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(d)) out[p.type] = p.value;
  return out;
};

// PUBLIC_INTERFACE
/** Convert an instant into the value of a `datetime-local` input showing the site's wall-clock time. */
export function isoToLocalInput(iso: string | null | undefined, tz: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = parts(d, tz || FALLBACK_TZ);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

// PUBLIC_INTERFACE
/**
 * Turn a `datetime-local` value into the correction payload: a naive site wall-clock time (the server
 * interprets it in the site zone and reports DST gaps or overlaps) or, when the user chose an explicit
 * UTC offset for an ambiguous time, an offset-aware string.
 */
export function localInputToPayload(value: string, offset?: string): string {
  const base = value.length === 16 ? `${value}:00` : value;
  const o = (offset ?? "").trim();
  return /^[+-]\d{2}:\d{2}$/.test(o) ? `${base}${o}` : base;
}

// PUBLIC_INTERFACE
/** Whole minutes as "H:MM" (attendance duration, not paid time). */
export function fmtDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}
