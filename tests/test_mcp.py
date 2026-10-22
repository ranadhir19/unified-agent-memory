"""MCP server: JSON-RPC handshake and tool calls."""

import json

from unified_agent_memory.mcp_server import call_tool, handle
from unified_agent_memory.store import InMemoryStore


def test_initialize_and_tools_list():
    store = InMemoryStore()
    resp = handle(store, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["result"]["serverInfo"]["name"] == "unified-agent-memory"
    resp = handle(store, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["memory_search", "memory_list", "memory_get",
                     "memory_store", "memory_update", "memory_delete"]


def test_tool_call_round_trip_via_protocol():
    store = InMemoryStore()
    resp = handle(store, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "memory_store", "arguments": {
            "path": "profile/role.md", "title": "Role",
            "body": "- **My role**: Scientist"}},
    })
    assert resp["result"]["isError"] is False
    resp = handle(store, {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "memory_search", "arguments": {"query": "scientist"}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload[0]["path"] == "profile/role.md"


def test_call_tool_crud_and_errors():
    store = InMemoryStore()
    call_tool(store, "memory_store", {"path": "a.md", "body": "one"})
    assert call_tool(store, "memory_get", {"path": "a.md"})["body"] == "one"
    call_tool(store, "memory_update", {"path": "a.md", "body": "two"})
    assert call_tool(store, "memory_get", {"path": "a.md"})["body"] == "two"
    assert call_tool(store, "memory_delete", {"path": "a.md"}) == {"deleted": True}
    assert call_tool(store, "memory_get", {"path": "a.md"}) is None
    try:
        call_tool(store, "memory_update", {"path": "a.md", "body": "x"})
        raise AssertionError("update of missing memory must fail")
    except KeyError:
        pass
