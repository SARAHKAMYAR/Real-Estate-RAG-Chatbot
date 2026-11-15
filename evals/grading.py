"""Deterministic grading for the eval set.

Grading uses fixed rules instead of a second model as judge: the same answer always gets the
same grade, a run costs nothing extra, and a failure names the exact check that failed.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

QUESTIONS_FILE = Path(__file__).with_name("questions.yaml")

# Ways an answer says "this is not in our information".
NOT_FOUND_PHRASES = [
    "couldn't find", "could not find", "can't find", "cannot find", "unable to find",
    "didn't find", "did not find", "don't have", "do not have", "doesn't have", "does not have",
    "no information", "not available", "isn't available", "not listed", "no listings",
    "not included", "isn't included", "not covered", "doesn't mention", "does not mention",
    "doesn't say", "does not say", "doesn't include", "does not include", "not specified",
    "no record", "not in our", "not in the company",
]  # fmt: skip


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    must_include: list[list[str]] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    sources: list[list[str]] = field(default_factory=list)
    not_found: bool = False
    derived: bool = False


@dataclass(frozen=True)
class Grade:
    passed: bool
    failures: list[str]


def load_questions(path: Path = QUESTIONS_FILE) -> list[Question]:
    return [Question(**item) for item in yaml.safe_load(path.read_text(encoding="utf-8"))]


def normalize(text: str) -> str:
    """Lower-case, unify quotes and spaces, and drop thousands separators (1,650 -> 1650)."""
    text = text.lower().replace("’", "'").replace(" ", " ").replace(" ", " ")
    text = re.sub(r"(?<=\d)[.,\s](?=\d{3}(?!\d))", "", text)
    return re.sub(r"\s+", " ", text)


def grade(question: Question, answer: str, cited_keys: list[str]) -> Grade:
    text = normalize(answer)
    cited = {key.lower() for key in cited_keys}
    failures: list[str] = []

    for group in question.must_include:
        if not any(normalize(option) in text for option in group):
            failures.append(f"answer is missing: {' / '.join(group)}")

    for banned in question.must_not_include:
        if normalize(banned) in text:
            failures.append(f"answer should not contain: {banned}")

    for group in question.sources:
        if not any(key.lower() in cited for key in group):
            failures.append(f"did not cite: {' / '.join(group)}")

    if question.not_found and not any(phrase in text for phrase in NOT_FOUND_PHRASES):
        failures.append("answer does not say the information is unavailable")

    return Grade(passed=not failures, failures=failures)
