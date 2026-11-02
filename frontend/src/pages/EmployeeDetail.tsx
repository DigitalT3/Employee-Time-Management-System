import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Credential } from "../api/types";
import { useAuth } from "../auth";
import { ErrorBanner, fmtTime, useLoad } from "../components/common";
import { useI18n } from "../i18n";

/** Employee detail with permanent QR delivery and auditable credential lifecycle controls. */
export default function EmployeeDetail() {
  const { id = "" } = useParams();
  const { lang, t } = useI18n();
  const { can } = useAuth();
  const employee = useLoad(() => api.employee(id), [id]);
  const credentials = useLoad<Credential[]>(() => can("credentials.manage") ? api.credentials(id) : Promise.resolve([]), [id, can]);
  const [error, setError] = useState<string | null>(null);
  const item = employee.data;

  const run = async (operation: () => Promise<unknown>) => {
    try {
      await operation();
      setError(null);
      await Promise.all([employee.reload(), credentials.reload()]);
    } catch (cause) {
      setError((cause as Error).message);
    }
  };

  const credentialAction = (credential: Credential, action: "block" | "unblock" | "revoke") => {
    const confirmation = t(`credential.confirm.${action}` as "credential.confirm.block");
    if (!window.confirm(confirmation)) return;
    const reason = window.prompt(t("common.optionalReason")) ?? undefined;
    void run(() => api.credentialAction(credential.id, action, reason));
  };
  const printQr = () => {
    void run(async () => {
      await api.qrReprint(id);
      window.print();
    });
  };

  if (!item) return <ErrorBanner message={employee.error ?? error} />;

  const canDownload = can("credentials.download");
  const canManage = can("credentials.manage");
  const current = credentials.data?.find((credential) => credential.is_current);

  return (
    <section>
      <ErrorBanner message={employee.error ?? credentials.error ?? error} />
      <div className="card">
        <h1>{item.first_name} {item.last_name}</h1>
        <p>#{item.employee_number} · <span className={`badge ${item.is_active ? "ok" : "off"}`}>{item.is_active ? t("common.active") : t("common.inactive")}</span> · {item.credential_status ? t(`credential.status.${item.credential_status}` as "credential.status.active") : t("credential.status.none")}</p>
        <p>{item.sites.map((site) => site.name).join(", ") || t("common.none")}</p>
        {can("employees.manage") && <div className="row no-print"><Link className="button" to={`/employees/${id}/edit`}>{t("common.edit")}</Link><button onClick={() => void run(() => api.setEmployeeActive(id, !item.is_active))}>{item.is_active ? t("common.deactivate") : t("common.activate")}</button></div>}

        {canDownload && current && (
          <div className="qr print-area">
            <h2>{t("employees.qr")}</h2>
            <p>{t("employees.qrNote")}</p>
            <img src={api.qrPngUrl(id)} alt={`QR ${item.employee_number}`} width={240} height={240} />
            <p className="print-only">{item.first_name} {item.last_name} · #{item.employee_number}</p>
            <div className="row no-print">
              <button onClick={printQr}>{t("employees.printQr")}</button>
              <a className="button" href={api.qrPngUrl(id)} download={`${item.employee_number}.png`}>{t("employees.downloadPng")}</a>
              <a className="button" href={api.qrPdfUrl(id)} download={`${item.employee_number}.pdf`}>{t("employees.downloadPdf")}</a>
            </div>
          </div>
        )}
        {canDownload && !current && <p className="muted">{t("employees.noQr")}</p>}

        {canManage && (
          <>
            <h2>{t("credential.manage")}</h2>
            {current ? <div className="row">
              {current.status === "active" && <button onClick={() => credentialAction(current, "block")}>{t("credential.block")}</button>}
              {current.status === "blocked" && <button onClick={() => credentialAction(current, "unblock")}>{t("credential.unblock")}</button>}
              {current.status !== "revoked" && <button onClick={() => credentialAction(current, "revoke")}>{t("credential.revoke")}</button>}
            </div> : <button onClick={() => {
              if (window.confirm(t("credential.confirm.reissue"))) void run(() => api.reissueCredential(id, window.prompt(t("common.optionalReason")) ?? undefined));
            }}>{t("credential.reissue")}</button>}
            <h3>{t("credential.history")}</h3>
            <table>
              <thead><tr><th>{t("common.status")}</th><th>{t("credential.issued")}</th><th>{t("credential.blockedAt")}</th><th>{t("credential.revokedAt")}</th><th>{t("credential.current")}</th></tr></thead>
              <tbody>{(credentials.data ?? []).map((credential) => <tr key={credential.id}><td>{t(`credential.status.${credential.status}` as "credential.status.active")}</td><td>{fmtTime(credential.issued_at, undefined, lang)}</td><td>{fmtTime(credential.blocked_at, undefined, lang)}</td><td>{fmtTime(credential.revoked_at, undefined, lang)}</td><td>{credential.is_current ? t("common.yes") : t("common.no")}</td></tr>)}</tbody>
            </table>
          </>
        )}
      </div>
    </section>
  );
}
