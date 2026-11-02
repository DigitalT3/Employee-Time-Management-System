import { useEffect, useState } from "react";
import { api } from "../api/client";
import { ErrorBanner, SiteSelect, todayIso, useLoad } from "../components/common";
import { useI18n } from "../i18n";

/** Daily and weekly attendance report previews with Excel-compatible CSV export. */
export default function Reports() {
  const { lang, t } = useI18n();
  const [period, setPeriod] = useState<"daily" | "weekly">("daily");
  const [date, setDate] = useState(todayIso());
  const [site, setSite] = useState("");
  const [employee, setEmployee] = useState("");
  const [delimiter, setDelimiter] = useState(lang === "nl" ? ";" : ",");
  const employees = useLoad(() => api.employees(), []);
  const preview = useLoad(() => api.reportPreview(period, { date, site_id: site || undefined, employee_id: employee || undefined }), [period, date, site, employee]);

  useEffect(() => setDelimiter(lang === "nl" ? ";" : ","), [lang]);

  return (
    <section className="card">
      <h1>{t("reports.title")}</h1>
      <div className="row">
        <label>{t("reports.period")}<select value={period} onChange={(event) => setPeriod(event.target.value as "daily" | "weekly")}><option value="daily">{t("reports.daily")}</option><option value="weekly">{t("reports.weekly")}</option></select></label>
        <label>{t("reports.date")}<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
        <SiteSelect value={site} onChange={setSite} />
        <label>{t("reports.employee")}<select value={employee} onChange={(event) => setEmployee(event.target.value)}><option value="">{t("reports.allEmployees")}</option>{(employees.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.employee_number} – {item.first_name} {item.last_name}</option>)}</select></label>
        <label>{t("reports.delimiter")}<select value={delimiter} onChange={(event) => setDelimiter(event.target.value)}><option value=",">{t("reports.comma")}</option><option value=";">{t("reports.semicolon")}</option><option value="\t">{t("reports.tab")}</option></select></label>
        <a className="button primary" href={api.exportUrl({ period, date, site_id: site || undefined, employee_id: employee || undefined, delimiter })} download>{t("reports.export")}</a>
      </div>
      <p className="muted">{t("reports.note")}</p>
      <ErrorBanner message={preview.error} />
      {preview.data && <><div className="summary-grid"><div><strong>{preview.data.summary.sessions}</strong><span>{t("reports.sessions")}</span></div><div><strong>{preview.data.summary.completed_hours}</strong><span>{t("reports.completed")}</span></div><div><strong>{preview.data.summary.incomplete}</strong><span>{t("reports.incomplete")}</span></div></div><h2>{t("reports.preview")}</h2><table><thead><tr><th>{t("reports.employee")}</th><th>{t("common.site")}</th><th>{t("attendance.in")}</th><th>{t("attendance.out")}</th><th>{t("attendance.duration")}</th><th>{t("common.status")}</th></tr></thead><tbody>{preview.data.rows.map((row) => <tr key={row.session_id}><td>{row.employee_number} – {row.first_name} {row.last_name}</td><td>{row.site_name}</td><td>{row.in_local}</td><td>{row.out_local || "—"}</td><td>{row.duration_hhmm || "—"}</td><td>{row.status}</td></tr>)}</tbody></table></>}
    </section>
  );
}
