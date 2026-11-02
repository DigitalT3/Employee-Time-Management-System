import { expect, test } from "@playwright/test";

const DEVICE_TOKEN_KEY = "etms.deviceToken";
const virtualCameraFile = process.env.ETMS_VIRTUAL_CAMERA_FILE;
const virtualCameraDeviceToken = process.env.ETMS_VIRTUAL_CAMERA_DEVICE_TOKEN;

test("virtual camera feed can activate the kiosk camera", async ({ page }) => {
  test.skip(
    !virtualCameraFile || !virtualCameraDeviceToken,
    "Not Run: provide ETMS_VIRTUAL_CAMERA_FILE and ETMS_VIRTUAL_CAMERA_DEVICE_TOKEN.",
  );
  test.info().annotations.push({
    type: "test-condition",
    description: "Virtual Chromium camera only; this is not physical-device evidence.",
  });

  await page.addInitScript((key) => {
    localStorage.setItem(key, virtualCameraDeviceToken!);
  }, DEVICE_TOKEN_KEY);
  await page.goto("/scanner");

  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.getByText("Camera active")).toBeVisible();
  await expect(page.getByText("Checked in")).toBeVisible({ timeout: 12_000 });
});
