"""
Global exception handlers for consistent API error responses.
Maps typed errors to proper HTTP status codes + structured error schema.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.errors import RetryableError, PermanentError, ValidationError

logger = logging.getLogger("brand-guardian.api")


def _error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError):
        return _error_response(400, "validation_error", str(exc))

    @app.exception_handler(PermanentError)
    async def permanent_error_handler(request: Request, exc: PermanentError):
        return _error_response(422, "permanent_error", str(exc))

    @app.exception_handler(RetryableError)
    async def retryable_error_handler(request: Request, exc: RetryableError):
        return _error_response(503, "service_unavailable", str(exc))

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return _error_response(500, "internal_error", "An internal error occurred.")
