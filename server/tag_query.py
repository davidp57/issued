"""Tag combinations shared by the web reader and the OPDS feeds.

A query has three lists of tag names:

- ``all``: the comic has every one of them;
- ``any``: the comic has at least one of them;
- ``none``: the comic has none of them.

An empty list puts no constraint, and a query with three empty lists matches
nothing, so an empty form does not dump the whole library.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlencode

from .logging_config import get_logger

logger = get_logger(__name__)

_LISTS = ("all", "any", "none")

# Tag names of one comic: correlated on ``c.id``, filtered by a list of names.
_COMIC_TAG_NAMES = (
    "SELECT t.name FROM comic_tags ct JOIN tags t ON t.id = ct.tag_id "
    "WHERE ct.comic_id = c.id AND t.name IN ({placeholders})"
)


def _clean(names) -> list[str]:
    """Strip, drop blanks and duplicates, keep the first spelling's order."""
    seen: dict[str, None] = {}
    for name in names or []:
        if isinstance(name, str) and name.strip():
            seen.setdefault(name.strip(), None)
    return list(seen)


@dataclass(frozen=True)
class TagQuery:
    all: list[str] = field(default_factory=list)
    any: list[str] = field(default_factory=list)
    none: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, all=None, any=None, none=None) -> "TagQuery":
        """Clean the lists and keep each tag in one list only: all, then any, then none.

        The tags page gives each tag a single state, so a URL that lists a tag
        twice is read the way the page would show it.
        """
        all_tags = _clean(all)
        any_tags = [name for name in _clean(any) if name not in all_tags]
        none_tags = [name for name in _clean(none) if name not in all_tags and name not in any_tags]
        return cls(all=all_tags, any=any_tags, none=none_tags)

    @classmethod
    def from_json(cls, text: str) -> "TagQuery":
        """Read stored criteria; unreadable ones give an empty query, which matches nothing."""
        try:
            data = json.loads(text) if text else {}
        except ValueError:
            logger.warning("Unreadable saved search criteria: %r", text)
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls.build(**{key: data.get(key) for key in _LISTS})

    def to_json(self) -> str:
        return json.dumps({key: getattr(self, key) for key in _LISTS}, ensure_ascii=False)

    def is_empty(self) -> bool:
        return not (self.all or self.any or self.none)

    def query_string(self) -> str:
        """``all=a&any=b&none=c``, repeating a key once per tag."""
        return urlencode([(key, name) for key in _LISTS for name in getattr(self, key)])

    def describe(self) -> str:
        """Human-readable form: ``humour AND (crime OR thriller) NOT read``."""
        parts = list(self.all)
        if self.any:
            joined = " OR ".join(self.any)
            grouped = len(self.any) > 1 and (parts or self.none)
            parts.append(f"({joined})" if grouped else joined)
        text = " AND ".join(parts)
        if self.none:
            excluded = " NOT ".join(self.none)
            text = f"{text} NOT {excluded}" if text else f"NOT {excluded}"
        return text

    def where_sql(self) -> tuple[str, list[str]]:
        """SQL condition on a ``comics`` row aliased ``c``, with its parameters."""
        if self.is_empty():
            return "0", []
        clauses: list[str] = []
        params: list[str] = []
        if self.all:
            placeholders = ",".join("?" * len(self.all))
            clauses.append(
                "(SELECT COUNT(DISTINCT name) FROM ("
                + _COMIC_TAG_NAMES.format(placeholders=placeholders)
                + f")) = {len(self.all)}"
            )
            params += self.all
        if self.any:
            placeholders = ",".join("?" * len(self.any))
            clauses.append("EXISTS (" + _COMIC_TAG_NAMES.format(placeholders=placeholders) + ")")
            params += self.any
        if self.none:
            placeholders = ",".join("?" * len(self.none))
            clauses.append("NOT EXISTS (" + _COMIC_TAG_NAMES.format(placeholders=placeholders) + ")")
            params += self.none
        return " AND ".join(clauses), params
