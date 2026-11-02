/** Backend connectivity detection: a probe against the API, never `navigator.onLine` alone. */
import { api, ApiError } from "../api/client";

export type ConnectionState = "online" | "offline" | "unknown";

export interface ProbeResult { online: boolean; invalidDevice?: boolean; lastSequence?: number }

// PUBLIC_INTERFACE
/** Call `/api/scanner/ping` with a timeout. A reachable server that rejects the token still counts as online. */
export async function probeBackend(deviceToken: string, timeoutMs = 3000): Promise<ProbeResult> {
  try {
    const { json } = await api.ping(deviceToken, timeoutMs);
    return { online: true, lastSequence: json.last_sequence };
  } catch (e) {
    if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) {
      return { online: true, invalidDevice: e.status === 401 || e.status === 403 };
    }
    return { online: false };
  }
}

// PUBLIC_INTERFACE
/** Holds the connection state, notifies listeners on change and re-probes on an interval. */
export class ConnectivityMonitor {
  state: ConnectionState = "unknown";
  private listeners = new Set<(s: ConnectionState) => void>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private running = false;

  constructor(
    private probe: () => Promise<boolean>,
    private onlineIntervalMs = 10000,
    private offlineIntervalMs = 4000,
  ) {}

  /** Subscribe to state changes; returns an unsubscribe function. */
  subscribe(fn: (s: ConnectionState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Record a known state (for example when a sync request failed or the browser fired an offline event). */
  report(online: boolean): void {
    const next: ConnectionState = online ? "online" : "offline";
    if (next === this.state) return;
    this.state = next;
    this.listeners.forEach((fn) => fn(next));
  }

  /** Run one probe now. */
  async check(): Promise<ConnectionState> {
    let ok = false;
    try { ok = await this.probe(); } catch { ok = false; }
    this.report(ok);
    return this.state;
  }

  /** Start periodic probing (first probe immediately). */
  start(): void {
    if (this.running) return;
    this.running = true;
    const loop = async () => {
      await this.check();
      if (!this.running) return;
      this.timer = setTimeout(() => void loop(), this.state === "online" ? this.onlineIntervalMs : this.offlineIntervalMs);
    };
    void loop();
  }

  /** Stop probing. */
  stop(): void {
    this.running = false;
    clearTimeout(this.timer);
  }
}
