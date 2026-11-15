"""Run the 30-question test set and print a score.

    python -m evals.run                    # full run: answers + citations (needs a model API key)
    python -m evals.run --retrieval-only   # search quality only, no model calls, no key needed
    python -m evals.run --min-score 27     # exit with an error below 27 correct (for CI)

Web search is switched off during the eval so that results depend only on the company data.
Results are written to evals/results/.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.db import close_pool, connection
from app.embeddings import get_embedder
from app.retrieval import search_documents
from evals.grading import Question, grade, load_questions

RESULTS_DIR = Path("evals/results")


def run_retrieval(questions: list[Question], top_k: int) -> dict:
    """For questions answered from documents: is the right document among the top results?"""
    embedder = get_embedder()
    rows = []
    with connection() as conn:
        for question in questions:
            expected = [g for g in question.sources if any(key.endswith(".md") for key in g)]
            if not expected:
                continue
            ranked = [
                hit.source_path
                for hit in search_documents(conn, embedder, question.question, top_k)
            ]
            first = min(
                (ranked.index(key) + 1 for group in expected for key in group if key in ranked),
                default=None,
            )
            rows.append(
                {
                    "id": question.id,
                    "question": question.question,
                    "expected": [key for group in expected for key in group],
                    "hit": all(any(key in ranked for key in group) for group in expected),
                    "top_rank": first,
                    "retrieved": ranked,
                }
            )
    hits = sum(row["hit"] for row in rows)
    return {
        "top_k": top_k,
        "hits": hits,
        "total": len(rows),
        "top1": sum(row["top_rank"] == 1 for row in rows),
        "mrr": round(sum(1 / row["top_rank"] for row in rows if row["top_rank"]) / len(rows), 3)
        if rows
        else 0.0,
        "rows": rows,
    }


def run_answers(questions: list[Question], workers: int) -> dict:
    from app.agent import Agent
    from app.llm import get_llm

    settings = get_settings()
    agent = Agent(get_llm(settings), get_embedder(), None, settings)

    def answer_one(question: Question) -> dict:
        try:
            result = agent.answer(question.question, allow_web=False)
        except Exception as exc:  # one failed call must not sink the whole run
            return {
                "id": question.id, "category": question.category, "question": question.question,
                "passed": False, "failures": [f"error: {exc}"], "answer": "", "cited": [],
                "tool_calls": [], "latency_ms": 0, "input_tokens": 0, "output_tokens": 0,
            }  # fmt: skip
        cited = [source.key for source in result.sources]
        outcome = grade(question, result.answer, cited)
        return {
            "id": question.id,
            "category": question.category,
            "question": question.question,
            "passed": outcome.passed,
            "failures": outcome.failures,
            "answer": result.answer,
            "cited": cited,
            "tool_calls": result.tool_calls,
            "latency_ms": result.latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(answer_one, questions))

    by_category: dict[str, list[int]] = {}
    for row in rows:
        passed, total = by_category.setdefault(row["category"], [0, 0])
        by_category[row["category"]] = [passed + row["passed"], total + 1]
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "model": agent.model_name,
        "correct": sum(row["passed"] for row in rows),
        "total": len(rows),
        "by_category": by_category,
        "median_latency_ms": latencies[len(latencies) // 2],
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "output_tokens": sum(row["output_tokens"] for row in rows),
        "rows": rows,
    }


def render_report(report: dict) -> str:
    lines = ["# Eval report", "", f"Run at {report['run_at']}.", ""]
    if answers := report.get("answers"):
        lines += [
            f"## Score: {answers['correct']} of {answers['total']} answered correctly",
            "",
            f"Model `{answers['model']}`, web search off. "
            f"Median response time {answers['median_latency_ms'] / 1000:.1f}s. "
            f"Tokens used: {answers['input_tokens']:,} in, {answers['output_tokens']:,} out.",
            "",
            "| Category | Correct |",
            "|---|---|",
            *(f"| {name} | {p} of {t} |" for name, (p, t) in answers["by_category"].items()),
            "",
            "| ID | Result | Question | Sources cited | Why it failed |",
            "|---|---|---|---|---|",
        ]
        for row in answers["rows"]:
            lines.append(
                f"| {row['id']} | {'pass' if row['passed'] else '**FAIL**'} | {row['question']} | "
                f"{', '.join(row['cited']) or '-'} | {'; '.join(row['failures'])} |"
            )
        lines += ["", "## Answers", ""]
        for row in answers["rows"]:
            lines += [f"### {row['id']}", "", row["answer"], ""]
    if retrieval := report.get("retrieval"):
        lines += [
            f"## Document search: right document in the top {retrieval['top_k']} for "
            f"{retrieval['hits']} of {retrieval['total']} questions",
            "",
            f"Right document ranked first for {retrieval['top1']} of {retrieval['total']}; "
            f"mean reciprocal rank {retrieval['mrr']}. Covers the questions whose answer is in a "
            "company document; listing questions go through SQL filters instead.",
            "",
        ]
        misses = [row for row in retrieval["rows"] if not row["hit"]]
        lines += [f"- Missed {row['id']}: {row['question']}" for row in misses]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--retrieval-only", action="store_true", help="skip model calls")
    parser.add_argument("--min-score", type=int, default=0, help="fail below this many correct")
    parser.add_argument(
        "--min-retrieval-hits", type=int, default=0, help="fail below this many retrieval hits"
    )
    parser.add_argument("--workers", type=int, default=1, help="questions answered in parallel")
    parser.add_argument("--only", nargs="*", help="run only these question IDs")
    args = parser.parse_args()

    if args.workers < 1 or args.min_score < 0 or args.min_retrieval_hits < 0:
        parser.error("workers must be positive and score thresholds nonnegative")
    if args.retrieval_only and args.min_score:
        parser.error("use --min-retrieval-hits with --retrieval-only")
    settings = get_settings()
    questions = load_questions()
    if args.only:
        unknown = set(args.only) - {q.id for q in questions}
        if unknown:
            parser.error(f"Unknown question IDs: {sorted(unknown)}")
        questions = [q for q in questions if q.id in set(args.only)]

    report: dict = {"run_at": datetime.now().isoformat(timespec="seconds")}
    try:
        report["retrieval"] = run_retrieval(questions, settings.retrieval_top_k)
        if not args.retrieval_only:
            from app.llm import is_configured, selected_provider

            if not is_configured(settings):
                print(
                    f"The selected model provider ({selected_provider(settings)}) has no API "
                    "key. Add it to .env, or use --retrieval-only."
                )
                return 2
            report["answers"] = run_answers(questions, args.workers)
    finally:
        close_pool()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(report, indent=2, default=str))
    markdown = render_report(report)
    (RESULTS_DIR / "REPORT.md").write_text(markdown)

    retrieval = report["retrieval"]
    print(
        f"Document search: right document in top {retrieval['top_k']} for "
        f"{retrieval['hits']} of {retrieval['total']} questions (MRR {retrieval['mrr']})"
    )
    if answers := report.get("answers"):
        for row in answers["rows"]:
            mark = "PASS" if row["passed"] else "FAIL"
            print(f"  {mark}  {row['id']}  {row['question']}")
            for failure in row["failures"]:
                print(f"          - {failure}")
        print(f"\nScore: {answers['correct']} of {answers['total']} answered correctly")
        if answers["correct"] < args.min_score:
            print(f"Below the required minimum of {args.min_score}.")
            return 1
    if retrieval["hits"] < args.min_retrieval_hits:
        print(f"Below the required retrieval minimum of {args.min_retrieval_hits}.")
        return 1
    print(f"Full report: {RESULTS_DIR / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
