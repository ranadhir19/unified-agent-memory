"""Minimal MCP server (stdio, JSON-RPC 2.0) over the memory graph.

The article notes MCP tools are the complementary, on-demand access
path to hook injection: the agent can search, store, update and delete
memories itself. This implements that CRUD surface directly against the
store -- no framework, just the protocol: ``initialize``,
``tools/list``, ``tools/call``, one JSON message per line.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

from .models import MemoryDoc
from .search import search as search_docs
from .store import GraphStore, open_store

TOOLS = [
    {
        "name": "memory_search",
        "description": "Search durable memories by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_list",
        "description": "List memory paths, optionally under a prefix.",
        "inputSchema": {
            "type": "object",
            "properties": {"prefix": {"type": "string"}},
        },
    },
    {
        "name": "memory_get",
        "description": "Read one memory document by semantic path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "memory_store",
        "description": "Create or replace a memory document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["path", "body"],
        },
    },
    {
        "name": "memory_update",
        "description": "Replace the body of an existing memory document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["path", "body"],
        },
    },
    {
        "name": "memory_delete",
        "description": "Delete a memory document by path.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]


def call_tool(store: GraphStore, name: str, args: dict[str, Any]) -> Any:
    if name == "memory_search":
        hits = search_docs(store.list_memories(), args["query"],
                           int(args.get("k", 5)))
        return [d.to_dict() for d in hits]
    if name == "memory_list":
        return [d.path for d in store.list_memories(args.get("prefix"))]
    if name == "memory_get":
        doc = store.get_memory(args["path"])
        return doc.to_dict() if doc else None
    if name == "memory_store":
        doc = store.get_memory(args["path"]) or MemoryDoc(path=args["path"])
        doc.title = args.get("title", doc.title)
        doc.body = args["body"]
        return store.upsert_memory(doc).to_dict()
    if name == "memory_update":
        doc = store.get_memory(args["path"])
        if doc is None:
            raise KeyError(f"no memory at {args['path']}")
        doc.body = args["body"]
        return store.upsert_memory(doc).to_dict()
    if name == "memory_delete":
        return {"deleted": store.delete_memory(args["path"])}
    raise KeyError(f"unknown tool {name}")


def handle(store: GraphStore, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    method = msg.get("method", "")
    mid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "unified-agent-memory", "version": "0.1.0"},
        }}
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = call_tool(store, params.get("name", ""),
                               params.get("arguments") or {})
            text = json.dumps(result, indent=2, default=str)
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"error: {exc}"}],
                "isError": True,
            }}
    return {"jsonrpc": "2.0", "id": mid, "error": {
        "code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    store = open_store()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        resp = handle(store, msg)
        if resp is not None:
            print(json.dumps(resp), flush=True)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
