"""Error envelope {code, message, request_id}. Request bodies (QR tokens) are never echoed."""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("etms")


class ApiError(Exception):
    """Domain error mapped to the JSON error envelope."""

    def __init__(self, status: int, code: str, message: str, headers: dict | None = None, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers
        self.extra = extra


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def _body(request: Request, code: str, message: str, **extra) -> dict:
    return {"code": code, "message": message, "request_id": _rid(request), **extra}


# PUBLIC_INTERFACE
def install_error_handling(app: FastAPI) -> None:
    """Register request-id middleware and exception handlers on the app."""

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message, **exc.extra),
                            status_code=exc.status, headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(request, f"http_{exc.status_code}", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Strip submitted input values so tokens/passwords are never reflected back.
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(_body(request, "validation_error", "Request validation failed", details=details),
                            status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error request_id=%s path=%s", _rid(request), request.url.path)
        return JSONResponse(_body(request, "internal_error", "Internal server error"), status_code=500)
