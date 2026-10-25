import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.models import (
    ClaimRequest,
    CustomerBatchRequest,
    TransitionRequest,
    VoiceRequest,
    WhatsAppClaimRequest,
    WhatsAppOutcomeRequest,
    WhatsAppReserveRequest,
)
from app.services.audio import (
    AudioConversionBusy,
    AudioConversionFailure,
    AudioConversionTimeout,
    AudioConversionUnavailable,
    AudioConverter,
)
from app.services.customers import prepare_customer_batch
from app.services.templates import Templates
from app.services.tracking import StateConflict, TrackingStore
from app.services.tts import TTSBusy, TTSFailure, TTSService
from app.services.whatsapp import RoutingBlocked, WhatsAppStore, prepare_whatsapp_batch

logger = logging.getLogger("reminder")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(
    settings: Settings | None = None, *, tts=None, store=None, whatsapp_store=None, converter=None
) -> FastAPI:
    settings = settings or Settings()
    templates = Templates(settings)
    # Validate configured prosody using the same constraints as HTTP input.
    VoiceRequest(
        customer_id="config",
        first_name="Config",
        bank_name="Demo",
        agent_name="Demo",
        due_date="2026-11-15",
        rate=settings.rate if settings.tts_provider == "edge" else None,
        volume=settings.volume if settings.tts_provider == "edge" else None,
    )
    tts = tts or TTSService(settings, templates)
    converter = converter or AudioConverter(settings)
    store = store or (TrackingStore(settings, templates) if settings.database_url else None)
    whatsapp_store = whatsapp_store or (
        WhatsAppStore(settings, templates) if settings.database_url else None
    )

    @asynccontextmanager
    async def lifespan(app):
        if store:
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(store.initialize)
        yield

    api = FastAPI(title="Fictional Voice Reminder MVP", version="1.0.0", lifespan=lifespan)

    @api.middleware("http")
    async def access_log(request: Request, call_next):
        request_id = str(uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            )
        )
        return response

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default error includes raw inputs; never echo customer records.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()
                ]
            },
        )

    @api.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        logger.error(json.dumps({"event": "database_unavailable"}))
        return JSONResponse(status_code=503, content={"detail": "Tracking unavailable"})

    def authorize(x_api_key: str = Header(default="")):
        if not secrets.compare_digest(
            x_api_key.encode(), settings.reminder_api_key.get_secret_value().encode()
        ):
            raise HTTPException(401, "Invalid API key")

    def tracking():
        if store is None:
            raise HTTPException(503, "Tracking is not configured")
        return store

    def whatsapp_tracking():
        if whatsapp_store is None:
            raise HTTPException(503, "WhatsApp tracking is not configured")
        return whatsapp_store

    @api.exception_handler(StateConflict)
    async def state_conflict(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": "Stale claim or invalid transition"}
        )

    @api.exception_handler(RoutingBlocked)
    async def routing_blocked(request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.get("/ready")
    def ready():
        if store:
            with store.connect() as conn:
                conn.execute("SELECT 1")
        return {"status": "ready", "tracking_enabled": store is not None}

    auth = [Depends(authorize)]

    @api.post("/api/v1/customers/prepare", dependencies=auth)
    def prepare_customers(request: CustomerBatchRequest):
        return {"customers": prepare_customer_batch(request.rows)}

    @api.post("/api/v1/whatsapp/customers/prepare", dependencies=auth)
    def prepare_whatsapp(request: CustomerBatchRequest):
        return {"customers": prepare_whatsapp_batch(request.rows)}

    @api.post("/api/v1/whatsapp/reminders/claim", dependencies=auth)
    def whatsapp_claim(request: WhatsAppClaimRequest, repository=Depends(whatsapp_tracking)):
        return repository.claim(request)

    @api.post("/api/v1/whatsapp/reminders/{reminder_id}/reserve", dependencies=auth)
    def whatsapp_reserve(
        reminder_id: str, request: WhatsAppReserveRequest, repository=Depends(whatsapp_tracking)
    ):
        return repository.reserve(reminder_id, request)

    @api.post("/api/v1/whatsapp/reminders/{reminder_id}/outcome", dependencies=auth)
    def whatsapp_outcome(
        reminder_id: str, request: WhatsAppOutcomeRequest, repository=Depends(whatsapp_tracking)
    ):
        return repository.outcome(reminder_id, request)

    @api.get("/api/v1/whatsapp/reminders", dependencies=auth)
    def whatsapp_history(
        limit: int = Query(default=100, ge=1, le=1000), repository=Depends(whatsapp_tracking)
    ):
        return repository.history(limit)

    @api.post("/api/v1/voice/preview", dependencies=auth)
    def preview(request: VoiceRequest):
        return {"script": templates.render("voice", request), "language": settings.language}

    @api.post("/api/v1/voice/generate", dependencies=auth)
    async def generate(request: VoiceRequest, audio_format: Literal["mp3", "ogg_opus"] = "mp3"):
        try:
            audio = await tts.generate(request)
            if audio_format == "ogg_opus":
                audio = await converter.to_opus(audio)
        except AudioConversionBusy:
            raise HTTPException(
                429, "Audio conversion capacity reached", headers={"Retry-After": "5"}
            ) from None
        except AudioConversionTimeout:
            raise HTTPException(504, "Audio conversion deadline exceeded") from None
        except AudioConversionUnavailable:
            raise HTTPException(503, "Audio conversion unavailable") from None
        except AudioConversionFailure:
            raise HTTPException(502, "Audio conversion failed") from None
        except ValueError:
            raise HTTPException(422, "Voice or speech settings are not supported") from None
        except TTSBusy:
            raise HTTPException(429, "TTS capacity reached", headers={"Retry-After": "5"}) from None
        except TimeoutError:
            raise HTTPException(504, "TTS deadline exceeded") from None
        except TTSFailure:
            raise HTTPException(502, "Speech provider failed") from None
        is_opus = audio_format == "ogg_opus"
        filename = "payment_reminder.ogg" if is_opus else "payment_reminder.mp3"
        return Response(
            audio,
            media_type="audio/ogg" if is_opus else "audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @api.post("/api/v1/reminders/claim", dependencies=auth)
    def claim(request: ClaimRequest, repository=Depends(tracking)):
        return repository.claim(request.row)

    @api.post("/api/v1/reminders/{reminder_id}/status", dependencies=auth)
    def status(reminder_id: str, request: TransitionRequest, repository=Depends(tracking)):
        try:
            return repository.transition(reminder_id, request)
        except StateConflict:
            raise HTTPException(409, "Stale claim or invalid transition") from None

    @api.get("/api/v1/reminders", dependencies=auth)
    def history(limit: int = Query(default=100, ge=1, le=1000), repository=Depends(tracking)):
        return repository.history(limit)

    return api
