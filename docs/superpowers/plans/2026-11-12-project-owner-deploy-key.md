# Project ownership and repository credentials implementation plan

Goal: project creators manage their own projects and connect GitHub/Orca with repository-scoped deploy keys.

Spec: user approved the design in chat. Trusted three-person shared Orca account; permanent deletion removes portal data/attachments and preserves Orca folders and GitHub repositories. Legacy ownership is assigned by an administrator. No new paid service or personal token. Main merge, deployment and AWS changes each require fresh confirmation.

Architecture: separate owner/repository/key/fixed-operation tables, central authorization, existing fixed root worker with allowlisted child environment. Private keys stay outside DB/backup. Existing code remains compatible with legacy unowned projects.

Review focus: ownership transfer/blocked accounts/stale jobs; private project owner access; deletion foreign keys and file outbox; private clone waiting for manual key registration; safe SSH host verification, child environment, fixed paths and no raw secret errors; old backup versions and restored credentials absent.

1. [x] Ownership: failing permission/transfer/delete tests; creator assignment, owner/admin management, legacy admin assignment, account deletion guard; permanent portal-only purge.
2. [x] GitHub and keys: failing atomic-create/job/access tests; optional GitHub URL and reserved ID-based folders; fixed key/link operations; shared runtime warning and public-key-only API.
3. [x] Worker: failing environment/key/config/cancellation tests; trusted fixed operations as orca, host key pinning/443, registration waiting, read-check and no false write verification.
4. [x] Backup/UI/docs: backup v4 with immutable v3 compatibility, owner metadata and key re-registration state; management forms/status/recovery guidance.
5. [x] Full tests, client/shell checks, independent read-only review and fixes; feature-branch commit/PR only. Ask separately before main/server/AWS actions.
