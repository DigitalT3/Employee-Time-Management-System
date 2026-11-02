import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import { CodeLatch } from "./camera";
import { enqueue, pendingScans, queueDb, recentScans } from "./queue";
import { backoffMs, drainQueue } from "./sync";

const ok = (c: string, seq: number, outcome = "accepted") => ({
  client_uuid: c, device_sequence: seq, outcome, direction: "IN", employee: { id: "e", employee_number: "1", name: "A B" },
});

describe("offline queue", () => {
  beforeEach(async () => { await queueDb.scans.clear(); await queueDb.meta.clear(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("allocates monotonic sequences and persists across reads", async () => {
    const a = await enqueue("t1", 5);
    const b = await enqueue("t2");
    expect([a.device_sequence, b.device_sequence]).toEqual([6, 7]);
    expect((await pendingScans()).map((r) => r.device_sequence)).toEqual([6, 7]);
  });

  it("drains a single entry via /scan and strips the token", async () => {
    await enqueue("secret");
    vi.spyOn(client.api, "scan").mockImplementation(async (_t, body) =>
      ({ status: 201, json: ok(body.client_uuid, body.device_sequence) as never }));
    const res = await drainQueue("dev");
    expect(res.resolved).toHaveLength(1);
    const [row] = await recentScans();
    expect(row.status).toBe("accepted");
    expect(row.token).toBeNull();
  });

  it("uses /sync in sequence order for a backlog", async () => {
    await enqueue("a"); await enqueue("b");
    const spy = vi.spyOn(client.api, "sync").mockImplementation(async (_t, items) =>
      ({ status: 200, json: { results: items.map((i) => ok(i.client_uuid, i.device_sequence) as never) } }));
    await drainQueue("dev");
    expect(spy.mock.calls[0][1].map((i) => i.device_sequence)).toEqual([1, 2]);
    expect(await pendingScans()).toHaveLength(0);
  });

  it("keeps entries pending on network failure and preserves capture-time mode", async () => {
    await enqueue("x");
    const spy = vi.spyOn(client.api, "scan").mockRejectedValueOnce(new TypeError("network"));
    const res = await drainQueue("dev");
    expect(res.retryLater).toBe(true);
    expect(await pendingScans()).toHaveLength(1);
    spy.mockImplementation(async (_t, body) => ({ status: 201, json: ok(body.client_uuid, body.device_sequence) as never }));
    await drainQueue("dev");
    expect(spy.mock.calls[1][1].capture_mode).toBe("online");
  });

  it("does not drop entries on an invalid device (401)", async () => {
    await enqueue("x");
    vi.spyOn(client.api, "scan").mockRejectedValue(new client.ApiError(401, "invalid_device", "bad"));
    const res = await drainQueue("dev");
    expect(res.fatal).toBeTruthy();
    expect(await pendingScans()).toHaveLength(1);
  });
});

describe("helpers", () => {
  it("latches repeated codes until they have been absent for two seconds", () => {
    const l = new CodeLatch();
    expect(l.accept("a", 0)).toBe(true);
    expect(l.accept("a", 1000)).toBe(false);
    expect(l.accept("b", 1500)).toBe(true);
    expect(l.accept("b", 5000)).toBe(false);
    l.markAbsent(5100);
    expect(l.accept("b", 7100)).toBe(true);
  });
  it("caps exponential backoff", () => {
    expect(backoffMs(1)).toBe(1000);
    expect(backoffMs(3)).toBe(4000);
    expect(backoffMs(20)).toBe(60000);
  });
});
