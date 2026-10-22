"""SlackExportAdapter: a Slack workspace export (JSON) as a data source.

Accepts either a directory in the standard export layout
(``channels.json`` plus one ``<channel>/<date>.json`` file per day) or a
single combined JSON file: a list of message objects, or an object with
a ``messages`` list and optional ``channel`` name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import Source, SourceRecord


class SlackExportAdapter:
    def __init__(self, path: str | Path, workspace: str = "workspace"):
        self.path = Path(path)
        self.workspace = workspace
        self.source = Source(
            id=f"slack:{workspace}", kind="slack",
            name=f"Slack export ({workspace})", uri=str(self.path),
        )

    def _messages(self) -> list[tuple[str, dict[str, Any]]]:
        """Yield (channel, message) pairs from either export layout."""
        out: list[tuple[str, dict[str, Any]]] = []
        if self.path.is_dir():
            channels: dict[str, str] = {}
            cj = self.path / "channels.json"
            if cj.exists():
                for ch in json.loads(cj.read_text()):
                    channels[ch["id"]] = ch.get("name", ch["id"])
            for day_file in sorted(self.path.rglob("*.json")):
                if day_file.name == "channels.json":
                    continue
                channel = day_file.parent.name
                try:
                    msgs = json.loads(day_file.read_text())
                except (ValueError, OSError):
                    continue
                if isinstance(msgs, list):
                    out.extend((channel, m) for m in msgs if isinstance(m, dict))
            return out
        data = json.loads(self.path.read_text())
        if isinstance(data, dict):
            channel = str(data.get("channel", "general"))
            return [(channel, m) for m in data.get("messages", [])
                    if isinstance(m, dict)]
        return [("general", m) for m in data if isinstance(m, dict)]

    def fetch(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for channel, msg in self._messages():
            if msg.get("subtype") in ("channel_join", "channel_leave"):
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            ts = float(msg.get("ts", 0) or 0)
            records.append(SourceRecord(
                id=f"{self.source.id}:{channel}:{msg.get('ts', '')}",
                source_id=self.source.id,
                kind="message",
                title=f"#{channel}: {text.splitlines()[0][:80]}",
                body=text,
                timestamp=ts,
                author=str(msg.get("user", "")),
            ))
        return records
