import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { ErrorBanner, useLoad } from "../components/common";
import { useI18n } from "../i18n";

/** Create or edit an employee (creation issues the permanent QR credential atomically). */
export default function EmployeeForm() {
  const { id } = useParams();
  const { t } = useI18n();
  const nav = useNavigate();
  const sites = useLoad(() => api.sites(), []);
  const [number, setNumber] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [siteIds, setSiteIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api.employee(id).then((e) => {
      setNumber(e.employee_number); setFirst(e.first_name); setLast(e.last_name); setSiteIds(e.site_ids);
    }).catch((e: Error) => setError(e.message));
  }, [id]);

  const toggle = (sid: string) =>
    setSiteIds((cur) => (cur.includes(sid) ? cur.filter((x) => x !== sid) : [...cur, sid]));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const payload = { employee_number: number, first_name: first, last_name: last, site_ids: siteIds };
    try {
      const saved = id ? await api.updateEmployee(id, payload) : await api.createEmployee(payload);
      nav(`/employees/${saved.id}`);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <form className="card" onSubmit={submit}>
      <h1>{id ? t("common.edit") : t("employees.new")}</h1>
      <label>{t("employees.number")}<input value={number} onChange={(e) => setNumber(e.target.value)} required /></label>
      <label>{t("employees.first")}<input value={first} onChange={(e) => setFirst(e.target.value)} required /></label>
      <label>{t("employees.last")}<input value={last} onChange={(e) => setLast(e.target.value)} required /></label>
      <fieldset>
        <legend>{t("employees.sites")}</legend>
        {(sites.data ?? []).map((s) => (
          <label key={s.id} className="check">
            <input type="checkbox" checked={siteIds.includes(s.id)} onChange={() => toggle(s.id)} />
            {s.code} – {s.name}
          </label>
        ))}
      </fieldset>
      <ErrorBanner message={error} />
      <div className="row">
        <button className="primary" type="submit" disabled={siteIds.length === 0}>{t("common.save")}</button>
        <button type="button" onClick={() => nav(-1)}>{t("common.cancel")}</button>
      </div>
    </form>
  );
}
