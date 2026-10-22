import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function Sessions({ sessions }) {
  const [selected, setSelected] = useState(null);
  const [events, setEvents] = useState([]);

  useEffect(() => {
    if (!selected) return;
    api.sessionEvents(selected).then(setEvents).catch(() => setEvents([]));
  }, [selected]);

  return (
    <div className="split">
      <div className="list">
        {sessions.map((s) => (
          <button
            key={s.id}
            className={s.id === selected ? "row active" : "row"}
            onClick={() => setSelected(s.id)}
          >
            <span className={`badge badge-${s.harness.split(":")[0]}`}>{s.harness}</span>
            <span className="row-title">{s.id}</span>
            <span className="row-sub">{s.cwd || "—"}</span>
          </button>
        ))}
        {sessions.length === 0 && <p className="empty">No sessions yet.</p>}
      </div>
      <div className="detail">
        {selected ? (
          <ol className="timeline">
            {events.map((e) => (
              <li key={e.id}>
                <span className="seq">{e.seq}</span>
                <span className="etype">{e.type}</span>
                <span className="epayload">
                  {e.payload?.prompt ||
                    e.payload?.title ||
                    e.payload?.tool_name ||
                    ""}
                </span>
                {e.source_id && <span className="prov">← {e.source_id}</span>}
              </li>
            ))}
          </ol>
        ) : (
          <p className="empty">Select a session to see its cross-harness timeline.</p>
        )}
      </div>
    </div>
  );
}

function Memories({ memories }) {
  const [selected, setSelected] = useState(null);
  const doc = useMemo(
    () => memories.find((m) => m.path === selected),
    [memories, selected]
  );
  const groups = useMemo(() => {
    const g = {};
    for (const m of memories) {
      const top = m.path.split("/")[0];
      (g[top] = g[top] || []).push(m);
    }
    return g;
  }, [memories]);

  return (
    <div className="split">
      <div className="list">
        {Object.entries(groups).map(([top, docs]) => (
          <div key={top}>
            <div className="group">{top}/</div>
            {docs.map((m) => (
              <button
                key={m.path}
                className={m.path === selected ? "row active" : "row"}
                onClick={() => setSelected(m.path)}
              >
                <span className="row-title">{m.path}</span>
                <span className="row-sub">v{m.version}</span>
              </button>
            ))}
          </div>
        ))}
        {memories.length === 0 && <p className="empty">No memories yet — run the dream phase.</p>}
      </div>
      <div className="detail">
        {doc ? (
          <>
            <h3>{doc.title || doc.path}</h3>
            <pre className="md">{doc.body}</pre>
            {doc.sources?.length > 0 && (
              <p className="prov-line">
                Provenance: {doc.sources.map((s) => (
                  <span key={s} className="badge">{s}</span>
                ))}
              </p>
            )}
          </>
        ) : (
          <p className="empty">Select a memory note.</p>
        )}
      </div>
    </div>
  );
}

function Sources({ sources, stats }) {
  return (
    <div>
      <p className="lede">
        Third-party data sources feeding the same memory graph. Every
        ingested record lands as an event with a provenance edge to its
        source — {stats.records ?? 0} records so far.
      </p>
      <div className="cards">
        {sources.map((s) => (
          <div key={s.id} className="card">
            <span className={`badge badge-${s.kind}`}>{s.kind}</span>
            <div className="card-title">{s.name || s.id}</div>
            <div className="card-sub">{s.id}</div>
            <div className="card-sub">{s.uri}</div>
          </div>
        ))}
        {sources.length === 0 && <p className="empty">No sources ingested yet.</p>}
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("sessions");
  const [stats, setStats] = useState({});
  const [sessions, setSessions] = useState([]);
  const [memories, setMemories] = useState([]);
  const [sources, setSources] = useState([]);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState(null);

  const load = useCallback(() => {
    Promise.all([api.stats(), api.sessions(), api.memories(), api.sources()])
      .then(([st, se, me, so]) => {
        setStats(st); setSessions(se); setMemories(me); setSources(so);
        setError("");
      })
      .catch((e) => setError(`API unreachable (${e.message}). Start it with: uam-serve`));
  }, []);

  useEffect(load, [load]);

  const doSearch = async (e) => {
    e.preventDefault();
    try {
      setHits(await api.search(query));
    } catch {
      setHits([]);
    }
  };

  return (
    <div className="app">
      <header>
        <h1>Unified Agent Memory</h1>
        <p>
          One memory layer under every harness — Claude Code, Codex,
          Cursor — and every source it learns from.
        </p>
      </header>

      <section className="stats">
        <Stat label="sessions" value={stats.sessions ?? "–"} />
        <Stat label="events" value={stats.events ?? "–"} />
        <Stat label="memories" value={stats.memories ?? "–"} />
        <Stat label="sources" value={stats.sources ?? "–"} />
        <button className="dream" onClick={() => api.dream().then(load)}>
          Run dream phase
        </button>
      </section>

      {error && <p className="error">{error}</p>}

      <form className="searchbar" onSubmit={doSearch}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search memories (same lexical retriever the hooks inject with)…"
        />
        <button type="submit">Search</button>
      </form>
      {hits && (
        <div className="hits">
          {hits.length === 0 && <p className="empty">No matches.</p>}
          {hits.map((h) => (
            <div key={h.path} className="hit">
              <strong>{h.path}</strong>
              <pre className="md">{h.body}</pre>
            </div>
          ))}
        </div>
      )}

      <nav className="tabs">
        {["sessions", "memories", "sources"].map((t) => (
          <button key={t} className={tab === t ? "tab active" : "tab"}
            onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>

      {tab === "sessions" && <Sessions sessions={sessions} />}
      {tab === "memories" && <Memories memories={memories} />}
      {tab === "sources" && <Sources sources={sources} stats={stats} />}
    </div>
  );
}
