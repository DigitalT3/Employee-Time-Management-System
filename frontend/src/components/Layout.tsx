import { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import LangSwitch from "./LangSwitch";

/** Authenticated page chrome with permission-aware staff navigation. */
export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout, can } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();

  return (
    <div className="shell">
      <header className="topbar">
        <strong>{t("appName")}</strong>
        <nav aria-label={t("nav.main")}>
          {can("dashboard.view") && <NavLink to="/" end>{t("nav.dashboard")}</NavLink>}
          {can("employees.view") && <NavLink to="/employees">{t("nav.employees")}</NavLink>}
          {can("sites.manage") && <NavLink to="/sites">{t("nav.sites")}</NavLink>}
          {can("attendance.view") && <NavLink to="/attendance">{t("nav.attendance")}</NavLink>}
          {can("corrections.view") && <NavLink to="/corrections">{t("nav.corrections")}</NavLink>}
          {can("reports.export") && <NavLink to="/reports">{t("nav.reports")}</NavLink>}
          {can("permissions.manage") && <NavLink to="/permissions">{t("nav.permissions")}</NavLink>}
        </nav>
        <span className="spacer" />
        <LangSwitch />
        <span className="muted">{user?.username} ({user?.role})</span>
        <button onClick={async () => { await logout(); navigate("/login"); }}>{t("nav.logout")}</button>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
