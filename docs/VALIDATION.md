# Release validation — 1.1.0

Validated on 15 November 2026, using Python 3.12.16 on macOS arm64. A new virtual environment
was installed from the committed `uv.lock` with the development extra. No model API keys or
paid model/search calls were used during this validation.

| Check | Observed result |
|---|---|
| Frozen dependency installation | Passed; 64 dependency packages plus this project |
| Full Python tests | **44 passed**, including 6 PostgreSQL integration cases |
| Frontend regression tests | **4 passed** using Node's test runner |
| Document retrieval evaluation | **17/17 in top five; 17/17 at rank one; MRR 1.0** |
| Ruff lint / format | Passed |
| Browser smoke test | 23 consecutive exchanges with a stub agent; citation expansion, escaped text and Clear worked |
| Source distribution and wheel | Both built successfully |
| Installed wheel outside checkout | Found all 10 documents, 19 listings, 30 evaluation questions and frontend assets |
| Dependency advisory scan | No known vulnerabilities reported for 64 audited dependencies; no skipped packages |
| Compose configuration | Parsed successfully without resolving a private `.env` |
| Shell helper syntax | Passed `bash -n` |
| Video | 85 seconds, 1280×720 H.264, no audio; revised title/overview/score cards inspected |

The integration run used a separately created temporary PostgreSQL database with pgvector.
It was removed after the checks; existing application data were not used. The retrieval
results are saved in [retrieval-validation.json](retrieval-validation.json).

Regression tests cover missing/empty ingestion input, malformed/duplicate listings, separate
citation snippets, URL scheme/domain rejection, concurrent pool creation, failing retrieval
thresholds, request-rate/body/concurrency limits, tool/time budgets, long frontend history
and readable validation errors. Browser testing used a test-only stub outside the packaged
application, so its responses must not be interpreted as live-model validation.

## Practical limits of this validation

- Docker Compose syntax was checked, but container build/start was not executed because
  Docker daemon access was unavailable. The dependency install, PostgreSQL behavior and
  packaging were tested directly. The first GitHub Actions run remains a remote CI check.
- Live Groq, Claude and Tavily requests were not made. The historical 28/30 answer score was
  not rerun after the code/prompt/data changes; it is not the accuracy of this release.
- Python 3.13 and other operating systems were not exercised locally.
- No Git history came with the source ZIP. Scan any repository history you intend to reuse.
- This is a shareable local demo, not certification of production security or legal accuracy.

The release archive is separately scanned for secrets and checked to exclude local
environments, databases, credentials, build intermediates and private conversation logs.
