"""FastAPI application entry point for ``uvicorn app.main:app``."""
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, attendance, auth, credentials, employees, reports, scan, sites
from app.config import get_settings
from app.errors import install_error_handling

TAGS = [
    {"name": "health", "description": "Service liveness"},
    {"name": "auth", "description": "Staff login with HttpOnly session cookies and login throttle"},
    {"name": "employees", "description": "Employees and permanent QR credentials"},
    {"name": "credentials", "description": "QR credential lifecycle: block, unblock, revoke, reissue"},
    {"name": "sites", "description": "Sites, gates, devices, and attendance policy"},
    {"name": "devices", "description": "Scanner tablets bound to sites and gates"},
    {"name": "scanning", "description": "Tablet scans, heartbeat and offline synchronization"},
    {"name": "attendance", "description": "Dashboard, history, scan log, exceptions, and corrections"},
    {"name": "reports", "description": "Daily/weekly attendance reports and CSV export"},
    {"name": "admin", "description": "Administrator permission matrix"},
]

# Paths whose pages (Swagger UI / ReDoc) load assets from a CDN and so get no strict CSP.
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
# Strict policy for the JSON API; it serves no HTML of its own.
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


# PUBLIC_INTERFACE
def create_app() -> FastAPI:
    """Build the documented FastAPI application and attach all API routers."""
    settings = get_settings()
    app = FastAPI(
        title="Employee Time Management System API",
        description=(
            "Self-contained local backend for QR attendance, sessions, corrections, "
            "and exports. Synthetic data only. Attendance values are recorded status, "
            "not verified presence."
        ),
        version="1.1.0",
        openapi_tags=TAGS,
        openapi_url="/openapi.json",
    )
    origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handling(app)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Add defensive response headers and a processing-time header to every response."""
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # The scanner page needs the camera of its own origin; nothing else is allowed.
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        if not request.url.path.startswith(_DOC_PATHS):
            response.headers["Content-Security-Policy"] = _API_CSP
        if settings.COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.get("/api/health", tags=["health"], summary="Health check")
    def health() -> dict:
        """Return backend liveness status."""
        return {"status": "ok"}

    for router in (
        auth.router,
        employees.router,
        credentials.router,
        sites.router,
        scan.router,
        attendance.router,
        reports.router,
        admin.router,
    ):
        app.include_router(router, prefix="/api")
    return app


app = create_app()
