# HANDOFF LOG

Append-only. Do not edit or delete prior entries — add a new entry at the
bottom before ending a significant unit of work. Keep entries concise; this
is not a status report.

Use this exact field format:

```
## <Task ID> — <ISO date>

Task ID:
Agent:
Branch:
Base SHA:
Current HEAD:
PR:
Status:
Files changed:
Tests:
CI:
Known blockers:
Next action:
Merge authorized:
Deploy authorized:
```

---

## RCE-20260807-CONTROL — 2026-08-07

Task ID: RCE-20260807-CONTROL
Agent: claude
Branch: chore/agent-control-plane
Base SHA: 5387af1f14888964b463b1fcaed8751d40ecbde6
Current HEAD: (set at commit time — see PR)
PR: (opened as draft against main — see PR link)
Status: review
Files changed: AGENTS.md, CLAUDE.md, .github/copilot-instructions.md, .github/pull_request_template.md, .github/workflows/agent-scope-guard.yml, AI_WORKSPACE/README.md, AI_WORKSPACE/ACTIVE_TASKS.yaml, AI_WORKSPACE/HANDOFF.md
Tests: N/A (governance/docs + read-only CI workflow only, no application code touched)
CI: agent-scope-guard workflow added; not yet observed running on this PR
Known blockers: none
Next action: human review of the draft PR; other agents should register their tasks in ACTIVE_TASKS.yaml if not already present
Merge authorized: no
Deploy authorized: no

## RCE-20260807-API — 2026-08-07

Task ID: RCE-20260807-API
Agent: github-copilot (implementation) / claude (registry reconciliation)
Branch: feat/control-api
Base SHA: 779c4d62af6abe349136e9fb2991b20ef719011e
Current HEAD: 3c2998367e3b8d9b18399cc052b3eccd834dfcab
PR: #6 (verified merged=true, merged_by=Binz2008-star)
Status: complete
Files changed: 6 files (+1276/-6) per PR #6
Tests: 35 passed, 1 warning (self-reported in PR body); GitHub Actions on final head verified PASS
CI: PASS (verified via GitHub)
Known blockers: none
Next action: none — closed. Merged into feat/initial-engine (result SHA 4d85d62ea4951a2eaf057e9f51f1a3b3f96dc647). Not merged to main. No deploy.
Merge authorized: n/a (already merged into feat/initial-engine by human)
Deploy authorized: no

## RCE-20260807-OAUTH — 2026-08-07

Task ID: RCE-20260807-OAUTH
Agent: claude
Branch: feat/youtube-oauth
Base SHA: 4d85d62ea4951a2eaf057e9f51f1a3b3f96dc647
Current HEAD: e7d51cf7ab32c901472598fe5d1c0baa39db72d2
PR: #7 (verified merged=true, merged_by=Binz2008-star)
Status: complete
Files changed: 5 files (+1029/-37) per PR #7
Tests: 65 passed, 1 warning; ruff clean; focused mypy clean; git diff --check clean (self-reported, matches this agent's own prior validation in this session)
CI: PASS
Known blockers: none
Next action: none — closed. Merged into feat/initial-engine (result SHA 741d2c8edf435da4c42bce7448710169307631cc). Real local OAuth smoke completed by the operator on their own machine: authenticated channel confirmed (Channel ID UCIcvbGsmSwMDXxjWXq4QG8A, Custom URL @roben.1). No credentials were read, printed, committed, or logged by any agent. Not merged to main. No deploy. No video uploaded.
Merge authorized: n/a (already merged into feat/initial-engine by human)
Deploy authorized: no

## RCE-20260807-CHANNELSYNC — 2026-08-07

Task ID: RCE-20260807-CHANNELSYNC
Agent: claude
Branch: feat/youtube-channel-sync
Base SHA: 741d2c8edf435da4c42bce7448710169307631cc
Current HEAD: ca307129dc7dd9830c931e8c42628cff57d1c8fc
PR: #8 (verified open, draft, mergeable_state=clean)
Status: CI GREEN / WAITING FOR NEON PRODUCTION MIGRATION AUTHORIZATION
Files changed: 8 files (+942/-2) per PR #8 — .env.example, schema.sql, src/robin_content_engine/channel_repository.py, src/robin_content_engine/cli.py, src/robin_content_engine/config.py, src/robin_content_engine/youtube_sync.py, tests/test_channel_repository.py, tests/test_youtube_sync.py
Tests: 1 GitHub check run ("test") verified completed/success on this head. Granular counts (pytest 73 passed, ruff clean, 1 non-blocking deprecation warning) are self-reported in the PR body/task brief, not independently re-executed by this agent this pass.
CI: PASS (verified)
Known blockers: Neon production migration not applied. Verified/tested on a temporary Neon branch only (self-reported, not independently re-verified this pass — Neon MCP connector connected at org level but not enabled in this chat session): migration_id cf430adc-bc83-4e21-aa4e-162a501682a7, temp branch mcp-migration-2026-08-07T19-31-58 (br-young-brook-axnnlev0), production branch br-lingering-poetry-axoi0r6y. Do not apply to production without explicit human authorization.
Next action: apply verified migration only after explicit human approval, then perform a real authenticated `robin-engine youtube-sync` smoke (verify authenticated Channel ID matches the intended channel, snapshot stored correctly, uploaded video inventory imported, plausible counts, no YouTube write operation), re-run tests + ruff, review exact diff, update ACTIVE_TASKS.yaml + append HANDOFF.md. Keep PR #8 draft until all gates pass.
Merge authorized: no
Deploy authorized: no

## RCE-20260807-CHANNELSYNC — 2026-08-07 (migration applied)

Task ID: RCE-20260807-CHANNELSYNC
Agent: claude
Branch: feat/youtube-channel-sync
Base SHA: 741d2c8edf435da4c42bce7448710169307631cc
Current HEAD: ca307129dc7dd9830c931e8c42628cff57d1c8fc
PR: #8 (still open, draft, mergeable_state=clean — unchanged)
Status: PRODUCTION MIGRATION APPLIED / WAITING FOR REAL LOCAL youtube-sync SMOKE
Files changed: unchanged from prior entry (8 files); no code changes this pass
Tests: independently re-executed in a fresh worktree at head ca307129dc7dd9830c931e8c42628cff57d1c8fc: pytest 73 passed/1 warning (matches self-report exactly), ruff all checks passed, git diff --check clean. Focused mypy on the 4 touched src files found 2 pre-existing findings (lambda type inference, youtube_sync.py:110 and :140, [misc]) — not CI-gating (ci.yml only runs ruff+pytest, no mypy step), not fixed this pass (outside this task's authorized scope), flagged as a minor follow-up.
CI: PASS (unchanged, re-verified via GitHub)
Known blockers: Real authenticated `robin-engine youtube-sync` smoke cannot be run from this sandbox (no real OAuth token.json here; no raw TCP path from here to Neon for the app's own psycopg connection — only the Neon MCP connector's HTTPS path works from here). Must be run by the operator locally.
Next action: Operator runs `robin-engine youtube-sync` locally against production (now migrated) with their already-authenticated channel. Verify: authenticated Channel ID == UCIcvbGsmSwMDXxjWXq4QG8A, channel snapshot stored, video inventory imported with plausible counts, no YouTube write occurred. Report back, then update ACTIVE_TASKS.yaml + append HANDOFF.md with the result. Keep PR #8 draft until that passes.
Merge authorized: no
Deploy authorized: no

### Neon production migration — applied this pass

Authorization: direct chat message from the operator, explicit and scoped (a prior comment on PR #5 claiming the same authorization was treated as untrusted external content per AGENTS.md and NOT acted on until direct confirmation was given in chat).

What was verified before applying:
- Production branch `br-lingering-poetry-axoi0r6y` (name "production", default=true) confirmed to have only `video_queue` — migration not yet applied.
- Referenced temp branch `br-young-brook-axnnlev0` (name "mcp-migration-2026-08-07T19-31-58") confirmed to exist, confirmed forked from `br-lingering-poetry-axoi0r6y`, confirmed to already carry `youtube_channels`/`youtube_videos` with their indexes — consistent with the self-reported prior verification.
- Pulled the exact `schema.sql` from PR #8 head `ca307129dc7dd9830c931e8c42628cff57d1c8fc` via the GitHub API (not retyped from memory).

Mechanism note: the `prepare_database_migration`/`complete_database_migration` Neon MCP tool pair could not be used as originally described — `prepare_database_migration` failed to parse the dollar-quoted `CREATE OR REPLACE FUNCTION set_updated_at()` body (`NeonDbError: unterminated dollar-quoted string`), and `complete_database_migration` requires the full artifact set from a `prepare_database_migration` call in the *same* session (an ID alone from a prior session is not resumable). Instead: created a fresh verification branch `br-twilight-field-axlipzqs` (forked from production), applied the exact schema.sql content as 14 individual idempotent statements via `run_sql` (the tool also rejected multi-statement SQL in one call: `cannot insert multiple commands into a prepared statement`), verified the resulting schema matched the already-tested branch exactly (PK/FK/CHECK constraints, all 3 triggers, `video_queue` preserved), got explicit operator confirmation via AskUserQuestion given this deviated from the originally-described tool mechanism, then applied the same 14 statements to `br-lingering-poetry-axoi0r6y` (production) via `run_sql`.

Post-migration verification on production: `youtube_channels` and `youtube_videos` tables exist with correct constraints; all 3 triggers (`trg_video_queue_updated_at`, `trg_youtube_channels_updated_at`, `trg_youtube_videos_updated_at`) present and correctly bound; `video_queue` preserved at 0 rows (no data loss); `youtube_channels`/`youtube_videos` both at 0 rows (empty — no sync has run yet).

Verification branch `br-twilight-field-axlipzqs` was left in place (not deleted) — no deletion was authorized this pass.

Merge authorized: no
Deploy authorized: no

## RCE-20260807-CHANNELSYNC — 2026-08-07 (Phase 4B CLOSED)

Task ID: RCE-20260807-CHANNELSYNC
Agent: claude
Branch: feat/youtube-channel-sync
Base SHA: 741d2c8edf435da4c42bce7448710169307631cc
Final HEAD (pre-merge): 375fe01fe472399deedc6378a4e3068ef4f3a0c0 (verified via GitHub, matched operator's report exactly)
PR: #8 — marked ready for review, then squash-merged
Status: COMPLETE / CLOSED
Files changed (final): .env.example, schema.sql, src/robin_content_engine/channel_repository.py, src/robin_content_engine/cli.py, src/robin_content_engine/config.py, src/robin_content_engine/youtube_sync.py, tests/test_api.py, tests/test_channel_repository.py, tests/test_youtube_sync.py (9 files, +1059/-4)
Tests: independently re-executed in a fresh worktree at head 375fe01fe472399deedc6378a4e3068ef4f3a0c0: pytest 77 passed/1 warning (matches operator's report exactly — 73 plus 4 new retry-logic tests), ruff all checks passed, git diff --check clean, git status clean.
CI: PASS (verified via GitHub check run "test", completed/success)
Known blockers: none — closed
Next action: Phase 4B closed. Wait for explicit human direction before starting any further phase. New baseline: feat/initial-engine @ 8a55704611bb4ae666951db487013a818f44730c.
Merge authorized: yes — explicit direct chat authorization, scoped to feat/initial-engine only, never main
Deploy authorized: no

### What changed since the last entry (retry hardening)

`ChannelRepository.save_snapshot()` was rewritten to wrap the whole atomic block (channel upsert + is_current reconciliation + per-video upserts, all inside one `conn.transaction()`) in a retry loop: up to 3 attempts, exponential backoff (0.5s, 1s), retrying only on `psycopg.OperationalError` (connection-level failures) — all other exceptions propagate immediately. Reviewed and confirmed safe: because each attempt re-runs the full transaction from a fresh connection and every statement is an idempotent upsert (`ON CONFLICT ... DO UPDATE`), a retry after a transient connection failure cannot produce duplicates or partial state. 4 new tests cover: retry-then-succeed, retry-limit-exhausted propagates the error, transaction boundary preserved across a retry, and idempotent upsert semantics preserved across repeated saves. Separately, `tests/test_api.py`'s `FakeSettings` now points `youtube_client_secret_file`/`youtube_token_file` at nonexistent absolute `/tmp` paths instead of relative `client_secret.json`/`token.json` — avoids tests accidentally picking up a real local credential file if one exists in the working directory (a real risk surfaced by the local OAuth/smoke testing on the operator's machine).

### Real authenticated smoke (operator-reported, not independently re-run by this agent)

`robin-engine youtube-sync` run locally against the now-migrated production Neon: 144 discovered / 144 stored; a second (idempotency) run also 144/144 with no duplicates; authenticated Channel ID `UCIcvbGsmSwMDXxjWXq4QG8A` (matches Phase 4A); a transient Neon `OperationalError` during the run was handled by the new retry logic and completed successfully; no YouTube write operations occurred; no deploy. This agent cannot independently verify this step — no real OAuth `token.json` and no raw TCP path to Neon exist in this sandbox for the app's own psycopg connection.

### Merge

Verified via GitHub before merging: PR #8 `draft: false`, `state: open`, `mergeable_state: clean`, base still `feat/initial-engine`, head still `375fe01fe472399deedc6378a4e3068ef4f3a0c0`. Squash-merged via `merge_pull_request` (method: squash). Merge commit: `8a55704611bb4ae666951db487013a818f44730c`. Verified post-merge: PR #8 `state: closed`, `merged: true`, `merged_by: Binz2008-star`; `feat/initial-engine` fetched and confirmed at `8a55704611bb4ae666951db487013a818f44730c`; `main` independently re-checked and confirmed unchanged at `5387af1f14888964b463b1fcaed8751d40ecbde6` (same SHA as the start of this entire engagement).

Merge authorized: yes (feat/initial-engine only)
Deploy authorized: no

## RCE-20260807-CAPTURE — 2026-08-07 (started)

Task ID: RCE-20260807-CAPTURE
Agent: claude
Branch: feat/local-capture-source
Base SHA: 8a55704611bb4ae666951db487013a818f44730c (verified via `git rev-parse origin/feat/initial-engine` before starting)
Current HEAD: n/a — implementation not started yet, this entry records the task start
PR: none yet — will open draft targeting feat/initial-engine, not main
Status: active
Files changed: none yet
Tests: none yet
CI: n/a
Known blockers: none
Next action: implement src/robin_content_engine/capture_scan.py (new), CLI capture-scan command, tests/test_capture_scan.py, small config.py additions (capture_source_dir, capture_stability_wait_seconds), .env.example documentation. No database.py or schema.sql changes — existing video_queue/enqueue_local()/list_jobs() fully cover this use case (see build_vs_adopt/duplicate_detection_strategy/schema_migration_needed fields on the task entry in ACTIVE_TASKS.yaml for the reasoning).
Merge authorized: no
Deploy authorized: no

Scope reminder for this phase: discovery and registration only — never render, upload, move, rename, or delete original files; no highlight detection, Content Radar, autonomous production, scheduler, or background watcher (those are later phases); no database migration is pre-authorized.

## RCE-20260807-CAPTURE — 2026-08-07 (implementation complete, draft PR open)

Task ID: RCE-20260807-CAPTURE
Agent: claude
Branch: feat/local-capture-source
Base SHA: 8a55704611bb4ae666951db487013a818f44730c
Current HEAD: 2a56d2d1f2004054344933aa040d581e7d7bb332
PR: #9 (draft, targeting feat/initial-engine, not main)
Status: review — CI queued at time of writing
Files changed: src/robin_content_engine/capture_scan.py (new), src/robin_content_engine/cli.py, src/robin_content_engine/config.py, .env.example, tests/test_capture_scan.py (new) — 5 files
Tests: 92 passed/1 warning (77 baseline + 15 new), independently run in the implementation worktree before opening the PR
Ruff: all checks passed
Mypy (focused: capture_scan.py, cli.py, config.py): no issues found
Diff check: clean
CI: queued (GitHub check run "test") at time of writing — this is my own PR, drive-to-green posture applies; self check-in scheduled
Known blockers: none for the implementation. Real local smoke against the actual capture directory still needed from the operator (this sandbox has no access to C:\Users\loyal\Videos\Captures).
Next action: wait for CI; operator runs `robin-engine capture-scan` locally per the smoke instructions below; report result; then update registry and decide on merge.
Merge authorized: no
Deploy authorized: no

### Real local smoke instructions (Windsurf / operator machine)

1. Pull `feat/local-capture-source` (or fetch PR #9) and install: `pip install -e ".[dev]"`
2. Confirm `.env` has `DATABASE_URL` set (existing production Neon — this only writes new `pending` rows to `video_queue`, same as any other `enqueue-local`/`capture-scan` call; nothing is rendered or uploaded).
3. Discover the actual current files in `C:\Users\loyal\Videos\Captures` first — do not assume `Fortnite 2026-08-07 23-14-11.mp4` (or any specific file) still exists; list the directory and use whatever `.mp4`/`.mov`/`.mkv` files are actually present.
4. Run: `robin-engine capture-scan` (uses the default configured directory) or `robin-engine capture-scan --path "C:\Users\loyal\Videos\Captures"` to be explicit.
5. Expected first-run output shape: `Capture scan completed.` / `Directory: ...` / `Videos discovered: N` / `New captures registered: N` (should be > 0 if new files are present) / `Already known: 0` (or however many were already queued from a prior manual `enqueue-local`) / `Skipped unstable: 0` (unless a recording was actively in progress) / `Skipped unsupported: <screenshot/other file count>`.
6. Immediately run it again: `robin-engine capture-scan`. Expected: `New captures registered: 0`, `Already known: N` (same N as the newly-registered count from step 5) — proves idempotency, no duplicate jobs.
7. Verify no originals changed: check file sizes/timestamps in the Captures folder are unchanged from before the scan (the tool never opens files for writing).
8. Verify no render/upload happened: `robin-engine run-once` was **not** invoked by capture-scan, and no YouTube activity should appear — this command only inserts `pending` rows.
9. Optional: inspect the new rows via `robin-engine enqueue-local`'s sibling read path (`GET /api/jobs` if the FastAPI service is running, or a direct read-only query) to confirm `status = 'pending'`, `rights_confirmed = true`, and a `rights_note` mentioning capture-scan provenance.

Report back: discovered/registered/already-known counts from both runs, confirmation originals are untouched, confirmation no render/upload occurred.

## RCE-20260807-CAPTURE — 2026-08-07 (rights-safety correction)

Task ID: RCE-20260807-CAPTURE
Agent: claude
Branch: feat/local-capture-source
Base SHA: 8a55704611bb4ae666951db487013a818f44730c
Current HEAD: ce23bd33e3d61f0e951ac1a8bf23f3640929fdae
PR: #9 (still draft, targeting feat/initial-engine)
Status: review — CI in progress on this head at time of writing
Files changed: src/robin_content_engine/capture_scan.py, tests/test_capture_scan.py
Tests: 96 passed/1 warning (92 baseline + 4 new), ruff clean, focused mypy clean, diff clean — all independently run before pushing
CI: in progress on ce23bd33e3d61f0e951ac1a8bf23f3640929fdae at time of writing
Known blockers: two items from the correction request are unresolved — see below
Next action: wait for CI; get the Neon connector enabled for this chat (or operator runs a direct read-only query) to inspect the 3 existing production rows; operator re-runs capture-scan to confirm the fix
Merge authorized: no
Deploy authorized: no

**IMPORTANT — corrects the previous entry above.** The prior "Real local smoke instructions" entry's step 9 said to confirm `rights_confirmed = true` on new rows — that was describing the buggy pre-fix behavior. It is now `rights_confirmed = FALSE` by design; that old entry is left unedited per the append-only rule, but should not be followed as-is.

### The bug (found by the real local smoke)

The actual capture directory contained gameplay footage (`Fortnite 2026-08-07 23-14-11.mp4`) alongside clearly non-gameplay recordings (`ChatGPT Classic 2026-08-07 23-17-33.mp4`, `ChatGPT Classic 2026-08-07 23-19-45.mp4`). `capture_scan.py` called `JobRepository.enqueue_local()`, which hardcodes `rights_confirmed=TRUE` in its `INSERT` — so all three got auto-confirmed publishing rights just for existing in the configured directory, regardless of content. This violates the principle that discovery/provenance must never automatically equal verified publishing rights.

### The fix

Switched to `JobRepository.enqueue_api_job()` — already existed, unmodified, already took `rights_confirmed` as an explicit parameter — and pass `rights_confirmed=False` for every capture-scan discovery. Rights note changed to: "Discovered from configured local capture directory. Publishing rights require explicit verification before processing." No schema or `database.py` change — smallest possible fix, reused an existing method. This means every capture-scan row is now correctly subject to the existing `quarantine_unconfirmed()` Rights Gate if a pipeline run is ever attempted before explicit confirmation — the gate is engaged correctly, not weakened.

### Item 8 — the 3 existing production rows: NOT YET INSPECTED

The Neon MCP connector is connected at the org level but **not enabled for this chat session**, and this sandbox has no other path to production Neon (no real `.env` credentials here, and no raw TCP egress to Neon from this sandbox even if it did). These 3 rows (for the Fortnite and two ChatGPT Classic files) were **not modified or deleted** — left exactly as the real smoke created them.

**Safest remediation proposal** (pending authorization, once the rows are actually inspected): if any of the 3 rows currently has `rights_confirmed = TRUE` (from the pre-fix code path) and `status = 'pending'`, the safe correction is a targeted `UPDATE video_queue SET rights_confirmed = FALSE, rights_note = '<corrected provenance note>' WHERE id IN (<the 3 specific job IDs>) AND status = 'pending'` — narrowly scoped to exactly those IDs, never a blanket update. This is a production data change and needs explicit authorization before it happens, exactly as requested — not performed in this pass.

### Item 9 — 15 vs 16 unsupported-file count: no code bug found

Reviewed the extension-filtering logic in `scan_captures()`: `entry.suffix.lower() not in ALLOWED_CAPTURE_EXTENSIONS` counts every non-video file as `skipped_unsupported` with no special-casing for hidden/system files — `desktop.ini` (suffix `.ini`) would be counted identically to a `.png`. `Path.iterdir()` does not filter hidden/system files on Windows (that's an Explorer/shell-level default, not an OS-level listing filter). No mechanism in the code would silently drop or miscount `desktop.ini`. Most likely explanation: a difference in how the operator described the count in natural language ("15 PNG files + desktop.ini" could mean 15 total including the ini, or 16 total — ambiguous), or `desktop.ini` not actually being present in the directory at the moment the scan ran. No speculative fix was made, per instruction not to invent one without a confirmed code problem.

## RCE-20260807-CAPTURE — 2026-08-07 (Phase 5 CLOSED)

Task ID: RCE-20260807-CAPTURE
Agent: claude
Branch: feat/local-capture-source
Base SHA: 8a55704611bb4ae666951db487013a818f44730c
Final HEAD (pre-merge): ce23bd33e3d61f0e951ac1a8bf23f3640929fdae (verified via GitHub before merging: CI completed/success, mergeable_state=clean, draft=false, base still feat/initial-engine, head unchanged from prior push)
PR: #9 — body updated to remove stale pre-fix language, marked ready for review, then squash-merged
Status: COMPLETE / CLOSED
Files changed (final): src/robin_content_engine/capture_scan.py, src/robin_content_engine/cli.py, src/robin_content_engine/config.py, .env.example, tests/test_capture_scan.py (5 files)
Tests: independently re-run immediately before merging at head ce23bd33e3d61f0e951ac1a8bf23f3640929fdae: pytest 96 passed/1 warning, ruff all checks passed, focused mypy (capture_scan.py/cli.py/config.py) no issues found, git diff --check clean
CI: PASS (verified via GitHub check run "test", completed/success)
Known blockers: none — closed
Next action: Phase 5 closed. Wait for explicit human direction before starting any further phase. New baseline: feat/initial-engine @ a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1.
Merge authorized: yes — explicit direct chat authorization, scoped to feat/initial-engine only, never main
Deploy authorized: no

### Merge

Verified via GitHub before merging: PR #9 `draft: false`, `state: open`, `mergeable_state: clean`, base still `feat/initial-engine`, head still `ce23bd33e3d61f0e951ac1a8bf23f3640929fdae`, CI still `completed`/`success` on that exact head (re-checked immediately before merging, not reused from an earlier check). Squash-merged via `merge_pull_request` (method: squash). Merge commit: `a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1`. Verified post-merge: PR #9 auto-unsubscribed (merged outcome confirmed by webhook); `feat/initial-engine` fetched and confirmed at `a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1`; `main` independently re-checked and confirmed unchanged at `5387af1f14888964b463b1fcaed8751d40ecbde6` (same SHA as the start of this entire engagement, across all six phases).

### Production remediation — reported, not agent-verified

Operator reported the 3 pre-fix production rows (IDs 6, 7, 8) corrected to `status = pending`, `rights_confirmed = false`, with the corrected provenance `rights_note`, and that no other rows were touched. This agent never independently queried production Neon at any point during this task — the Neon MCP connector remained connected at the org level but not enabled in this chat session throughout. If independent verification is wanted, enable the connector for this chat and it can be checked directly.

Merge authorized: yes (feat/initial-engine only)
Deploy authorized: no

## RCE-20260808-RIGHTS — 2026-08-08 (started)

Task ID: RCE-20260808-RIGHTS
Agent: claude
Branch: feat/rights-approval-flow
Base SHA: a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1 (verified via `git rev-parse origin/feat/initial-engine` and `git pull --ff-only` before starting)
Current HEAD: n/a — implementation not started yet, this entry records the task start
PR: none yet — will open draft targeting feat/initial-engine, not main
Status: active
Files changed: none yet
Tests: none yet
CI: n/a
Known blockers: none
Next action: implement approve/reject/list/show rights-review flow on JobRepository + CLI, per the security decision below.

### Verified current model (before writing any code)

- `video_queue.status` is a fixed CHECK-constraint enum: pending, processing, rendered, uploaded, failed, quarantined — no new status value without a migration.
- `rights_confirmed BOOLEAN`, `rights_note TEXT` — no verified_at/verified_by audit columns exist.
- `quarantine_job(job_id)` already does exactly the atomic-conditional-UPDATE pattern needed for rejection (`WHERE id=%s AND status IN (...)`, rowcount-checked) — reused as the template, not called directly (its precondition is broader than what Phase 6 needs).
- `retry_job(job_id)` requires `rights_confirmed = TRUE` already, so it cannot be used to un-quarantine an already-auto-quarantined unconfirmed row (a gap noted, not solved this phase — out of the narrow scope given).
- No existing method sets `rights_confirmed = TRUE`. This is the actual gap Phase 6 fills.
- `claim_next()`/`claim_job()` only match `status='pending' AND rights_confirmed=TRUE` — so approval alone (leaving status at 'pending') is sufficient to make a row eligible for later processing under the existing rules; no additional code is needed to "enable" it.

### Security decision (per explicit instruction)

No HTTP mutation added. `api.py` is in `forbidden_paths` for this task. Local operator CLI only (`robin-engine rights-*`), reusing `JobRepository` as the domain boundary so a future authenticated Studio surface can call the same methods later without duplicating the rules.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-RIGHTS — 2026-08-08 (implementation complete, draft PR open)

Task ID: RCE-20260808-RIGHTS
Agent: claude
Branch: feat/rights-approval-flow
Base SHA: a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1
Current HEAD: 6686b42a9296f9047e3306aa60c2f5d1d8679202
PR: #10 (draft, targeting feat/initial-engine, not main)
Status: review — CI in progress at time of writing
Files changed: src/robin_content_engine/database.py, src/robin_content_engine/cli.py, tests/test_database.py, tests/test_rights_approval.py (new) — 4 files
Tests: 124 passed/1 warning (96 baseline + 7 repository SQL tests + 21 CLI regression tests), independently run before pushing
Ruff: all checks passed
Mypy (focused: database.py, cli.py): no issues found
Diff check: clean
CI: in progress on 6686b42a9296f9047e3306aa60c2f5d1d8679202 at time of writing — reported once, no self check-in scheduled per this task's explicit no-background-polling instruction
Known blockers: none for the implementation. Real operator smoke against production rows 6/7/8 still needs explicit authorization.
Next action: wait for CI (checked by the operator when they bring the result back); after review, real operator smoke per the plan below, only after explicit authorization.
Merge authorized: no
Deploy authorized: no

### BUILD vs ADOPT

No new dependency. Reuses the existing FastAPI/Pydantic architecture, Typer CLI, and `JobRepository` as the domain boundary — a small domain/CLI workflow does not justify a workflow/agent framework or event bus.

### Approval transition rules

`approve_rights(job_id, note)`: atomic conditional `UPDATE ... WHERE id=%s AND status='pending' AND rights_confirmed=FALSE` (same pattern as the existing `retry_job()`/`quarantine_job()` — not read-then-write). Sets `rights_confirmed=TRUE`, appends to `rights_note` (never overwrites — discovery provenance preserved), leaves `status` at `'pending'`. Returns `None` (safe conflict, no exception, no partial mutation) for any other starting state: already confirmed, in-progress, terminal, or a race where state changed underneath the operator between read and write.

### Rejection/quarantine transition rules

`reject_rights(job_id, reason)`: same atomic pattern and preconditions. Sets `status='quarantined'` (the existing status value — no schema change), `last_error='Rights rejected by operator.'`, appends the reason to `rights_note`. `rights_confirmed` stays `FALSE`. Row and source file are never deleted. Quarantined rows are excluded from `claim_next()`/`claim_job()` by their existing `WHERE status='pending'` clauses.

### Schema migration

No. `video_queue` already had everything needed. No `verified_at`/`verified_by` audit columns were introduced — the append-only `rights_note` carries the verification/rejection history instead, which was judged sufficient for this phase's narrow scope.

### Content-rights boundary (documented in CLI help text)

`rights_confirmed=TRUE` means the operator approves the source's *provenance* to proceed through Robin's rights gate. It does not mean every frame/audio element is copyright-clear, monetization is guaranteed, or YouTube's reused-content policy is satisfied — later quality/rights QA must still catch third-party-content issues before publishing.

### Known limitation (not solved this phase, out of narrow scope)

A row that gets auto-quarantined by the *existing* `quarantine_unconfirmed()` safety net (if the pipeline is ever run before review — `status='quarantined'`, `rights_confirmed=FALSE`) has no path back through `rights-approve`/`rights-reject` (both require `status='pending'`) or `retry_job()` (requires `rights_confirmed=TRUE` already). This is a real gap but was judged out of this phase's narrow scope (the intended flow is capture-scan → pending+unconfirmed → operator review, before any pipeline run) and is noted here rather than silently expanding scope to fix it.

### Proposed real operator smoke plan for IDs 6/7/8 (NOT executed — requires explicit authorization)

Production rows were not touched during implementation (read-only). Proposed plan once authorized:
1. `robin-engine rights-list` — confirm all 3 rows appear (Fortnite + 2× ChatGPT Classic), `rights_confirmed=false`, `status=pending`.
2. `robin-engine rights-show <Fortnite ID>` — confirm fields, especially the discovery `rights_note`.
3. `robin-engine rights-approve <Fortnite ID> --note "Confirmed personally recorded gameplay, no third-party content."` — confirm output shows `rights_confirmed=True`, `status=pending`.
4. `robin-engine rights-reject <ChatGPT Classic ID 1> --note "Not gameplay footage - excluded from this pipeline."` and the same for the second ChatGPT Classic row — confirm `status=quarantined`, `rights_confirmed` stays `false`.
5. `robin-engine rights-list` again — confirm the Fortnite row no longer appears (now confirmed) and neither ChatGPT Classic row appears (now quarantined).
6. Confirm no render/upload occurred (no `run-once` invoked, no YouTube activity).
7. Confirm the source files themselves are untouched.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-RIGHTS — 2026-08-08 (state-machine correction, supersedes prior "known limitation")

Task ID: RCE-20260808-RIGHTS
Agent: claude
Branch: feat/rights-approval-flow
Base SHA: a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1
Prior HEAD (verified before this correction): 6686b42a9296f9047e3306aa60c2f5d1d8679202 (GitHub CI on this exact sha independently confirmed SUCCESS before starting the correction)
Current HEAD: c9054f6f02fbf341885d7b8a479e153d3b86a0b5
PR: #10 (still draft, targeting feat/initial-engine, not main; description updated to document this correction)
Status: review — CI in progress on c9054f6 at time of writing
Files changed: src/robin_content_engine/database.py, src/robin_content_engine/cli.py, tests/test_database.py, tests/test_rights_approval.py — same 4 files as the original implementation, no other paths touched
Tests: 139 passed/1 warning (124 prior baseline + 15 new auto-quarantine regression tests), independently run before pushing
Ruff: all checks passed
Mypy (focused: database.py, cli.py): no issues found
Diff check: clean
CI: in progress on c9054f6f02fbf341885d7b8a479e153d3b86a0b5 at time of writing — checked once after push, no self check-in scheduled per this task's explicit no-background-polling instruction
Known blockers: none for the correction itself. Real operator smoke against production rows 6/7/8 still needs explicit authorization and is unaffected in scope by this fix.
Next action: wait for CI on c9054f6 (operator will bring the result back, or it will be checked on the next turn touching this task); once green, proceed to the same proposed operator smoke plan as before, only after explicit authorization.
Merge authorized: no
Deploy authorized: no

### What triggered this correction

A review (relayed by the operator, independently verified against the actual code in this repository before any change was made) found that `ContentEngine.run_once()` (`pipeline.py`) calls `repository.quarantine_unconfirmed()` before `claim_next()`. That method performs `UPDATE video_queue SET status='quarantined', last_error='Publishing rights were not confirmed.' WHERE status='pending' AND rights_confirmed=FALSE` — moving any not-yet-reviewed discovered capture straight to `quarantined`. The original `list_pending_rights_review()`/`approve_rights()`/`reject_rights()` from the prior handoff entry only matched `status='pending'`, so a single engine run before an operator got to review a capture would strand it: invisible to `rights-list`, and both `rights-approve` and `rights-reject` would return the same safe-conflict `None` as if the job didn't exist in a reviewable state. This directly contradicted the "Known limitation" note in the prior handoff entry, which had judged this out of scope — a CTO-level review correctly identified it as a Phase 6 blocker instead, since it makes the just-built rights-review flow silently unable to recover captures under a common real operational sequence (discover, then a stray/scheduled `run-once` before the operator gets to reviewing).

### Corrected state model

- **Reviewable** (shown by default `rights-list`, mutable by `rights-approve`/`rights-reject`): `rights_confirmed=FALSE` AND (`status='pending'` OR (`status='quarantined'` AND `last_error` exactly equals `AUTO_QUARANTINE_REASON` = `"Publishing rights were not confirmed."`, the literal `quarantine_unconfirmed()` sets)).
- **Not reviewable, permanently excluded from the default list and from both mutations**: `status='quarantined'` with `last_error='Rights rejected by operator.'` (explicit operator rejection — final), any other quarantined state (e.g. `quarantine_job()`'s generic `'Quarantined by operator.'` marker), `rights_confirmed=TRUE` already, or any in-progress/terminal status (`processing`/`rendered`/`uploaded`/`failed`).
- `approve_rights()` now sets `rights_confirmed=TRUE, status='pending', last_error=NULL` (previously left `status`/`last_error` untouched, which was correct only because it never matched an already-quarantined row before). The append-only `rights_note` behavior is unchanged.
- `reject_rights()`'s effect is unchanged (`status='quarantined'`, `last_error='Rights rejected by operator.'`) but its WHERE clause now also accepts the auto-quarantined starting state.
- All three queries remain single atomic conditional `UPDATE`/`SELECT` statements — no read-then-write, no new lock pattern, no schema change.

### Correction to the prior handoff entry

The "Known limitation (not solved this phase, out of narrow scope)" paragraph in the entry immediately above this one is **superseded**: as of `c9054f6`, an auto-quarantined row (`status='quarantined'`, `rights_confirmed=FALSE`, `last_error='Publishing rights were not confirmed.'`) has a full review path again through `rights-approve`/`rights-reject`. Per this repository's append-only handoff convention, that entry's text is left as-is (it was accurate at the time it was written); this entry is the correction of record.

### Explicitly not done in this correction

- `pipeline.py` was not modified — `quarantine_unconfirmed()`'s existing safety behavior is unchanged, only made recoverable.
- `schema.sql` was not modified — no new column, no new status value.
- No HTTP endpoint was added or changed — still CLI-only.
- No new dependency was added.
- Production rows 6/7/8 were not touched.
- PR #10 was not merged, and remains in draft.
- Phase 7 was not started.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-RIGHTS — 2026-08-07/08 (closed: real production smoke + merge)

Task ID: RCE-20260808-RIGHTS
Agent: claude
Branch: feat/rights-approval-flow
Base SHA: a0feaedcf6e47f1aeca0ccc76dbba37d6bc704e1
Final HEAD (PR head at merge time): c9054f6f02fbf341885d7b8a479e153d3b86a0b5
PR: #10 — merged (squash) into feat/initial-engine at c80b1ce54ddbdedf615cb88942fdd7e68c77b613; main was not touched; no deploy occurred. Merged by Binz2008-star.
Status: complete
Merge authorized: no (this agent did not merge; the operator merged directly via GitHub, independently verified below — not something this agent needs merge authority for)
Deploy authorized: no

### Independent verification performed by this agent (not assumed from chat)

- `git fetch origin feat/initial-engine feat/rights-approval-flow` showed `feat/initial-engine` advanced `a0feaed..c80b1ce`, with `c80b1ce` = `feat(rights): add local operator rights verification/approval flow`.
- GitHub `pull_request_read` on PR #10 independently confirmed: `state=closed`, `merged=true`, `merged_by=Binz2008-star`, `head.sha=c9054f6...`, `base.ref=feat/initial-engine`, `merge_commit` matching `c80b1ce...`.
- Exact-head CI on `c9054f6` (the corrected head, see the prior handoff entry) was independently checked via `get_check_runs` as `SUCCESS` before the operator merged.

### Real production rights smoke — attempted and blocked in this agent's sandbox, then executed by the operator

This agent first attempted the authorized real smoke directly (copying the same production `DATABASE_URL` already used earlier in this project into the `feat/rights-approval-flow` worktree, without ever printing it). `robin-engine rights-list` hung and timed out; a raw Python socket connect to the resolved Neon IPs on port 5432 timed out from both addresses (DNS resolution itself succeeded — this is a network-egress restriction in this agent's sandbox, not a DNS or credentials problem, consistent with the same limitation noted earlier in this project for direct Postgres access). The agent's `.env` copy was deleted immediately after confirming the failure; no further attempt was made and no manual SQL was substituted for the CLI decisions.

The operator then ran the smoke themselves, from their own Windows machine (`X:\content engine\Robin-Content-Engine-v2`), on the exact verified branch/head `feat/rights-approval-flow @ c9054f6`, using the real `robin-engine` CLI only (`rights-list`, `rights-show`, `rights-approve`, `rights-reject` — no manual SQL for the rights decisions themselves, matching the task's explicit requirement). Operator-reported results, pasted verbatim into chat:

- Precheck (`rights-show 6/7/8`) matched the expected starting state exactly: job 6 "ChatGPT Classic 2026-08-07 23-17-33" pending/unconfirmed; job 7 "ChatGPT Classic 2026-08-07 23-19-45" pending/unconfirmed; job 8 "Fortnite 2026-08-07 23-14-11" pending/unconfirmed.
- `rights-approve 8 --note "Personally recorded gameplay capture confirmed by operator. ..."` → `Rights approved for job 8. Status: pending. Rights confirmed: True.`
- `rights-reject 6 --note "Not gameplay footage; excluded from Robin gameplay production pipeline."` → `Rights rejected for job 6. Status: quarantined. Rights confirmed: False.`
- `rights-reject 7` with the same note → same result shape for job 7.
- Post-smoke `rights-show` for all three matched the corrected state model exactly: jobs 6 and 7 → `status=quarantined, rights_confirmed=false, last_error='Rights rejected by operator.'`, `rights_note` preserving original discovery provenance plus the appended `Operator rejection: ...` text; job 8 → `status=pending, rights_confirmed=true, last_error=null`, `rights_note` preserving discovery provenance plus the appended `Operator verification: ...` text.
- Final `rights-list` → `No jobs awaiting rights review.`
- No render, worker, upload, or YouTube-write command was reported run during the smoke.

The operator additionally reported a separate, independent read-only query against the production Neon database (run outside this agent's session) confirming the same final `status`/`rights_confirmed`/`last_error` values for rows 6, 7, and 8.

**This agent did not itself execute the production mutation or the post-state verification query** — both were performed by the operator (and, for the DB read, a separate tool/session outside this agent's control) due to this agent's sandbox having no outbound Postgres path to Neon. This entry records the operator's reported results as operator-executed and operator-reported; it is not first-hand verification by this agent, and is written that way deliberately rather than claimed as this agent's own action.

### Overall Phase 6 result

REAL PRODUCTION RIGHTS STATE SMOKE: PASS (operator-executed, operator-reported, cross-checked by the operator via an independent DB read — not independently re-verified by this agent).

PR #10 merged into `feat/initial-engine` only. `main` untouched. No deploy. RCE-20260808-RIGHTS is now `complete` in `AI_WORKSPACE/ACTIVE_TASKS.yaml`.

### Explicitly not authorized by this closure

- Phase 7 (Open-Source Harvest Audit follow-up, or any Highlight Engine implementation) is a separate task and requires its own explicit authorization and its own `AI_WORKSPACE/ACTIVE_TASKS.yaml` registration before any branch or code work begins.
- No merge to `main`.
- No deploy.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HARVEST7A — 2026-08-08 (research delivered, complete)

Task ID: RCE-20260808-HARVEST7A
Agent: claude
Branch: none (research/architecture only — no branch, no implementation code, no dependency install, no production DB access)
Base: feat/initial-engine @ c80b1ce54ddbdedf615cb88942fdd7e68c77b613
Status: complete
Merge authorized: n/a (no code produced)
Deploy authorized: n/a

### What was done

Four parallel read-only research passes (WebFetch against public GitHub/PyPI/docs URLs only — this session's GitHub App access is scoped to this repository only, so mcp__github__ tools were not used against third-party repos):
1. Source-level audit of `divyaprakash0426/autoshorts` — segmentation, audio/motion scoring, semantic classification (confirmed: no kill-feed/HUD detection exists, contrary to what the name implies — it's LLM-based category classification), score fusion, ranking, window selection, overlap handling (confirmed gap — none exists), vertical reframe, CUDA/CuPy/Decord assumptions (CuPy confirmed imported but never called — dead dependency). License: MIT, exact copyright verified.
2. Source-level audit of `mutonby/openshorts` — precise MIT-vs-proprietary license boundary mapped (`cloud/` is billing/entitlement only, zero analysis/render logic; every other file is MIT). Full pipeline audited: dual-engine scene detection, dual-backend transcription with quality-gated fallback, candidate window extraction (backed by cited retention data), two-pass Gemini moment analysis, two-generation vertical reframe (tracking-based v1, render-native v2), FFmpeg composition, karaoke subtitles, concurrency/cleanup patterns. yt-dlp usage confirmed cleanly isolated to one function + one probe script + one CLI branch.
3. PySceneDetect adoption check (BSD-3-Clause confirmed, v0.7.1, pure CPU/numpy/OpenCV, no GPU dependency at all — `AdaptiveDetector` recommended over `ContentDetector` for fast-motion gameplay) + MoneyPrinterTurbo relevant-component audit (MIT confirmed, but bundled fonts/songs are NOT MIT and must be excluded) + ShortGPT (yt-dlp dependency re-confirmed, rejected as a dependency; its resumable step-pipeline pattern noted as a future idea only).
4. ASR benchmark protocol design for the operator's Windows + AMD RX 6800 XT machine — faster-whisper (CPU int8, recommended to adopt), whisper.cpp (Vulkan/AMD path exists but unverified — recommended as the other real benchmark candidate), WhisperX (rejected for now — no AMD/Vulkan/DirectML path documented anywhere in its official docs).

### Deliverable

A full architecture decision matrix (per-project tables covering exact file/function, license, dependencies, hardware assumption, and one of ADOPT/COPY-ADAPT/REIMPLEMENT-IDEA/INSPIRE/REJECT per component), a proposed Phase 7B module architecture (`scene_detector.py`, `highlight_features.py`, `highlight_scoring.py`, `clip_selector.py`, `transcription.py`; `vertical_reframe.py` explicitly deferred to a later phase since nothing renders yet), a GPU-neutral highlight-scoring design separating deterministic signals (this phase) from AI semantic signals (future) from learned analytics signals (explicitly out of scope), and a "smallest useful first implementation" recommendation (ID 8 Fortnite capture → ranked candidate timestamps + scores only, no render/upload/DB write) with proposed dependencies, files, tests, acceptance criteria, and a smoke plan. Full text was delivered directly in chat, not written to a repo file.

### Explicitly not done / not authorized by this task

- No code was written, no feature branch was created, no dependency was installed, no `pyproject.toml` change was made.
- No production database was accessed or modified.
- Phase 7B (actual implementation) was NOT marked active and is NOT authorized by this closure — it requires its own separate explicit authorization and its own task registration.

Merge authorized: n/a
Deploy authorized: n/a

## RCE-20260808-HIGHLIGHT7B — 2026-08-08 (implementation complete, draft PR open)

Task ID: RCE-20260808-HIGHLIGHT7B
Agent: claude
Branch: feat/highlight-intelligence-mvp
Base SHA: c80b1ce54ddbdedf615cb88942fdd7e68c77b613
Current HEAD: 7e34c3289974e3af7c8351ae091f2de30948c5ea
PR: #11 (draft, targeting feat/initial-engine, not main)
Status: review — CI in progress at time of writing
Files changed: pyproject.toml, src/robin_content_engine/{cli.py,models.py} (modified), src/robin_content_engine/{scene_detector.py,highlight_features.py,highlight_scoring.py,clip_selector.py} (new), tests/{test_scene_detector.py,test_highlight_features.py,test_highlight_scoring.py,test_clip_selector.py,test_highlight_scan_cli.py} (new) — 12 files
Tests: 194 passed/1 warning (139 baseline + 55 new), independently run before pushing
Ruff: all checks passed
Mypy (focused: scene_detector.py, highlight_features.py, highlight_scoring.py, clip_selector.py, cli.py, models.py): no issues found
Diff check: clean
CI: in progress on 7e34c3289974e3af7c8351ae091f2de30948c5ea at time of writing — reported once, 60-minute send_later safety-net check-in scheduled (silent unless action needed) per this task's explicit no-background-polling instruction
Known blockers: none for the implementation. Real Windows ID-8 smoke still needs separate explicit authorization.
Next action: wait for CI; after review, real Windows smoke per the plan below, only after explicit authorization.
Merge authorized: no
Deploy authorized: no

### BUILD vs ADOPT (final, executing the Phase 7A harvest audit's decision)

ADOPT: PySceneDetect `AdaptiveDetector` via the `scenedetect-headless` PyPI distribution (bundles `opencv-python-headless` instead of the base `scenedetect` package's GUI-linked `opencv-python`, avoiding a second conflicting OpenCV install — confirmed by direct dependency inspection: bare `scenedetect` hard-requires `opencv-python`, no headless extra exists on that distribution name). REIMPLEMENT CLEANLY (idea only): AutoShorts' audio-energy, motion-activity, and sliding-window candidate search, in NumPy/OpenCV only. INSPIRE: OpenShorts' clip-selection architecture (window building around word/scene boundaries, mean-score comparability across durations). Explicitly excluded: transcription of any kind, vertical reframing, AI/LLM semantic scoring, yt-dlp, OpenShorts `cloud/`, torch/torchaudio/decord/CuPy/CUDA/NVENC.

### Dependencies added

`scenedetect-headless>=0.7.1,<0.8`, `numpy>=2.1,<3`, `opencv-python-headless>=4.10,<5` (pinned to 4.x — 5.0.0 is a very recent major release with no track record). No `scipy` (RMS/spectral flux use NumPy's own `rfft`/`hanning`). Added a narrow `[[tool.mypy.overrides]]` for `scenedetect.*`/`moviepy.*` (neither ships type stubs); this is the only non-dependency `pyproject.toml` change.

### Scoring formula and rationale

`base_activity_score = 0.60 * audio_score + 0.40 * motion_score`, preserving only AutoShorts' broad audio/motion fusion *ratio hypothesis* — not its GPU implementation, not any other constant. `audio_score = 0.5*normalized_rms + 0.5*normalized_spectral_flux` (both are legitimate, uncalibrated-against-each-other audio-energy signals, combined equally). Scene-change density is a **capped bonus**, not a third primary weight: `scene_bonus = min(0.10, 0.10 * normalized_scene_density)` — deliberately small and hard-capped, since fast cuts also happen at menus/respawns/loading screens, which are not highlights. `final_score = base_activity_score + scene_bonus`, bounded to `[0, 1.10]`. Every candidate carries `final_score`, `audio_score`, `motion_score`, `scene_signal`, and a deterministic `reason` string built from fixed thresholds (e.g. `"high audio spike + high motion"`) — never an LLM call.

### Detector configuration

`AdaptiveDetector` via `SceneDetectorConfig` (adaptive_threshold=3.0, min_scene_len_frames=15, window_width=2, min_content_val=15.0 — PySceneDetect's own library defaults, no evidence yet to deviate), optional `downscale` override. Detection only — `detect_scenes()` never invokes PySceneDetect's video-splitting/rendering; verified with a dedicated test asserting zero new files appear after calling it.

### Overlap strategy

`generate_candidate_windows()` runs a cumsum sliding-window search per tested duration (min→max clip seconds, stepped), producing one best-scoring candidate per duration tested; `suppress_overlaps()` then greedily accepts candidates highest-score-first, rejecting any whose temporal IoU with an already-accepted candidate exceeds `overlap_iou_threshold` (default 0.35, not hidden — a `WindowSelectorConfig` field). Neither AutoShorts nor OpenShorts had a complete overlap-handling solution (confirmed during the Phase 7A audit), so this is original to Robin.

### CLI contract

`robin-engine highlight-scan <job_id> [--top N] [--json]`. Requires `rights_confirmed=true` and a valid local `source_path` (rejects missing job, unconfirmed rights, missing/remote source). The only database call is `JobRepository.get_job()` — no claim, no attempts increment, no `generated_*`/`output_path`/`status` write. Never constructs `ContentEngine`, never renders, never uploads. Verified by a `FakeRepository` test double that implements *only* `get_job()`/`running()` — any accidental call to a mutating method would raise `AttributeError` and fail the test.

### JSON contract

`{"job_id", "source_title", "duration_seconds", "candidates": [{"rank", "start_seconds", "end_seconds", "duration_seconds", "score", "signals": {"audio", "motion", "scene"}, "reason"}]}`. Verified end-to-end against a real ~20s synthetic clip (10s black/silence + 10s moving pattern/tone, generated via the `imageio-ffmpeg`-bundled ffmpeg binary already pulled in transitively by moviepy) — the pipeline correctly found the injected signal spike and produced a sensible ranked candidate spanning into it.

### Performance

Deliberately CPU-only by construction (no torch/CUDA anywhere in the new code) so it runs on the operator's Windows + AMD RX 6800 XT machine without any GPU dependency; GPU acceleration was not pursued since correctness for this MVP doesn't require it. Real wall-clock timing against the operator's actual machine and actual ID 8 capture will be captured during the real smoke, not fabricated here.

### Explicitly not done in this phase

- No render, clip/export, captions, transcription, AI/LLM semantic scoring, vertical reframing, upload, YouTube write, queue claiming, or automatic processing.
- No production DB mutation — read-only `get_job()` only.
- No changes to `pipeline.py`, `uploader.py`, `youtube_auth.py`, `api.py`, or `schema.sql`.
- No schema migration.
- No real-machine smoke executed yet — proposed command: `robin-engine highlight-scan 8 --top 5 --json`, pending separate explicit authorization after CI/review.
- PR #11 not merged, remains draft.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HIGHLIGHT7B — 2026-08-08 (candidate-generation correction, PR #11)

Task ID: RCE-20260808-HIGHLIGHT7B
Agent: claude
Branch: feat/highlight-intelligence-mvp
Prior HEAD (CI independently confirmed SUCCESS before this correction): 7e34c3289974e3af7c8351ae091f2de30948c5ea
Current HEAD: 07407aaaef75412cec5f2ea38803d42133b592c7
PR: #11 (still draft, targeting feat/initial-engine, not main)
Status: review — CI queued on 07407aa at time of writing
Files changed: src/robin_content_engine/clip_selector.py, src/robin_content_engine/highlight_scoring.py, tests/test_clip_selector.py — same allowed_paths as the original implementation, no other paths touched
Tests: 196 passed/1 warning (194 prior + 2 new multi-peak regression tests), independently run before pushing
Ruff: all checks passed
Mypy (focused: scene_detector.py, highlight_features.py, highlight_scoring.py, clip_selector.py, cli.py, models.py): no issues found
Diff check: clean
CI: queued on 07407aaaef75412cec5f2ea38803d42133b592c7 at time of writing — checked once after push, 60-minute send_later safety-net check-in scheduled, silent unless action needed
Known blockers: none. Real Windows ID-8 smoke still needs separate explicit authorization and is unaffected in scope by this fix.
Merge authorized: no
Deploy authorized: no

### What triggered this correction

A CTO review found that `generate_candidate_windows()` kept only `np.argmax(window_sums)` - the single best start position - per tested clip duration. With durations 15s/20s/.../60s all searching the same score timeline, their individual best-start positions tend to cluster around whichever one event is strongest, so `suppress_overlaps()` downstream had only near-duplicates of that one event to choose from. Genuinely separate highlights elsewhere in the source were silently discarded before overlap suppression ever got a chance to consider them - directly undermining Phase 7B's actual purpose (find and rank *multiple* distinct gameplay moments). Verified independently before making any change: re-ran the pre-fix algorithm against a synthetic fixture with three widely-separated, clearly-scored events (single tested duration, to remove any ambiguity) and confirmed it produced exactly **one** raw candidate, not three.

### Fix

`generate_candidate_windows()` now computes, for every tested duration, the mean score at **every** valid start position (via `_sliding_means()`, a vectorized cumsum-difference divide - still O(n) per duration, not an O(n × duration) per-candidate loop), builds a `HighlightCandidate` for each one, and only after collecting the full pool across all durations does it globally sort by `(-score, start_seconds)` and truncate to `max_candidates_before_dedup`. `suppress_overlaps()` itself is unchanged. Per-candidate `reason` now comes from the candidate's own aggregate `(audio, motion, scene)` means via a newly-public `highlight_scoring.describe_reason()` (previously a private `_describe_reason()`, used only inside `score_windows()`) rather than borrowing a single peak bin's reason - a necessary side effect of considering every start rather than just one per duration, and arguably a more accurate description of the candidate as a whole.

### Regression tests added

`test_three_distinct_peaks_yield_three_distinct_candidates` and `test_five_distinct_peaks_yield_five_distinct_candidates` in `tests/test_clip_selector.py`: synthetic timelines with 3 and 5 widely-separated elevated regions (region width kept close to the single tested clip duration specifically so one real event cannot itself be split into two low-mutual-IoU candidates), asserting the final top-N selection covers every region exactly once with pairwise IoU below the configured threshold. Both were run against the pre-fix algorithm on the same fixtures and confirmed to fail (1 candidate produced, not 3) before this fix landed - they are genuine regression guards, not tests written to merely pass.

### Explicitly not done in this correction

- No render, transcription, AI/LLM scoring, upload, or DB mutation - unaffected, unchanged scope.
- No changes to `pipeline.py`, `uploader.py`, `youtube_auth.py`, `api.py`, or `schema.sql`.
- No schema migration.
- No real Windows ID-8 smoke executed - still pending separate explicit authorization after this corrected head is reviewed.
- PR #11 not merged, remains draft.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HIGHLIGHT7B — 2026-08-08 (post-smoke duration-boundary correction, PR #11)

Task ID: RCE-20260808-HIGHLIGHT7B
Agent: claude
Branch: feat/highlight-intelligence-mvp
Prior HEAD (CI independently confirmed SUCCESS before this correction): 07407aaaef75412cec5f2ea38803d42133b592c7
Current HEAD: f56ae1b1e65b38cd4d52ceff977cbb14013c6a27
PR: #11 (still draft, targeting feat/initial-engine, not main)
Status: review — CI in progress on f56ae1b at time of writing
Files changed: src/robin_content_engine/clip_selector.py, tests/test_clip_selector.py — same allowed_paths as before, no other paths touched
Tests: 198 passed/1 warning (196 prior + 2 new non-integral-duration regression tests), independently run before pushing
Ruff: all checks passed
Mypy (focused: scene_detector.py, highlight_features.py, highlight_scoring.py, clip_selector.py, cli.py, models.py): no issues found
Diff check: clean
CI: in progress on f56ae1b1e65b38cd4d52ceff977cbb14013c6a27 at time of writing — checked once, no further self-check-in scheduled per this correction's explicit instruction to stop hourly/background polling
Known blockers: none. Real Windows ID-8 re-smoke and any merge still need separate explicit authorization.
Merge authorized: no
Deploy authorized: no

### Real Windows smoke result (operator-executed, first run against 07407aa)

- Source duration: 26.555s. Elapsed analysis time: ~19.84s. Requested `--top 5`, returned 2 candidates.
- Candidate #1: `start_seconds=12.0, end_seconds=26.555, duration_seconds=14.555` - violates `WindowSelectorConfig.min_clip_seconds=15.0`. This is the defect fixed here.

### What triggered this correction

`generate_time_windows()` (`highlight_features.py`) truncates the final bin when the source duration isn't an exact multiple of the 1.0s grid - a 26.555s source produces 26 full 1.0s bins plus one 0.555s final bin, not 27 full bins. `generate_candidate_windows()` (`clip_selector.py`) converted `min_clip_seconds`/`max_clip_seconds` into a bin COUNT using only the *first* window's width as the nominal bin size (`bin_seconds = window_scores[0].window.end_seconds - window_scores[0].window.start_seconds`), implicitly assuming every bin has that same width. A candidate spanning the configured bin count (e.g. 15 bins) could therefore span less real time than `min_clip_seconds` whenever it included the truncated final bin. Verified independently before making any change: reproduced the operator's exact numbers (`start=12.0, end=26.555, duration=14.555`) using the real `generate_time_windows(26.555, 1.0)` output with tail-concentrated activity, via the actual production functions (not a reimplementation).

### Fix

Bin count still decides which durations to search (unchanged). But now, for every candidate, `actual_duration = end_seconds - start_seconds` (the real timestamp span) is computed and validated against `min_clip_seconds`/`max_clip_seconds` (with a `1e-6` second float tolerance for negligible accumulation only, not for genuine shortfalls) before the candidate is kept - any candidate whose real span falls outside the configured bounds is dropped, never padded or extended past the source's actual duration to force a fit. The corrected multi-event candidate generation from `07407aa` (every valid start position considered, not just `np.argmax()` per duration) is unchanged.

### Regression tests added

`test_non_integral_final_bin_does_not_produce_undersized_candidate`: reproduces the exact real-smoke scenario (26.555s source via the real `generate_time_windows()`, tail activity including the truncated final bin) and asserts the defective 12.0s-26.555s candidate never appears, every returned candidate meets `min_clip_seconds`, and the true best 15.0s-real-duration window (11.0s-26.0s) is found instead. `test_all_candidates_respect_real_time_bounds_on_non_integral_duration`: a general sweep over a non-integral-duration timeline with a varied score profile, asserting every candidate's real duration stays within `[min_clip_seconds, max_clip_seconds]`. Both constructed with the real `generate_time_windows()` output, not synthetic exact-second bins (which is exactly why the original test suite didn't catch this).

### Secondary smoke observation (recorded, not actioned yet)

ID 8 is only 26.555s long. With a 15s minimum clip duration and temporal-IoU suppression, it cannot meaningfully test Robin's ability to return five distinct highlights - it remains useful for correctness/performance smoke (and was exactly how this defect surfaced), but qualitative "top 5 highlight intelligence" validation will need a longer (multi-minute) owned Fortnite capture later, under the same rights-safe local-capture boundary as ID 8. Not actioned in this correction - noted for whenever that validation is authorized.

### Explicitly not done in this correction

- No render, transcription, AI/LLM scoring, upload, or DB mutation - unaffected, unchanged scope.
- No changes to `pipeline.py`, `uploader.py`, `youtube_auth.py`, `api.py`, or `schema.sql`.
- No schema migration.
- No real Windows re-smoke executed automatically - per explicit instruction, this is left for the operator.
- PR #11 not merged, remains draft.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HIGHLIGHT7B — 2026-08-08 (closed: merged)

Task ID: RCE-20260808-HIGHLIGHT7B
Agent: claude
Branch: feat/highlight-intelligence-mvp
Base SHA: c80b1ce54ddbdedf615cb88942fdd7e68c77b613
Final HEAD (PR head at merge time): f56ae1b1e65b38cd4d52ceff977cbb14013c6a27
PR: #11 — merged (squash) into feat/initial-engine at 67064bdcacb20df1362c786be6f3046514f5cfa3; main was not touched; no deploy occurred. Merged by Binz2008-star.
Status: complete
Merge authorized: no (this agent did not merge; the operator merged directly via GitHub, independently verified below)
Deploy authorized: no

### Independent verification performed by this agent

- `git fetch origin feat/initial-engine feat/highlight-intelligence-mvp` showed `feat/initial-engine` advanced `c80b1ce..67064bd`, with `67064bd` = `feat(highlight): add deterministic gameplay highlight intelligence MVP (#11)`.
- GitHub `pull_request_read` on PR #11 independently confirmed: `state=closed`, `merged=true`, `merged_by=Binz2008-star`, `head.sha=f56ae1b...`, `base.ref=feat/initial-engine`, matching the merge commit on `feat/initial-engine`.

### What shipped

The full Phase 7B deterministic highlight-intelligence MVP, including the post-implementation CTO-review correction (candidate generation surfacing multiple distinct events instead of clustering on one, HEAD `07407aa`) and the post-real-smoke correction (real-timestamp duration validation fixing the non-integral-source-duration boundary defect the operator's actual ID 8 smoke exposed, HEAD `f56ae1b`, the merged head). `robin-engine highlight-scan <job_id> [--top N] [--json]` is now available on `feat/initial-engine`: read-only, requires `rights_confirmed=true` and a local `source_path`, single `JobRepository.get_job()` call, no render/upload/transcription/AI scoring/DB mutation.

### Open follow-up (not part of this task, not authorized by this closure)

- ID 8 (26.555s) is too short for a meaningful "top 5 distinct highlights" qualitative validation under the default 15s minimum clip duration + IoU suppression. A longer (multi-minute) owned Fortnite capture will be needed for that later, under the same rights-safe local-capture boundary used for ID 8.
- Any further phase - transcription, vertical reframing, AI/LLM semantic scoring, rendering, upload, or a qualitative multi-highlight smoke on a longer capture - is a separate task requiring its own explicit authorization and its own `AI_WORKSPACE/ACTIVE_TASKS.yaml` registration before any branch or code work begins.
- No merge to `main`.
- No deploy.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HIGHLIGHT-DIVERSITY — 2026-08-08 (candidate-diversity correction, PR #12)

Task ID: RCE-20260808-HIGHLIGHT-DIVERSITY
Agent: claude
Branch: fix/highlight-candidate-diversity
Base SHA: 67064bdcacb20df1362c786be6f3046514f5cfa3 (feat/initial-engine, post Phase 7B merge)
Current HEAD: 6e671e905140da2f3076f57cac03b05b28e4ee14
PR: #12 (new, draft, targeting feat/initial-engine, not main)
Status: review — CI in progress at time of writing
Files changed: src/robin_content_engine/clip_selector.py, tests/test_clip_selector.py — 2 files, exactly as expected
Tests: 199 passed/1 warning (198 prior + 1 new regression test), independently run before pushing
Ruff: all checks passed
Mypy (focused: clip_selector.py): no issues found
Diff check: clean
CI: in progress on 6e671e905140da2f3076f57cac03b05b28e4ee14 at time of writing — checked once, 60-minute send_later safety-net check-in scheduled, silent unless action needed
Known blockers: none. Job 19 must NOT be re-run until code review + exact-head CI are both complete, per explicit instruction.
Merge authorized: no
Deploy authorized: no

### Real long-form validation result that triggered this (operator-executed, job 19)

Source duration ~409.055s. Requested `--top 5`, returned only 2 candidates: `389–404s` and `378–398s` — both clustered in the final ~30 seconds of the source, with a mutual IoU of ~0.346 (just under the 0.35 suppression threshold), so `suppress_overlaps()` treated them as "distinct" even though they're really two overlapping views of the same event.

### Root cause (independently verified in the merged code before any change)

`generate_candidate_windows()` (`clip_selector.py`) built the full globally-ranked candidate pool correctly, but then did `return candidates[: config.max_candidates_before_dedup]` (default 50) - truncating the pool **before** `suppress_overlaps()` ever ran. On a long source, the highest-scoring ~50 raw candidates can all be overlapping/diluted variants of one dominant event (every tested duration × every start offset that still substantially covers the same active region), so genuinely distinct but lower-scoring events elsewhere in the video never made it into the pool `suppress_overlaps()` was ever shown - discarded before deduplication got a chance to consider them at all.

### Fix

Removed the pre-dedup cap and the now-dead `max_candidates_before_dedup` field from `WindowSelectorConfig` entirely, rather than raising it to a larger number (explicitly rejected per review guidance - that would only move the failure point to longer sources). The complete globally-ranked pool is now passed straight to `suppress_overlaps()`, which already stops as soon as `top_n` distinct candidates are accepted, so it is the only place a result-size bound belongs. No new bound was reintroduced - ranking/dedup is not the expensive part of this pipeline relative to scene/audio/motion feature extraction, so this is not a premature-optimization risk.

### Regression test

`test_pre_dedup_truncation_no_longer_discards_distinct_earlier_events` (`tests/test_clip_selector.py`): a ~409s synthetic timeline (matching job 19's real length) with one dominant late event and four widely-separated earlier events, using a dense `duration_step_seconds=1.0` so the dominant event alone generates well over 50 raw candidates. Event width is kept exactly at `min_clip_seconds` (15) so each event's own candidates cleanly collapse to a single survivor under IoU suppression - a wider plateau can itself produce two low-mutual-IoU variants of the *same* event (confirmed while designing this fixture: this is exactly the mechanism behind job 19's real 2-near-duplicate-candidate symptom), which is a separate, real characteristic of temporal IoU suppression and not what this correction addresses. The test explicitly proves the fixture reproduces the old defect by simulating the old cap-then-suppress behavior (`ranked[:50]` then `suppress_overlaps()`) on the *same* ranked pool and asserting it yields fewer than 5 candidates, before asserting the actual fix finds all 5 distinct events (one per region) with pairwise IoU within threshold.

### Preserved unchanged

Multi-start candidate generation (prior correction), real-timestamp duration validation (prior correction), the scoring formula, the IoU threshold, the CLI JSON contract, and read-only CLI behavior. No `pipeline.py`, `uploader.py`, `youtube_auth.py`, `api.py`, `schema.sql`, `scene_detector.py`, `highlight_features.py`, `highlight_scoring.py`, or `cli.py` changes.

### Expected impact

Raw candidate counts on long sources increase substantially now that the pool isn't artificially capped pre-dedup (e.g. 17,180 raw candidates for the ~409s test fixture vs. a hard 50 before) - but `suppress_overlaps()`'s existing early-exit-at-`top_n` means the final returned candidate count and the CLI JSON contract shape are unaffected.

### Explicitly not done

- No production DB mutation, no render, no upload, no transcription, no AI scoring, no score-weight tuning.
- Job 19 was **not** re-run - explicitly deferred until code review + exact-head CI are both complete.
- PR #12 not merged, remains draft.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HIGHLIGHT-DIVERSITY — 2026-08-08 (closed: merged, then near-duplicate follow-up split into PR #13)

Task ID: RCE-20260808-HIGHLIGHT-DIVERSITY
Agent: claude
Final HEAD (PR head at merge time): 6e671e905140da2f3076f57cac03b05b28e4ee14
PR: #12 — merged (squash) into feat/initial-engine at d2fe7474667491c83f0ea393e6e43fd6b199f15e; main untouched; no deploy. Merged by this agent under explicit, precisely-scoped operator authorization ("نعمله Ready ثم squash merge إلى feat/initial-engine فقط. لا main ولا deploy") - independently verified afterward via git fetch and the GitHub API, matching exactly.
Status: complete
Merge authorized: yes, for this exact action only (feat/initial-engine, not main, no deploy)
Deploy authorized: no

### Operator-reported real job-19 qualitative results (post PR #12, pre PR #13)

3/5 top candidates graded **A** (genuinely independent regions) - confirms base audio/motion scoring works, no ASR/Vision AI or weight retuning needed. 2/5 graded **B** but assessed as the same event: `389-404s` and `378-398s`. Independently confirmed by this agent: temporal IoU between these two is `9/26 ~= 0.346` - just under the existing `0.35` suppress_overlaps() threshold. Operator's engineering decision: this is a distinct containment/near-duplicate concept, not a threshold tune (0.35->0.34), and is tracked as its own new task/PR rather than folded into PR #12 - see RCE-20260808-HIGHLIGHT-CONTAINMENT / PR #13 below.

Merge authorized: yes (as above, PR #12 only)
Deploy authorized: no

## RCE-20260808-HIGHLIGHT-CONTAINMENT — 2026-08-08 (implementation complete, draft PR #13 open)

Task ID: RCE-20260808-HIGHLIGHT-CONTAINMENT
Agent: claude
Branch: fix/highlight-near-duplicate-containment
Base SHA: d2fe7474667491c83f0ea393e6e43fd6b199f15e (feat/initial-engine, post PR #12 merge)
Current HEAD: 79ad515836d4aae1288d5c6d6e36579d75fea7f6
PR: #13 (draft, targeting feat/initial-engine, not main)
Status: review — CI in progress at time of writing
Files changed: src/robin_content_engine/clip_selector.py, tests/test_clip_selector.py — 2 files, exactly as scoped
Tests: 204 passed/1 warning (199 prior + 5 new), independently run before pushing
Ruff: all checks passed
Mypy (focused: clip_selector.py): no issues found
Diff check: clean
CI: in progress on 79ad515836d4aae1288d5c6d6e36579d75fea7f6 at time of writing - checked once, 60-minute send_later safety-net check-in scheduled, silent unless action needed
Known blockers: none. Job 19 must NOT be re-run until this PR is reviewed and CI is green, per explicit instruction.
Merge authorized: no
Deploy authorized: no

### Fix

`suppress_overlaps()` now rejects a candidate as a duplicate of an already-accepted one if EITHER its temporal IoU exceeds `overlap_iou_threshold` (unchanged, 0.35) OR its containment ratio (`intersection / min(duration_a, duration_b)`, via new `_containment_ratio()`) meets or exceeds a new `containment_threshold` (`WindowSelectorConfig` field, default 0.50). Verified against the exact real numbers: `389-404s` (15s) vs `378-398s` (20s) has IoU~=0.346 (under 0.35, so it would have passed the old check) but containment=9/15=0.60 (over 0.50, so it's now correctly rejected). `suppress_overlaps()` gained a `containment_threshold: float = 0.50` parameter with a default, so the existing CLI call site (which doesn't pass it) needed no change - cli.py stayed outside this task's allowed_paths.

### Regression tests

`test_exact_job19_duplicate_is_rejected` (the real case, now correctly rejected) and `test_genuinely_adjacent_low_overlap_candidates_both_kept` (a real-shaped adjacent-events case, IoU~=0.143/containment=0.25, correctly stays independent) are the two operator-required cases. Plus three supporting tests verifying the exact IoU/containment numbers, config exposure, and ratio symmetry/bounds.

### Explicitly not done

No scoring formula, audio/motion weight, or new signal-source change - per the operator's own review, 3/5 already graded A, so the base scoring doesn't need adjustment yet. No `pipeline.py`, `uploader.py`, `youtube_auth.py`, `api.py`, `schema.sql`, `scene_detector.py`, `highlight_features.py`, `highlight_scoring.py`, or `cli.py` changes. No production DB mutation. Job 19 not re-run - deferred until review + CI. PR #13 not merged, remains draft.

Merge authorized: no
Deploy authorized: no

## RCE-20260808-HIGHLIGHT-CONTAINMENT — 2026-08-08 (closed: merged)

Task ID: RCE-20260808-HIGHLIGHT-CONTAINMENT
Agent: claude
Branch: fix/highlight-near-duplicate-containment
Base SHA: d2fe7474667491c83f0ea393e6e43fd6b199f15e
Final HEAD (PR head at merge time): 69a005307df30ff680a63b70b2a21e7d066798e3
PR: #13 — merged (squash) into feat/initial-engine at 8a0ffa8ec6d8ff86edb42075adea9e7866cd64f5; main was not touched; no deploy occurred. Merged by this agent under explicit, precisely-scoped operator authorization - independently verified afterward via git fetch and the GitHub API, matching exactly.
Status: complete
Merge authorized: yes, for this exact action only (feat/initial-engine, not main, no deploy)
Deploy authorized: no

### Independent verification performed by this agent

- Re-verified PR #13's head (`69a005307df30ff680a63b70b2a21e7d066798e3`) matched the operator's stated value exactly, and exact-head CI was `SUCCESS`, before marking ready and merging.
- After merge: `git fetch origin feat/initial-engine main` showed `feat/initial-engine` advanced `d2fe747..8a0ffa8`, with `8a0ffa8` = `fix(highlight): add near-duplicate containment-ratio dedup criterion (#13)`. `main` confirmed unchanged at `5387af1f14888964b463b1fcaed8751d40ecbde6`.

### Resolution of the open event-level-diversity question

The operator's informal post-fix job-19 re-run surfaced a new close-in-time pair (`389-404s` / `381-396s`, IoU≈0.304, containment≈46.7% - just under this PR's 0.50 threshold) that raised whether a deeper "event-level diversity" mechanism was needed. This agent was explicitly asked to visually judge two timestamp ranges and correctly declined - no access to the actual video file from this sandbox, no camera/game, no Windows environment - and asked the operator to make that call themselves rather than guess. The operator visually confirmed both pairs are **genuinely separate gameplay events** within the same Fortnite match, not near-duplicates. Explicit operator decision, recorded verbatim: do NOT add event-level minimum-separation logic, do NOT change the IoU threshold (0.35), do NOT change the containment threshold (0.50), do NOT change scoring/audio/motion weights. No further code work resulted from this open question.

Merge authorized: yes (as above, PR #13 only)
Deploy authorized: no

## RCE-20260808-HIGHLIGHT7B-QV — 2026-08-08 (CLOSED: PASS)

Task ID: RCE-20260808-HIGHLIGHT7B-QV
Agent: claude (governance/report) + operator (all real execution)
Status: complete — PASS
Final result SHA on feat/initial-engine: 8a0ffa8ec6d8ff86edb42075adea9e7866cd64f5
Merge authorized: n/a (this task itself had no branch/PR/code - see PR #12/#13 above)
Deploy authorized: no

### Closure summary

Phase 7B-QV validated the already-merged deterministic Highlight Intelligence (`robin-engine highlight-scan`) against real owned Fortnite gameplay on the operator's Windows machine, end to end:

1. Real job-19 smoke (source ~409.055s) exposed the pre-dedup-truncation defect → fixed and merged as PR #12 (`d2fe747`).
2. Operator's A/B/C qualitative grading of the corrected output: 3/5 candidates graded **A** (genuinely independent, useful moments) - confirming the base deterministic audio/motion scoring works and does not need ASR/Vision AI or weight retuning. 2/5 graded **B**, later diagnosed as a single near-duplicate pair (`389-404s`/`378-398s`, containment=60%) → fixed and merged as PR #13 (`8a0ffa8`).
3. Operator re-ran the final authorized job-19 smoke against the merged fix: **5 useful candidates returned**.
4. Operator visually confirmed the closest-in-time remaining pair (`389-404s` and `381-396s`) are genuinely **separate gameplay events** in the same match, not a residual near-duplicate - resolving the last open question without any further code change (see RCE-20260808-HIGHLIGHT-CONTAINMENT entry above for detail).

**Final operator decision, recorded verbatim:** Phase 7B-QV = PASS / CLOSED. Do not add event-level minimum-separation/diversity logic. Do not change IoU threshold (0.35). Do not change containment threshold (0.50). Do not change scoring/audio/motion weights.

### What this agent did and did not verify

Independently verified by this agent: both PR merges (via `git fetch` + GitHub API), both PRs' exact-head CI results, all code-level regression tests. **Not** independently verified by this agent (operator-executed and operator-reported only, consistent with this agent having no access to the operator's real Windows machine, real capture files, or real Neon production DB from this sandbox): the actual job-19 wall-clock smoke runs, the A/B/C qualitative grading, and the final visual same-event/different-event judgment. This agent explicitly declined to guess at the visual judgment when asked, and waited for the operator's own review.

### Immediately following this closure

Phase 8A (Clip Cutting MVP) was separately authorized in the same operator message that closed this phase, and registered as its own task (`RCE-20260808-CLIPCUT8A`) with its own branch, allowed_paths, and stop conditions - not implied or auto-authorized by this phase's closure alone.

Merge authorized: n/a
Deploy authorized: no

## RCE-20260808-CLIPCUT8A — 2026-08-08 (implementation complete, awaiting review)

Task ID: RCE-20260808-CLIPCUT8A
Agent: claude
Status: review (draft PR open, not merged)
Branch: feat/highlight-clip-cutting
Base branch/sha: feat/initial-engine @ 8a0ffa8ec6d8ff86edb42075adea9e7866cd64f5
Head sha: 204276bc6d11426159ae504c331a423717cd1e0d
PR: #14 (draft) → https://github.com/Binz2008-star/Robin-Content-Engine-v2/pull/14
Merge authorized: no
Deploy authorized: no

### Build vs Adopt (performed before implementation, per directive)

Confirmed the existing `moviepy` + ffmpeg dependency (already used by `video_editor.py`'s `ShortsRenderer.render()`) is sufficient for accurate local clip extraction. No new video framework/dependency was added. FPS preservation uses moviepy's own `@use_clip_fps_by_default` fallback (confirmed via `inspect.getsource`) by simply omitting `fps=` on `write_videofile()`, rather than any manual detection logic.

### What was implemented

- `src/robin_content_engine/clip_cutter.py` (new): `cut_clip(source_path, output_path, start_seconds, end_seconds) -> CutResult`. Validates start/end ordering, source existence, and refuses to overwrite an existing `output_path`. Extracts via `VideoFileClip.subclipped()` + `write_videofile(codec="libx264", audio_codec="aac", ..., ffmpeg_params=["-movflags","+faststart"])`, matching the project's existing render convention. Never touches `source_path`.
- `src/robin_content_engine/cli.py` (modified): factored the shared read-only job-loading and analysis logic out of `highlight-scan` into two reusable helpers, `_load_rights_confirmed_local_job()` and `_run_highlight_analysis()` (both call only the pre-existing, unmodified `scene_detector`/`highlight_features`/`highlight_scoring`/`clip_selector` functions - the scoring algorithm itself was not duplicated or reimplemented). Added `robin-engine highlight-cut <job_id> --rank <N>`, which loads the job, reruns the same deterministic analysis at `top_n=rank`, selects `selected[rank-1]`, and calls `cut_clip()` to write `work_dir/highlights/job-<id>-highlight-<rank>-<start_ms>-<end_ms>.mp4`, printing job ID, rank, source path, start, end, duration, score, and output path. Never claims the job, never mutates job/rights state, never constructs `ContentEngine`, never calls YouTube/LLM.
- `tests/test_clip_cutter.py` (new, 6 tests): successful cut + duration check, source-file-unchanged, refuses-to-overwrite, rejects end<=start, rejects missing source, rejects end beyond source duration.
- `tests/test_highlight_cut_cli.py` (new, 9 tests): rights-unconfirmed rejected, missing `source_path` rejected, nonexistent source file rejected, invalid rank (too high) rejected, rank 0 rejected before any `get_job()` call, successful cut whose output duration matches `highlight-scan`'s same-rank candidate (proving rank-consistency), never constructs `ContentEngine`, only calls `get_job()` and no mutating repository method (`FakeRepository` implements nothing else, so any mutation attempt would raise `AttributeError` and fail the test), refuses to overwrite an existing output file.

### Validation performed

- `pytest` (full suite, worktree `/home/user/Robin-Content-Engine-v2-clipcut`): all tests pass, including the 15 new ones.
- `ruff check .`: clean (fixed two `E501` line-length and two `RUF046` redundant-`int()` findings during implementation).
- Focused `mypy` on `clip_cutter.py` and `cli.py`: `Success: no issues found in 2 source files`.
- `git diff --check`: clean, no whitespace errors.
- Pushed once to `origin/feat/highlight-clip-cutting`. Checked exact-head CI once (per the no-recurring-polling operating rule): GitHub check run "test" was `in_progress` on `204276b` at the time of checking; not polled further.

### Explicitly not done in this phase (by design)

No vertical crop/reframe, no captions/ASR/LLM, no thumbnail generation, no publishing/upload, no scheduler/analytics, no DB/schema migration, no merge to `feat/initial-engine` or `main`, no deploy, and the real Job 19 cut was **not** run - it requires separate explicit operator authorization after implementation review and confirmed-green exact-head CI, per the directive.
