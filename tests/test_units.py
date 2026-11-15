"""Fast tests with no database, model or network."""

import json
from pathlib import Path

from app.chunking import parse_markdown
from app.retrieval import reciprocal_rank_fusion
from app.sources import SourceRegistry, resolve_citations, strip_citations
from evals.grading import Question, grade, load_questions, normalize

DATA = Path(__file__).resolve().parent.parent / "app" / "data"


def test_markdown_is_chunked_by_heading():
    doc = parse_markdown("# Fees\n\nintro\n\n## Selling\n\nA.\n\nB.\n\n## Buying\n\nC.\n", "x")
    assert doc.title == "Fees"
    assert [(c.heading, c.content) for c in doc.chunks] == [
        ("Overview", "intro"),
        ("Selling", "A.\n\nB."),
        ("Buying", "C."),
    ]


def test_long_sections_split_at_paragraphs_only():
    body = "\n\n".join(" ".join(["word"] * 100) for _ in range(3))
    doc = parse_markdown(f"# T\n\n## Long\n\n{body}\n", "x", max_words=220)
    assert [len(c.content.split()) for c in doc.chunks] == [200, 100]
    assert {c.heading for c in doc.chunks} == {"Long"}


def test_rrf_rewards_agreement_between_rankings():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"]])
    assert [item for item, _ in fused][0] == "b"
    assert {item for item, _ in fused} == {"a", "b", "c", "d"}


def _registry() -> SourceRegistry:
    registry = SourceRegistry()
    registry.add("document", "fees.md", "Fees", "Selling", "1.35%")
    registry.add("listing", "NL-1002", "NL-1002 - House", "Merelstraat 17", "desc")
    return registry


def test_same_source_keeps_its_number():
    registry = _registry()
    assert registry.add("document", "fees.md", "Fees", "Selling", "1.35%") == 1
    assert len(registry.all()) == 2


def test_citations_resolve_in_order_and_drop_unknown_numbers():
    answer, cited = resolve_citations(
        "Price is X [2]. Fee is 1.35% [1, 7]. Unknown [9].", _registry()
    )
    assert answer == "Price is X [2]. Fee is 1.35% [1]. Unknown."
    assert [s.key for s in cited] == ["NL-1002", "fees.md"]


def test_alternative_citation_styles_and_typographic_characters_are_normalised():
    answer, cited = resolve_citations(
        "NL\u20111002 costs €689\u202f000【2】, fee 1.35%【1†L3-L5】.", _registry()
    )
    assert answer == "NL-1002 costs €689 000[2], fee 1.35%[1]."
    assert [s.key for s in cited] == ["NL-1002", "fees.md"]


def test_strip_citations():
    assert strip_citations("Two months [3]. Then [1, 2] more.") == "Two months. Then more."


def test_normalize_drops_thousands_separators_only():
    assert normalize("€3,950 or € 689.000 at 1.35%") == "€3950 or € 689000 at 1.35%"


def test_grading_checks_facts_sources_and_refusals():
    question = Question("q", "c", "?", must_include=[["3950"], ["1.35"]], sources=[["fees.md"]])
    assert grade(question, "It is 1.35%, minimum €3,950.", ["fees.md"]).passed
    assert not grade(question, "It is 1.35%, minimum €3,950.", []).passed
    assert not grade(question, "It is 1.35%.", ["fees.md"]).passed

    negative = Question("n", "c", "?", not_found=True, must_not_include=["NL-1"])
    assert grade(negative, "I couldn’t find that in our information.", []).passed
    assert not grade(negative, "Sure, it is 5%.", []).passed
    assert not grade(negative, "I couldn't find it, but see NL-1001.", []).passed


def test_eval_set_is_consistent_with_the_data():
    """Guards the answer key: every expected source exists and contains the expected facts."""
    questions = load_questions()
    assert len(questions) == 30
    assert len({q.id for q in questions}) == 30

    corpus = {p.name: p.read_text() for p in (DATA / "documents").glob("*.md")}
    corpus |= {
        item["id"]: json.dumps(item) for item in json.loads((DATA / "listings.json").read_text())
    }

    for q in questions:
        keys = [key for group in q.sources for key in group]
        assert all(key in corpus for key in keys), f"{q.id}: unknown source"
        assert q.not_found or (q.must_include and q.sources), f"{q.id}: nothing to check"
        if q.derived:
            continue
        haystack = normalize(" ".join(corpus[key] for key in keys).replace("_", " "))
        for group in q.must_include:
            assert any(normalize(o) in haystack for o in group), f"{q.id}: {group} not in sources"
