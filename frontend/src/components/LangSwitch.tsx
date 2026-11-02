import { useI18n } from "../i18n";

/** EN/NL selector. */
export default function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <label className="lang">
      <span className="sr-only">{t("lang.label")}</span>
      <select value={lang} onChange={(e) => setLang(e.target.value as "en" | "nl")} aria-label={t("lang.label")}>
        <option value="en">EN</option>
        <option value="nl">NL</option>
      </select>
    </label>
  );
}
