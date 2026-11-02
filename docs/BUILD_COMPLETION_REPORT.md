# Build Completion Report

Date: 2026-11-02. Evidence source: `docs/TEST_RESULTS.md` and the repository sources. All data is synthetic. This report classifies every requirement of the Renewi Master Build Prompt v0.2 into the five categories the specification requires: fully implemented and tested, implemented but not fully tested, partially implemented, not implemented, and requires Renewi confirmation. It makes no legal, DPIA or GDPR compliance claim.

## Summary of verified results

The integration run passed 39 backend tests against PostgreSQL, a migration upgrade, downgrade and upgrade cycle, 39 of 39 live API smoke checks and 20 of 20 scripted scan scenarios. After a frontend-only repair pass the browser suite passed 24 tests with 1 skipped, Vitest passed 15 tests, the typecheck was clean and the production build succeeded. Browser evidence is headless Chromium on the production preview with a virtual camera, not a physical tablet. The backend suite and live scripts were not re-run after the repair pass. Details, conditions and timings are in `docs/TEST_RESULTS.md`.

## Category definitions

Fully implemented and tested means code exists and automated tests (backend, scripts or browser with a virtual camera) exercise the acceptance behaviour, with any remaining manual or physical checks named. Implemented but not fully tested means code exists but part of the acceptance behaviour depends on a check that was not run. Partially implemented means part of the specified behaviour is absent or deviates. Not implemented means no code path exists. Requires Renewi confirmation marks a decision that belongs to Renewi and currently has a configurable default.

## Requirement status

| Requirement | Priority | Status | Evidence and caveats |
| --- | --- | --- | --- |
| FR-01 Automatic unique QR | Must | Fully implemented and tested | Atomic creation, 25-employee uniqueness and failure-atomicity tests; PNG decoded independently by zxing-cpp and equal to the stored payload; no personal data in the 43-character payload |
| FR-01a Permanent QR | Must | Fully implemented and tested | Reprint and download never change the credential (Demonstration A, backend tests); block, unblock, revoke and re-issue with audit and preserved history; revoked tokens never reassigned |
| FR-01b QR printing and delivery | Must | Implemented but not fully tested | PNG, A6 PDF badge and print area work in tests; paper print, phone display, `pdftoppm` badge decode and LibreOffice conversion Not Run |
| FR-02 Tablet scanner | Must | Implemented but not fully tested | Kiosk, camera states, latch and connectivity probe tested with a virtual camera; physical camera, fullscreen, wake lock and sub-second decoding on a tablet Not Run |
| FR-03 Validation | Must | Fully implemented and tested | Server checks credential, state, employee, active flag and site; rejections create no event and disclose no identity; scan log; safe log line (backend tests, scenarios S05 to S09, S17) |
| FR-04 Automatic IN/OUT | Must | Fully implemented and tested | Backend decision under a row lock; concurrent, cross-device and rejected-then-retried tests; scenario S20. Site-level interpretation needs Renewi confirmation |
| FR-05 Event recording | Must | Fully implemented and tested | Events store employee, site, gate, device, direction, original and received times, capture mode and client UUID; rejected, duplicate, conflict and failed states live in `scan_requests` and the tablet queue. Deliberate deviation: no `sync_status` or `event_status` column on events (see `docs/ARCHITECTURE.md`) |
| FR-06 Scan confirmation | Must | Implemented but not fully tested | Green IN and OUT with name, direction, site-local time and OUT duration, translated red rejections, already-processed message and auto-return tested by component and browser specs with a virtual camera; physical-tablet display and over-network timing Not Run |
| FR-07 Duplicate protection | Must | Fully implemented and tested | Per-site window enforced by the backend, client-UUID idempotency, tablet suppression; scenarios S04, S10, S11 and Demonstration D. Window default needs Renewi confirmation |
| FR-08 Offline capture and sync | Must | Implemented but not fully tested | Ordered lossless sync, stop-at-first-failure, bounds and recovery tested (backend, scenarios S12 to S16, browser offline reload, restart with a persistent profile and lost response); physical tablet restart and multi-tablet behaviour Not Run. Single-tablet assumption needs Renewi confirmation |
| FR-09 Supervisor dashboard | Must | Implemented but not fully tested | Counts, on-site list, recent activity, exceptions, filters, recorded-status label, five-second polling and printable list tested; appearance latency measured once (about 5.1 s) in a headless virtual-camera run, under the specification's ten seconds |
| FR-10 Hours and missing OUT | Must | Fully implemented and tested | Overnight (S18), multiple sessions, cut-off (S19), late-OUT flag, attendance-duration wording; cut-off and overnight attribution need Renewi confirmation |
| FR-11 Corrections | Must | Fully implemented and tested | Mandatory reason, actor, time, original preserved, global audit, site-zone input with daylight-saving errors (backend tests and Demonstration F) |
| FR-12 CSV export | Should | Implemented but not fully tested | Daily, weekly, delimiter, one row per session and value equality checked; opening in Excel with a Dutch locale Not Run |
| FR-13 Administration | Should | Implemented but not fully tested | Employee, credential, site, gate, device and permission administration through backend tests and browser specs; site and gate editing screens have no dedicated browser spec |
| FR-14 Dutch and English | Should | Implemented but not fully tested | Dictionary parity test, language-switch and top-bar browser specs, axe scans; translation quality not reviewed by a Dutch speaker |
| FR-15 Evacuation list | Could | Implemented but not fully tested | Printable recorded on-site list with the not-a-roll-call disclaimer; paper printing Not Run |
| Authentication, RBAC, security (sections 5, 13, 15) | Must | Fully implemented and tested | Secure defaults, throttle, headers, server-side permissions, no secrets or frames in source. Not delivered by the application: TLS termination and a production deployment |
| Seed and demonstrations A to G (sections 17, 19) | Must | Implemented but not fully tested | Reset and demo seed reproduce A to G in headless Chromium with a virtual camera; the Excel step of G and every physical-device step Not Run |
| Performance measurement (sections 3.2, 16.8) | Must | Partially implemented | Loopback API timings and one browser sample recorded; QR decode time and scan-to-confirmation on a tablet not measured |

No requirement is Not implemented.

## Known limitations

The offline design assumes a single tablet per site; with several independently offline tablets the tentative direction shown while offline can be wrong until synchronisation, when the server decides and any mismatch is surfaced. Unsynchronised scans live in browser storage and are lost if site data is cleared. The tablet clock is trusted inside the 48-hour offline window. The application shell works offline only in the production build and only over `localhost` or HTTPS; the Vite dev server cannot work offline. Direction is decided at site level, not per gate. A scan after the missing-OUT cut-off closes the stale session and flags it `out_after_cutoff`. Hours are attendance duration, not paid time, and there are no break, overtime or leave rules. The scan log has no retention period implemented. Rotating `SECRET_KEY` would invalidate issued credentials. The interface is neutral and text-only because no Renewi brand assets exist. The frontend index chunk exceeds 500 kB after minification. Browser evidence is headless Chromium only. A visual check of the top bar on a real tablet remains manual.

## Not Run and unverified

Physical camera scanning and decode time, a physical tablet restart, tablet fullscreen and wake lock, lighting conditions, opening the CSV in Excel with a Dutch locale, LibreOffice conversion and `pdftoppm` badge decoding, keyboard-only and touch-target inspection, the opt-in `test_virtual_camera.spec.ts`, pilot-week targets and real-network or multi-tablet behaviour were not run. Each has an owner and action in `docs/TEST_RESULTS.md`.

## Items requiring Renewi confirmation

| ID | Item | Current default |
| --- | --- | --- |
| RC-01 | Duplicate scan window | 120 seconds per site, configurable |
| RC-02 | Missing-OUT cut-off | 06:00 the next local day per site, configurable |
| RC-03 | Overnight attribution and site-level versus gate-level IN/OUT | IN local date; site-level |
| RC-04 | One tablet per site versus several independently offline tablets | One tablet assumed |
| RC-05 | Correction approval flow and role permission policy | Authorised correction with audit; matrix per specification section 5.5, configurable |
| RC-06 | Data processing agreement, works council, DPIA, lawful basis, retention, approved EU hosting | Synthetic data only; pilot gates, not addressed by this software |
| RC-07 | Maximum age of an offline-captured scan and trust in the tablet clock | 48 hours |
| RC-08 | First scan after the cut-off while a stale session is open | Closes the stale session, flagged `out_after_cutoff` |
| RC-09 | Approved Renewi brand assets | None; neutral text-only styling |
| RC-10 | Employee data source and real site list | Synthetic data and one demonstration site |

The platform provisioning failure root cause is unresolved and is not needed for the local build.
