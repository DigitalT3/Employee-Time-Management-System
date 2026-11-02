import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { EventRow } from "../api/types";
import { ErrorBanner, fmtTime, SiteSelect, todayIso, useLoad } from "../components/common";
import { useI18n } from "../i18n";

type Mode = "daily" | "history" | "events";

/** Attendance sessions and immutable events with server-side filters and pagination. */
export default function Attendance() {
  const { lang, t } = useI18n();
  const [mode, setMode] = useState<Mode>("daily");
  const [site, setSite] = useState("");
  const [date, setDate] = useState(todayIso());
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const daily = useLoad(() => api.daily({ site_id: site || undefined, date }), [site, date]);
  const history = useLoad(() => api.history({ site_id: site || undefined, from: date, to: date, status: status || undefined, offset, limit: 25 }), [site, date, status, offset]);
  const events = useLoad(() => api.events({ site_id: site || undefined, from: `${date}T00:00:00`, to: `${date}T23:59:59` }), [site, date]);

  const changeMode = (next: Mode) => {
    setMode(next);
    setOffset(0);
  };

  return (
    <section>
      <div className="row">
        <h1>{t("attendance.title")}</h1>
        <select value={mode} onChange={(event) => changeMode(event.target.value as Mode)} aria-label={t("attendance.title")}>
          <option value="daily">{t("attendance.mode.daily")}</option>
          <option value="history">{t("attendance.mode.history")}</option>
          <option value="events">{t("attendance.mode.events")}</option>
        </select>
        <input type="date" value={date} onChange={(event) => { setDate(event.target.value); setOffset(0); }} aria-label={t("common.date")} />
        <SiteSelect value={site} onChange={(value) => { setSite(value); setOffset(0); }} />
        {mode === "history" && <select value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0); }} aria-label={t("common.status")}><option value="">{t("attendance.allStatuses")}</option><option value="open">{t("status.open")}</option><option value="missing_out">{t("status.missing_out")}</option><option value="complete">{t("status.complete")}</option><option value="corrected">{t("attendance.statusCorrected")}</option></select>}
      </div>
      <p className="muted">{t("attendance.durationNote")}</p>
      <ErrorBanner message={daily.error ?? history.error ?? events.error} />

      {mode === "daily" && <table>
        <thead><tr><th>#</th><th>{t("attendance.employee")}</th><th>{t("attendance.in")}</th><th>{t("attendance.out")}</th><th>{t("attendance.duration")}</th><th /></tr></thead>
        <tbody>
          {(daily.data?.employees ?? []).flatMap((employee) => [
            ...employee.sessions.map((session) => <tr key={session.id} className={session.missing_out ? "warn" : ""}><td>{employee.employee_number}</td><td>{employee.employee_name}</td><td>{fmtTime(session.effective_in, session.site_timezone, lang)}</td><td>{fmtTime(session.effective_out, session.site_timezone, lang)}</td><td>{session.hours ?? (session.missing_out ? t("attendance.missingOut") : t("attendance.open"))}{session.corrected && <span className="badge info">{t("attendance.corrected")}</span>}</td><td><Link to={`/attendance/sessions/${session.id}`}>{t("common.view")}</Link></td></tr>),
            <tr key={`${employee.employee_id}-total`} className="total"><td colSpan={4}>{t("attendance.total")} – {employee.employee_name}</td><td colSpan={2}>{employee.total_hours}</td></tr>,
          ])}
          {daily.data?.employees.length === 0 && <tr><td colSpan={6} className="muted">{t("attendance.empty")}</td></tr>}
        </tbody>
      </table>}

      {mode === "history" && <>
        <table>
          <thead><tr><th>#</th><th>{t("attendance.employee")}</th><th>{t("common.site")}</th><th>{t("attendance.in")}</th><th>{t("attendance.out")}</th><th>{t("common.status")}</th></tr></thead>
          <tbody>{(history.data?.items ?? []).map((session) => <tr key={session.id}><td>{session.employee_number}</td><td><Link to={`/attendance/sessions/${session.id}`}>{session.employee_name}</Link></td><td>{session.site_name}</td><td>{fmtTime(session.effective_in, session.site_timezone, lang)}</td><td>{fmtTime(session.effective_out, session.site_timezone, lang)}</td><td>{t(`status.${session.status}` as "status.open")}</td></tr>)}</tbody>
        </table>
        <div className="row"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>{t("common.prev")}</button><span>{t("common.page").replace("{from}", String(history.data ? offset + 1 : 0)).replace("{to}", String(Math.min(offset + 25, history.data?.total ?? 0))).replace("{total}", String(history.data?.total ?? 0))}</span><button disabled={!history.data || offset + 25 >= history.data.total} onClick={() => setOffset(offset + 25)}>{t("common.next")}</button></div>
      </>}

      {mode === "events" && <table>
        <thead><tr><th>{t("attendance.employee")}</th><th>{t("attendance.gate")}</th><th>{t("attendance.direction")}</th><th>{t("attendance.time")}</th><th>{t("attendance.capture")}</th></tr></thead>
        <tbody>{(events.data?.items ?? []).map((event: EventRow) => <tr key={event.id}><td>{event.employee_name}</td><td>{event.gate_name}</td><td>{t(event.direction === "IN" ? "dir.IN" : "dir.OUT")}</td><td>{fmtTime(event.occurred_at, event.site_timezone, lang)}</td><td>{event.capture_mode}</td></tr>)}</tbody>
      </table>}
    </section>
  );
}
