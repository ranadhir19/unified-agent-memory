"""Dream phase: extraction, merge, contradiction rewrite, watermark."""

import json

from unified_agent_memory.dream import DeterministicDistiller, LLMDistiller
from unified_agent_memory.hooks import run_hook
from unified_agent_memory.models import Event
from unified_agent_memory.store import InMemoryStore


def _prompt(store, client, sid, text, ts, cwd="/work/atlas-api"):
    raw = json.dumps({
        "session_id": sid, "hook_event_name": "UserPromptSubmit",
        "prompt": text, "cwd": cwd, "timestamp": ts,
    })
    run_hook(store, client, raw)


def test_fact_extraction_and_paths():
    store = InMemoryStore()
    _prompt(store, "claude-code", "s1", "remember: My role is Staff Engineer", 100.0)
    _prompt(store, "claude-code", "s1", "remember: The deploy target is AWS", 101.0)
    report = DeterministicDistiller().dream(store)
    role = store.get_memory("profile/role.md")
    assert role is not None and "Staff Engineer" in role.body
    project = store.get_memory("project/atlas-api.md")
    assert project is not None and "AWS" in project.body
    assert report.facts_written >= 2
    assert store.get_watermark() == 101.0


def test_contradiction_rewrites_instead_of_appending():
    store = InMemoryStore()
    _prompt(store, "codex", "s1", "remember: The deploy target is AWS", 100.0)
    _prompt(store, "codex", "s1", "remember: The deploy target is GCP", 200.0)
    report = DeterministicDistiller().dream(store)
    doc = store.get_memory("project/atlas-api.md")
    facts = [f for f in doc.facts if f["subject"] == "The deploy target"]
    assert len(facts) == 1, "contradiction must merge into one fact"
    assert facts[0]["value"] == "GCP"
    assert "GCP" in doc.body and "AWS" not in doc.body
    assert report.contradictions_rewritten == 1


def test_second_dream_run_is_incremental():
    store = InMemoryStore()
    _prompt(store, "codex", "s1", "remember: My role is Staff Engineer", 100.0)
    d = DeterministicDistiller()
    d.dream(store)
    report2 = d.dream(store)
    assert report2.events_processed == 0  # watermark consumed everything


def test_preference_extraction():
    store = InMemoryStore()
    _prompt(store, "cursor", "c1", "I prefer tabs over spaces", 100.0)
    DeterministicDistiller().dream(store)
    doc = store.get_memory("profile/preferences.md")
    assert doc is not None and "tabs over spaces" in doc.body


def test_tool_flag_harvest():
    store = InMemoryStore()
    raw = json.dumps({
        "session_id": "s1", "hook_event_name": "PostToolUse",
        "tool_name": "Bash", "tool_input": {"command": "git commit --amend --no-edit"},
        "cwd": "/work/atlas-api", "timestamp": 100.0,
    })
    run_hook(store, "claude-code", raw)
    DeterministicDistiller().dream(store)
    doc = store.get_memory("tools/git.md")
    assert doc is not None and "--amend" in doc.body


def test_source_record_facts_distilled():
    store = InMemoryStore()
    store.append_event(Event(
        id="e1", session_id="ingest:github:a/b", type="SourceRecord",
        timestamp=50.0, harness="ingest", source_id="github:a/b",
        payload={"record_id": "github:a/b:issue:1", "kind": "issue",
                 "title": "Issue #1: The freeze date is 2026-11-01",
                 "body": "", "url": "", "author": ""},
    ))
    DeterministicDistiller().dream(store)
    docs = store.list_memories(prefix="sources/")
    assert docs and "2026-11-01" in docs[0].body
    assert "github:a/b" in docs[0].sources  # provenance carried into memory


class _FakeProvider:
    name = "fake"

    def complete(self, prompt: str) -> str:
        assert "EVENTS:" in prompt
        return "=== profile/role.md ===\n# Role\n\nDistilled by fake provider.\n"


def test_llm_distiller_with_fake_provider():
    store = InMemoryStore()
    _prompt(store, "codex", "s1", "hello", 100.0)
    report = LLMDistiller(_FakeProvider()).dream(store)
    assert report.events_processed == 1
    assert store.get_memory("profile/role.md").body.find("fake provider") >= 0


def test_llm_distiller_refuses_without_provider():
    store = InMemoryStore()
    try:
        LLMDistiller(None).dream(store)
        raise AssertionError("should have refused")
    except RuntimeError as exc:
        assert "deterministic" in str(exc)
