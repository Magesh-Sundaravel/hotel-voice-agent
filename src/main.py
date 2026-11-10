"""FastAPI entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from src.config import Settings
from src.db.postgres import PostgresBookingRepository, PostgresHotelRepository
from src.email.sender import GmailSender
from src.tools.send_confirmation_email import drain_background
from src.voice import llm_proxy, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database pool and the HTTP client for the life of the app."""
    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url)
    try:
        async with httpx.AsyncClient() as http:
            app.state.services = webhooks.Services(
                hotel=PostgresHotelRepository(pool),
                bookings=PostgresBookingRepository(pool),
                sender=GmailSender(
                    http,
                    address=settings.gmail_sender,
                    client_id=settings.google_client_id,
                    client_secret=settings.google_client_secret,
                    refresh_token=settings.google_refresh_token,
                ),
                settings=settings,
                http=http,
            )
            try:
                yield
            finally:
                # Queued confirmation emails need the client and pool still open.
                await drain_background(timeout_s=10.0)
    finally:
        await pool.close()


app = FastAPI(title="Hotel Voice Agent", lifespan=lifespan)
app.include_router(webhooks.router)
app.include_router(llm_proxy.router)


class HealthResponse(BaseModel):
    """Response schema for the health check."""

    status: str


@app.get("/health")
async def health() -> HealthResponse:
    """Return service liveness."""
    return HealthResponse(status="ok")
