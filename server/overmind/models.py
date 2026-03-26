"""Pydantic models for Overmind events and API requests/responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


EventType = Literal["decision", "correction", "discovery", "change", "broadcast"]
Priority = Literal["normal", "urgent"]


class MemoryEvent(BaseModel):
    """A single memory event in the Overmind system."""

    id: str
    repo_id: str
    user: str
    ts: str
    type: EventType
    result: str

    # Optional fields
    prompt: str | None = None
    files: list[str] = Field(default_factory=list)
    process: list[str] = Field(default_factory=list)
    priority: Priority = "normal"
    scope: str | None = None


class PushEventInput(BaseModel):
    """Event input within a push request. repo_id and user are inherited from parent."""

    id: str
    type: EventType
    ts: str
    result: str

    repo_id: str = ""
    user: str = ""

    prompt: str | None = None
    files: list[str] = Field(default_factory=list)
    process: list[str] = Field(default_factory=list)
    priority: Priority = "normal"
    scope: str | None = None

    def to_event(self, repo_id: str, user: str) -> MemoryEvent:
        return MemoryEvent(
            repo_id=repo_id,
            user=user,
            **{k: v for k, v in self.model_dump().items() if k not in ("repo_id", "user")},
        )


class PushRequest(BaseModel):
    """Request body for POST /api/memory/push."""

    repo_id: str
    user: str
    events: list[PushEventInput]

    @model_validator(mode="after")
    def populate_event_fields(self) -> PushRequest:
        populated = []
        for evt in self.events:
            data = evt.model_dump()
            data["repo_id"] = self.repo_id
            data["user"] = self.user
            populated.append(PushEventInput(**data))
        self.events = populated
        return self


class PushResponse(BaseModel):
    """Response for POST /api/memory/push."""

    accepted: int
    duplicates: int


class PullResponse(BaseModel):
    """Response for GET /api/memory/pull."""

    events: list[MemoryEvent]
    count: int
    has_more: bool


class BroadcastRequest(BaseModel):
    """Request body for POST /api/memory/broadcast."""

    repo_id: str
    user: str
    message: str
    priority: Priority = "normal"
    scope: str | None = None
    related_files: list[str] = Field(default_factory=list)


class BroadcastResponse(BaseModel):
    """Response for POST /api/memory/broadcast."""

    id: str
    delivered: bool


class ReportResponse(BaseModel):
    """Response for GET /api/report."""

    repo_id: str
    period: str
    total_pushes: int
    total_pulls: int
    unique_users: int
    events_by_type: dict[str, int]


class GraphNode(BaseModel):
    """A node in the Overmind graph visualization."""

    id: str
    type: Literal["user", "event", "scope"]
    label: str | None = None
    event_type: EventType | None = None
    data: dict | None = None


class GraphEdge(BaseModel):
    """An edge in the Overmind graph visualization."""

    source: str
    target: str
    relation: Literal["pushed", "affects", "pulled", "consumed"]


class PolymorphismAlert(BaseModel):
    """A polymorphism detection alert."""

    scope: str
    users: list[str]
    intents: list[str]


class GraphResponse(BaseModel):
    """Response for GET /api/report/graph."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    polymorphisms: list[PolymorphismAlert]
