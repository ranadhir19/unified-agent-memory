"""Access layer: REST smoke tests + GraphQL queries over a seeded store."""

import pytest
from fastapi.testclient import TestClient

from unified_agent_memory.models import MemoryDoc, Session
from unified_agent_memory.server.app import create_app
from unified_agent_memory.store import InMemoryStore


@pytest.fixture()
def client():
    store = InMemoryStore()
    store.create_session(Session(id="s1", harness="codex", cwd="/work/atlas-api"))
    store.upsert_memory(MemoryDoc(
        path="profile/role.md", title="Role",
        body="# Role\n\n- **My role**: Principal Research Scientist\n"))
    return TestClient(create_app(store))


def test_health_and_stats(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    stats = client.get("/api/stats").json()
    assert stats["sessions"] == 1 and stats["memories"] == 1


def test_memory_crud_via_rest(client):
    r = client.put("/api/memories/topics/testing.md",
                   json={"title": "Testing", "body": "pytest notes"})
    assert r.status_code == 200
    got = client.get("/api/memories/topics/testing.md")
    assert got.json()["body"] == "pytest notes"
    assert client.delete("/api/memories/topics/testing.md").status_code == 200
    assert client.get("/api/memories/topics/testing.md").status_code == 404


def test_search_endpoint(client):
    hits = client.get("/api/search", params={"q": "research scientist"}).json()
    assert hits and hits[0]["path"] == "profile/role.md"


def test_sessions_endpoint(client):
    sessions = client.get("/api/sessions").json()
    assert sessions[0]["id"] == "s1" and sessions[0]["harness"] == "codex"


def test_graphql_query(client):
    query = "{ stats { sessions memories } memories { path title } }"
    resp = client.post("/graphql", json={"query": query})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stats"] == {"sessions": 1, "memories": 1}
    assert data["memories"][0]["path"] == "profile/role.md"


def test_graphql_search_and_mutation(client):
    q = 'mutation { storeMemory(path: "a/b.md", title: "B", body: "body") { path } }'
    resp = client.post("/graphql", json={"query": q})
    assert resp.json()["data"]["storeMemory"]["path"] == "a/b.md"
    q2 = '{ search(query: "body") { path } }'
    resp2 = client.post("/graphql", json={"query": q2})
    assert resp2.json()["data"]["search"][0]["path"] == "a/b.md"
