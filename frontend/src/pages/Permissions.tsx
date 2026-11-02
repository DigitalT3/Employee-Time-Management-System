import { useState } from "react";
import { api } from "../api/client";
import { ErrorBanner, useLoad } from "../components/common";
import { useI18n } from "../i18n";

/** Administrator view and editor for the server-enforced role-permission matrix. */
export default function Permissions() {
  const { t } = useI18n();
  const matrix = useLoad(() => api.permissions(), []);
  const [draft, setDraft] = useState<Record<string, Record<string, boolean>> | null>(null);
  const [saved, setSaved] = useState(false);
  const values = draft ?? matrix.data?.matrix;

  const setValue = (role: string, permission: string, allowed: boolean) => {
    setDraft((current) => {
      const source = current ?? matrix.data?.matrix ?? {};
      return { ...source, [role]: { ...source[role], [permission]: allowed } };
    });
    setSaved(false);
  };

  const save = async () => {
    if (!values) return;
    await api.savePermissions(values);
    setDraft(null);
    setSaved(true);
    await matrix.reload();
  };

  return (
    <section>
      <h1>{t("permissions.title")}</h1>
      <p>{t("permissions.intro")}</p>
      <ErrorBanner message={matrix.error} />
      {values && <><table><thead><tr><th>{t("permissions.permission")}</th>{matrix.data!.roles.map((role) => <th key={role}>{t(`role.${role}` as "role.admin")}</th>)}</tr></thead><tbody>{matrix.data!.permissions.map((permission) => <tr key={permission.key}><td>{t(`perm.${permission.key}` as "perm.dashboard.view")}</td>{matrix.data!.roles.map((role) => {
        const locked = matrix.data!.locked.some((item) => item.role === role && item.permission === permission.key);
        return <td key={role}><input type="checkbox" checked={!!values[role]?.[permission.key]} disabled={locked} aria-label={`${role} ${permission.key}`} onChange={(event) => setValue(role, permission.key, event.target.checked)} />{locked && <span className="sr-only">{t("permissions.locked")}</span>}</td>;
      })}</tr>)}</tbody></table><div className="row"><button className="primary" onClick={() => void save()}>{t("permissions.save")}</button>{saved && <span className="notice">{t("permissions.saved")}</span>}</div></>}
    </section>
  );
}
