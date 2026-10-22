"""Command-line entrypoints (installed by pyproject as ``uam-*``).

- ``uam-hook``     -- the hook runtime (see hooks.py; re-exported here)
- ``uam-dream``    -- run the dream phase once, print the report
- ``uam-config``   -- print a ready-to-install hook config for a harness
- ``uam-ingest``   -- run one source adapter into the store
- ``uam-simulate`` -- replay a scripted event stream through the *real*
  hook entrypoint as subprocesses (true end-to-end runs)
- ``uam-serve``    -- run the FastAPI access layer
- ``uam-mcp``      -- run the MCP server on stdio
- ``uam-export-cursor-rules`` -- snapshot profile memories into a Cursor
  rules file (Cursor's hook contract cannot inject at prompt time)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import hook_configs
from .dream import DeterministicDistiller, LLMDistiller
from .hooks import profile_context
from .providers import default_provider
from .store import open_store


def dream_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uam-dream")
    parser.add_argument("--distiller", choices=["deterministic", "llm"],
                        default="deterministic")
    args = parser.parse_args(argv)
    store = open_store()
    if args.distiller == "llm":
        distiller = LLMDistiller(default_provider())
    else:
        distiller = DeterministicDistiller()
    report = distiller.dream(store)
    store.close()
    print(json.dumps(report.__dict__, indent=2, default=str))
    return 0


def config_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uam-config")
    parser.add_argument("client", choices=list(hook_configs._GENERATORS))
    args = parser.parse_args(argv)
    fname, text = hook_configs.generate(args.client)
    print(f"# -> {fname}\n{text}", end="")
    return 0


def ingest_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uam-ingest")
    sub = parser.add_subparsers(dest="kind", required=True)
    gh = sub.add_parser("github")
    gh.add_argument("owner")
    gh.add_argument("repo")
    fl = sub.add_parser("files")
    fl.add_argument("directory")
    rs = sub.add_parser("rss")
    rs.add_argument("url")
    sl = sub.add_parser("slack")
    sl.add_argument("path")
    sl.add_argument("--workspace", default="workspace")
    args = parser.parse_args(argv)

    from .adapters import (FilesAdapter, GitHubAdapter, RSSAdapter,
                            SlackExportAdapter, ingest)

    if args.kind == "github":
        adapter = GitHubAdapter(args.owner, args.repo)
    elif args.kind == "files":
        adapter = FilesAdapter(args.directory)
    elif args.kind == "rss":
        adapter = RSSAdapter(args.url)
    else:
        adapter = SlackExportAdapter(args.path, workspace=args.workspace)
    store = open_store()
    report = ingest(store, adapter)
    store.close()
    print(json.dumps(report.__dict__, indent=2))
    return 0


def simulate_main(argv: list[str] | None = None) -> int:
    """Replay [{client, payload}] items through the real hook entrypoint.

    Each item is a separate ``uam-hook`` subprocess sharing one store via
    ``UAM_STATE_FILE`` -- exactly how a harness invokes hooks.
    """
    parser = argparse.ArgumentParser(prog="uam-simulate")
    parser.add_argument("stream", help="JSON file: list of {client, payload}")
    parser.add_argument("--state", required=True, help="state file path")
    parser.add_argument("--show-output", action="store_true")
    args = parser.parse_args(argv)

    items = json.loads(Path(args.stream).read_text())
    env = dict(os.environ, UAM_STATE_FILE=args.state)
    env.pop("NEO4J_URI", None)
    for i, item in enumerate(items):
        proc = subprocess.run(
            [sys.executable, "-m", "unified_agent_memory.hooks",
             "--client", item["client"]],
            input=json.dumps(item["payload"]), capture_output=True,
            text=True, env=env,
        )
        if proc.returncode != 0:
            print(f"[{i}] hook exited {proc.returncode}: {proc.stderr}",
                  file=sys.stderr)
            return 1
        if args.show_output and proc.stdout.strip():
            print(f"[{i}] {item['client']} -> {proc.stdout.strip()}")
    print(f"replayed {len(items)} events")
    return 0


def serve_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uam-serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn

    uvicorn.run("unified_agent_memory.server.app:app",
                host=args.host, port=args.port)
    return 0


def export_cursor_rules_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uam-export-cursor-rules")
    parser.add_argument("--out", default=".cursor/rules/uam-memory.mdc")
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args(argv)
    store = open_store()
    context = profile_context(store, args.cwd)
    store.close()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "---\ndescription: Unified agent memory (profile snapshot, "
        "regenerated by uam-export-cursor-rules)\nalwaysApply: true\n---\n\n"
        + (context or "(no profile memories yet -- run uam-dream)")
        + "\n"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(dream_main())
