#!/usr/bin/env python3
"""Seeded, reproducible experiments for unified-agent-memory.

Every experiment runs the production code paths: E1 replays scripted
harness streams through the real ``uam-hook`` entrypoint as subprocesses
sharing one state file, ingests the adapter fixtures, dreams, and then
probes a *fresh* session in a *different* harness. Nothing is mocked.

Writes experiments/results.json; RESULTS.md is authored from its output.
Usage: python3 experiments/run_experiments.py
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "experiments" / "fixtures"
sys.path.insert(0, str(ROOT / "src"))

from unified_agent_memory.adapters import (  # noqa: E402
    FilesAdapter, GitHubAdapter, RSSAdapter, SlackExportAdapter, ingest,
)
from unified_agent_memory.dream import DeterministicDistiller  # noqa: E402
from unified_agent_memory.hooks import run_hook  # noqa: E402
from unified_agent_memory.models import MemoryDoc  # noqa: E402
from unified_agent_memory.search import search as search_docs  # noqa: E402
from unified_agent_memory.store import InMemoryStore  # noqa: E402


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


def _adapters():
    return [
        GitHubAdapter("octocat", "hello-world", fetch_json=_github_fetch),
        FilesAdapter(FIXTURES / "notes"),
        RSSAdapter("https://example.com/feed.xml",
                   fetch_text=lambda _u: (FIXTURES / "feed.xml").read_text()),
        SlackExportAdapter(FIXTURES / "slack_export.json"),
    ]


def _hook_subprocess(client: str, payload: dict, state: Path) -> tuple[str, float]:
    env = dict(os.environ, UAM_STATE_FILE=str(state))
    env.pop("NEO4J_URI", None)
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "unified_agent_memory.hooks", "--client", client],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
    )
    wall = time.perf_counter() - start
    if proc.returncode != 0:
        raise RuntimeError(f"hook failed: {proc.stderr}")
    return proc.stdout, wall


# --------------------------------------------------------------------- E1
E1_FACTS = [
    ("role", ["Principal Research Scientist"]),
    ("deploy target", ["deploy target", "AWS"]),
    ("staging database", ["Postgres 16"]),
    ("preference", ["tabs over spaces"]),
    ("rate limit", ["600 requests per minute"]),
    ("release cadence", ["second Friday"]),
    ("on-call", ["on-call rotation"]),
    ("git branch", ["git default branch"]),
    ("standup", ["09:30"]),
    ("migration deadline", ["2026-11-15"]),
    ("incident channel", ["#ops-alerts"]),
    ("community meetup", ["2026-12-05"]),
]


def experiment_e1(tmp: Path) -> tuple[dict, list[float]]:
    state = tmp / "e1-state.json"
    stream = json.loads((FIXTURES / "e1_stream.json").read_text())
    walls: list[float] = []
    for item in stream:
        _, wall = _hook_subprocess(item["client"], item["payload"], state)
        walls.append(wall)

    store = InMemoryStore(state_path=state)
    for adapter in _adapters():
        ingest(store, adapter)
    DeterministicDistiller().dream(store)

    probes = [
        {"session_id": "probe-1", "hook_event_name": "SessionStart",
         "cwd": "/work/atlas-api", "timestamp": 1760010000},
        {"session_id": "probe-1", "hook_event_name": "UserPromptSubmit",
         "cwd": "/work/atlas-api", "timestamp": 1760010060,
         "prompt": "what is the git default branch and when is the migration deadline?"},
        {"session_id": "probe-1", "hook_event_name": "UserPromptSubmit",
         "cwd": "/work/atlas-api", "timestamp": 1760010120,
         "prompt": "where is the incident channel and when is the community meetup?"},
    ]
    context = ""
    for payload in probes:
        out, _ = _hook_subprocess("codex", payload, state)
        if out.strip():
            context += json.loads(out)["hookSpecificOutput"]["additionalContext"]

    found, missed = [], []
    for name, markers in E1_FACTS:
        (found if all(m in context for m in markers) else missed).append(name)
    return {
        "seeded_facts": len(E1_FACTS),
        "recalled": len(found),
        "hit_rate": round(len(found) / len(E1_FACTS), 3),
        "found": found,
        "missed": missed,
        "probe_harness": "codex (facts seeded via claude-code, cursor, codex + 4 adapters)",
    }, walls


# --------------------------------------------------------------------- E2
def experiment_e2() -> dict:
    store = InMemoryStore()
    first = [ingest(store, a) for a in _adapters()]
    second = [ingest(store, a) for a in _adapters()]
    fetched = sum(r.fetched for r in first)
    added = sum(r.added for r in first)
    dup_second = sum(r.duplicates for r in second)
    events = [e for e in store.list_events() if e.type == "SourceRecord"]
    with_prov = sum(1 for e in events if e.source_id)
    return {
        "per_adapter": {
            a.source.id: {"fetched": r.fetched, "added": r.added}
            for a, r in zip(_adapters(), first)
        },
        "fetched": fetched,
        "added_first_pass": added,
        "duplicates_second_pass": dup_second,
        "dedup_rate_second_pass": round(dup_second / fetched, 3) if fetched else 0.0,
        "provenance_completeness": round(with_prov / len(events), 3) if events else 0.0,
        "source_events": len(events),
    }


# --------------------------------------------------------------------- E3
def experiment_e3() -> dict:
    store = InMemoryStore()
    for text, ts in (("remember: The deploy target is AWS", 100.0),
                     ("remember: The deploy target is GCP", 200.0)):
        run_hook(store, "codex", json.dumps({
            "session_id": "e3", "hook_event_name": "UserPromptSubmit",
            "prompt": text, "cwd": "/work/atlas-api", "timestamp": ts}))
    report = DeterministicDistiller().dream(store)
    doc = store.get_memory("project/atlas-api.md")
    facts = [f for f in doc.facts if f["subject"] == "The deploy target"]
    return {
        "notes_for_path": len(store.list_memories(prefix="project/atlas-api")),
        "deploy_target_facts": len(facts),
        "final_value": facts[0]["value"] if facts else None,
        "stale_value_in_body": "AWS" in doc.body,
        "contradictions_rewritten": report.contradictions_rewritten,
        "note_version": doc.version,
    }


# --------------------------------------------------------------------- E4
def experiment_e4() -> dict:
    store = InMemoryStore()
    stream = json.loads((FIXTURES / "e1_stream.json").read_text())
    times = []
    for item in stream:
        start = time.perf_counter()
        run_hook(store, item["client"], json.dumps(item["payload"]))
        times.append((time.perf_counter() - start) * 1000.0)
    times.sort()
    p95 = times[min(len(times) - 1, int(0.95 * len(times)))]
    return {
        "events": len(times),
        "mean_ms": round(statistics.mean(times), 3),
        "p95_ms": round(p95, 3),
        "max_ms": round(times[-1], 3),
        "scope": "in-process dispatch + in-memory store write (excludes interpreter start)",
    }


# --------------------------------------------------------------------- E5
def experiment_e5() -> dict:
    corpus = [
        MemoryDoc(path="tools/git.md", title="Git",
                  body="git rebase branches commits merging rebasing history"),
        MemoryDoc(path="tools/docker.md", title="Docker",
                  body="containers images volumes networks compose builds"),
        MemoryDoc(path="tools/kubectl.md", title="Kubectl",
                  body="kubernetes pods deployments services namespaces rollout"),
        MemoryDoc(path="profile/role.md", title="Role",
                  body="principal research scientist ai research"),
        MemoryDoc(path="project/atlas-api.md", title="Atlas Api",
                  body="deploy target cloud staging database releases"),
        MemoryDoc(path="topics/observability.md", title="Observability",
                  body="tracing metrics logs dashboards alerts"),
        MemoryDoc(path="topics/security.md", title="Security",
                  body="oauth tokens authentication encryption secrets"),
        MemoryDoc(path="topics/testing.md", title="Testing",
                  body="pytest fixtures assertions coverage mocks"),
    ]
    queries = [
        ("git rebase branches", "tools/git.md"),
        ("docker images volumes", "tools/docker.md"),
        ("kubernetes pods deployments", "tools/kubectl.md"),
        ("container orchestration platform", "tools/kubectl.md"),
        ("oauth tokens authentication", "topics/security.md"),
        ("pytest fixtures", "topics/testing.md"),
        ("deploy staging database", "project/atlas-api.md"),
        ("tracing metrics logs", "topics/observability.md"),
    ]
    precisions, hits, detail = [], 0, []
    for query, expected in queries:
        got = [d.path for d in search_docs(corpus, query, k=3)]
        hit = expected in got
        hits += hit
        precisions.append((1 if hit else 0) / len(got) if got else 0.0)
        detail.append({"query": query, "expected": expected,
                       "got": got, "hit": hit})
    return {
        "queries": len(queries),
        "precision_at_3": round(statistics.mean(precisions), 3),
        "hit_rate_at_3": round(hits / len(queries), 3),
        "detail": detail,
    }


def main() -> int:
    results: dict = {}
    with tempfile.TemporaryDirectory() as td:
        e1, walls = experiment_e1(Path(td))
    results["E1_cross_harness_continuity"] = e1
    results["E2_adapter_ingestion"] = experiment_e2()
    results["E3_dream_merge"] = experiment_e3()
    e4 = experiment_e4()
    e4["subprocess_wall_mean_s"] = round(statistics.mean(walls), 3)
    e4["subprocess_wall_note"] = (
        "full uam-hook subprocess per event from E1 (interpreter start + "
        "state load/save included) -- the number a harness actually pays")
    results["E4_hook_latency"] = e4
    results["E5_retrieval_quality"] = experiment_e5()
    out = ROOT / "experiments" / "results.json"
    out.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
