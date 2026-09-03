"""Subscription manager for live WebSocket push to GraphQL subscribers.

Each subscriber gets an asyncio.Queue. The file watcher and ingestion pipeline
push DashboardEvent objects, which subscription resolvers consume via async iteration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator
from uuid import uuid4


class EventType(Enum):
    TASK_STATUS_CHANGED = "task_status_changed"
    AGENT_RUN_COMPLETED = "agent_run_completed"
    COST_ACCUMULATION = "cost_accumulation"
    SPEC_CHANGED = "spec_changed"
    AUDIT_COMPLETED = "audit_completed"
    PROCESS_STATUS_CHANGED = "process_status_changed"
    CONTEXT_ASSEMBLY_PROGRESS = "context_assembly_progress"
    DRAFT_GENERATION_PROGRESS = "draft_generation_progress"
    DECOMPOSITION_PROGRESS = "decomposition_progress"
    AUTHORING_SESSION_CHANGED = "authoring_session_changed"


@dataclass
class DashboardEvent:
    type: EventType
    feature: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class SubscriptionManager:
    """Fan-out events to all connected GraphQL subscription clients."""

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[DashboardEvent]] = {}

    def subscribe(self) -> tuple[str, asyncio.Queue[DashboardEvent]]:
        """Register a new subscriber. Returns (subscriber_id, queue)."""
        sub_id = uuid4().hex
        queue: asyncio.Queue[DashboardEvent] = asyncio.Queue(maxsize=256)
        self._subscribers[sub_id] = queue
        return sub_id, queue

    def unsubscribe(self, sub_id: str) -> None:
        """Remove a subscriber."""
        self._subscribers.pop(sub_id, None)

    async def publish(self, event: DashboardEvent) -> None:
        """Push an event to all subscribers. Drops if queue is full."""
        self.publish_sync(event)

    def publish_sync(self, event: DashboardEvent) -> None:
        """Push an event to all subscribers (sync-safe). Drops if queue is full."""
        dead: list[str] = []
        for sub_id, queue in self._subscribers.items():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(sub_id)
        for sub_id in dead:
            self._subscribers.pop(sub_id, None)

    async def listen(
        self, event_type: EventType, feature: str | None = None
    ) -> AsyncGenerator[DashboardEvent, None]:
        """Async generator that yields events of the given type, optionally filtered by feature."""
        sub_id, queue = self.subscribe()
        try:
            while True:
                event = await queue.get()
                if event.type != event_type:
                    continue
                if feature and event.feature and event.feature != feature:
                    continue
                yield event
        finally:
            self.unsubscribe(sub_id)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
