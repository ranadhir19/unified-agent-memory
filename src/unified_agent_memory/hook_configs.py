"""Ready-to-install hook configurations for the three harnesses.

Each generator returns the exact JSON a user drops into the harness's
settings file so every lifecycle event shells out to
``uam-hook --client <harness>``. Event coverage differs because the
harnesses' hook surfaces differ -- the gaps are documented, not hidden:

- Claude Code and Codex expose all five canonical events.
- Cursor exposes prompt/shell/file hooks but no session-start or stop
  hook; session boundaries there are inferred from prompt events, and
  prompt-time injection is not possible in Cursor's contract (its
  ``beforeSubmitPrompt`` can only allow or block). Cursor therefore
  logs everything and reads memory back through the MCP tools and the
  generated rules snapshot.
"""

from __future__ import annotations

import json
from typing import Any

_COMMAND = "uam-hook"


def _cmd(client: str, event: str | None = None) -> str:
    base = f"{_COMMAND} --client {client}"
    return f"{base} --event {event}" if event else base


def claude_code_config() -> dict[str, Any]:
    """~/.claude/settings.json (or .claude/settings.json per project)."""
    events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
    return {
        "hooks": {
            e: [{"hooks": [{"type": "command", "command": _cmd("claude-code")}]}]
            for e in events
        }
    }


def codex_config() -> dict[str, Any]:
    """~/.codex/hooks.json -- Codex mirrors the Claude Code event names."""
    events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
    return {
        "hooks": {
            e: [{"hooks": [{"type": "command", "command": _cmd("codex")}]}]
            for e in events
        }
    }


def cursor_config() -> dict[str, Any]:
    """.cursor/hooks.json -- Cursor's own event names, passed via --event."""
    mapping = {
        "beforeSubmitPrompt": "beforeSubmitPrompt",
        "beforeShellExecution": "beforeShellExecution",
        "afterFileEdit": "afterFileEdit",
        "stop": "stop",
    }
    return {
        "version": 1,
        "hooks": {
            name: [{"command": _cmd("cursor", evt)}]
            for name, evt in mapping.items()
        },
    }


_GENERATORS = {
    "claude-code": (claude_code_config, ".claude/settings.json"),
    "codex": (codex_config, ".codex/hooks.json"),
    "cursor": (cursor_config, ".cursor/hooks.json"),
}


def generate(client: str) -> tuple[str, str]:
    """Return (target filename, JSON text) for a harness's hook config."""
    gen, fname = _GENERATORS[client]
    return fname, json.dumps(gen(), indent=2) + "\n"
