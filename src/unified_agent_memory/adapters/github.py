"""GitHubAdapter: repos, issues, PRs and commits via the GitHub REST API.

Works against public data with no token; a token (``GITHUB_TOKEN`` env)
only raises rate limits. Network access is isolated behind a single
``fetch_json`` callable so tests run entirely on recorded fixtures.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from typing import Any, Callable, Optional

from ..models import Source, SourceRecord


def _ts(iso: Optional[str]) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _default_fetch_json(url: str) -> Any:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "unified-agent-memory"}
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class GitHubAdapter:
    """Fetch one repository's metadata, issues, PRs and recent commits."""

    def __init__(
        self,
        owner: str,
        repo: str,
        fetch_json: Optional[Callable[[str], Any]] = None,
        per_page: int = 30,
        api_base: str = "https://api.github.com",
    ):
        self.owner = owner
        self.repo = repo
        self.api_base = api_base.rstrip("/")
        self._fetch_json = fetch_json or _default_fetch_json
        self.per_page = per_page
        self.source = Source(
            id=f"github:{owner}/{repo}", kind="github",
            name=f"{owner}/{repo}", uri=f"https://github.com/{owner}/{repo}",
        )

    def _get(self, path: str) -> Any:
        return self._fetch_json(f"{self.api_base}{path}")

    def fetch(self) -> list[SourceRecord]:
        sid = self.source.id
        records: list[SourceRecord] = []
        repo = self._get(f"/repos/{self.owner}/{self.repo}")
        records.append(SourceRecord(
            id=f"{sid}:repo", source_id=sid, kind="repo",
            title=f"{self.owner}/{self.repo}",
            body=str(repo.get("description") or ""),
            url=str(repo.get("html_url", "")),
            timestamp=_ts(repo.get("updated_at")),
        ))
        pulls = self._get(
            f"/repos/{self.owner}/{self.repo}/pulls?state=all&per_page={self.per_page}"
        )
        pr_numbers = set()
        for pr in pulls or []:
            pr_numbers.add(pr["number"])
            records.append(SourceRecord(
                id=f"{sid}:pr:{pr['number']}", source_id=sid,
                kind="pull_request",
                title=f"PR #{pr['number']}: {pr.get('title', '')}",
                body=str(pr.get("body") or ""),
                url=str(pr.get("html_url", "")),
                timestamp=_ts(pr.get("updated_at")),
                author=str((pr.get("user") or {}).get("login", "")),
            ))
        issues = self._get(
            f"/repos/{self.owner}/{self.repo}/issues?state=all&per_page={self.per_page}"
        )
        for issue in issues or []:
            if issue["number"] in pr_numbers or "pull_request" in issue:
                continue  # the issues endpoint also returns PRs
            records.append(SourceRecord(
                id=f"{sid}:issue:{issue['number']}", source_id=sid,
                kind="issue",
                title=f"Issue #{issue['number']}: {issue.get('title', '')}",
                body=str(issue.get("body") or ""),
                url=str(issue.get("html_url", "")),
                timestamp=_ts(issue.get("updated_at")),
                author=str((issue.get("user") or {}).get("login", "")),
            ))
        commits = self._get(
            f"/repos/{self.owner}/{self.repo}/commits?per_page={self.per_page}"
        )
        for c in commits or []:
            commit = c.get("commit") or {}
            message = str(commit.get("message", ""))
            records.append(SourceRecord(
                id=f"{sid}:commit:{c['sha'][:12]}", source_id=sid,
                kind="commit",
                title=message.splitlines()[0] if message else c["sha"][:12],
                body=message,
                url=str(c.get("html_url", "")),
                timestamp=_ts((commit.get("author") or {}).get("date")),
                author=str((commit.get("author") or {}).get("name", "")),
            ))
        return records
