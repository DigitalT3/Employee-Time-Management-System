import { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import { useI18n } from "./i18n";
import Attendance from "./pages/Attendance";
import Corrections from "./pages/Corrections";
import Dashboard from "./pages/Dashboard";
import EmployeeDetail from "./pages/EmployeeDetail";
import EmployeeForm from "./pages/EmployeeForm";
import Employees from "./pages/Employees";
import Login from "./pages/Login";
import Permissions from "./pages/Permissions";
import Reports from "./pages/Reports";
import Scanner from "./pages/Scanner";
import ScannerSetup from "./pages/ScannerSetup";
import SessionDetailPage from "./pages/SessionDetail";
import Sites from "./pages/Sites";

function Protected({ children, permission }: { children: ReactNode; permission?: string }) {
  const { user, ready, can } = useAuth();
  const { t } = useI18n();
  if (!ready) return <p className="muted">…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (permission && !can(permission)) return <Layout><p className="error" role="alert">{t("common.noAccess")}</p></Layout>;
  return <Layout>{children}</Layout>;
}

/** Route table; scanner routes use their paired device token instead of a staff session. */
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/scanner" element={<Scanner />} />
      <Route path="/scanner/setup" element={<ScannerSetup />} />
      <Route path="/" element={<Protected permission="dashboard.view"><Dashboard /></Protected>} />
      <Route path="/employees" element={<Protected permission="employees.view"><Employees /></Protected>} />
      <Route path="/employees/new" element={<Protected permission="employees.manage"><EmployeeForm /></Protected>} />
      <Route path="/employees/:id" element={<Protected permission="employees.view"><EmployeeDetail /></Protected>} />
      <Route path="/employees/:id/edit" element={<Protected permission="employees.manage"><EmployeeForm /></Protected>} />
      <Route path="/sites" element={<Protected permission="sites.manage"><Sites /></Protected>} />
      <Route path="/attendance" element={<Protected permission="attendance.view"><Attendance /></Protected>} />
      <Route path="/attendance/sessions/:id" element={<Protected permission="attendance.view"><SessionDetailPage /></Protected>} />
      <Route path="/corrections" element={<Protected permission="corrections.view"><Corrections /></Protected>} />
      <Route path="/reports" element={<Protected permission="reports.export"><Reports /></Protected>} />
      <Route path="/permissions" element={<Protected permission="permissions.manage"><Permissions /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
