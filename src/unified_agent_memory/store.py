"""Graph store layer.

``GraphStore`` is the protocol every backend implements with identical
semantics:

- sessions own an ordered (linked-list) timeline of events;
- memories are markdown documents at semantic paths;
- sources are nodes; events and memories carry provenance edges
  (``SOURCED_FROM``) to them;
- a single watermark records how far the dream phase has distilled.

Two implementations ship:

- ``InMemoryStore`` -- zero-dependency, deterministic. Used by tests,
  experiments and the demo. Optionally persists to a JSON snapshot file
  (write-through) so separate hook processes share one memory.
- ``Neo4jStore`` -- the production graph from the article: ``(:Session)``
  nodes with a ``[:NEXT]`` linked list of ``(:Event)`` nodes,
  ``(:Memory)`` documents and ``(:Source)`` provenance, via the official
  ``neo4j`` driver. Selected automatically when ``NEO4J_URI`` is set.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from .models import Event, MemoryDoc, Session, Source, SourceRecord


@runtime_checkable
class GraphStore(Protocol):
    # sessions & events -------------------------------------------------
    def create_session(self, session: Session) -> Session: ...
    def get_session(self, session_id: str) -> Optional[Session]: ...
    def list_sessions(self) -> list[Session]: ...
    def append_event(self, event: Event) -> Event: ...
    def list_events(
        self, session_id: Optional[str] = None, since: Optional[float] = None
    ) -> list[Event]: ...
    def get_event(self, event_id: str) -> Optional[Event]: ...

    # memories ----------------------------------------------------------
    def upsert_memory(self, doc: MemoryDoc) -> MemoryDoc: ...
    def get_memory(self, path: str) -> Optional[MemoryDoc]: ...
    def list_memories(self, prefix: Optional[str] = None) -> list[MemoryDoc]: ...
    def delete_memory(self, path: str) -> bool: ...

    # sources & provenance ----------------------------------------------
    def upsert_source(self, source: Source) -> Source: ...
    def get_source(self, source_id: str) -> Optional[Source]: ...
    def list_sources(self) -> list[Source]: ...
    def add_record(self, record: SourceRecord) -> bool:
        """Write a record as an event in the source's ingest session.

        Returns False when the record is a duplicate (dedup key seen)."""
        ...

    # dream watermark -----------------------------------------------------
    def get_watermark(self) -> float: ...
    def set_watermark(self, ts: float) -> None: ...

    # introspection -------------------------------------------------------
    def stats(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


class InMemoryStore:
    """Deterministic in-process store with optional JSON persistence."""

    def __init__(self, state_path: Optional[str | Path] = None):
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._events: dict[str, Event] = {}
        self._session_events: dict[str, list[str]] = {}
        self._memories: dict[str, MemoryDoc] = {}
        self._sources: dict[str, Source] = {}
        self._record_keys: set[str] = set()
        self._watermark: float = 0.0
        self._state_path = Path(state_path) if state_path else None
        if self._state_path and self._state_path.exists():
            self._load()

    # -- persistence ----------------------------------------------------
    def _load(self) -> None:
        data = json.loads(self._state_path.read_text())
        for s in data.get("sessions", []):
            self._sessions[s["id"]] = Session(**s)
        for e in data.get("events", []):
            ev = Event.from_dict(e)
            self._events[ev.id] = ev
            self._session_events.setdefault(ev.session_id, []).append(ev.id)
        for m in data.get("memories", []):
            doc = MemoryDoc.from_dict(m)
            self._memories[doc.path] = doc
        for s in data.get("sources", []):
            self._sources[s["id"]] = Source(**s)
        self._record_keys = set(data.get("record_keys", []))
        self._watermark = float(data.get("watermark", 0.0))

    def _save(self) -> None:
        if not self._state_path:
            return
        data = {
            "sessions": [s.to_dict() for s in self._sessions.values()],
            "events": [e.to_dict() for e in self._events.values()],
            "memories": [m.to_dict() for m in self._memories.values()],
            "sources": [s.to_dict() for s in self._sources.values()],
            "record_keys": sorted(self._record_keys),
            "watermark": self._watermark,
        }
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self._state_path)

    # -- sessions & events ----------------------------------------------
    def create_session(self, session: Session) -> Session:
        with self._lock:
            if session.id not in self._sessions:
                self._sessions[session.id] = session
                self._session_events.setdefault(session.id, [])
                self._save()
            return self._sessions[session.id]

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.started_at)

    def append_event(self, event: Event) -> Event:
        with self._lock:
            if event.session_id not in self._sessions:
                self.create_session(
                    Session(id=event.session_id, harness=event.harness or "unknown")
                )
            ids = self._session_events.setdefault(event.session_id, [])
            event.seq = len(ids)
            ids.append(event.id)
            self._events[event.id] = event
            self._save()
            return event

    def list_events(
        self, session_id: Optional[str] = None, since: Optional[float] = None
    ) -> list[Event]:
        with self._lock:
            if session_id is not None:
                evs = [self._events[i] for i in self._session_events.get(session_id, [])]
            else:
                evs = sorted(
                    self._events.values(), key=lambda e: (e.timestamp, e.session_id, e.seq)
                )
            if since is not None:
                evs = [e for e in evs if e.timestamp > since]
            return list(evs)

    def get_event(self, event_id: str) -> Optional[Event]:
        return self._events.get(event_id)

    # -- memories ---------------------------------------------------------
    def upsert_memory(self, doc: MemoryDoc) -> MemoryDoc:
        with self._lock:
            existing = self._memories.get(doc.path)
            if existing is not None and existing.version >= doc.version:
                doc.version = existing.version + 1
            self._memories[doc.path] = doc
            self._save()
            return doc

    def get_memory(self, path: str) -> Optional[MemoryDoc]:
        return self._memories.get(path)

    def list_memories(self, prefix: Optional[str] = None) -> list[MemoryDoc]:
        docs = sorted(self._memories.values(), key=lambda d: d.path)
        if prefix:
            docs = [d for d in docs if d.path.startswith(prefix)]
        return docs

    def delete_memory(self, path: str) -> bool:
        with self._lock:
            if path in self._memories:
                del self._memories[path]
                self._save()
                return True
            return False

    # -- sources ----------------------------------------------------------
    def upsert_source(self, source: Source) -> Source:
        with self._lock:
            self._sources[source.id] = source
            self._save()
            return source

    def get_source(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    def list_sources(self) -> list[Source]:
        return sorted(self._sources.values(), key=lambda s: s.id)

    def add_record(self, record: SourceRecord) -> bool:
        with self._lock:
            key = record.dedup_key()
            if key in self._record_keys:
                return False
            self._record_keys.add(key)
            session_id = f"ingest:{record.source_id}"
            if session_id not in self._sessions:
                self.create_session(
                    Session(
                        id=session_id,
                        harness="ingest",
                        meta={"source_id": record.source_id},
                    )
                )
            self.append_event(
                Event(
                    id=f"evt-{key[:16]}",
                    session_id=session_id,
                    type="SourceRecord",
                    timestamp=record.timestamp,
                    harness="ingest",
                    source_id=record.source_id,
                    payload={
                        "record_id": record.id,
                        "kind": record.kind,
                        "title": record.title,
                        "body": record.body,
                        "url": record.url,
                        "author": record.author,
                    },
                )
            )
            self._save()
            return True

    # -- watermark ---------------------------------------------------------
    def get_watermark(self) -> float:
        return self._watermark

    def set_watermark(self, ts: float) -> None:
        with self._lock:
            self._watermark = float(ts)
            self._save()

    # -- misc ----------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        return {
            "sessions": len(self._sessions),
            "events": len(self._events),
            "memories": len(self._memories),
            "sources": len(self._sources),
            "records": len(self._record_keys),
            "watermark": self._watermark,
        }

    def close(self) -> None:
        pass


class Neo4jStore:
    """Neo4j-backed store implementing the article's graph model.

    Schema:
      (:Session {id, harness, started_at, cwd})
        -[:HAS_EVENT]-> (:Event) -[:NEXT]-> (:Event) ...   (linked list)
      (:Memory {path, title, body, frontmatter, version, updated_at})
      (:Source {id, kind, name, uri})
      (Event|Memory) -[:SOURCED_FROM]-> (Source)
      (:Meta {key:"watermark", value})
    """

    def __init__(self, uri: str, user: str = "neo4j", password: str = "neo4j"):
        from neo4j import GraphDatabase  # optional dependency

        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    # helpers ------------------------------------------------------------
    def _run(self, cypher: str, **params: Any):
        with self._driver.session() as s:
            return list(s.run(cypher, **params))

    # sessions & events ----------------------------------------------------
    def create_session(self, session: Session) -> Session:
        self._run(
            "MERGE (s:Session {id:$id}) "
            "SET s.harness=$harness, s.started_at=$started_at, s.cwd=$cwd",
            id=session.id, harness=session.harness,
            started_at=session.started_at, cwd=session.cwd,
        )
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        rows = self._run(
            "MATCH (s:Session {id:$id}) RETURN s", id=session_id
        )
        if not rows:
            return None
        n = rows[0]["s"]
        return Session(id=n["id"], harness=n["harness"],
                       started_at=n["started_at"], cwd=n.get("cwd", ""))

    def list_sessions(self) -> list[Session]:
        rows = self._run("MATCH (s:Session) RETURN s ORDER BY s.started_at")
        return [
            Session(id=r["s"]["id"], harness=r["s"]["harness"],
                    started_at=r["s"]["started_at"], cwd=r["s"].get("cwd", ""))
            for r in rows
        ]

    def append_event(self, event: Event) -> Event:
        if not self.get_session(event.session_id):
            self.create_session(Session(id=event.session_id,
                                        harness=event.harness or "unknown"))
        rows = self._run(
            "MATCH (s:Session {id:$sid}) "
            "OPTIONAL MATCH (s)-[:HAS_EVENT]->(first:Event) "
            "WHERE NOT (first)<-[:NEXT]-() "
            "WITH s, first "
            "OPTIONAL MATCH (tail:Event) WHERE (s)-[:HAS_EVENT]->(tail) "
            "AND NOT (tail)-[:NEXT]->() "
            "WITH s, tail, count(tail) AS n "
            "CREATE (e:Event {id:$id, type:$type, seq:n, timestamp:$ts, "
            "harness:$harness, payload:$payload, source_id:$src}) "
            "MERGE (s)-[:HAS_EVENT]->(e) "
            "FOREACH (_ IN CASE WHEN tail IS NULL THEN [] ELSE [1] END | "
            "  CREATE (tail)-[:NEXT]->(e)) "
            "RETURN e.seq AS seq",
            sid=event.session_id, id=event.id, type=event.type,
            ts=event.timestamp, harness=event.harness,
            payload=json.dumps(event.payload), src=event.source_id,
        )
        if rows:
            event.seq = rows[0]["seq"] or 0
        if event.source_id:
            self._run(
                "MATCH (e:Event {id:$eid}), (src:Source {id:$src}) "
                "MERGE (e)-[:SOURCED_FROM]->(src)",
                eid=event.id, src=event.source_id,
            )
        return event

    def list_events(
        self, session_id: Optional[str] = None, since: Optional[float] = None
    ) -> list[Event]:
        if session_id is not None:
            rows = self._run(
                "MATCH (s:Session {id:$sid})-[:HAS_EVENT]->(e:Event) "
                "RETURN e ORDER BY e.seq", sid=session_id)
        else:
            rows = self._run("MATCH (e:Event) RETURN e ORDER BY e.timestamp, e.seq")
        out = []
        for r in rows:
            n = r["e"]
            ev = Event(
                id=n["id"], session_id=session_id or "",
                type=n["type"], seq=n.get("seq", 0), timestamp=n["timestamp"],
                harness=n.get("harness", ""),
                payload=json.loads(n.get("payload") or "{}"),
                source_id=n.get("source_id"),
            )
            if session_id is None:
                owner = self._run(
                    "MATCH (s:Session)-[:HAS_EVENT]->(e:Event {id:$id}) "
                    "RETURN s.id AS sid", id=ev.id)
                ev.session_id = owner[0]["sid"] if owner else ""
            if since is None or ev.timestamp > since:
                out.append(ev)
        return out

    def get_event(self, event_id: str) -> Optional[Event]:
        rows = self._run("MATCH (e:Event {id:$id}) RETURN e", id=event_id)
        if not rows:
            return None
        evs = self.list_events()
        for ev in evs:
            if ev.id == event_id:
                return ev
        return None

    # memories ---------------------------------------------------------------
    def upsert_memory(self, doc: MemoryDoc) -> MemoryDoc:
        existing = self.get_memory(doc.path)
        if existing is not None and existing.version >= doc.version:
            doc.version = existing.version + 1
        self._run(
            "MERGE (m:Memory {path:$path}) SET m.title=$title, m.body=$body, "
            "m.frontmatter=$fm, m.version=$version, m.updated_at=$updated_at",
            path=doc.path, title=doc.title, body=doc.body,
            fm=json.dumps(doc.frontmatter()), version=doc.version,
            updated_at=doc.updated_at,
        )
        for src in doc.sources:
            self._run(
                "MATCH (m:Memory {path:$path}), (s:Source {id:$src}) "
                "MERGE (m)-[:SOURCED_FROM]->(s)",
                path=doc.path, src=src,
            )
        return doc

    def get_memory(self, path: str) -> Optional[MemoryDoc]:
        rows = self._run("MATCH (m:Memory {path:$path}) RETURN m", path=path)
        if not rows:
            return None
        n = rows[0]["m"]
        fm = json.loads(n.get("frontmatter") or "{}")
        return MemoryDoc(
            path=n["path"], title=n.get("title", ""), body=n.get("body", ""),
            facts=fm.get("facts", []), tags=fm.get("tags", []),
            sources=fm.get("sources", []), version=n.get("version", 1),
            updated_at=n.get("updated_at", 0.0),
        )

    def list_memories(self, prefix: Optional[str] = None) -> list[MemoryDoc]:
        rows = self._run("MATCH (m:Memory) RETURN m.path AS path ORDER BY m.path")
        return [d for d in (self.get_memory(r["path"]) for r in rows)
                if d and (prefix is None or d.path.startswith(prefix))]

    def delete_memory(self, path: str) -> bool:
        existed = self.get_memory(path) is not None
        self._run("MATCH (m:Memory {path:$path}) DETACH DELETE m", path=path)
        return existed

    # sources ------------------------------------------------------------------
    def upsert_source(self, source: Source) -> Source:
        self._run(
            "MERGE (s:Source {id:$id}) SET s.kind=$kind, s.name=$name, s.uri=$uri",
            id=source.id, kind=source.kind, name=source.name, uri=source.uri,
        )
        return source

    def get_source(self, source_id: str) -> Optional[Source]:
        rows = self._run("MATCH (s:Source {id:$id}) RETURN s", id=source_id)
        if not rows:
            return None
        n = rows[0]["s"]
        return Source(id=n["id"], kind=n["kind"], name=n.get("name", ""),
                      uri=n.get("uri", ""))

    def list_sources(self) -> list[Source]:
        rows = self._run("MATCH (s:Source) RETURN s ORDER BY s.id")
        return [Source(id=r["s"]["id"], kind=r["s"]["kind"],
                       name=r["s"].get("name", ""), uri=r["s"].get("uri", ""))
                for r in rows]

    def add_record(self, record: SourceRecord) -> bool:
        key = record.dedup_key()
        rows = self._run(
            "MATCH (e:Event {id:$id}) RETURN count(e) AS n",
            id=f"evt-{key[:16]}")
        if rows and rows[0]["n"]:
            return False
        session_id = f"ingest:{record.source_id}"
        if not self.get_session(session_id):
            self.create_session(Session(id=session_id, harness="ingest"))
        self.append_event(Event(
            id=f"evt-{key[:16]}", session_id=session_id, type="SourceRecord",
            timestamp=record.timestamp, harness="ingest",
            source_id=record.source_id,
            payload={"record_id": record.id, "kind": record.kind,
                     "title": record.title, "body": record.body,
                     "url": record.url, "author": record.author},
        ))
        return True

    # watermark ------------------------------------------------------------------
    def get_watermark(self) -> float:
        rows = self._run(
            "MATCH (m:Meta {key:'watermark'}) RETURN m.value AS v")
        return float(rows[0]["v"]) if rows else 0.0

    def set_watermark(self, ts: float) -> None:
        self._run(
            "MERGE (m:Meta {key:'watermark'}) SET m.value=$v", v=float(ts))

    def stats(self) -> dict[str, Any]:
        def count(label: str) -> int:
            rows = self._run(f"MATCH (n:{label}) RETURN count(n) AS n")
            return int(rows[0]["n"]) if rows else 0

        return {
            "sessions": count("Session"), "events": count("Event"),
            "memories": count("Memory"), "sources": count("Source"),
            "records": count("Event"), "watermark": self.get_watermark(),
        }

    def close(self) -> None:
        self._driver.close()


def open_store(state_path: Optional[str | Path] = None) -> GraphStore:
    """Store factory: Neo4j when NEO4J_URI is set, else the in-memory store.

    ``UAM_STATE_FILE`` (or the explicit argument) gives the in-memory store
    a JSON snapshot so separate hook processes share one memory.
    """
    uri = os.environ.get("NEO4J_URI")
    if uri:
        return Neo4jStore(
            uri,
            user=os.environ.get("NEO4J_USER", "neo4j"),
            password=os.environ.get("NEO4J_PASSWORD", "neo4j"),
        )
    path = state_path or os.environ.get("UAM_STATE_FILE")
    return InMemoryStore(state_path=path)
