"""unified-agent-memory: a harness-agnostic agentic memory layer.

One memory graph (Neo4j, or an identical in-memory store) fed by:

- lifecycle **hooks** from Claude Code, Codex and Cursor (passive,
  deterministic logging + context injection), and
- **adapters** to third-party data sources (GitHub, files, RSS, Slack
  exports), normalized into the same graph with provenance,

distilled offline by a **dream phase** into durable markdown memories
that any harness can read cold at session start.

Inspired by "Unified Agentic Memory Across Harnesses Using Hooks"
(Towards Data Science) -- see README.md for attribution and for what
this repository adds.
"""

from .models import Event, MemoryDoc, Session, Source, SourceRecord
from .store import GraphStore, InMemoryStore, Neo4jStore, open_store

__version__ = "0.1.0"

__all__ = [
    "Event",
    "MemoryDoc",
    "Session",
    "Source",
    "SourceRecord",
    "GraphStore",
    "InMemoryStore",
    "Neo4jStore",
    "open_store",
    "__version__",
]
