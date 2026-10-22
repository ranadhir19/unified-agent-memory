"""FilesAdapter: a directory of markdown/text notes becomes memory input."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..models import Source, SourceRecord

_SUFFIXES = {".md", ".markdown", ".txt", ".rst"}


class FilesAdapter:
    def __init__(self, root: str | Path, source_id: str | None = None):
        self.root = Path(root)
        sid = source_id or f"files:{self.root.name}"
        self.source = Source(
            id=sid, kind="files", name=f"Notes in {self.root}",
            uri=str(self.root),
        )

    def fetch(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _SUFFIXES:
                continue
            text = path.read_text(errors="replace")
            rel = path.relative_to(self.root).as_posix()
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            title = next(
                (ln.lstrip("# ").strip() for ln in text.splitlines()
                 if ln.strip().startswith("#")),
                rel,
            )
            records.append(
                SourceRecord(
                    id=f"{self.source.id}:{rel}:{digest}",
                    source_id=self.source.id,
                    kind="note",
                    title=title,
                    body=text,
                    url=f"file://{path}",
                    timestamp=path.stat().st_mtime,
                )
            )
        return records
