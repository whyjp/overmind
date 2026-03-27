"""Summary generation for Overmind events."""

from __future__ import annotations

from typing import Protocol

from overmind.models import MemoryEvent


class SummaryGenerator(Protocol):
    """Event summary generator. Implement this Protocol for LLM-based summary."""

    async def generate(self, event: MemoryEvent) -> str | None:
        """Generate a summary from event's process + result. None if not applicable."""
        ...


class MockSummaryGenerator:
    """Pass-through: returns result as summary when process exists."""

    async def generate(self, event: MemoryEvent) -> str | None:
        if not event.process:
            return None
        return event.result
