"""Strawberry GraphQL schema over the memory graph.

GraphQL earns its place here because the demo UI (and any other client)
queries across entity kinds in one round trip: a session *with* its
event timeline, a memory *with* its provenance sources, search hits
*with* stats. The store is injected through the app's context getter.
"""

from __future__ import annotations

from typing import Optional

import strawberry
from strawberry.fastapi import GraphQLRouter

from ..dream import DeterministicDistiller
from ..models import MemoryDoc
from ..search import search as search_docs


def _store(info: strawberry.Info) -> object:
    return info.context["store"]


@strawberry.type
class SessionType:
    id: str
    harness: str
    started_at: float
    cwd: str

    @strawberry.field
    def events(self, info: strawberry.Info) -> list["EventType"]:
        store = _store(info)
        return [EventType.from_model(e) for e in store.list_events(self.id)]

    @classmethod
    def from_model(cls, s) -> "SessionType":
        return cls(id=s.id, harness=s.harness, started_at=s.started_at, cwd=s.cwd)


@strawberry.type
class EventType:
    id: str
    session_id: str
    type: str
    seq: int
    timestamp: float
    harness: str
    source_id: Optional[str]

    @classmethod
    def from_model(cls, e) -> "EventType":
        return cls(id=e.id, session_id=e.session_id, type=e.type, seq=e.seq,
                   timestamp=e.timestamp, harness=e.harness,
                   source_id=e.source_id)


@strawberry.type
class MemoryType:
    path: str
    title: str
    body: str
    version: int
    updated_at: float
    sources: list[str]

    @classmethod
    def from_model(cls, d) -> "MemoryType":
        return cls(path=d.path, title=d.title, body=d.body,
                   version=d.version, updated_at=d.updated_at,
                   sources=list(d.sources))


@strawberry.type
class SourceType:
    id: str
    kind: str
    name: str
    uri: str

    @classmethod
    def from_model(cls, s) -> "SourceType":
        return cls(id=s.id, kind=s.kind, name=s.name, uri=s.uri)


@strawberry.type
class StatsType:
    sessions: int
    events: int
    memories: int
    sources: int
    watermark: float


@strawberry.type
class DreamResult:
    events_processed: int
    facts_written: int
    memories_created: int
    memories_updated: int
    contradictions_rewritten: int


@strawberry.type
class Query:
    @strawberry.field
    def sessions(self, info: strawberry.Info) -> list[SessionType]:
        return [SessionType.from_model(s) for s in _store(info).list_sessions()]

    @strawberry.field
    def session(self, info: strawberry.Info, id: str) -> Optional[SessionType]:
        s = _store(info).get_session(id)
        return SessionType.from_model(s) if s else None

    @strawberry.field
    def memories(self, info: strawberry.Info, prefix: Optional[str] = None) -> list[MemoryType]:
        return [MemoryType.from_model(d)
                for d in _store(info).list_memories(prefix)]

    @strawberry.field
    def memory(self, info: strawberry.Info, path: str) -> Optional[MemoryType]:
        d = _store(info).get_memory(path)
        return MemoryType.from_model(d) if d else None

    @strawberry.field
    def search(self, info: strawberry.Info, query: str, k: int = 5) -> list[MemoryType]:
        store = _store(info)
        return [MemoryType.from_model(d)
                for d in search_docs(store.list_memories(), query, k)]

    @strawberry.field
    def sources(self, info: strawberry.Info) -> list[SourceType]:
        return [SourceType.from_model(s) for s in _store(info).list_sources()]

    @strawberry.field
    def stats(self, info: strawberry.Info) -> StatsType:
        st = _store(info).stats()
        return StatsType(sessions=st["sessions"], events=st["events"],
                         memories=st["memories"], sources=st["sources"],
                         watermark=st["watermark"])


@strawberry.type
class Mutation:
    @strawberry.mutation
    def store_memory(self, info: strawberry.Info, path: str, title: str, body: str) -> MemoryType:
        store = _store(info)
        doc = store.get_memory(path) or MemoryDoc(path=path)
        doc.title = title
        doc.body = body
        return MemoryType.from_model(store.upsert_memory(doc))

    @strawberry.mutation
    def delete_memory(self, info: strawberry.Info, path: str) -> bool:
        return _store(info).delete_memory(path)

    @strawberry.mutation
    def run_dream(self, info: strawberry.Info) -> DreamResult:
        report = DeterministicDistiller().dream(_store(info))
        return DreamResult(
            events_processed=report.events_processed,
            facts_written=report.facts_written,
            memories_created=report.memories_created,
            memories_updated=report.memories_updated,
            contradictions_rewritten=report.contradictions_rewritten,
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)


def graphql_router(store) -> GraphQLRouter:
    async def get_context():
        return {"store": store}

    return GraphQLRouter(schema, context_getter=get_context)
