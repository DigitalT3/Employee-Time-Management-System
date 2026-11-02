# Test Results

All results below were recorded on 2026-11-02 against synthetic data. Nothing here is physical-device evidence, and no figure from the specification has been copied into a result: where a specification target exists it is stated separately and compared only with what was measured.

## Test conditions

The runs used a single Linux host (4 vCPU, kernel 6.12), Python 3.12.3, Node 18, PostgreSQL 16 on port 5433 over loopback, and headless Chromium (revision 1234 under `/ms-playwright`, Playwright 1.48.2) driving the production build served by `vite preview`. Browser scanning used a **virtual camera**: a generated video of a real issued credential, so the real ZXing decoding path ran, but no physical camera, tablet, lighting or network was involved. The runs happened in two groups, and the distinction matters:

1. The integration run (STEP-04) executed the migration cycle, the backend suite, the frontend suites, the typecheck and build, the API smoke script, the 20 scenarios, the performance script and the Playwright suite.
2. A later frontend-only repair pass fixed three product defects and re-ran the Playwright suite, the typecheck, the Vitest suite and the build. The backend suite and the live scripts (smoke, scenarios, performance) were not re-run after that pass, because no backend or script file changed.

## Executed checks

| Check | Command or method | Result | Run |
| --- | --- | --- | --- |
| Migration chain | `alembic -x url=... upgrade head`, `downgrade -1`, `upgrade head`, `downgrade base`, `upgrade head` on scratch database `etms_scratch` | All succeeded; head `0002_gap_remediation` | Integration run |
| Backend suite | `APP_ENV=test .venv/bin/python -m pytest -q` on a freshly migrated `etms_test` | 39 passed in 22.36 s | Integration run |
| Frontend unit and component tests | `npm test -- --run` | 15 passed in 4 files | Re-run after the repair |
| Type check | `npm run typecheck` | Clean | Re-run after the repair |
| Production build | `npm run build` | Clean; service worker generated (7 precache entries, about 729 KiB in the integration run); non-blocking chunk-size warning (index chunk 736 kB in that run) | Re-run after the repair |
| API smoke | `scripts/e2e_smoke.py` against the live stack | 39 of 39 checks passed | Integration run |
| 20 scenarios | `scripts/scenarios_20.py` | 20 of 20 on the rerun; the first run was 19 of 20 because of a harness defect (below) | Integration run |
| Browser suite | `CI=true PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx playwright test --reporter=list` | 24 passed, 1 skipped | Re-run after the repair |
| Independent QR decode | zxing-cpp on `qr.png` of three employees | All decoded to the stored payload; payload 43 characters and contains neither name nor employee number | Integration run |
| CSV structure | Demonstration G | Byte-order mark present, one row per session, `corrected` is yes for the corrected session, `site_name` equals the site | Integration run |
| Secret and frame search | Search over `backend/app`, `scripts`, `frontend/src`, `frontend/e2e`, README and docs | No password or secret literal; no `getImageData`, `toDataURL`, `toBlob`, `ImageCapture`, `takePhoto`, `grabFrame` or `MediaRecorder` in `frontend/src` | Integration run |
| Accessibility scan (automated) | axe-core (wcag2a, wcag2aa) over login, kiosk, dashboard, employees, new employee, sites, attendance, corrections, reports and permissions | No critical or serious findings after two fixes | Integration run, re-run in the final browser suite |

The 20 scenarios are S01 first scan IN; S02 OUT with duration; S03 next scan IN; S04 duplicate ignored; S05 unknown token rejected without identity; S06 blocked rejected; S07 unblocked accepted; S08 inactive employee rejected; S09 wrong site rejected; S10 exact replay; S11 reused client UUID with a different payload conflicts; S12 ordered offline batch; S13 replay of a synchronised batch; S14 reused device sequence recovers with `last_sequence`; S15 older-than-previous timestamp rejected; S16 over-age offline capture rejected; S17 revoked rejected and re-issued accepted; S18 overnight 8 hours; S19 open session past cut-off in exceptions; S20 concurrent scans produce one accepted event and one duplicate. The runner used a 60-second duplicate window, and S18 and S19 use the real clock through offline capture timestamps. These are API-level results and are not mixed with the browser evidence.

### Browser specifications

The Playwright suite (`frontend/e2e`) ran Demonstrations A, B and D, C, E, E (restart), F and G with the virtual camera, the production-preview offline reload, a lost-response-after-commit scenario (one stored event after retry), a language-switch spec (3 tests), a permission-visibility spec (6 tests), a top-bar controls regression spec (4 tests) and the axe specifications for login, kiosk and the staff pages. The opt-in `test_virtual_camera.spec.ts` was skipped because its fixture variables (`ETMS_VIRTUAL_CAMERA_FILE`, `ETMS_VIRTUAL_CAMERA_DEVICE_TOKEN`) were not supplied; a skip is not a pass and the spec is recorded as Not Run. The same virtual-camera path ran inside Demonstrations B to E. Playwright 1.48.2 `context.setOffline` does not affect service-worker requests, so outages were produced by `e2e/outage-proxy.mjs`, a proxy on port 8100 that the preview server targets.

## Measured timings

These are one-host loopback measurements and a single headless-browser sample. They are not extrapolated to physical devices.

| Measurement | Method | Result |
| --- | --- | --- |
| Scan request (client side) | `scripts/perf_check.py`, 50 sequential online scans, duplicate window 0 | Median 11.65 ms, 95th percentile 15.52 ms |
| Backend processing | `X-Process-Time-Ms` header, same 50 scans | Median 10.45 ms, 95th percentile 14.10 ms |
| Scan to dashboard read model (API polling) | Same script | Median 39.14 ms, 95th percentile 54.81 ms |
| Camera start to green IN | `frontend/test-results/browser-timings.json`, one sample | 483 ms |
| Green IN to dashboard row | One sample | 5124 ms |
| Green OUT to dashboard update | One sample | 3912 ms |
| Reconnect to queue drained | One sample | 4876 ms |

The browser dashboard values are dominated by the five-second polling interval, were measured once, ran with the duplicate window set to four seconds and a virtual camera, and are not a distribution. The specification's proposed targets (QR decode under one second, scan-to-confirmation under two seconds, dashboard update within ten seconds) are DigitalT3 proposals, not Renewi acceptance criteria. The loopback API figures and the single browser sample are consistent with those proposals under these conditions only; QR decoding time on a tablet camera and scan-to-confirmation time over a real network were not measured.

## Defects found and repaired

- Harness defect in `scripts/scenarios_20.py`: after S14 re-sequenced an item the runner did not advance its own device sequence, so S15 reused a sequence. The backend was correct; the runner now adopts the repaired sequence.
- Accessibility defects: the Corrections date input had no accessible name and `.muted` text failed contrast; fixed with an `aria-label` and a darker colour in `frontend/src/styles.css`.
- Product defects found by browser specs and fixed in the repair pass: the saved language was not applied to `<html lang>` on reload, the no-access message was English-only, and the language select and log-out button in the top bar rendered white on white (contrast 1:1). Reproduced first by `test_topbar_controls.spec.ts` (4 of 4 failed), fixed in `frontend/src/styles.css`, `frontend/src/i18n/index.tsx` and `frontend/src/App.tsx`, then 4 of 4 passed. These are no longer open limitations. A visual check on a real tablet remains manual.
- Harness limitation: Demonstration E needed the outage proxy (see above); not a product defect.
- Verification-environment defects: a stale pre-change backend process on port 8000 was replaced by current code, and the unused repository-local `.localdb/` cluster was moved out of the repository (the active cluster is `~/.etms-localdb`).

## Not Run

| Item | Reason | Owner and action |
| --- | --- | --- |
| Physical tablet camera scanning, QR decode time, lighting conditions | No physical device | Renewi pilot tester with the tablet, following `docs/DEMONSTRATION.md` |
| Physical tablet or browser restart with pending scans | No physical device (a persistent Chromium profile relaunch passed) | Renewi pilot tester |
| Tablet fullscreen and wake-lock behaviour | No physical device | Renewi pilot tester |
| CSV opened in Excel with a Dutch locale (delimiter and characters) | Excel unavailable | Renewi tester opens the exported CSV |
| LibreOffice (`soffice`) conversion and `pdftoppm` decode of the A6 badge PDF | Tools absent; installation not attempted | Environment owner installs LibreOffice and poppler-utils, then decodes the badge |
| Keyboard-only walk-through and touch-target size inspection | Manual observation | Reviewer with a tablet and keyboard |
| Opt-in `test_virtual_camera.spec.ts` | Fixture variables not supplied | Any agent: export the two variables (see `scripts/make_fake_camera.py`) and run the spec |
| Pilot-week targets (95 percent of shifts with IN and OUT; hours compared with the current method) | No pilot | Renewi pilot owner |
| Real-network, multi-tablet and load behaviour | Single host, one virtual tablet | Renewi and DigitalT3 pilot team |
| Renewi approvals and the decisions RC-01 to RC-10 | External | Renewi (see `docs/BUILD_COMPLETION_REPORT.md`) |

## Reproduction notes

Before the backend suite, migrate the test database (`bash scripts/db_reset_test.sh` only recreates it empty, and the tests error at setup otherwise). The browser suite needs the backend on port 8000 against a seeded `etms_dev` and `backend/.env` containing the seed passwords; it changes site settings and adds data, so run `bash scripts/reset_demo.sh` afterwards. Services started for a run should be terminated afterwards. The development database was reset after the final run; the device token is printed once by the seed and was not recorded.
