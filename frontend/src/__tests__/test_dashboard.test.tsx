import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "../pages/Dashboard";
import { I18nProvider } from "../i18n";

const apiMocks = vi.hoisted(() => ({
  dashboard: vi.fn(),
  sites: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api: {
    dashboard: apiMocks.dashboard,
    sites: apiMocks.sites,
  },
}));

describe("dashboard", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders recorded attendance data and retains the non-presence disclaimer", async () => {
    apiMocks.sites.mockResolvedValue([]);
    apiMocks.dashboard.mockResolvedValue({
      as_of: "2026-03-02T08:00:00+00:00",
      site_id: null,
      date: "2026-03-02",
      label: "Recorded attendance status",
      counts: { on_site: 1, off_site: 2, incomplete: 0 },
      on_site: [{
        id: "session-1",
        employee_id: "employee-1",
        employee_number: "E-1",
        employee_name: "Ada Lovelace",
        site_id: "site-1",
        site_code: "AMS",
        site_name: "Amsterdam",
        site_timezone: "Europe/Amsterdam",
        effective_in: "2026-03-02T07:00:00+00:00",
        effective_out: null,
        local_in: "2026-03-02T08:00:00+01:00",
        local_out: null,
        latest_in: "2026-03-02T07:00:00+00:00",
        latest_direction: "IN",
        shift_date: "2026-03-02",
        version: 1,
        corrected: false,
        hours: null,
        duration_minutes: null,
        missing_out: false,
        status: "open",
        flags: [],
      }],
      recent_activity: [],
      exceptions: [],
      scan_problems: [],
      device_sync: [],
    });

    render(
      <MemoryRouter>
        <I18nProvider>
          <Dashboard />
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Ada Lovelace")).toBeTruthy();
    expect(screen.getByText("Recorded attendance status based on scans. It is not verified presence.")).toBeTruthy();
    expect(screen.getByText("Amsterdam")).toBeTruthy();
    expect(apiMocks.dashboard).toHaveBeenCalled();
  });
});
