import { FormEvent, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth";
import { ErrorBanner } from "../components/common";
import LangSwitch from "../components/LangSwitch";
import { useI18n } from "../i18n";

/** Staff login with loading and server-provided throttle feedback. */
export default function Login() {
  const { user, login } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (cause) {
      const apiError = cause as ApiError;
      setError(apiError.status === 429
        ? t("login.locked").replace("{n}", String(apiError.retryAfter ?? ""))
        : `${t("login.failed")}: ${apiError.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="card login" onSubmit={submit}>
      <LangSwitch />
      <h1>{t("login.title")}</h1>
      <label>{t("login.username")}<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label>
      <label>{t("login.password")}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label>
      <ErrorBanner message={error} />
      <button className="primary" type="submit" disabled={submitting}>{submitting ? t("login.loading") : t("login.submit")}</button>
    </form>
  );
}
