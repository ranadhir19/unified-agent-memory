"""Third-party source adapters: the extension beyond the article.

The article's memory layer is fed only by harness hooks. Here the same
graph is also fed by *adapters* to third-party data sources, so a fact
that lives in a GitHub issue, a Slack thread, a note file, or an RSS
item becomes memory any harness can recall -- memory belongs to the
user, not the tool.

Adapter contract (``SourceAdapter`` protocol):

    adapter.source            -> Source (stable id, kind, uri)
    adapter.fetch()           -> list[SourceRecord]  (normalized)
    ingest(store, adapter)    -> IngestReport        (dedup + provenance)

Every record is written through ``GraphStore.add_record``, which stores
it as an event in the source's ingest session with a ``SOURCED_FROM``
edge to the ``Source`` node. The dream phase then distills records with
exactly the same machinery it applies to hook events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import Source, SourceRecord
from ..store import GraphStore


class SourceAdapter(Protocol):
    source: Source

    def fetch(self) -> list[SourceRecord]: ...


@dataclass
class IngestReport:
    source_id: str
    fetched: int = 0
    added: int = 0
    duplicates: int = 0

    @property
    def dedup_rate(self) -> float:
        return self.duplicates / self.fetched if self.fetched else 0.0


def ingest(store: GraphStore, adapter: SourceAdapter) -> IngestReport:
    """Fetch an adapter's records and write the new ones into the store."""
    store.upsert_source(adapter.source)
    report = IngestReport(source_id=adapter.source.id)
    for record in adapter.fetch():
        report.fetched += 1
        if store.add_record(record):
            report.added += 1
        else:
            report.duplicates += 1
    return report
