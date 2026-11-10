# Public operations portal implementation plan

Goal: add a working public HTTPS portal to the existing EC2, keeping Orca behind its existing authenticated access path.
Spec: PROJECT_SPEC.md and docs/course-review.md. User resumed implementation; AI login remains deferred.
Stack: FastAPI, SQLAlchemy, server-served HTML/CSS/JS, RDS MySQL in deployment and SQLite for isolated local tests, private S3 attachments/backups, Nginx.

- [ ] Task 1: `app/config.py`, `app/models.py`, `app/security.py`, `app/main.py`, `tests/test_portal.py`: meaningful failing integration tests first; authentication, cookie/CSRF checks, projects/notes persistence, input validation, file authorization.
- [ ] Task 2: `app/templates/`, `app/static/`: two screens, login and operations dashboard. Never expose Orca pairing credentials or arbitrary shell commands.
- [ ] Task 3: `app/storage.py`, `app/ops.py`, `tests/test_ops.py`: private object storage; fixed monitoring targets; logical DB plus designated project backup and restore verification. Test real round trip and failure recording.
- [ ] Task 4: `deploy/portal-*`, `scripts/deploy-portal.ps1`: prepare concrete RDS/S3/HTTPS changes and exact cost/retention information before any required new-resource approval. Existing 24-hour EC2 deadline is unchanged.
- [ ] Task 5: deploy to AWS; verify actual RDS persistence, S3 upload/download, public HTTPS login, unauthorized rejection, monitor outage recovery, backup restore, restart behavior. Record anything deferred or blocked.

Review focus: login throttling; expired/revoked sessions; CSRF/Origin enforcement; HTML injection; unauthorized file access; DB/storage outages; credential-free logs; archive traversal and symlinks; RDS/ALB costs survive EC2 shutdown.
Progress ledger: docs/portal-progress.md. Work in the existing dedicated project folder on feat/operations-portal; synced sources remain read-only.

2026-11-10 implementation: portal integration suite 9/9 and operations suite 5/5 passed. Remaining: isolated dependency installation, AWS deployment, public HTTPS, RDS/S3 cost approval, real AWS restore and presentation evidence.

Final: local/EC2 suite 17/17; public HTTPS, RDS/S3 round trip, restart persistence, actual Orca outage/recovery, isolated SQLite restore verified. Both review findings fixed with RED→GREEN tests. Additional regression enforces actual object byte budget. AI login and three-person testing remain deferred. Private progress ledger is intentionally excluded from publication.
