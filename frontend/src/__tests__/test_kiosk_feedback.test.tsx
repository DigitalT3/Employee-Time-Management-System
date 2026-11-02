import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScanResult } from "../api/types";
import { ResultPanel } from "../components/common";
import { I18nProvider } from "../i18n";
import { feedbackFromResult, HOLD_MS, useFeedback } from "../scanner/feedback";

function FeedbackProbe() {
  const { feedback, show } = useFeedback();
  return (
    <>
      <button
        onClick={() => show({ kind: "confirmed", direction: "IN", name: "Ada Lovelace" })}
      >
        Show feedback
      </button>
      <output>{feedback?.kind ?? "ready"}</output>
    </>
  );
}

describe("kiosk feedback", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("does not disclose an identity in a rejected result panel", () => {
    const { container } = render(
      <I18nProvider>
        <ResultPanel
          timezone="Europe/Amsterdam"
          feedback={{
            kind: "rejected",
            reason: "unknown_credential",
            name: "Ada Lovelace",
          }}
        />
      </I18nProvider>,
    );

    const panel = container.querySelector(".result.bad");
    expect(panel).not.toBeNull();
    expect(panel?.textContent).toContain("Unknown QR code");
    expect(panel?.textContent).not.toContain("Ada Lovelace");
  });

  it("shows accepted OUT feedback with the employee name and duration", () => {
    const { container } = render(
      <I18nProvider>
        <ResultPanel
          timezone="Europe/Amsterdam"
          feedback={{
            kind: "confirmed",
            direction: "OUT",
            name: "Ada Lovelace",
            time: "09:00",
            durationMinutes: 90,
          }}
        />
      </I18nProvider>,
    );

    const panel = container.querySelector(".result.in");
    expect(panel).not.toBeNull();
    expect(panel?.textContent).toContain("Checked OUT");
    expect(panel?.textContent).toContain("Ada Lovelace");
    expect(panel?.textContent).toContain("Attendance duration: 1:30");
  });

  it("maps rejected API outcomes to anonymous kiosk feedback", () => {
    const result: ScanResult = {
      client_uuid: "request-1",
      device_sequence: 1,
      outcome: "rejected",
      reason: "blocked",
      employee: { name: "Ada Lovelace" },
    };

    expect(feedbackFromResult(result, "Europe/Amsterdam", "en")).toEqual({
      kind: "rejected",
      reason: "blocked",
      uuid: "request-1",
    });
  });

  it("returns to ready after the configured confirmation hold period", () => {
    vi.useFakeTimers();
    render(<FeedbackProbe />);

    fireEvent.click(screen.getByRole("button", { name: "Show feedback" }));
    expect(screen.getByText("confirmed")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(HOLD_MS.confirmed - 1);
    });
    expect(screen.getByText("confirmed")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByText("ready")).toBeTruthy();
  });
});
