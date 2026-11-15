# Security and deployment scope

This repository is a local portfolio demo, using fictional data. The Compose API binds only
to loopback; its database has no host port. Demo database credentials and the conda helper's
local trust authentication must not be reused for an internet-facing deployment.

## Reporting a vulnerability

Do not post API keys, private data or exploit details in a public issue. If the repository's
Security tab offers **Report a vulnerability**, use that private channel. Otherwise contact
the maintainer privately through the contact route on their GitHub profile. Maintainers
should enable private vulnerability reporting when creating the repository.

## Before operating a hosted service

- Add authentication or suitable anonymous-user abuse controls, TLS, trusted proxy handling,
  distributed rate limits, per-account quotas and provider spending caps. The in-process
  limits reset on restart and are not shared across workers.
- Use unique database credentials, isolated networking and a runtime role with only the
  permissions it needs. Separate schema migrations/ingestion from the serving role; this
  demo's bootstrap path creates schema objects and uses the same role for both.
- Index only authorized content. There is no tenant isolation or document-level access policy.
- Review model/search provider data handling and retention before accepting real user data.
  A prompt is not an authorization boundary. Web queries are selected by the model.
- Define backup, migration, monitoring and incident-response procedures. Test shutdown,
  outages, load and recovery. Provider timeouts are not a hard end-to-end cancellation system.
- Maintain the lock file, scan the deployment image and review security updates. Base-image
  tags remain mutable; use a reviewed digest for a production release.

Never commit `.env`, provider keys, real customer documents, database volumes or raw private
conversation logs. If a credential was committed, revoke/rotate it and inspect history;
adding it to `.gitignore` does not remove old commits.
