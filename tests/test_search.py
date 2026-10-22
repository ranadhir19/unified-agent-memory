"""Lexical search ranking."""

from unified_agent_memory.models import MemoryDoc
from unified_agent_memory.search import search, tokenize


def _doc(path, title, body):
    return MemoryDoc(path=path, title=title, body=body)


def test_tokenize_drops_stopwords():
    assert tokenize("What is the deploy target?") == ["deploy", "target"]


def test_search_ranks_title_matches_first():
    docs = [
        _doc("topics/misc.md", "Misc", "git appears once in passing"),
        _doc("tools/git.md", "Git", "git branches and git rebase workflows"),
    ]
    hits = search(docs, "git rebase", k=2)
    assert hits[0].path == "tools/git.md"


def test_search_empty_query_returns_nothing():
    docs = [_doc("a/b.md", "B", "content")]
    assert search(docs, "the and of", k=3) == []
