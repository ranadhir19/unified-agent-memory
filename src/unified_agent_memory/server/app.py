"""FastAPI access layer over the memory graph.

REST for the demo UI and scripts; GraphQL (Strawberry) mounted at
``/graphql`` for cross-entity queries. The store is Neo4j when
``NEO4J_URI`` is set, otherwise the in-memory store (with an optional
``UAM_STATE_FILE`` snapshot, and optional demo seeding via
``UAM_SEED_FIXTURES`` pointing at a fixtures directory).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..adapters import FilesAdapter, GitHubAdapter, RSSAdapter, SlackExportAdapter, ingest
from ..dream import DeterministicDistiller
from ..hooks import run_hook
from ..models import MemoryDoc
from ..search import search as search_docs
from ..store import GraphStore, open_store
from .schema import graphql_router


class MemoryIn(BaseModel):
    title: str = ""
    body: str = ""
    tags: list[str] = []


def _fixture_fetch_json(fixtures: Path):
    def fetch(url: str):
        name = url.rsplit("/", 1)[-1].split("?")[0]
        if "/pulls" in url:
            name = "pulls"
        elif "/issues" in url:
            name = "issues"
        elif "/commits" in url:
            name = "commits"
        elif "/repos/" in url:
            name = "repo"
        return json.loads((fixtures / "github_api" / f"{name}.json").read_text())

    return fetch


def seed_demo(store: GraphStore, fixtures: Path) -> dict[str, Any]:
    """Populate an empty store with the scripted cross-harness scenario
    and every adapter fixture, then run the dream phase."""
    stream = json.loads((fixtures / "e1_stream.json").read_text())
    for item in stream:
        run_hook(store, item["client"], json.dumps(item["payload"]))
    reports = {}
    gh = GitHubAdapter("octocat", "hello-world",
                       fetch_json=_fixture_fetch_json(fixtures))
    reports["github"] = ingest(store, gh).__dict__
    reports["files"] = ingest(store, FilesAdapter(fixtures / "notes")).__dict__
    rss = RSSAdapter(
        "https://example.com/feed.xml",
        fetch_text=lambda _url: (fixtures / "feed.xml").read_text(),
    )
    reports["rss"] = ingest(store, rss).__dict__
    reports["slack"] = ingest(
        store, SlackExportAdapter(fixtures / "slack_export.json")
    ).__dict__
    dream = DeterministicDistiller().dream(store)
    return {"ingest": reports, "dream": dream.__dict__}


def create_app(store: Optional[GraphStore] = None) -> FastAPI:
    store = store or open_store()
    app = FastAPI(title="unified-agent-memory", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = store

    fixtures_env = os.environ.get("UAM_SEED_FIXTURES")
    if fixtures_env and store.stats()["events"] == 0:
        seed_demo(store, Path(fixtures_env))

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        return store.stats()

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        return [s.to_dict() for s in store.list_sessions()]

    @app.get("/api/sessions/{session_id}/events")
    def session_events(session_id: str) -> list[dict[str, Any]]:
        if store.get_session(session_id) is None:
            raise HTTPException(404, "session not found")
        return [e.to_dict() for e in store.list_events(session_id)]

    @app.get("/api/events")
    def events() -> list[dict[str, Any]]:
        return [e.to_dict() for e in store.list_events()]

    @app.get("/api/memories")
    def memories(prefix: Optional[str] = None) -> list[dict[str, Any]]:
        return [d.to_dict() for d in store.list_memories(prefix)]

    @app.get("/api/memories/{path:path}")
    def memory(path: str) -> dict[str, Any]:
        doc = store.get_memory(path)
        if doc is None:
            raise HTTPException(404, "memory not found")
        return doc.to_dict()

    @app.put("/api/memories/{path:path}")
    def put_memory(path: str, body: MemoryIn) -> dict[str, Any]:
        doc = store.get_memory(path) or MemoryDoc(path=path)
        doc.title = body.title or doc.title
        doc.body = body.body
        doc.tags = body.tags or doc.tags
        return store.upsert_memory(doc).to_dict()

    @app.delete("/api/memories/{path:path}")
    def delete_memory(path: str) -> dict[str, bool]:
        if not store.delete_memory(path):
            raise HTTPException(404, "memory not found")
        return {"deleted": True}

    @app.get("/api/search")
    def search(q: str = Query(...), k: int = 5) -> list[dict[str, Any]]:
        return [d.to_dict() for d in search_docs(store.list_memories(), q, k)]

    @app.get("/api/sources")
    def sources() -> list[dict[str, Any]]:
        return [s.to_dict() for s in store.list_sources()]

    @app.post("/api/dream")
    def run_dream() -> dict[str, Any]:
        return DeterministicDistiller().dream(store).__dict__

    app.include_router(graphql_router(store), prefix="/graphql")
    return app


app = create_app()
