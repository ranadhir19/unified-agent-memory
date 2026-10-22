# Validation

`python3 validate.py` runs the repository harness. It is deterministic
and offline (the test suite and experiments use recorded fixtures; no
network, no API keys).

Stages:

1. **import/compile** — `compileall` over the tree's Python sources,
   then imports of the `unified_agent_memory` package (every module) and
   the server package in a clean subprocess.
2. **test suite** — `pytest` over `tests/`.
3. **employer-reference scan** — the standing gate scanner
   (`~/workspace/github-fis-watch/fis_scan.py`) over the repo's sources;
   every candidate is judged in context by the rules in `validate.py`.
   A real employer reference FAILs this stage. This project is
   independent open-source work and must contain none. `validate.py`
   and this file name the gate they enforce, so they are excluded from
   the scan and reviewed by hand.
4. **results/docs consistency** — every path the README references
   exists, and the committed experiment outputs
   (`experiments/results.json`, `experiments/RESULTS.md`) and demo
   surfaces (docs page, web UI, render.yaml, docker-compose.yml) are
   present.

Final line is exactly `HARNESS GREEN` (exit 0) or `HARNESS RED:
<stages>` (exit 1).

What this harness does **not** verify: live Neo4j behaviour (the suite
runs on the in-memory store implementing the same protocol), live
GitHub/RSS fetching (adapters are tested on recorded fixtures), and the
deployed demo (Render blueprint is shipped; deployment is verified
separately, if at all).
