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
