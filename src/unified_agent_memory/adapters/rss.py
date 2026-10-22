"""RSSAdapter: RSS 2.0 and Atom feeds, parsed with the standard library."""

from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

from ..models import Source, SourceRecord

_ATOM = "{http://www.w3.org/2005/Atom}"


def _parse_date(text: Optional[str]) -> float:
    if not text:
        return 0.0
    text = text.strip()
    try:
        return parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


class RSSAdapter:
    def __init__(
        self,
        feed_url: str,
        name: str = "",
        fetch_text: Optional[Callable[[str], str]] = None,
    ):
        self.feed_url = feed_url
        self._fetch_text = fetch_text or self._default_fetch_text
        slug = feed_url.split("//", 1)[-1].split("/")[0]
        self.source = Source(
            id=f"rss:{slug}", kind="rss", name=name or slug, uri=feed_url
        )

    @staticmethod
    def _default_fetch_text(url: str) -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": "unified-agent-memory"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="replace")

    def fetch(self) -> list[SourceRecord]:
        xml = self._fetch_text(self.feed_url)
        root = ET.fromstring(xml)
        records: list[SourceRecord] = []
        if root.tag.endswith("feed"):  # Atom
            for entry in root.findall(f"{_ATOM}entry"):
                title = _text(entry.find(f"{_ATOM}title"))
                summary = _text(entry.find(f"{_ATOM}summary")) or _text(
                    entry.find(f"{_ATOM}content"))
                link_el = entry.find(f"{_ATOM}link")
                link = link_el.get("href", "") if link_el is not None else ""
                eid = _text(entry.find(f"{_ATOM}id")) or link or title
                records.append(SourceRecord(
                    id=f"{self.source.id}:{eid}", source_id=self.source.id,
                    kind="feed_item", title=title, body=summary, url=link,
                    timestamp=_parse_date(_text(entry.find(f"{_ATOM}updated"))),
                ))
            return records
        channel = root.find("channel") if root.tag.endswith("rss") else root
        if channel is None:
            return records
        for item in channel.findall("item"):
            title = _text(item.find("title"))
            body = _text(item.find("description"))
            link = _text(item.find("link"))
            guid = _text(item.find("guid")) or link or title
            records.append(SourceRecord(
                id=f"{self.source.id}:{guid}", source_id=self.source.id,
                kind="feed_item", title=title, body=body, url=link,
                timestamp=_parse_date(_text(item.find("pubDate"))),
            ))
        return records
