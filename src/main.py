"""FastAPI entrypoint."""

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Hotel Voice Agent")


class HealthResponse(BaseModel):
    """Response schema for the health check."""

    status: str


@app.get("/health")
async def health() -> HealthResponse:
    """Return service liveness."""
    return HealthResponse(status="ok")
