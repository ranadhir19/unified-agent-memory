# Experiment results

All numbers below come from actual runs of `experiments/run_experiments.py`
(production code paths throughout; raw output in `experiments/results.json`).
Reproduce: `pip install -e ".[dev,server]" && python3 experiments/run_experiments.py`.

## E1 — Cross-harness continuity: 12/12 facts recalled (hit rate 1.00)

A scripted scenario (14 hook events) was replayed through the **real
`uam-hook` entrypoint as subprocesses** — sessions in Claude Code and
Codex, prompt events in Cursor — then all four adapters were ingested
and the dream phase ran. A **fresh Codex session** was then probed
(SessionStart + two UserPromptSubmit events, again as subprocesses).

The 12 seeded facts: 9 stated in harness prompts across the three
harnesses, 3 that existed *only* in third-party sources (a GitHub issue
title, a Slack message, an RSS item title). All 12 appeared in the
context injected into the new harness — including the three that no
harness ever saw, which is the adapter thesis working end to end.

*Limit:* the probe prompts were written knowing the facts' vocabulary;
E5 measures retrieval under less cooperative queries.

## E2 — Adapter ingestion: 16 records, dedup 1.00, provenance 100%

| Adapter | Fetched | Added (1st pass) |
|---|---|---|
| GitHub (recorded API fixtures) | 9 | 9 |
| Files (notes dir) | 2 | 2 |
| RSS (recorded feed) | 2 | 2 |
| Slack export | 3 | 3 |

A second ingest pass added 0 records — every record was recognized as
a duplicate (dedup rate 1.00). 100% of ingested events carry a
`SOURCED_FROM` provenance edge to their source node.

## E3 — Dream-phase merge: contradiction rewritten, not duplicated

Two prompts asserted `deploy target is AWS`, then later
`deploy target is GCP`. After one dream run: exactly **1** note for the
path, exactly **1** fact for the subject, value **GCP**, the stale value
absent from the note body, and 1 contradiction counted as rewritten.

## E4 — Hook latency

- In-process dispatch + store write (the hook's own work): **mean
  0.029 ms, p95 0.08 ms** per event over the 14-event fixture stream.
- Full `uam-hook` subprocess per event (interpreter start + state-file
  load/save included — the number a harness actually pays): **mean
  0.082 s**.

Hooks make no model calls, so latency is interpreter start, not the
memory layer. A persistent daemon or the Neo4j backend changes the
second number's composition but not the first's order of magnitude.

## E5 — Retrieval quality: precision@3 0.875, hit rate 0.875

Seeded 8 memory documents and 8 queries with one expected hit each.
7/8 queries returned exactly the right document as the only hit. The
failure is instructive: **"container orchestration platform" returned
nothing** for a note about Kubernetes — the retriever is lexical (no
stemming: *container* ≠ *containers*; no embeddings: no synonymy).

## Honest limitations

- **Retrieval is keyword search.** E5's miss is the standing gap; a
  vector index is the obvious next layer, deliberately not faked here.
- **The deterministic distiller extracts explicit facts** (`remember:
  X is Y`, preferences, tool-usage patterns, statement-shaped source
  titles). It does not summarize free prose — that is what the optional
  LLM distiller is for, and it is not exercised by these experiments.
- **E1's facts are short and unambiguous.** Real prompt streams are
  noisier; recall on organic data will be lower.
- **Neo4j parity is by construction, not by test**: the suite runs
  against the in-memory store; `Neo4jStore` implements the same
  protocol against the article's graph model but is not spun up in CI.
- Latency figures are from one machine, one run; treat them as orders
  of magnitude, not benchmarks.
