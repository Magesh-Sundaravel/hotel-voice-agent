"""Tests for the /health endpoint."""

import httpx
import pytest

from src.main import app


@pytest.mark.asyncio
async def test_health() -> None:
    """GET /health returns status ok."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
