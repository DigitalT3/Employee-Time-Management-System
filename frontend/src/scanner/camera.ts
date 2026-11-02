/** Camera QR decoding with ZXing plus an absence-based latch. No frame is ever captured or stored. */
import { BrowserQRCodeReader } from "@zxing/browser";

export type CameraState = "off" | "starting" | "active" | "denied" | "unavailable" | "insecure_context" | "error";

// PUBLIC_INTERFACE
/**
 * Suppresses repeats while a code stays in view: a code is processed again only after it has been
 * absent (not seen in any frame) for `absentMs` or after a different code was seen.
 */
export class CodeLatch {
  private current = "";
  private absentSince: number | null = null;
  constructor(private absentMs = 2000) {}
  /** Returns true when the code should be processed; every sighting refreshes the "in view" time. */
  accept(code: string, now = Date.now()): boolean {
    if (code === this.current) {
      if (this.absentSince === null || now - this.absentSince < this.absentMs) {
        this.absentSince = null;
        return false;
      }
      this.absentSince = null;
    }
    this.current = code;
    this.absentSince = null;
    return true;
  }

  /** Mark a decoder frame with no QR result so the current code can re-arm after the required absence. */
  markAbsent(now = Date.now()): void {
    if (this.current && this.absentSince === null) this.absentSince = now;
  }
}

/** Map a getUserMedia failure to a camera state. */
export function cameraStateForError(e: unknown): CameraState {
  const name = (e as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError" || name === "NotReadableError" || name === "DevicesNotFoundError") return "unavailable";
  return "error";
}

export interface CameraHandle { stop: () => void }

// PUBLIC_INTERFACE
/**
 * Start decoding from the rear camera (when present) into the video element and report state changes.
 * Camera access needs a secure context (HTTPS or localhost); otherwise `insecure_context` is reported.
 */
export async function startCamera(
  video: HTMLVideoElement, onCode: (code: string) => void, onState: (s: CameraState) => void,
): Promise<CameraHandle | null> {
  if (typeof window !== "undefined" && window.isSecureContext === false) { onState("insecure_context"); return null; }
  if (!navigator.mediaDevices?.getUserMedia) { onState("unavailable"); return null; }
  onState("starting");
  const latch = new CodeLatch();
  const reader = new BrowserQRCodeReader();
  try {
    const controls = await reader.decodeFromConstraints(
      { video: { facingMode: { ideal: "environment" } }, audio: false }, video,
      (result) => {
        if (result && latch.accept(result.getText())) onCode(result.getText());
        else if (!result) latch.markAbsent();
      },
    );
    onState("active");
    return { stop: () => controls.stop() };
  } catch (e) {
    onState(cameraStateForError(e));
    return null;
  }
}
