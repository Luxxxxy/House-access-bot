from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.schemas import StrictModel  # noqa: F401 - keeps schema import visible for OpenAPI tooling
from app.config import settings
from app.web.api import api_router
from app.web.db import SessionLocal


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.environment.lower() == "production":
        if settings.max_update_mode != "webhook":
            raise RuntimeError("Production MAX updates must use MAX_UPDATE_MODE=webhook")
        if not settings.max_bot_token or not settings.max_webhook_secret:
            raise RuntimeError("MAX_BOT_TOKEN and MAX_WEBHOOK_SECRET are required in production")
        if not settings.app_base_url.startswith("https://") or not settings.miniapp_url.startswith("https://"):
            raise RuntimeError("APP_BASE_URL and MINIAPP_URL must use HTTPS in production")
    yield


app = FastAPI(
    title="Безопасный проход API",
    description="MAX Mini App + backend для заявок посетителей ЖК",
    version="1.0.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)
origins = [value.strip() for value in settings.cors_origins.split(",") if value.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Demo-User"],
)
app.include_router(api_router)


@app.middleware("http")
async def safe_headers_and_timing(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    fields = [".".join(str(part) for part in error["loc"][1:]) for error in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": "Проверьте введённые данные", "fields": fields}},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_request: Request, exc: IntegrityError):
    logger.warning("Database uniqueness or constraint violation ({})", type(exc.orig).__name__)
    return JSONResponse(
        status_code=409,
        content={"error": {"code": "CONFLICT", "message": "Операция конфликтует с существующими данными"}},
    )


@app.get("/healthz", tags=["system"])
async def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["system"])
async def readyz():
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready"}
