"""The dream phase: offline distillation of events into durable memories.

A distiller reads every event since the store watermark and merges what
it finds into memory documents. Memories are *living documents*: a fact
is stored once per subject inside a note's frontmatter, the body is
rendered from the fact set, and a later contradicting fact rewrites the
note instead of appending a second, stale claim.

Two distillers implement the ``Distiller`` protocol:

- ``DeterministicDistiller`` -- the default. Fully offline, no model
  calls: extracts explicit facts (``remember: X is Y`` lines, statements
  in source-record titles/bodies), tool-usage patterns (which binaries
  and flags a harness actually ran), and per-project session digests.
- ``LLMDistiller`` -- optional, behind the provider seam in
  ``providers.py``. Only runs when a real provider is configured.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from .models import Event, MemoryDoc
from .providers import LLMProvider
from .store import GraphStore

_FACT_LINE = re.compile(
    r"(?:^|\n)\s*(?:remember|note|fact)\s*[:\-]\s*(.+?)\s*(?:\bis\b|=)\s*(.+?)\s*(?:\n|$)",
    re.IGNORECASE,
)
_TITLE_FACT = re.compile(r"^(.{3,80}?)\s+is\s+(.{2,200})$", re.IGNORECASE)
_PATH_HINT = re.compile(r"\[\s*path\s*:\s*([a-z0-9\-_/]+\.md)\s*\]", re.IGNORECASE)
_PREFERENCE = re.compile(
    r"\bI\s+(?:prefer|always use|use)\s+(.+?)(?:\.|,|\n|$)", re.IGNORECASE
)
_KNOWN_TOOLS = {
    "git", "docker", "kubectl", "npm", "pytest", "python", "python3", "bash",
    "curl", "aws", "gcloud", "az", "terraform", "make", "cargo", "go",
}
_ROLE_WORDS = ("role", "title", "job", "position", "occupation")


@dataclass
class DreamReport:
    events_processed: int = 0
    facts_written: int = 0
    memories_created: int = 0
    memories_updated: int = 0
    contradictions_rewritten: int = 0
    watermark_before: float = 0.0
    watermark_after: float = 0.0
    paths: list[str] = field(default_factory=list)


class Distiller(Protocol):
    name: str

    def dream(self, store: GraphStore) -> DreamReport: ...


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "misc"


def _title_for(path: str) -> str:
    base = path.rsplit("/", 1)[-1].removesuffix(".md")
    return base.replace("-", " ").title()


def _path_for_fact(subject: str, event: Event, prompt: str) -> str:
    hint = _PATH_HINT.search(prompt or "")
    if hint:
        return hint.group(1)
    low = subject.lower()
    if any(w in low for w in _ROLE_WORDS):
        return "profile/role.md"
    if low.startswith("preference"):
        return "profile/preferences.md"
    for tool in _KNOWN_TOOLS:
        if re.search(rf"\b{tool}\b", low):
            return f"tools/{tool}.md"
    session_cwd = ""
    if event.session_id and not event.session_id.startswith("ingest:"):
        session_cwd = (event.payload.get("cwd") or "").rstrip("/")
    if session_cwd:
        return f"project/{_slug(session_cwd.rsplit('/', 1)[-1])}.md"
    if event.source_id:
        return f"sources/{_slug(event.source_id)}.md"
    return "profile/facts.md"


def _render_body(doc: MemoryDoc) -> str:
    lines = [f"# {doc.title}", ""]
    for fact in sorted(doc.facts, key=lambda f: f["subject"].lower()):
        lines.append(f"- **{fact['subject']}**: {fact['value']}")
    return "\n".join(lines) + "\n"


class _FactSink:
    """Accumulates fact writes against the store, tracking the report."""

    def __init__(self, store: GraphStore, report: DreamReport):
        self.store = store
        self.report = report
        self._dirty: dict[str, MemoryDoc] = {}
        self._created: set[str] = set()

    def add(self, path: str, subject: str, value: str, source: str, ts: float) -> None:
        doc = self._dirty.get(path) or self.store.get_memory(path)
        if doc is None:
            doc = MemoryDoc(path=path, title=_title_for(path))
            self._created.add(path)
        subject = subject.strip()
        value = value.strip()
        existing = next((f for f in doc.facts if f["subject"] == subject), None)
        if existing is not None:
            if existing["value"] == value:
                self._dirty[path] = doc
                return  # no-op: identical fact, no churn
            existing["value"] = value
            existing["updated_at"] = ts
            if source and source not in existing.get("sources", []):
                existing.setdefault("sources", []).append(source)
            self.report.contradictions_rewritten += 1
        else:
            doc.facts.append(
                {"subject": subject, "value": value, "sources": [source],
                 "updated_at": ts}
            )
        if source and source not in doc.sources:
            doc.sources.append(source)
        doc.updated_at = max(doc.updated_at, ts)
        doc.body = _render_body(doc)
        self._dirty[path] = doc
        self.report.facts_written += 1

    def flush(self) -> None:
        for path, doc in self._dirty.items():
            self.store.upsert_memory(doc)
            if path in self._created:
                self.report.memories_created += 1
            else:
                self.report.memories_updated += 1
            if path not in self.report.paths:
                self.report.paths.append(path)


class DeterministicDistiller:
    """Offline distiller: pattern extraction + merge/rewrite semantics."""

    name = "deterministic"

    def dream(self, store: GraphStore) -> DreamReport:
        report = DreamReport(watermark_before=store.get_watermark())
        events = store.list_events(since=report.watermark_before)
        events.sort(key=lambda e: (e.timestamp, e.session_id, e.seq))
        sink = _FactSink(store, report)
        flag_facts: dict[str, set[str]] = {}
        sessions_seen: dict[str, dict[str, Any]] = {}

        for ev in events:
            report.events_processed += 1
            payload = ev.payload or {}
            source = ev.source_id or ev.harness or ""
            if ev.type == "UserPromptSubmit":
                prompt = str(payload.get("prompt", ""))
                for m in _FACT_LINE.finditer(prompt):
                    sink.add(_path_for_fact(m.group(1), ev, prompt),
                             m.group(1), m.group(2), source, ev.timestamp)
                for m in _PREFERENCE.finditer(prompt):
                    sink.add("profile/preferences.md",
                             f"preference: {m.group(1).strip()[:40]}",
                             m.group(1).strip(), source, ev.timestamp)
                sessions_seen.setdefault(
                    ev.session_id,
                    {"harness": ev.harness, "prompts": 0, "tools": set()},
                )["prompts"] += 1
            elif ev.type in ("PreToolUse", "PostToolUse"):
                tool = str(payload.get("tool_name", ""))
                if ev.session_id in sessions_seen:
                    sessions_seen[ev.session_id]["tools"].add(tool)
                if tool.lower() in ("bash", "shell", "execute_command"):
                    cmd = str((payload.get("tool_input") or {}).get("command", ""))
                    tokens = cmd.split()
                    if tokens:
                        binary = os.path.basename(tokens[0])
                        flags = {t for t in tokens[1:] if t.startswith("-")}
                        if flags:
                            flag_facts.setdefault(binary, set()).update(flags)
            elif ev.type == "SourceRecord":
                title = str(payload.get("title", ""))
                title = re.sub(r"^(Issue|PR)\s+#\d+:\s*", "", title)
                m = None if title.startswith("#") else _TITLE_FACT.match(title)
                if m:
                    sink.add(_path_for_fact(m.group(1), ev, ""),
                             m.group(1), m.group(2), source, ev.timestamp)
                body = str(payload.get("body", ""))
                for fm in _FACT_LINE.finditer(body):
                    sink.add(_path_for_fact(fm.group(1), ev, body),
                             fm.group(1), fm.group(2), source, ev.timestamp)

        for binary, flags in sorted(flag_facts.items()):
            sink.add(f"tools/{_slug(binary)}.md", f"{binary} common flags",
                     ", ".join(sorted(flags)), "hooks", 0.0)

        for session_id, info in sessions_seen.items():
            if session_id.startswith("ingest:"):
                continue
            sess = store.get_session(session_id)
            cwd = (sess.cwd if sess else "").rstrip("/")
            if not cwd:
                continue
            path = f"project/{_slug(cwd.rsplit('/', 1)[-1])}.md"
            sink.add(path, "harnesses used",
                     info["harness"], "hooks", 0.0)
            if info["tools"]:
                sink.add(path, "tools used",
                         ", ".join(sorted(info["tools"])), "hooks", 0.0)

        sink.flush()
        if events:
            report.watermark_after = max(e.timestamp for e in events)
            store.set_watermark(report.watermark_after)
        else:
            report.watermark_after = report.watermark_before
        return report


class LLMDistiller:
    """Optional distiller backed by the provider seam.

    Sends the undigested events plus current memory paths to the provider
    and expects blocks of the form::

        === profile/role.md ===
        <markdown body>

    Parsed blocks are upserted as memory documents. Without a configured
    provider it refuses rather than silently degrading.
    """

    name = "llm"

    _BLOCK = re.compile(r"^===\s*([a-z0-9\-_/]+\.md)\s*===\s*$", re.MULTILINE)

    def __init__(self, provider: Optional[LLMProvider]):
        self.provider = provider

    def dream(self, store: GraphStore) -> DreamReport:
        if self.provider is None:
            raise RuntimeError(
                "LLMDistiller requires a provider (set OPENAI_API_KEY or "
                "ANTHROPIC_API_KEY); the deterministic distiller is the "
                "offline default"
            )
        report = DreamReport(watermark_before=store.get_watermark())
        events = store.list_events(since=report.watermark_before)
        events.sort(key=lambda e: (e.timestamp, e.session_id, e.seq))
        if not events:
            report.watermark_after = report.watermark_before
            return report
        existing = [d.path for d in store.list_memories()]
        transcript = "\n".join(
            f"[{e.type}@{e.harness}] {e.payload}" for e in events
        )
        prompt = (
            "You are the dream phase of a personal agent memory system.\n"
            f"Existing memory paths: {existing}\n"
            "Distill the events below into a small set of durable markdown "
            "memories. Merge rather than append; rewrite contradictions.\n"
            "Output format, repeated per memory:\n"
            "=== semantic/path.md ===\n<markdown body>\n\n"
            f"EVENTS:\n{transcript}"
        )
        text = self.provider.complete(prompt)
        parts = self._BLOCK.split(text)
        # split yields [prefix, path1, body1, path2, body2, ...]
        sink = _FactSink(store, report)
        it = iter(parts[1:])
        for path, body in zip(it, it):
            doc = store.get_memory(path) or MemoryDoc(
                path=path, title=_title_for(path))
            doc.body = body.strip() + "\n"
            doc.title = doc.title or _title_for(path)
            store.upsert_memory(doc)
            report.paths.append(path)
            report.memories_updated += 1
        report.events_processed = len(events)
        report.watermark_after = max(e.timestamp for e in events)
        store.set_watermark(report.watermark_after)
        return report
