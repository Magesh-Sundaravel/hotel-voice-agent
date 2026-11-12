"""Shared fixtures: each test starts with empty in-memory, per-process state."""

from collections import OrderedDict

import pytest

from src.tools import once
from src.voice import call_language


@pytest.fixture(autouse=True)
def _fresh_process_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Call languages and send-once keys live for the server's life; not a test's."""
    monkeypatch.setattr(call_language, "_known", OrderedDict())
    monkeypatch.setattr(once, "_seen", OrderedDict())
