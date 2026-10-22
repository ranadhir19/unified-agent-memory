"""Hook runtime: normalization, passive logging, injection contracts."""

import json

from unified_agent_memory.hooks import normalize_payload, run_hook
from unified_agent_memory.models import MemoryDoc
from unified_agent_memory.store import InMemoryStore


def _payload(event, **kw):
    base = {"session_id": "s1", "hook_event_name": event, "cwd": "/work/atlas-api"}
    base.update(kw)
    return json.dumps(base)


def test_normalize_claude_code_payload():
    ev = normalize_payload("claude-code", {
        "session_id": "abc", "hook_event_name": "PreToolUse",
        "tool_name": "Bash", "tool_input": {"command": "ls"},
    })
    assert ev.session_id == "abc" and ev.type == "PreToolUse"
    assert ev.payload["tool_name"] == "Bash"


def test_normalize_cursor_event_names():
    ev = normalize_payload("cursor", {
        "conversation_id": "conv-9", "hook_event_name": "beforeSubmitPrompt",
        "prompt": "hi", "workspace_roots": ["/work/atlas-api"],
    })
    assert ev.type == "UserPromptSubmit"
    assert ev.session_id == "conv-9"
    assert ev.payload["cwd"] == "/work/atlas-api"


def test_hook_logs_every_event_type():
    store = InMemoryStore()
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        run_hook(store, "codex", _payload(event, prompt="x", tool_name="Bash"))
    types = [e.type for e in store.list_events("s1")]
    assert types == ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]


def test_session_start_injects_profile_memory():
    store = InMemoryStore()
    store.upsert_memory(MemoryDoc(
        path="profile/role.md", title="Role",
        body="# Role\n\n- **My role**: Principal Research Scientist\n"))
    out = run_hook(store, "claude-code", _payload("SessionStart"))
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Principal Research Scientist" in out["hookSpecificOutput"]["additionalContext"]


def test_user_prompt_submit_injects_relevant_memory():
    store = InMemoryStore()
    store.upsert_memory(MemoryDoc(
        path="tools/git.md", title="Git",
        body="# Git\n\n- **git default branch**: main\n"))
    out = run_hook(store, "codex", _payload(
        "UserPromptSubmit", prompt="what is the git default branch?"))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "git default branch" in ctx


def test_no_context_no_output_for_logging_events():
    store = InMemoryStore()
    out = run_hook(store, "claude-code", _payload("PreToolUse", tool_name="Bash"))
    assert out is None


def test_cursor_prompt_hook_logs_and_allows():
    store = InMemoryStore()
    raw = json.dumps({
        "conversation_id": "c1", "hook_event_name": "beforeSubmitPrompt",
        "prompt": "hello", "workspace_roots": ["/work/atlas-api"],
    })
    out = run_hook(store, "cursor", raw)
    assert out == {"continue": True}
    assert store.list_events("c1")[0].type == "UserPromptSubmit"


def test_hook_never_raises_on_bad_json():
    store = InMemoryStore()
    out = run_hook(store, "codex", "{}")
    assert out is None  # empty payload -> a session-less event, no injection
