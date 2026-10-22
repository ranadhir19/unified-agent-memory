"""Third-party source adapters for the unified memory layer."""

from .base import IngestReport, SourceAdapter, ingest
from .files import FilesAdapter
from .github import GitHubAdapter
from .rss import RSSAdapter
from .slack import SlackExportAdapter

__all__ = [
    "SourceAdapter",
    "IngestReport",
    "ingest",
    "FilesAdapter",
    "GitHubAdapter",
    "RSSAdapter",
    "SlackExportAdapter",
]
