import { FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useAuth } from "../auth";
import { ErrorBanner, fmtTime, useLoad } from "../components/common";
import { localInputToPayload } from "../lib/time";
import { useI18n } from "../i18n";

/** Session detail with immutable source events, audit history, and site-zone correction input. */
export default function SessionDetailPage() {
  const { id = "" } = useParams();
  const { lang, t } = useI18n();
  const { can } = useAuth();
  const session = useLoad(() => api.session(id), [id]);
  const [field, setField] = useState<"in" | "out">("out");
  const [value, setValue] = useState("");
  const [offset, setOffset] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const detail = session.data;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!detail) return;
    try {
      await api.correct(id, { field, new_value: localInputToPayload(value, offset), reason, expected_version: detail.version });
      setReason("");
      setValue("");
      setOffset("");
      setError(null);
      await session.reload();
    } catch (cause) {
      const apiError = cause as ApiError;
      if (apiError.code === "ambiguous_local_time") setError(t("session.ambiguous"));
      else if (apiError.code === "nonexistent_local_time") setError(t("session.nonexistent"));
      else setError(apiError.status === 409 ? t("session.conflict") : apiError.message);
    }
  };

  if (!detail) return <ErrorBanner message={session.error ?? error} />;

  return (
    <section>
      <ErrorBanner message={session.error ?? error} />
      <h1>{t("session.title")}: {detail.employee_name} (#{detail.employee_number})</h1>
      <p>{t("session.zoneNote").replace("{tz}", detail.site_timezone)}</p>
      <p>{t("attendance.in")}: {fmtTime(detail.effective_in, detail.site_timezone, lang)} · {t("attendance.out")}: {fmtTime(detail.effective_out, detail.site_timezone, lang)} · {t("attendance.duration")}: {detail.hours ?? "—"}</p>
      <h2>{t("session.events")}</h2>
      <ul>{[detail.in_event, detail.out_event].filter(Boolean).map((event) => <li key={event!.id}>{t(event!.direction === "IN" ? "dir.IN" : "dir.OUT")} · {fmtTime(event!.occurred_at, detail.site_timezone, lang)} · {event!.capture_mode}</li>)}</ul>
      <h2>{t("session.history")}</h2>
      {detail.corrections.length === 0 && <p className="muted">{t("session.noHistory")}</p>}
      <table><tbody>{detail.corrections.map((correction) => <tr key={correction.id}><td>{fmtTime(correction.created_at, detail.site_timezone, lang)}</td><td>{correction.field.toUpperCase()}</td><td>{fmtTime(correction.old_value, detail.site_timezone, lang)} → {fmtTime(correction.new_value, detail.site_timezone, lang)}</td><td>{correction.reason}</td><td>{t("session.by")} {correction.actor}</td></tr>)}</tbody></table>
      {can("attendance.correct") && <form className="card" onSubmit={submit}>
        <h2>{t("session.correct")}</h2>
        <label>{t("session.field")}<select value={field} onChange={(event) => setField(event.target.value as "in" | "out")}><option value="in">{t("attendance.in")}</option><option value="out">{t("attendance.out")}</option></select></label>
        <label>{t("session.newValue")}<input type="datetime-local" value={value} onChange={(event) => setValue(event.target.value)} required /></label>
        <label>{t("session.offset")}<input value={offset} placeholder="+01:00" pattern="[+-][0-9]{2}:[0-9]{2}" onChange={(event) => setOffset(event.target.value)} /></label>
        <label>{t("session.reason")}<textarea value={reason} onChange={(event) => setReason(event.target.value)} required maxLength={1000} /></label>
        <button className="primary" type="submit" disabled={!reason.trim() || !value}>{t("session.apply")}</button>
      </form>}
    </section>
  );
}
