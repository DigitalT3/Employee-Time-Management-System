import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ScannerContext } from "../api/types";
import LangSwitch from "../components/LangSwitch";
import { ResultPanel } from "../components/common";
import { useI18n } from "../i18n";
import { registerScannerShell } from "../pwa";
import { startCamera, type CameraState } from "../scanner/camera";
import { ConnectivityMonitor, probeBackend, type ConnectionState } from "../scanner/connectivity";
import { feedbackFromResult, useFeedback } from "../scanner/feedback";
import { recordTiming } from "../scanner/perf";
import { enqueue, queueStats } from "../scanner/queue";
import { backoffMs, drainQueue, sendHeartbeat } from "../scanner/sync";
import { digestToken, recentCaptureWithin, recordTentative, tentativeFor } from "../scanner/tokenState";
import { DEVICE_TOKEN_KEY } from "./ScannerSetup";

/** Tablet kiosk: durable local capture first, then ordered synchronisation with server-confirmed directions. */
export default function Scanner() {
  const { lang, t } = useI18n();
  const [token, setToken] = useState(() => localStorage.getItem(DEVICE_TOKEN_KEY) ?? "");
  const [context, setContext] = useState<ScannerContext | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("unknown");
  const [cameraState, setCameraState] = useState<CameraState>("off");
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState(0);
  const [syncProblem, setSyncProblem] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const contextRef = useRef<ScannerContext | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout>>();
  const failures = useRef(0);
  const monitor = useRef<ConnectivityMonitor | null>(null);
  const { feedback, show } = useFeedback();
  contextRef.current = context;

  const refreshStats = useCallback(async () => {
    const stats = await queueStats();
    setPending(stats.pending);
    setFailed(stats.failed);
  }, []);

  const drain = useCallback(async () => {
    if (!token) return;
    const started = performance.now();
    const result = await drainQueue(token);
    for (const resolved of result.resolved) {
      const mapped = feedbackFromResult(resolved.result, contextRef.current?.site.timezone ?? null, lang);
      if (mapped) show(mapped);
      void recordTiming("scan_to_confirmation_ms", performance.now() - started);
    }
    await sendHeartbeat(token);
    await refreshStats();

    if (result.fatal) {
      setSyncProblem(result.fatal);
      return;
    }
    setSyncProblem(null);
    if (result.retryLater) {
      failures.current += 1;
      clearTimeout(retryTimer.current);
      retryTimer.current = setTimeout(() => void drain(), backoffMs(failures.current));
    } else {
      failures.current = 0;
    }
  }, [lang, refreshStats, show, token]);

  useEffect(() => {
    if (!token) return undefined;
    void registerScannerShell();
    let mounted = true;
    const load = async () => {
      try {
        const scannerContext = await api.scannerContext(token);
        if (mounted) setContext(scannerContext);
      } catch {
        if (mounted) setSyncProblem(t("scanner.pairFailed"));
      }
    };
    void load();
    void refreshStats();

    const nextMonitor = new ConnectivityMonitor(async () => {
      const state = await probeBackend(token);
      if (state.lastSequence !== undefined && mounted) {
        setContext((current) => current ? { ...current, device: { ...current.device, last_sequence: state.lastSequence! } } : current);
      }
      return state.online;
    });
    monitor.current = nextMonitor;
    const unsubscribe = nextMonitor.subscribe((state) => {
      if (!mounted) return;
      setConnection(state);
      if (state === "online") void drain();
    });
    nextMonitor.start();

    return () => {
      mounted = false;
      unsubscribe();
      nextMonitor.stop();
      clearTimeout(retryTimer.current);
    };
  }, [drain, refreshStats, t, token]);

  const capture = useCallback(async (rawCode: string) => {
    const code = rawCode.trim();
    if (!code || !contextRef.current) return;
    const digest = await digestToken(code);
    if (await recentCaptureWithin(digest, contextRef.current.duplicate_window_seconds)) {
      show({ kind: "already", reason: "within_duplicate_window" });
      return;
    }

    const tentative = await tentativeFor(digest);
    const online = monitor.current?.state === "online";
    const row = await enqueue(code, contextRef.current.device.last_sequence, {
      captureMode: online ? "online" : "offline",
      tentativeDirection: tentative,
    });
    if (!online && tentative) await recordTentative(digest, tentative);
    show({ kind: "pending", tentative, uuid: row.client_uuid });
    await refreshStats();
    if (online) void drain();
  }, [drain, refreshStats, show]);

  const toggleCamera = useCallback(() => {
    setCameraState((state) => state === "off" ? "starting" : "off");
  }, []);

  useEffect(() => {
    if (cameraState !== "starting" || !video.current) return undefined;
    let stopped = false;
    let stop: (() => void) | undefined;
    void startCamera(video.current, (code) => void capture(code), (state) => {
      if (!stopped) setCameraState(state);
    }).then((handle) => {
      if (stopped) handle?.stop();
      else stop = handle?.stop;
    });
    return () => {
      stopped = true;
      stop?.();
    };
  }, [cameraState, capture]);

  const submitManual = async (event: FormEvent) => {
    event.preventDefault();
    await capture(manual);
    setManual("");
  };

  const unpair = () => {
    if (!window.confirm(t("scanner.confirmUnpair"))) return;
    localStorage.removeItem(DEVICE_TOKEN_KEY);
    setToken("");
    setContext(null);
  };

  if (!token) {
    return (
      <main className="kiosk">
        <LangSwitch />
        <h1>{t("scanner.title")}</h1>
        <p>{t("scanner.notPaired")}</p>
        <a className="button primary" href="/scanner/setup">{t("scanner.setup")}</a>
      </main>
    );
  }

  const connectionText = connection === "online" ? t("scanner.online")
    : connection === "offline" ? t("scanner.offline") : t("scanner.checking");

  return (
    <main className="kiosk">
      <header className="kiosk-header">
        <div>
          <h1>{context ? `${context.site.name} · ${context.gate.name}` : t("scanner.title")}</h1>
          <span className={`badge ${connection === "online" ? "ok" : "warn"}`}>{connectionText}</span>
          <span className="badge">{t(`scanner.camera.${cameraState}` as "scanner.camera.off")}</span>
        </div>
        <LangSwitch />
      </header>
      <ResultPanel feedback={feedback} timezone={context?.site.timezone ?? null} />
      {syncProblem && <p className="error" role="alert">{t("scanner.syncFailed")}: {syncProblem}</p>}
      <div className="scanner-status" aria-live="polite">
        <span>{t("scanner.pendingCount")}: <strong>{pending}</strong></span>
        <span>{t("scanner.failedCount")}: <strong>{failed}</strong></span>
      </div>
      <div className="row kiosk-actions">
        <button className="primary big" onClick={toggleCamera}>
          {cameraState === "active" || cameraState === "starting" ? t("scanner.stop") : t("scanner.start")}
        </button>
        <button onClick={() => void document.documentElement.requestFullscreen?.()}>{t("scanner.fullscreen")}</button>
        <button onClick={unpair}>{t("scanner.unpair")}</button>
      </div>
      {cameraState !== "off" && <video ref={video} className="video" muted playsInline aria-label={t("scanner.title")} />}
      <form className="manual-entry" onSubmit={submitManual}>
        <label>{t("scanner.manual")}
          <input value={manual} onChange={(event) => setManual(event.target.value)} placeholder={t("scanner.manualHint")} />
        </label>
        <button type="submit">{t("scanner.submit")}</button>
      </form>
    </main>
  );
}
