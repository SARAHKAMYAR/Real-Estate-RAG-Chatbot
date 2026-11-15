# Contributing

Use Python 3.12 and Node.js 22 or later for the frontend tests.

```bash
python -m pip install uv==0.13.8
uv sync --frozen --extra dev
make lint
make test
```

For database tests, use a dedicated disposable PostgreSQL database with pgvector. Ingestion
synchronizes the index to the input files and removes obsolete records. Never point tests at
a production database. Set `REQUIRE_INTEGRATION=1` when database coverage must be mandatory.

Add focused regression tests for changed behavior. Keep all committed examples fictional.
Run the full paid-model evaluation only with intentionally configured credentials and a
spending budget. Record the revision, model, settings, date and web-search setting alongside
new answer-evaluation results; never replace old measurements with estimated scores.

Use `uv lock` to update dependencies intentionally, then validate the frozen install. If you
change source data, validate the answer key and rerun retrieval checks. If you change an
embedding model/dimension, document the required new index rather than silently reusing an
old one. See SECURITY.md for private vulnerability reporting.
