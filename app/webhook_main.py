"""Separate public ASGI app: never expose n8n or the private generation API."""

import hashlib
import hmac
import json
import logging
import secrets
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.services.templates import Templates
from app.services.webhooks import WebhookStore

logger = logging.getLogger("reminder.webhook")
logging.basicConfig(level=logging.INFO, format="%(message)s")
MAX_BODY = 1_000_000


def create_app(settings: Settings | None = None, *, store=None) -> FastAPI:
    settings = settings or Settings()
    store = store or (
        WebhookStore(settings, Templates(settings)) if settings.database_url else None
    )

    @asynccontextmanager
    async def lifespan(app):
        if store:
            await run_in_threadpool(store.initialize)
        yield

    api = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @api.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        logger.error('{"event":"webhook_database_unavailable"}')
        return JSONResponse(status_code=503, content={"detail": "Tracking unavailable"})

    @api.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.get("/health")
    def health():
        if not store:
            raise HTTPException(503, "Tracking is not configured")
        with store.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}

    @api.get("/webhooks/whatsapp", response_class=PlainTextResponse)
    def verify(request: Request):
        token = settings.whatsapp_webhook_verify_token
        if not token or not token.get_secret_value():
            raise HTTPException(503, "Webhook verification is not configured")
        params = request.query_params
        if params.get("hub.mode") != "subscribe" or not secrets.compare_digest(
            params.get("hub.verify_token", "").encode(), token.get_secret_value().encode()
        ):
            raise HTTPException(403, "Verification failed")
        challenge = params.get("hub.challenge", "")
        if not challenge.isascii() or not challenge.isdigit() or len(challenge) > 200:
            raise HTTPException(400, "Invalid challenge")
        return challenge

    @api.post("/webhooks/whatsapp")
    async def receive(request: Request):
        secret = settings.whatsapp_app_secret
        if (
            not secret
            or not secret.get_secret_value()
            or store is None
            or not settings.whatsapp_phone_number_id
            or not settings.whatsapp_business_account_id
        ):
            raise HTTPException(503, "Webhook processing is not configured")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "Webhook too large")
        expected = (
            "sha256="
            + hmac.new(secret.get_secret_value().encode(), body, hashlib.sha256).hexdigest()
        )
        if not secrets.compare_digest(
            request.headers.get("x-hub-signature-256", "").encode(), expected.encode()
        ):
            raise HTTPException(401, "Invalid signature")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError
            counts = await run_in_threadpool(store.ingest, payload)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise HTTPException(400, "Invalid notification") from None
        logger.info(json.dumps({"event": "whatsapp_webhook", **counts}))
        return {"status": "accepted"}

    return api
