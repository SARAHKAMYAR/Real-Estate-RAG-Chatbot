"""Split a markdown document into retrieval chunks along its headings.

Company documents are written as short sections that each answer one kind of question, so a
section is the natural unit to retrieve and to cite. A section longer than `max_words` is
split further at paragraph boundaries; paragraphs themselves are never cut.
"""

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Chunk:
    heading: str
    content: str


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    chunks: list[Chunk]


def _pack_paragraphs(paragraphs: list[str], max_words: int) -> list[str]:
    packed: list[str] = []
    current: list[str] = []
    count = 0
    for paragraph in paragraphs:
        words = len(paragraph.split())
        if current and count + words > max_words:
            packed.append("\n\n".join(current))
            current, count = [], 0
        current.append(paragraph)
        count += words
    if current:
        packed.append("\n\n".join(current))
    return packed


def parse_markdown(text: str, fallback_title: str, max_words: int = 220) -> ParsedDocument:
    title = fallback_title
    sections: list[tuple[str, list[str]]] = []
    heading = "Overview"
    lines: list[str] = []
    seen_title = False

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match and len(match.group(1)) == 1 and not seen_title:
            title = match.group(2)
            seen_title = True
            continue
        if match:
            sections.append((heading, lines))
            heading, lines = match.group(2), []
        else:
            lines.append(line)
    sections.append((heading, lines))

    chunks: list[Chunk] = []
    for section_heading, section_lines in sections:
        body = "\n".join(section_lines).strip()
        if not body:
            continue
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        for part in _pack_paragraphs(paragraphs, max_words):
            chunks.append(Chunk(heading=section_heading, content=part))
    return ParsedDocument(title=title, chunks=chunks)
