#!/usr/bin/env python3
"""Validation harness for the unified-agent-memory repository.

Usage:  python3 validate.py     (deterministic, offline, no network)

Stages, in order, each printing one PASS/FAIL line:
  1. import/compile  - compileall over the tree's Python sources, then
                       import the unified_agent_memory package (every
                       module) and the server package in a subprocess.
  2. test suite      - pytest over tests/ in a subprocess.
  3. employer scan   - the standing gate scanner over the repo's
                       sources; every candidate is judged in context
                       below. A real reference FAILs this stage.
  4. docs/results    - every path the README references exists, and the
                       committed experiment outputs and demo surfaces
                       exist.

Final line is exactly "HARNESS GREEN" (exit 0) or
"HARNESS RED: <stages>" (exit 1). See VALIDATION.md for what this
harness does and does not verify.
"""

import compileall
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
GATE_SCANNER = Path(
    os.environ.get(
        "FIS_SCAN",
        Path.home() / "workspace" / "github-fis-watch" / "fis_scan.py",
    )
)
# This harness and its companion doc must name the gate they enforce,
# so they are excluded from the scan and reviewed by hand instead.
SCAN_EXCLUDE = {"validate.py", "VALIDATION.md"}
SCAN_PATHS = ["src", "tests", "experiments", "examples", "web/src",
              "web/index.html", "web/package.json", "docs", "README.md",
              "render.yaml", "docker-compose.yml", "pyproject.toml"]

FAILED = []


def report(stage, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {stage}" + (f" - {detail}" if detail else ""))
    if not ok:
        FAILED.append(stage)
    return ok


def project_packages():
    with open(ROOT / "pyproject.toml", "rb") as fh:
        name = tomllib.load(fh)["project"]["name"]
    top = name.replace("-", "_")
    pkgs = [top]
    base = SRC / top
    for mod in sorted(base.rglob("*.py")):
        if mod.name != "__init__.py":
            rel = mod.relative_to(SRC).with_suffix("")
            pkgs.append(".".join(rel.parts))
    return name, pkgs


def stage_import_compile():
    targets = [SRC, ROOT / "tests", ROOT / "experiments", ROOT / "examples"]
    ok = True
    for t in targets:
        if t.exists() and not compileall.compile_dir(str(t), quiet=1):
            ok = False
            print(f"    compile failed under {t.relative_to(ROOT)}")
    name, pkgs = project_packages()
    env = dict(os.environ, PYTHONPATH=f"{SRC}:{ROOT}")
    code = "; ".join(f"import {p}" for p in pkgs)
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        ok = False
        print("    import errors:\n" + proc.stderr[-1500:])
    return report("1. import/compile", ok,
                  f"project {name}; imported {len(pkgs)} packages/modules")


def stage_tests():
    env = dict(os.environ, PYTHONPATH=str(SRC))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=1800)
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    print("    pytest: " + tail)
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-1500:])
    return report("2. test suite", proc.returncode == 0, tail)


def judge(hit):
    """Judge one scanner candidate in context. Returns (real, label)."""
    pattern, text = hit["pattern"], hit["text"]
    low = text.lower()
    if pattern in ("fisglobal", "fis-global", "fisglobal-domain"):
        return True, "REAL"
    if pattern == "Zenith-codename":
        if any(w in low for w in ("telescope", "astronom", "star", "sky")) \
                and not any(w in low for w in ("ai", "platform", "product")):
            return False, "BENIGN (astronomy)"
        return True, "REAL"
    if pattern == "FIS-word":
        if "affiliation" in low:
            return True, "USER-DECISION (affiliation)"
        return True, "REAL"
    # GOS-word and fis-path-segment have no benign use in this repo.
    return True, "REAL"


def stage_employer_scan():
    if not GATE_SCANNER.exists():
        return report("3. employer-reference scan", False,
                      f"scanner not found at {GATE_SCANNER}")
    paths = [str(ROOT / p) for p in SCAN_PATHS if (ROOT / p).exists()]
    proc = subprocess.run([sys.executable, str(GATE_SCANNER), *paths],
                          capture_output=True, text=True)
    hits, excluded = [], 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            h = json.loads(line)
            rel = os.path.relpath(h["file"], ROOT)
            if rel in SCAN_EXCLUDE:
                excluded += 1
            else:
                hits.append((rel, h))
    if excluded:
        print(f"    note: {excluded} candidate(s) inside validate.py / "
              "VALIDATION.md name the gate itself - excluded, judged "
              "benign, see VALIDATION.md")
    real = []
    for rel, h in hits:
        is_real, label = judge(h)
        print(f"    candidate {rel}:{h['line']} [{h['pattern']}] "
              f"-> {label}: {h['text'][:120]}")
        if is_real:
            real.append((rel, h, label))
    ok = not real
    detail = (f"{len(hits)} candidate(s), {len(real)} real"
              if hits else "0 candidates")
    return report("3. employer-reference scan", ok, detail)


REF_RE = re.compile(
    r"(?<![\w./-])((?:results|examples|experiments|docs|src|web)/[\w./<>*-]+"
    r")(?![\w/-])")


def stage_docs_results():
    readmes = [ROOT / "README.md"]
    refs, missing = set(), []
    for rm in readmes:
        if not rm.exists():
            continue
        for m in REF_RE.finditer(rm.read_text(errors="replace")):
            refs.add(m.group(1).rstrip(".,;:"))
    for ref in sorted(refs):
        if "<" in ref or "*" in ref:
            continue
        if not (ROOT / ref).exists():
            missing.append(ref)
    for rel in ("examples/quickstart.py",
                "experiments/run_experiments.py", "experiments/RESULTS.md",
                "experiments/results.json",
                "docs/index.html", "web/src/App.jsx", "web/package.json",
                "render.yaml", "docker-compose.yml", "Dockerfile",
                "LICENSE", "pyproject.toml"):
        if not (ROOT / rel).exists():
            missing.append(rel)
    for m in missing:
        print(f"    missing: {m}")
    results_ok = True
    try:
        data = json.loads((ROOT / "experiments" / "results.json").read_text())
        results_ok = all(
            k in data for k in (
                "E1_cross_harness_continuity", "E2_adapter_ingestion",
                "E3_dream_merge", "E4_hook_latency", "E5_retrieval_quality"))
    except Exception:
        results_ok = False
    return report("4. results/docs consistency",
                  not missing and results_ok,
                  f"{len(refs)} README references checked, "
                  f"{len(missing)} missing; results.json complete: {results_ok}")


def main():
    print(f"validate.py - {ROOT.name} ({ROOT})")
    stage_import_compile()
    stage_tests()
    stage_employer_scan()
    stage_docs_results()
    if FAILED:
        print("HARNESS RED: " + ", ".join(FAILED))
        return 1
    print("HARNESS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
