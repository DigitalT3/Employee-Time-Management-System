/** Minimal i18n context with English and Dutch dictionaries persisted in localStorage. */
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import en, { Key } from "./en";
import nl from "./nl";

export type Lang = "en" | "nl";
const dictionaries: Record<Lang, Record<Key, string>> = { en, nl };

/** Translate a key for a language, falling back to English. */
export function translate(lang: Lang, key: Key): string {
  return dictionaries[lang][key] ?? en[key];
}

interface I18n { lang: Lang; setLang: (l: Lang) => void; t: (k: Key) => string }
const Ctx = createContext<I18n>({ lang: "en", setLang: () => undefined, t: (k) => en[k] });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => (localStorage.getItem("etms.lang") === "nl" ? "nl" : "en"));
  // Keep <html lang> in step with the active language, including a language restored from storage on load.
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    localStorage.setItem("etms.lang", l);
    setLangState(l);
  }, []);
  const value = useMemo<I18n>(() => ({ lang, setLang, t: (k) => translate(lang, k) }), [lang, setLang]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useI18n = () => useContext(Ctx);
export type { Key };
