import { FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ErrorBanner } from "../components/common";
import LangSwitch from "../components/LangSwitch";
import { useI18n } from "../i18n";

export const DEVICE_TOKEN_KEY = "etms.deviceToken";

/** Pairs this tablet by validating a device token and storing it locally. */
export default function ScannerSetup() {
  const { t } = useI18n();
  const nav = useNavigate();
  const loc = useLocation();
  const [token, setToken] = useState<string>((loc.state as { token?: string } | null)?.token ?? "");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.scannerContext(token.trim());
      localStorage.setItem(DEVICE_TOKEN_KEY, token.trim());
      nav("/scanner");
    } catch {
      setError(t("scanner.pairFailed"));
    }
  };

  return (
    <form className="card login" onSubmit={submit}>
      <LangSwitch />
      <h1>{t("scanner.setup")}</h1>
      <label>{t("scanner.token")}<input value={token} onChange={(e) => setToken(e.target.value)} required /></label>
      <ErrorBanner message={error} />
      <button className="primary" type="submit">{t("scanner.pair")}</button>
      <Link to="/">{t("nav.dashboard")}</Link>
    </form>
  );
}
