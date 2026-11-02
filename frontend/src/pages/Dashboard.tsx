import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorBanner, fmtTime, SiteSelect, todayIso, useLoad, usePolling } from "../components/common";
import { useI18n } from "../i18n";

/** Live recorded-attendance dashboard. It never claims to verify physical presence. */
export default function Dashboard() {
  const { lang, t } = useI18n();
  const [site, setSite] = useState("");
  const [date, setDate] = useState(todayIso());
  const dashboard = useLoad(() => api.dashboard({ site_id: site || undefined, date }), [site, date]);
  const updated = usePolling(dashboard.reload, 5000);
  const data = dashboard.data;

  return (
    <section>
      <div className="row no-print">
        <h1>{t("dashboard.title")}</h1>
        <SiteSelect value={site} onChange={setSite} />
        <input type="date" value={date} onChange={(event) => setDate(event.target.value)} aria-label={t("common.date")} />
        <button onClick={() => void dashboard.reload()}>{t("common.refresh")}</button>
        <Link className="button" to="/attendance">{t("dashboard.history")}</Link>
        <Link className="button" to="/reports">{t("dashboard.csv")}</Link>
        <button onClick={() => window.print()}>{t("dashboard.printList")}</button>
      </div>
      <p className="muted">{t("dashboard.recorded")}</p>
      <p className="muted">{t("dashboard.refreshing")}{updated && ` · ${t("dashboard.updated")}: ${fmtTime(updated.toISOString(), undefined, lang)}`}</p>
      <ErrorBanner message={dashboard.error} />

      <div className="summary-grid">
        <div className="card"><strong>{data?.counts.on_site ?? "…"}</strong><span>{t("dashboard.onSite")}</span></div>
        <div className="card"><strong>{data?.counts.off_site ?? "…"}</strong><span>{t("dashboard.offSite")}</span></div>
        <div className="card"><strong>{data?.counts.incomplete ?? "…"}</strong><span>{t("dashboard.incomplete")}</span></div>
      </div>

      <div className="print-only">
        <h1>{t("dashboard.printTitle")}</h1>
        <p>{t("dashboard.asOf")}: {fmtTime(data?.as_of, undefined, lang)}</p>
        <p>{t("dashboard.printDisclaimer")}</p>
      </div>

      <h2>{t("dashboard.onSite")}</h2>
      <table>
        <thead><tr><th>#</th><th>{t("common.name")}</th><th>{t("common.site")}</th><th>{t("dashboard.latestDirection")}</th><th>{t("dashboard.latestIn")}</th><th>{t("common.status")}</th></tr></thead>
        <tbody>
          {(data?.on_site ?? []).map((session) => (
            <tr key={session.id}>
              <td>{session.employee_number}</td>
              <td><Link to={`/attendance/sessions/${session.id}`}>{session.employee_name}</Link></td>
              <td>{session.site_name ?? session.site_code}</td>
              <td>{t("dir.IN")}</td>
              <td>{fmtTime(session.latest_in, session.site_timezone, lang)}</td>
              <td><span className={`badge ${session.missing_out ? "warn" : "ok"}`}>{t(`status.${session.status}` as "status.open")}</span></td>
            </tr>
          ))}
          {data?.on_site.length === 0 && <tr><td colSpan={6} className="muted">{t("dashboard.noOnSite")}</td></tr>}
        </tbody>
      </table>

      <h2>{t("dashboard.recent")}</h2>
      <table>
        <thead><tr><th>{t("common.employee")}</th><th>{t("attendance.gate")}</th><th>{t("attendance.direction")}</th><th>{t("attendance.time")}</th></tr></thead>
        <tbody>
          {(data?.recent_activity ?? []).map((item) => <tr key={item.id}><td>{item.employee_name}</td><td>{item.gate_name}</td><td>{t(item.direction === "IN" ? "dir.IN" : "dir.OUT")}</td><td>{fmtTime(item.occurred_at, item.site_timezone, lang)}</td></tr>)}
          {data?.recent_activity.length === 0 && <tr><td colSpan={4} className="muted">{t("dashboard.noRecent")}</td></tr>}
        </tbody>
      </table>

      <h2>{t("dashboard.exceptions")}</h2>
      <table>
        <tbody>
          {(data?.exceptions ?? []).map((session) => <tr key={session.id} className="warn"><td>{session.employee_number}</td><td><Link to={`/attendance/sessions/${session.id}`}>{session.employee_name}</Link></td><td>{fmtTime(session.effective_in, session.site_timezone, lang)}</td><td>{t("attendance.missingOut")}</td></tr>)}
          {data?.exceptions.length === 0 && <tr><td className="muted">{t("dashboard.noExceptions")}</td></tr>}
        </tbody>
      </table>

      <h2>{t("dashboard.scanProblems")}</h2>
      <table>
        <tbody>
          {(data?.scan_problems ?? []).map((entry) => <tr key={entry.id}><td>{entry.device_name}</td><td>{t(`outcome.${entry.outcome}` as "outcome.rejected")}</td><td>{entry.reason ?? "—"}</td><td>{fmtTime(entry.received_at, entry.site_timezone, lang)}</td></tr>)}
          {data?.scan_problems.length === 0 && <tr><td className="muted">{t("dashboard.noScanProblems")}</td></tr>}
        </tbody>
      </table>

      <h2>{t("dashboard.deviceSync")}</h2>
      <table>
        <tbody>
          {(data?.device_sync ?? []).map((device) => <tr key={device.device_id}><td>{device.device_name}</td><td>{t(`sync.${device.connection}` as "sync.online")}</td><td>{device.pending} / {device.failed}</td><td>{fmtTime(device.last_seen_at, undefined, lang)}</td></tr>)}
          {data?.device_sync.length === 0 && <tr><td className="muted">{t("dashboard.noDevices")}</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
