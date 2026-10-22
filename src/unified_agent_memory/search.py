"""Deterministic lexical search over memory documents.

No embeddings, no model calls: tokenize, score by weighted term frequency
(title/path weigh more than body), tie-break by recency. This is the same
retriever the dream phase uses for turn-level injection and the API/MCP
layers expose -- so experiment E5 measures the production path.
"""

from __future__ import annotations

import re
from typing import Iterable

from .models import MemoryDoc

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-_/]*")
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "was", "were", "be", "with", "by", "at", "from", "that", "this",
    "it", "as", "we", "i", "you", "our", "my", "do", "does", "what", "how",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def _score(doc: MemoryDoc, terms: list[str]) -> float:
    if not terms:
        return 0.0
    title = tokenize(doc.title + " " + doc.path)
    body = tokenize(doc.body + " " + " ".join(doc.tags))
    score = 0.0
    for term in terms:
        score += 3.0 * title.count(term)
        score += 1.0 * body.count(term)
        # partial credit: term appears inside a longer path segment
        if any(term in seg for seg in doc.path.split("/")):
            score += 0.5
    # mild recency tie-break, bounded so it cannot dominate relevance
    score += min(doc.updated_at / 1e12, 0.5)
    return score


def search(docs: Iterable[MemoryDoc], query: str, k: int = 5) -> list[MemoryDoc]:
    terms = tokenize(query)
    scored = [(d, _score(d, terms)) for d in docs]
    hits = [d for d, s in scored if s > 0.6]
    hits.sort(key=lambda d: (-_score(d, terms), d.path))
    return hits[:k]


def render_context(docs: list[MemoryDoc], header: str) -> str:
    """Render memories as injectable context text."""
    if not docs:
        return ""
    lines = [header]
    for d in docs:
        lines.append(f"\n## {d.path} -- {d.title}\n{d.body.strip()}")
    return "\n".join(lines)
