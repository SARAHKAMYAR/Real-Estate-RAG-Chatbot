"""Source bookkeeping and citation parsing.

Every passage, listing or web page handed to the model gets a reference number. The model
cites with bracketed numbers like [2]; after the answer is written we map those numbers back
to the sources, so the response only ever lists sources that were really retrieved.
"""

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlsplit

SourceKind = Literal["document", "listing", "web"]


def is_safe_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return (
            parts.scheme.lower() in {"http", "https"}
            and bool(parts.hostname)
            and not parts.username
            and not parts.password
            and not any(c.isspace() or ord(c) < 32 for c in value)
        )
    except ValueError:
        return False


_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Some open models cite in their own style: 【1】 or 【1†L3-L5】 instead of [1].
_ALT_MARKER = re.compile(r"【\s*(\d+)[^】]*】")
# Typographic characters some models emit, mapped to plain ones so IDs like NL-1002 stay
# searchable and copyable: non-breaking hyphen, narrow no-break space, no-break space.
_PLAIN = str.maketrans({"\u2011": "-", "\u202f": " ", "\u00a0": " "})


def normalize_model_text(text: str) -> str:
    return _ALT_MARKER.sub(r"[\1]", text.translate(_PLAIN))


@dataclass(frozen=True)
class Source:
    ref: int
    kind: SourceKind
    key: str  # file name, listing id or URL - stable across requests
    title: str
    locator: str  # where inside the source: section heading, address, site name
    snippet: str
    url: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SourceRegistry:
    """Hands out reference numbers for one question; the same source keeps the same number."""

    def __init__(self) -> None:
        self._by_identity: dict[tuple[str, str, str, str], Source] = {}

    def add(
        self,
        kind: SourceKind,
        key: str,
        title: str,
        locator: str,
        snippet: str,
        url: str | None = None,
    ) -> int:
        identity = (kind, key, locator, hashlib.sha256(snippet.encode()).hexdigest())
        if url is not None and not is_safe_url(url):
            url = None
        if identity not in self._by_identity:
            ref = len(self._by_identity) + 1
            self._by_identity[identity] = Source(ref, kind, key, title, locator, snippet, url)
        return self._by_identity[identity].ref

    def all(self) -> list[Source]:
        return list(self._by_identity.values())

    def get(self, ref: int) -> Source | None:
        return next((s for s in self._by_identity.values() if s.ref == ref), None)


def resolve_citations(answer: str, registry: SourceRegistry) -> tuple[str, list[Source]]:
    """Return the answer with unknown reference numbers removed, and the sources it cites
    in order of first appearance."""
    cited: dict[int, Source] = {}

    def keep_known(match: re.Match) -> str:
        known = []
        for raw in match.group(1).split(","):
            source = registry.get(int(raw))
            if source:
                cited.setdefault(source.ref, source)
                known.append(str(source.ref))
        return f"[{', '.join(known)}]" if known else ""

    cleaned = _MARKER.sub(keep_known, normalize_model_text(answer))
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip(), list(cited.values())


def strip_citations(text: str) -> str:
    """Remove citation markers, e.g. before replaying an earlier answer as conversation history
    (its numbers would clash with the numbering of the new question)."""
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\s*" + _MARKER.pattern, "", text)).strip()
