"""Tablet scan endpoints authenticated by the X-Device-Token header."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_device
from app.models import Device
from app.schemas import ScanIn, SyncIn
from app.services.attendance import process_scan, process_sync

router = APIRouter(prefix="/attendance", tags=["scanning"])


# PUBLIC_INTERFACE
@router.post(
    "/scan",
    summary="Submit a scan",
    description=(
        "Determines IN or OUT automatically. Returns accepted, duplicate, rejected, "
        "replay, or conflict outcomes."
    ),
    responses={
        201: {"description": "Accepted scan"},
        200: {"description": "Duplicate, rejection, or exact replay"},
        409: {"description": "Conflicting idempotency key or device sequence"},
    },
)
def scan(
    body: ScanIn,
    device: Device = Depends(get_device),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Process a single tablet QR scan and return a token-safe result."""
    status, payload = process_scan(db, device, body)
    return JSONResponse(
        payload,
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


# PUBLIC_INTERFACE
@router.post(
    "/sync",
    summary="Synchronize offline queue",
    description="Processes queued scans by device sequence and reports an outcome per item.",
)
def sync(
    body: SyncIn,
    device: Device = Depends(get_device),
    db: Session = Depends(get_db),
) -> dict:
    """Process an ordered batch of offline scan captures."""
    return {"results": process_sync(db, device, body.items)}
