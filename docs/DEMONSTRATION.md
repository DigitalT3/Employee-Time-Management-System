# Demonstration Instructions

This page describes how to run the required Demonstrations A to G (specification section 19) on the synthetic demo data without manual database intervention. An automated headless-Chromium rehearsal with a virtual camera exists for A to G in `frontend/e2e/test_demonstrations.spec.ts`; the manual steps below with a physical tablet camera and Excel are Not Run and are for a Renewi or DigitalT3 tester to perform.

## Preparation

Run the commands from the repository root and always through `bash`. The first time only, run `bash scripts/setup.sh`. Then reset the demonstration data and start the services.

```bash
bash scripts/reset_demo.sh          # drops and recreates etms_dev, migrates, seeds the demo profile; prints the Tablet-1 device token once
bash scripts/run_backend.sh         # keep running in the background (port 8000)
cd frontend && npm run build && npm run preview     # production build on port 4173, required for the offline demonstration
```

Copy the device token printed by the reset command for the tablet pairing step; it is shown only once. For Demonstrations A to D, F and G the development server also works (`bash scripts/run_frontend.sh`, port 3000), but Demonstration E needs the production preview because only the production build has the offline service worker. Log in with the usernames `admin`, `supervisor` and `hr`; their generated passwords are the `SEED_*_PASSWORD` values in `backend/.env` (open that file locally and do not copy the values into documents).

The camera works from `http://localhost` only. A tablet that opens the machine by LAN address needs HTTPS, so serve the build with `npm run preview:https` and accept the self-signed certificate. To pair the tablet, open `/scanner/setup`, enter the device token and confirm. Alternatively, an administrator pairs a new tablet on the Sites page with the "Pair this tablet" action.

The demo data contains EMP-002 Jamie Taylor, EMP-003 Sam Wilson (a corrected session), EMP-004 Taylor Brown (an open session with no OUT, a missing-OUT exception) and the inactive EMP-005 Jordan Lee (one rejected scan). EMP-001 Alex Morgan is deliberately not registered.

## Demonstration A: register and issue the QR

Log in as `admin`, open Employees and add the employee with number `EMP-001`, first name Alex and last name Morgan, assigned to Amsterdam Depot. Save. The employee page shows the automatically generated QR code with download PNG, download PDF and print actions. Download or print the QR. Open the employee from the list again and confirm that the QR shown is the same image (its permanent opaque credential is unchanged by reprinting or downloading). Block, unblock, revoke and re-issue controls with a credential history are on the same page.

## Demonstration B: employee checks IN

Open `/scanner` on the paired tablet. Present Alex's QR (printed, or displayed on a phone screen) to the camera. The kiosk shows a green IN confirmation with the name, direction and site-local time and returns to ready after about four seconds. Log in as `supervisor` and open the dashboard: Alex appears in the recorded on-site list, and the on-site count increased. The dashboard refreshes every five seconds and is labelled as recorded attendance status.

For an automated alternative with a virtual camera instead of a physical one, build the video with `scripts/make_fake_camera.py --employee-id <employee-uuid> --output <file.y4m>` (the employee id is in the employee page address) and export `ETMS_VIRTUAL_CAMERA_FILE` and `ETMS_VIRTUAL_CAMERA_DEVICE_TOKEN` before running the opt-in `test_virtual_camera.spec.ts`. The result is virtual-camera evidence only.

## Demonstration C: employee checks OUT

The duplicate window is 120 seconds by default. To avoid waiting two minutes, an administrator sets a shorter value (for example 10 seconds) on the Sites page under duplicate window, which is the per-site setting enforced by the backend. After the window passes, present Alex's same QR again. The kiosk shows a green OUT confirmation with the attendance duration, and the dashboard no longer lists Alex.

## Demonstration D: duplicate scan

Within the duplicate window present the same QR twice. The second presentation shows the amber already-processed message and no second event is created: the scan log (staff with scan-log permission) lists the duplicate, and the attendance history shows one session. While the code stays in front of the camera it is not submitted repeatedly; it must leave the camera view for about two seconds before it can be scanned again.

## Demonstration E: offline operation

Use the production preview. Make the backend unreachable for the tablet: on a physical tablet disconnect the network, or in a local rehearsal stop the backend process. The scanner's connectivity probe fails and the kiosk shows the offline state. Capture one or more scans; each is stored locally, shown as pending (amber) with a tentative direction or the message that the direction is decided on synchronisation, and the pending count increases. Reload the page, and restart the browser where practical: the shell still loads and the pending count is preserved. Restore the network or restart the backend (`bash scripts/run_backend.sh`). The queue drains automatically, in order, and any direction mismatch is surfaced. Check the attendance history: each scan appears once with its original time and capture mode offline. Chromium's built-in offline emulation does not cut service-worker requests in the Playwright version used, so the automated spec stops the API through `frontend/e2e/outage-proxy.mjs` instead.

## Demonstration F: supervisor correction

Log in as `supervisor`. The dashboard exceptions list shows the EMP-004 session with a missing OUT. Open the session, enter the corrected OUT time (interpreted in the site time zone), enter a reason and save. The session now shows the corrected time and the corrected indicator. The correction history (the Corrections page, or the session detail) shows the original value, the new value, the reason, the actor and the time; the original event is unchanged. An empty reason is refused.

## Demonstration G: export

Log in as a user with report export permission (`admin`, `supervisor` or `hr` by default). Open Reports, choose daily or weekly or a date range, optionally filter by employee and site, preview and export the CSV. Choose the semicolon delimiter for a Dutch-locale Excel (the page defaults to a semicolon when the interface language is Dutch). Check employee, site, IN, OUT, duration and flags, including the incomplete EMP-004 session with a blank OUT and the corrected indicator for EMP-003. Opening the file in Excel with a Dutch locale is Not Run and must be done by a Renewi tester.

## Running the automated rehearsal

With the backend running on port 8000 against a freshly reset `etms_dev`:

```bash
cd frontend
CI=true PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx playwright test --reporter=list
cd .. && bash scripts/reset_demo.sh
```

The suite builds nothing by itself except through `npm run test:e2e` (which runs the build first); it starts the outage proxy and the production preview. It changes site settings and adds data, which is why the reset command is run afterwards. Terminate the backend and any other process you started when finished.
