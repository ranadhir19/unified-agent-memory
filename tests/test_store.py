"""Store semantics: the in-memory implementation of the GraphStore protocol."""

import json

import pytest

from unified_agent_memory.models import Event, MemoryDoc, Session, Source, SourceRecord
from unified_agent_memory.store import InMemoryStore


def _ev(eid, sid, etype="UserPromptSubmit", ts=1000.0, **kw):
    return Event(id=eid, session_id=sid, type=etype, timestamp=ts, **kw)


def test_session_event_ordering_and_seq():
    store = InMemoryStore()
    store.create_session(Session(id="s1", harness="codex"))
    store.append_event(_ev("e1", "s1", "SessionStart", 1000.0))
    store.append_event(_ev("e2", "s1", ts=1001.0))
    store.append_event(_ev("e3", "s1", "Stop", 1002.0))
    events = store.list_events("s1")
    assert [e.id for e in events] == ["e1", "e2", "e3"]
    assert [e.seq for e in events] == [0, 1, 2]  # linked-list positions


def test_append_event_creates_session_implicitly():
    store = InMemoryStore()
    store.append_event(_ev("e1", "ghost"))
    assert store.get_session("ghost") is not None


def test_list_events_since_watermark_filter():
    store = InMemoryStore()
    store.append_event(_ev("e1", "s", ts=10.0))
    store.append_event(_ev("e2", "s", ts=20.0))
    assert [e.id for e in store.list_events(since=10.0)] == ["e2"]
    store.set_watermark(20.0)
    assert store.get_watermark() == 20.0


def test_memory_crud_and_version_bump():
    store = InMemoryStore()
    doc = store.upsert_memory(MemoryDoc(path="profile/role.md", title="Role", body="v1"))
    assert doc.version == 1
    doc2 = store.upsert_memory(MemoryDoc(path="profile/role.md", title="Role", body="v2"))
    assert doc2.version == 2
    assert store.get_memory("profile/role.md").body == "v2"
    assert [d.path for d in store.list_memories("profile/")] == ["profile/role.md"]
    assert store.delete_memory("profile/role.md") is True
    assert store.delete_memory("profile/role.md") is False


def test_record_dedup_and_provenance():
    store = InMemoryStore()
    store.upsert_source(Source(id="github:a/b", kind="github"))
    rec = SourceRecord(id="github:a/b:issue:1", source_id="github:a/b",
                       kind="issue", title="Issue #1: Bug", timestamp=5.0)
    assert store.add_record(rec) is True
    assert store.add_record(rec) is False  # duplicate rejected
    events = store.list_events("ingest:github:a/b")
    assert len(events) == 1
    assert events[0].type == "SourceRecord"
    assert events[0].source_id == "github:a/b"  # SOURCED_FROM provenance
    assert store.stats()["records"] == 1


def test_state_file_persistence_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    store = InMemoryStore(state_path=path)
    store.create_session(Session(id="s1", harness="cursor"))
    store.append_event(_ev("e1", "s1", ts=42.0))
    store.upsert_memory(MemoryDoc(path="a/b.md", body="hello"))
    store.set_watermark(42.0)

    reopened = InMemoryStore(state_path=path)
    assert reopened.get_session("s1").harness == "cursor"
    assert [e.id for e in reopened.list_events("s1")] == ["e1"]
    assert reopened.get_memory("a/b.md").body == "hello"
    assert reopened.get_watermark() == 42.0
    json.loads(path.read_text())  # snapshot is valid JSON


def test_memory_markdown_rendering():
    doc = MemoryDoc(path="profile/role.md", title="Role", body="# Role\n",
                    facts=[{"subject": "My role", "value": "Scientist"}])
    md = doc.to_markdown()
    assert md.startswith("---\n")
    assert "My role" in md and "# Role" in md
