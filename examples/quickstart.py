#!/usr/bin/env python3
"""Two-minute tour: hooks in, dream, recall in a different harness.

Runs fully offline against the in-memory store:
    python3 examples/quickstart.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unified_agent_memory.dream import DeterministicDistiller
from unified_agent_memory.hooks import run_hook
from unified_agent_memory.store import InMemoryStore


def fire(store, client, payload):
    return run_hook(store, client, json.dumps(payload))


def main() -> int:
    store = InMemoryStore()

    # A Claude Code session states two facts.
    fire(store, "claude-code", {
        "session_id": "s1", "hook_event_name": "SessionStart",
        "cwd": "/work/atlas-api"})
    fire(store, "claude-code", {
        "session_id": "s1", "hook_event_name": "UserPromptSubmit",
        "cwd": "/work/atlas-api",
        "prompt": "remember: My role is Principal Research Scientist"})
    fire(store, "claude-code", {
        "session_id": "s1", "hook_event_name": "UserPromptSubmit",
        "cwd": "/work/atlas-api",
        "prompt": "remember: The deploy target is AWS"})

    # Offline dream phase distills them into durable memories.
    report = DeterministicDistiller().dream(store)
    print(f"dream: {report.facts_written} facts -> {report.paths}")

    # A brand-new Codex session -- a different harness -- starts, and the
    # profile memory is injected before the model sees anything.
    out = fire(store, "codex", {
        "session_id": "s2", "hook_event_name": "SessionStart",
        "cwd": "/work/atlas-api"})
    print("\nInjected into the Codex session's system prompt:")
    print(out["hookSpecificOutput"]["additionalContext"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
