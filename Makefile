PY ?= .venv/bin/python

.PHONY: db ingest serve test eval eval-search lint
db:           ## start local Postgres + pgvector without Docker
	scripts/local_db.sh start
ingest:       ## load documents and listings into the database
	$(PY) -m app.ingest
serve:        ## run the API and chat page on http://localhost:8000
	$(PY) -m uvicorn app.main:app --reload --port 8000
test:
	$(PY) -m pytest -q
	node --test tests/test_frontend.mjs
eval:         ## run the 30 questions and print the score
	$(PY) -m evals.run
eval-search:  ## search quality only - no model calls, no API key
	$(PY) -m evals.run --retrieval-only --min-retrieval-hits 17
lint:
	$(PY) -m ruff check . && $(PY) -m ruff format --check .
