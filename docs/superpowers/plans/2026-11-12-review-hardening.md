# Review hardening implementation plan

Goal: resolve all items in the main review, merge tested changes, deploy to the existing single EC2.

Architecture: retain FastAPI/SQLAlchemy/plain JavaScript, one worker and existing private RDS/S3. Add separate metadata tables without destructive ALTERs. No new paid service, no shell input API, no AI login.

Spec: the user's accepted review in this chat (P0/P1 corrections and P2 quota, ACL preview, notification preferences, diagnostics).

## Constraints and decisions
- Preserve other people's files and existing stop deadlines. Do not restart stopped resources or extend paid operation without a confirmed window.
- Keep project restrictions explicit even when their final group is removed.
- Centralize idle/forced-password/role checks for HTTP and WebSocket; GET polling never extends activity.
- Back up business data and public identity mappings, never credentials, sessions or TOTP seeds; restore identities blocked with unusable passwords.
- Reuse one worker with locks, atomic upserts and audience-scoped change signals.
- Deployment requires current main, green checks, preflight file hashes, backup, additive schema creation, health verification and rollback.

## Review focus
- Last group removed and legacy ACL migration: remain restricted.
- Deleted chat files and failed storage deletion: inaccessible immediately, retry durable.
- Restarted process and WebSocket idle: same persisted session policy.
- Backlog >200 and concurrent reads/logins: no skipped messages or regressed cursor.
- Restore latest schema into empty target: ACL, groups, tasks, chat files preserved without reusable credentials.

## Tasks (execute in this session)
1. [x] Add failing regressions for ACL, deletion, TOTP, idle, pagination and recovery; implement security fixes and additive migrations.
2. [x] Versioned complete business backup with safe identity mappings, validation and restore roundtrip.
3. [x] Atomic read cursor/login/reaction handling, scoped wakeups, batched queries and bounded uploads/retention.
4. [x] ACL preview, notifications, request IDs and redacted diagnostics; update usage/help/ERD/operations and evidence.
5. [x] Full tests, concurrency/load checks and independent final review; fix findings and run required checks.
6. [ ] Push branch, merge main after CI; preflight AWS, deploy with rollback, verify HTTPS/RDS/S3 and unchanged shutdown deadline.

Validation: 108 Python tests, 2 client regressions; isolated local 10/30/100 load probe. Independent review important findings fixed. Main merge/server/AWS gates pending user confirmation.
