import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorBanner, fmtTime, SiteSelect, todayIso, useLoad } from "../components/common";
import { useI18n } from "../i18n";

/** Paginated global correction audit history for authorised staff. */
export default function Corrections() {
  const { lang, t } = useI18n();
  const [site, setSite] = useState("");
  const [date, setDate] = useState(todayIso());
  const [offset, setOffset] = useState(0);
  const corrections = useLoad(() => api.corrections({ site_id: site || undefined, from: date, to: date, limit: 25, offset }), [site, date, offset]);

  return (
    <section>
      <div className="row"><h1>{t("corrections.title")}</h1><input type="date" aria-label={t("common.date")} value={date} onChange={(event) => { setDate(event.target.value); setOffset(0); }} /><SiteSelect value={site} onChange={(value) => { setSite(value); setOffset(0); }} /></div>
      <ErrorBanner message={corrections.error} />
      <table>
        <thead><tr><th>{t("common.employee")}</th><th>{t("corrections.original")}</th><th>{t("corrections.new")}</th><th>{t("common.reason")}</th><th>{t("corrections.actor")}</th><th>{t("corrections.when")}</th></tr></thead>
        <tbody>
          {(corrections.data?.items ?? []).map((correction) => <tr key={correction.id}><td>{correction.employee_name ? <Link to={`/attendance/sessions/${correction.session_id}`}>{correction.employee_name}</Link> : "—"}</td><td>{fmtTime(correction.old_value, correction.site_timezone, lang)}</td><td>{fmtTime(correction.new_value, correction.site_timezone, lang)}</td><td>{correction.reason}</td><td>{correction.actor}</td><td>{fmtTime(correction.created_at, correction.site_timezone, lang)}</td></tr>)}
          {corrections.data?.items.length === 0 && <tr><td colSpan={6} className="muted">{t("corrections.empty")}</td></tr>}
        </tbody>
      </table>
      <div className="row"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>{t("common.prev")}</button><button disabled={!corrections.data || offset + 25 >= corrections.data.total} onClick={() => setOffset(offset + 25)}>{t("common.next")}</button></div>
    </section>
  );
}
