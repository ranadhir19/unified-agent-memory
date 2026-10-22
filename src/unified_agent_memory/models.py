"""Core data model for the unified agent memory layer.

Everything that flows through the system is one of these shapes:

- ``Session``  -- one agent run in one harness (Claude Code, Codex, Cursor).
- ``Event``    -- one lifecycle hook invocation (or one ingested source
  record), appended to a session's ordered timeline.
- ``MemoryDoc``-- one durable memory: a markdown note at a semantic path
  (``profile/role.md``) with YAML frontmatter, distilled by the dream phase.
- ``Source``   -- a third-party data source feeding the layer via an adapter
  (a GitHub repo, a notes directory, an RSS feed, a Slack export).
- ``SourceRecord`` -- one normalized item from a source, written into the
  graph as an event with provenance.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Lifecycle event types fired by harness hooks (article-faithful set).
HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
)

# Event type used for adapter-ingested records.
SOURCE_EVENT = "SourceRecord"


def _now() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


@dataclass
class Session:
    id: str
    harness: str  # "claude-code" | "codex" | "cursor" | "ingest:<source>" ...
    started_at: float = field(default_factory=_now)
    cwd: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Event:
    id: str
    session_id: str
    type: str  # one of HOOK_EVENTS, or SOURCE_EVENT
    seq: int = 0  # per-session order (linked-list position)
    timestamp: float = field(default_factory=_now)
    harness: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source_id: Optional[str] = None  # provenance: SOURCED_FROM target

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        return cls(**d)


@dataclass
class MemoryDoc:
    """A durable memory note: markdown body + structured frontmatter.

    ``facts`` lives in frontmatter as a list of {subject, value, source,
    updated_at} entries so the deterministic distiller can merge and
    rewrite contradictions mechanically: the body is rendered from the
    fact set, so a path is a living document, never an append-only log.
    """

    path: str  # semantic path, e.g. "profile/role.md"
    title: str = ""
    body: str = ""
    facts: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # provenance ids
    version: int = 1
    updated_at: float = field(default_factory=_now)

    def frontmatter(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "tags": self.tags,
            "sources": self.sources,
            "version": self.version,
            "updated_at": self.updated_at,
            "facts": self.facts,
        }

    def to_markdown(self) -> str:
        import yaml

        fm = yaml.safe_dump(self.frontmatter(), sort_keys=False)
        return f"---\n{fm}---\n\n{self.body}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryDoc":
        return cls(**d)


@dataclass
class Source:
    id: str  # e.g. "github:octocat/hello-world"
    kind: str  # "github" | "files" | "rss" | "slack"
    name: str = ""
    uri: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRecord:
    """One normalized item from a third-party source."""

    id: str  # stable dedup key, e.g. "github:octocat/hello:issue:42"
    source_id: str
    kind: str  # "issue" | "pull_request" | "commit" | "note" | "feed_item" | "message" | "repo"
    title: str = ""
    body: str = ""
    url: str = ""
    timestamp: float = field(default_factory=_now)
    author: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def dedup_key(self) -> str:
        return hashlib.sha256(self.id.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
