/** Service-worker app shell registration (DEC-06): only the scanner route registers it, and only in production builds. */

// PUBLIC_INTERFACE
/**
 * Register the precached application shell so the scanner page reloads while the network is unavailable.
 * The Vite dev server has no service worker; a plain-HTTP LAN origin is not a secure context and
 * cannot register one (use `npm run preview:https`, see README). Failures never affect scanning.
 */
export async function registerScannerShell(): Promise<boolean> {
  if (!import.meta.env.PROD || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return false;
  try {
    const { registerSW } = await import("virtual:pwa-register");
    registerSW({ immediate: true });
    return true;
  } catch {
    return false;
  }
}
