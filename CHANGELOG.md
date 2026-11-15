# Changes

## 1.1.0 — 15 November 2026

- Bounded browser history and byte size; added a clear-chat control and readable errors.
- Added per-process chat rate/concurrency/body limits, explicit provider timeouts, tool-call
  budgets, host/origin validation and browser security headers.
- Disabled SDK retries for interactive calls and default Groq rate-limit sleeping.
- Guarded ingestion against missing/empty sources, malformed listings and duplicate IDs.
- Synchronized initial database-pool creation; bounded pool waits and SQL statement time.
- Preserved separate citation previews for different passages under the same heading.
- Included structured price/size/status fields in listing source previews.
- Restricted citation URL schemes and default web searches to public-authority domains.
- Added a failing retrieval-quality threshold and required database checks in CI.
- Packaged sample data and evaluation questions; committed a reproducible dependency lock.
- Isolated Docker's database and moved ingestion into a separate startup job.
- Corrected demo/privacy/evaluation wording, revised the video and added regression tests.

The 28/30 answer score is the original recorded baseline. It is not a measurement of 1.1.0.
