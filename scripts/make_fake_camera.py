#!/usr/bin/env python3
"""Create a deterministic Y4M virtual-camera stream containing one issued ETMS QR.

The resulting file is suitable for Chromium's
``--use-file-for-fake-video-capture`` flag. It is test data only: use a
synthetic credential, store the output outside version control, and delete it
when browser validation is complete.

Examples:
    backend/.venv/bin/python scripts/make_fake_camera.py \
        --employee-id <synthetic-employee-uuid> --output /tmp/etms-qr.y4m

    ETMS_VIRTUAL_CAMERA_FILE=/tmp/etms-qr.y4m \
    ETMS_VIRTUAL_CAMERA_DEVICE_TOKEN=<paired-device-token> \
    npm --prefix frontend run test:e2e
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import qrcode
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _issued_payload(employee_id: str) -> str:
    """Return an existing synthetic employee credential without printing it."""
    sys.path.insert(0, str(ROOT / "backend"))
    os.chdir(ROOT / "backend")

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import QrCredential
    from app.services.credentials import credential_payload, current_credential

    with SessionLocal() as db:
        employee_uuid = uuid.UUID(employee_id)
        credential = current_credential(db, employee_uuid)
        if credential is None:
            known = db.scalar(
                select(QrCredential).where(QrCredential.employee_id == employee_uuid)
            )
            if known is None:
                raise ValueError("employee has no issued QR credential")
            raise ValueError(
                "employee has no current credential; reissue one before generating a fixture"
            )
        return credential_payload(credential)


def _frame(payload: str, width: int, height: int) -> bytes:
    """Render an opaque QR payload as a centered grayscale video frame."""
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    code.add_data(payload)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white").convert("L")

    usable = min(width, height) - 40
    side = max(2, min(usable, max(image.size)))
    # Nearest-neighbour scaling keeps QR modules crisp for the real browser decoder.
    image = image.resize((side, side), Image.Resampling.NEAREST)
    canvas = Image.new("L", (width, height), color=255)
    canvas.paste(image, ((width - side) // 2, (height - side) // 2))
    return canvas.tobytes()


# PUBLIC_INTERFACE
def main() -> int:
    """Generate a Y4M file from a supplied test token or an issued employee credential."""
    parser = argparse.ArgumentParser(
        description="Generate a virtual Chromium camera fixture from a synthetic ETMS QR."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--employee-id",
        help="UUID of an employee with an issued current synthetic QR credential.",
    )
    source.add_argument(
        "--token",
        help="Synthetic test QR token. Prefer --employee-id so the token is never typed in a shell.",
    )
    parser.add_argument("--output", required=True, type=Path, help="Destination .y4m file.")
    parser.add_argument("--width", type=int, default=640, help="Even frame width (default: 640).")
    parser.add_argument("--height", type=int, default=480, help="Even frame height (default: 480).")
    parser.add_argument("--frames", type=int, default=90, help="Repeated QR frames (default: 90).")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second (default: 30).")
    args = parser.parse_args()

    if args.width < 160 or args.height < 160 or args.width % 2 or args.height % 2:
        parser.error("--width and --height must be even values of at least 160")
    if args.frames < 1 or args.fps < 1:
        parser.error("--frames and --fps must be positive")

    try:
        payload = args.token or _issued_payload(args.employee_id)
        y_plane = _frame(payload, args.width, args.height)
    except (ValueError, RuntimeError) as exc:
        print(f"Cannot create virtual-camera fixture: {exc}", file=sys.stderr)
        return 2

    # Y4M 4:2:0 uses one luma plane and two half-resolution chroma planes.
    chroma = bytes([128]) * ((args.width // 2) * (args.height // 2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as output:
        output.write(
            f"YUV4MPEG2 W{args.width} H{args.height} F{args.fps}:1 Ip A0:0 C420jpeg\n".encode()
        )
        for _ in range(args.frames):
            output.write(b"FRAME\n")
            output.write(y_plane)
            output.write(chroma)
            output.write(chroma)

    print(
        "Created virtual Chromium camera fixture "
        f"({args.width}x{args.height}, {args.frames} frames at {args.fps} fps): {args.output}"
    )
    print("Condition: virtual camera evidence only; this does not validate a physical camera or tablet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
