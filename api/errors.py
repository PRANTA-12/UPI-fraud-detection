"""Centralised exception handling: consistent JSON, no internal details leaked to clients."""
import logging

import psycopg2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.model_store import ModelNotAvailable

log = logging.getLogger("api.errors")


def _body(request: Request, detail, code: str) -> dict:
    return {"detail": detail, "code": code, "request_id": getattr(request.state, "request_id", None)}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        return JSONResponse(_body(request, exc.detail, f"http_{exc.status_code}"), status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exc(request: Request, exc: RequestValidationError):
        errs = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(_body(request, errs, "validation_error"), status_code=422)

    @app.exception_handler(ModelNotAvailable)
    async def model_exc(request: Request, exc: ModelNotAvailable):
        log.error("model unavailable", extra={"error": str(exc)})
        return JSONResponse(_body(request, "Model not available", "model_unavailable"), status_code=503)

    @app.exception_handler(psycopg2.Error)
    async def db_exc(request: Request, exc: psycopg2.Error):
        log.error("database error", extra={"error": type(exc).__name__, "pgcode": getattr(exc, "pgcode", None)})
        return JSONResponse(_body(request, "Database temporarily unavailable", "database_error"), status_code=503)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(_body(request, "Internal server error", "internal_error"), status_code=500)
