import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorBanner, SiteSelect, useLoad } from "../components/common";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

/** Employee list with search and status/site filters. */
export default function Employees() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState("");
  const [site, setSite] = useState("");
  const list = useLoad(
    () => api.employees({ search, site_id: site || undefined, active: active === "" ? undefined : active === "1" }),
    [search, active, site],
  );
  return (
    <section>
      <div className="row">
        <h1>{t("employees.title")}</h1>
        <input type="search" placeholder={t("common.search")} value={search}
          onChange={(e) => setSearch(e.target.value)} aria-label={t("common.search")} />
        <select value={active} onChange={(e) => setActive(e.target.value)} aria-label={t("common.status")}>
          <option value="">{t("common.all")}</option>
          <option value="1">{t("common.active")}</option>
          <option value="0">{t("common.inactive")}</option>
        </select>
        <SiteSelect value={site} onChange={setSite} />
        {can("employees.manage") && <Link className="button primary" to="/employees/new">{t("employees.new")}</Link>}
      </div>
      <ErrorBanner message={list.error} />
      <table>
        <thead><tr><th>#</th><th>{t("common.name")}</th><th>{t("common.site")}</th><th>{t("common.status")}</th><th>{t("employees.credential")}</th><th>{t("common.actions")}</th></tr></thead>
        <tbody>
          {(list.data ?? []).map((e) => (
            <tr key={e.id}>
              <td>{e.employee_number}</td>
              <td><Link to={`/employees/${e.id}`}>{e.first_name} {e.last_name}</Link></td>
              <td>{e.sites.map((siteRef) => siteRef.name).join(", ") || "—"}</td>
              <td><span className={`badge ${e.is_active ? "ok" : "off"}`}>{e.is_active ? t("common.active") : t("common.inactive")}</span></td>
              <td>{e.credential_status ?? "—"}</td>
              <td><Link to={`/employees/${e.id}`}>{t("common.view")}</Link></td>
            </tr>
          ))}
          {list.data?.length === 0 && <tr><td colSpan={6} className="muted">{t("employees.empty")}</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
