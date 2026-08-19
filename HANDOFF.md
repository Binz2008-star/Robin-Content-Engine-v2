# Session Handoff — Robin Content Engine

_Updated: 2026-08-20. Read this first in a new session to resume instantly._

## What this system is

A production pipeline that turns **operator-owned gaming footage** into
auto-published YouTube Shorts: capture-scan → rights approval → highlight
selection → 9:16 reframe + captions → quality gate → AI metadata (Arabic or
English) → private-first upload → flip to public. **Owned/licensed content
only - no internet scraping, ever.**

## Repos and branch strategy (updated 2026-08-20)

- **`main` is now the trunk.** The entire production engine landed on `main`
  via PR #1 (2026-08-19) plus PR #5 (governance control plane). All NEW work
  must branch from `main`, not from `feat/initial-engine`.
- Production (active): `X:\content engine\production` — switch this worktree
  to `main` (it currently tracks `feat/initial-engine`; `feat/initial-engine`
  has been merged into `main`, so a fast-forward/pull then `git switch main`
  is clean).
- Legacy v2: `X:\content engine\Robin-Content-Engine-v2` — branch `feat/vertical-captions-mvp`
- Remote: `https://github.com/Binz2008-star/Robin-Content-Engine-v2.git`
- CI runs on PRs and on pushes to `main`. Job timeout raised to 30m
  (2026-08-20) — the full suite + install was flaking out at 15m.

### Merge record (2026-08-20, CTO session)

- PR #1 `feat/initial-engine` → `main` — production trunk landed. Merge commit `bc079b2b`.
- PR #5 `chore/agent-control-plane` → `main` — governance layer (AGENTS.md,
  scope guard, task registry). Merge commit `8a5e0a5e`.
- PR #20 `feat/quality-gate-decode-integrity` → `feat/initial-engine` (now in
  main) — quality gate full-decodes artifacts, rejects corrupt/truncated
  files. Merge commit `268b1bbe`.
- PR #21 `feat/highlight-ai-ranking` → `feat/initial-engine` (now in main) —
  AI-assisted candidate ranking (advice-only). Merge commit `bd364eef`.
- CI infra: `.github/workflows/ci.yml` `timeout-minutes` 15 → 30.
- Mypy is configured (strict) but NOT yet a CI gate — see Open Work.

## How to start the app

1. Double-click the desktop icon **"Robin Content Engine"** (or run
   `ops\start_control_panel.cmd`) → starts the control panel + opens
   `http://127.0.0.1:8765`.
2. The panel has a built-in **"How to use"** guide. Buttons: scan captures,
   approve rights, process+upload, make-public, metadata-fix, channel-import.

## Current state (snapshot)

- **Queue: 109 pending Shorts** (jobs #34→#145), all rights-confirmed, cut
  from the channel's own long videos. First in queue: #34 Roblox, #36 CoD
  Zombies, #37-41 Apex, #42/44 neutral "Archived gameplay".
- **23 uploaded**, 0 failed, 8 quarantined (non-gaming/rejects + 7s clip).
- **Daily upload cap: 4/day** (`YOUTUBE_MAX_UPLOADS_PER_DAY=4`) — raised
  from 2 now that YouTube's `uploadLimitExceeded` cool-down has resolved.
- **HD channel-import downloads (2026-08-19):** imports are capped at
  360p because the no-cookie android yt-dlp client is the only working
  path. To get 720p/1080p sources, export a browser `cookies.txt`, set
  `YOUTUBE_COOKIES_FILE` in `.env`, and re-import. Existing downloads
  aren't re-fetched (idempotent cache) — delete the specific
  `work/downloads/<id>.mp4` file first to force a re-download. Imported
  jobs now record source resolution in the rights note (HD/SD), and SD
  downloads log a warning.
- **Video quality overhaul (2026-08-19):** the 9:16 reframe now always
  delivers **1080x1920** (lanczos upscale, CRF 18, was: tiny 200-360p crops
  at a fixed 4000k bitrate), caption burn-in re-encodes at CRF 18 (was 23),
  and the quality gate now **requires >=1080x1920** (`min_resolution`).
  Old low-resolution artifacts fail the gate and are auto-rebuilt at full
  resolution on the next run — no manual cleanup needed.
- **YouTube `uploadLimitExceeded` resolved** — the earlier daily-limit
  throttle cleared after the cool-down; uploads are back to the normal
  cap. If it ever returns, verify the channel in YouTube Studio (Settings →
  Channel → Feature eligibility → Verification); do NOT try to bypass.
- **Metadata corrections: DONE on YouTube** — 24 "Furniture" + 12 "Black
  ops" captures retitled to neutral archive titles; 2 verified-Apex videos
  (`N1IMHGr3Lx0`, `sQert_40bmc`) retitled to Apex. Metadata plan is cleared.
- **Snapshot refreshed** (192 videos). Panel running on 127.0.0.1:8765.

## Key paths

- Finished Shorts: `production\work\highlights\`
- Publish packages: `production\work\ready\`
- Downloaded sources: `production\work\downloads\`
- Analysis cache: `production\work\analysis\`
- Upload budget: `production\work\upload_budget.json`
- Scheduled task launcher: `ops\run_production_once.ps1` (every ~2h)
- Panel launcher: `ops\start_control_panel.cmd`

## Useful commands (run from `production`)

```powershell
$env:ROBIN_APP_ROOT="X:\content engine\production"; $env:PYTHONPATH="X:\content engine\production\src"
$env:YOUTUBE_EXPECTED_CHANNEL_ID="UCIcvbGsmSwMDXxjWXq4QG8A"
& "X:\content engine\.venv\Scripts\python.exe" -m robin_content_engine.cli <command>
```

- `production-status` / `production-status --json` — queue overview
- `production-run-once --execute-private-upload` — process + upload next job
- `capture-scan` → `rights-list` → `rights-approve <id> --note "..."` — new clips
- `channel-long-videos` — list Short candidates
- `channel-import <ID> --no-upload` — cut a channel video into a Short (no upload)
- `channel-metadata-fix --status` / `--apply --max-updates N` — fix titles
- `youtube-sync` — refresh the channel snapshot (BEFORE metadata-fix)

## IN-PROGRESS WORK — resume here in a new session

Everything on the trunk is committed, pushed, and CI-green. A new session
should branch from `main`.

1. **PR 2 (NOT started): AI hook integration.** Burn the PR-21 hook as the
   OPENING caption (captioner `segments_to_srt`/`burn_captions` `hook_text`)
   and use it in `build_production_metadata`; persist ASR transcripts to
   `work/transcripts/job-<id>-rank-<n>.json` in the format PR-21's
   `highlight_ranking.load_transcript()` reads (format version 1:
   `{"format_version":1,"segments":[...]}`), so the ranking can consume them
   on re-runs. Fallback = no hook (ranking reports `hook: null`). Must NOT
   touch rights/upload/budget gates.
2. **PR 3 (NOT started): posting-time recommendation.** Read-only report from
   `youtube_videos` (published_at + view_count) suggesting best posting
   windows. No scheduler, no upload authority.
3. **Infra (NOT started): make mypy a CI gate.** `mypy strict` is configured
   but never runs in CI. Add `mypy src` to `.github/workflows/ci.yml`.
   Expect to fix a handful of pre-existing type issues when first enabled
   (a numpy-stub/Python-version conflict was noted in Phase 10).
4. **Open decision (operator): Studio disposition.** PRs #2/#3
   (`feat/studio-ui`, `feat/studio-api-readiness`) are a React/Vite + FastAPI
   sub-project frozen since 2026-08-06 and stale relative to the engine. The
   registered task RCE-20260807-STUDIO is `status: review`, "Frozen pending
   live FastAPI integration". CTO recommendation: either revive as a separate
   repo rebased on `main`, or close the PRs and archive the branch. Do not
   merge into the production lineage as-is.

## Guardrails — HARD (a prior draft was reverted for violating these)

- Sourcing stays 100% local. capture_scan.py must NEVER gain internet/HTTP
  fetch. NO third-party content harvesting (Pexels/Pixabay/Commons/scraping
  are explicitly rejected).
- rights_confirmed is a MANUAL operator action ONLY. NO auto-approve path,
  NO AI/heuristic approval, NO `AUTO_CONFIRM_LOCAL_CAPTURES`.
- Upload cap + channel-ID pin stay hard-enforced; no configurable off switch.
- Uploads stay private-first → flip-to-public.
- NO "AI Strategy Controller" with authority to decide which jobs get
  sourced/approved/uploaded. AI may only advise (ranking, hooks, metadata).
- Secrets/.env never printed, logged, or committed.

## Guardrails (do not remove)

- Rights gate: captures are never auto-approved; only owned/licensed content.
- Conservative game detection: bare "Black ops"/"Furniture" titles → neutral
  archive metadata (never guess the game).
- Daily upload cap + retry-safe handling of `uploadLimitExceeded`.
- Uploads go private-first, then flip public (`YOUTUBE_PUBLIC_AFTER_UPLOAD`).
- Channel ID pin: uploads abort if the authenticated channel mismatches.
