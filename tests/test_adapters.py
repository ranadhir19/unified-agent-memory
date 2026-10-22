"""Adapters: normalization over recorded fixtures + ingest semantics."""

import json
from pathlib import Path

from unified_agent_memory.adapters import (
    FilesAdapter, GitHubAdapter, RSSAdapter, SlackExportAdapter, ingest,
)
from unified_agent_memory.store import InMemoryStore

FIXTURES = Path(__file__).resolve().parent.parent / "experiments" / "fixtures"


def _github_fetch(url: str):
    if "/pulls" in url:
        name = "pulls"
    elif "/issues" in url:
        name = "issues"
    elif "/commits" in url:
        name = "commits"
    else:
        name = "repo"
    return json.loads((FIXTURES / "github_api" / f"{name}.json").read_text())


def test_github_adapter_normalizes_all_kinds():
    adapter = GitHubAdapter("octocat", "hello-world", fetch_json=_github_fetch)
    records = adapter.fetch()
    kinds = sorted(r.kind for r in records)
    assert kinds == ["commit", "commit", "commit", "issue", "issue", "issue",
                     "pull_request", "pull_request", "repo"]
    issue = next(r for r in records if r.kind == "issue")
    assert issue.id == "github:octocat/hello-world:issue:7"
    assert issue.timestamp > 0 and issue.url.startswith("https://github.com/")
    assert adapter.source.kind == "github"


def test_files_adapter_reads_notes():
    adapter = FilesAdapter(FIXTURES / "notes")
    records = adapter.fetch()
    assert len(records) == 2
    assert all(r.kind == "note" for r in records)
    conv = next(r for r in records if "conventions" in r.id)
    assert conv.title == "Team conventions"


def test_rss_adapter_parses_feed():
    adapter = RSSAdapter(
        "https://example.com/feed.xml",
        fetch_text=lambda _u: (FIXTURES / "feed.xml").read_text(),
    )
    records = adapter.fetch()
    assert len(records) == 2
    assert records[0].kind == "feed_item" and records[0].timestamp > 0
    assert "meetup" in records[0].title


def test_slack_adapter_skips_join_events():
    adapter = SlackExportAdapter(FIXTURES / "slack_export.json", workspace="acme")
    records = adapter.fetch()
    assert len(records) == 3  # 4 raw messages, 1 channel_join skipped
    assert all(r.kind == "message" for r in records)


def test_ingest_dedup_and_provenance_completeness():
    store = InMemoryStore()
    adapters = [
        GitHubAdapter("octocat", "hello-world", fetch_json=_github_fetch),
        FilesAdapter(FIXTURES / "notes"),
        RSSAdapter("https://example.com/feed.xml",
                   fetch_text=lambda _u: (FIXTURES / "feed.xml").read_text()),
        SlackExportAdapter(FIXTURES / "slack_export.json"),
    ]
    total = 0
    for adapter in adapters:
        report = ingest(store, adapter)
        total += report.added
    assert total == 16
    # second pass: everything is a duplicate
    for adapter in adapters:
        report = ingest(store, adapter)
        assert report.added == 0 and report.duplicates == report.fetched
    # every ingested event carries provenance
    events = [e for e in store.list_events() if e.type == "SourceRecord"]
    assert len(events) == 16
    assert all(e.source_id for e in events)
    assert len(store.list_sources()) == 4
