"""Hook runtime: the online half of the memory layer.

One entrypoint (``uam-hook``) serves every harness. A harness fires it as
a shell command with a JSON payload on stdin; the runtime:

1. normalizes the payload into a canonical ``Event``,
2. appends it to the session's timeline in the store (passive logging --
   no model calls, ever),
3. for the two injection points, prints the harness-specific JSON that
   puts pre-computed memories into context:

   - ``SessionStart`` output is prepended to the system prompt, so the
     profile memories are rendered there;
   - ``UserPromptSubmit`` output is appended to the user prompt, so
     memories relevant to what the user just typed are rendered there.

Hooks must never break the harness: any internal error is reported on
stderr and the process still exits 0 with no (or a minimal valid) output.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

from . import search as search_mod
from .models import Event, Session, new_id
from .store import GraphStore

CLIENTS = ("claude-code", "codex", "cursor")

# Cursor speaks different event names; map them onto the canonical set.
_CURSOR_EVENTS = {
    "beforeSubmitPrompt": "UserPromptSubmit",
    "beforeShellExecution": "PreToolUse",
    "beforeMCPExecution": "PreToolUse",
    "afterFileEdit": "PostToolUse",
    "afterMCPExecution": "PostToolUse",
    "stop": "Stop",
}


def canonical_event(client: str, raw_event: str) -> str:
    if client == "cursor":
        return _CURSOR_EVENTS.get(raw_event, raw_event)
    return raw_event


def normalize_payload(client: str, payload: dict[str, Any],
                      event_override: Optional[str] = None) -> Event:
    """Turn a harness-specific hook payload into a canonical Event."""
    raw_event = (
        event_override
        or payload.get("hook_event_name")
        or payload.get("event")
        or payload.get("hookEventName")
        or ""
    )
    etype = canonical_event(client, str(raw_event))
    if client == "cursor":
        session_id = str(
            payload.get("conversation_id") or payload.get("session_id") or "cursor"
        )
        cwd = ""
        roots = payload.get("workspace_roots") or []
        if roots:
            cwd = str(roots[0])
    else:
        session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
        cwd = str(payload.get("cwd") or "")
    data: dict[str, Any] = {"cwd": cwd}
    if payload.get("prompt") is not None:
        data["prompt"] = payload.get("prompt")
    if payload.get("tool_name") is not None:
        data["tool_name"] = payload.get("tool_name")
    if payload.get("tool_input") is not None:
        data["tool_input"] = payload.get("tool_input")
    if payload.get("tool_response") is not None:
        data["tool_response"] = payload.get("tool_response")
    if payload.get("command") is not None:  # Cursor shell hooks
        data["tool_name"] = "Bash"
        data["tool_input"] = {"command": payload.get("command")}
    if payload.get("file_path") is not None:  # Cursor file hooks
        data.setdefault("tool_name", "Edit")
        data.setdefault("tool_input", {"file_path": payload.get("file_path")})
    ts = payload.get("timestamp")
    return Event(
        id=new_id("evt-"),
        session_id=session_id or new_id("sess-"),
        type=etype,
        timestamp=float(ts) if ts is not None else time.time(),
        harness=client,
        payload=data,
    )


def profile_context(store: GraphStore, cwd: str = "") -> str:
    """Context for SessionStart: the profile tree + this project's note."""
    docs = store.list_memories(prefix="profile/")
    if cwd:
        base = os.path.basename(cwd.rstrip("/"))
        proj = store.get_memory(f"project/{base}.md")
        if proj is not None:
            docs = docs + [proj]
    return search_mod.render_context(
        docs, "# Unified memory (profile -- written by the dream phase)"
    )


def prompt_context(store: GraphStore, prompt: str) -> str:
    """Context for UserPromptSubmit: memories relevant to this prompt."""
    hits = search_mod.search(store.list_memories(), prompt, k=3)
    # profile docs already ride in at SessionStart; avoid repeating them
    hits = [d for d in hits if not d.path.startswith("profile/")]
    return search_mod.render_context(hits, "# Unified memory (relevant notes)")


def format_output(client: str, event_type: str, context: str) -> Optional[dict]:
    """Render injection output in each harness's stdout contract."""
    if client == "cursor":
        # Cursor's beforeSubmitPrompt contract cannot append context to
        # the prompt; it can only allow/block -- and it expects an
        # explicit answer, so always emit one. Logging still happened.
        # Cursor receives memory via MCP tools and a generated rules
        # snapshot (`uam-export-cursor-rules`). See README.
        if event_type == "UserPromptSubmit":
            return {"continue": True}
        return None
    if not context:
        return None
    if client in ("claude-code", "codex"):
        return {
            "hookSpecificOutput": {
                "hookEventName": event_type,
                "additionalContext": context,
            }
        }
    return None


def run_hook(store: GraphStore, client: str, raw: str,
             event_override: Optional[str] = None) -> Optional[dict]:
    """Process one hook invocation. Returns the stdout payload, if any."""
    payload = json.loads(raw) if raw.strip() else {}
    event = normalize_payload(client, payload, event_override)
    if event.type == "SessionStart":
        store.create_session(
            Session(id=event.session_id, harness=client,
                    cwd=str(event.payload.get("cwd", "")))
        )
    store.append_event(event)
    context = ""
    if event.type == "SessionStart":
        context = profile_context(store, str(event.payload.get("cwd", "")))
    elif event.type == "UserPromptSubmit":
        context = prompt_context(store, str(event.payload.get("prompt", "")))
    return format_output(client, event.type, context)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="uam-hook")
    parser.add_argument("--client", required=True, choices=CLIENTS)
    parser.add_argument("--event", default=None,
                        help="event name override (Cursor passes it this way)")
    args = parser.parse_args(argv)

    from .store import open_store

    raw = sys.stdin.read()
    try:
        store = open_store()
        out = run_hook(store, args.client, raw, args.event)
        store.close()
    except Exception as exc:  # hooks never break the harness
        print(f"uam-hook: {exc}", file=sys.stderr)
        return 0
    if out is not None:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
