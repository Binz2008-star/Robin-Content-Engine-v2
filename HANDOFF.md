# Session Handoff — Robin Content Engine

_Updated: 2026-08-19. Read this first in a new session to resume instantly._

## What this system is

A production pipeline that turns **operator-owned gaming footage** into
auto-published YouTube Shorts: capture-scan → rights approval → highlight
selection → 9:16 reframe + captions → quality gate → AI metadata (Arabic or
English) → private-first upload → flip to public. **Owned/licensed content
only - no internet scraping, ever.**

## Repos (same GitHub remote, different branches)

- Production (active): `X:\content engine\production` — branch `feat/initial-engine`
- Legacy v2: `X:\content engine\Robin-Content-Engine-v2` — branch `feat/vertical-captions-mvp`
- Remote: `https://github.com/Binz2008-star/Robin-Content-Engine-v2.git`
- All work is committed and pushed to `feat/initial-engine`.

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

The operator paused for a PC restart. Everything below is committed + pushed;
no uncommitted work exists. A new session should pick up the NEXT OPEN PR.

1. **PR #20 OPEN (awaiting human review, do NOT merge):**
   `feat/quality-gate-decode-integrity` — quality gate now full-decodes every
   artifact and rejects truncated/corrupt files (`decode_integrity_ffmpeg`).
   Tests + ruff green. If merged, base for later PRs.
2. **PR #21 OPEN (merge pending CI, do NOT close):**
   `feat/highlight-ai-ranking` — AI-assisted candidate ranking.
   `robin-engine highlight-rank <job>` re-runs the deterministic highlight
   analysis (same as highlight-scan), asks DeepSeek to reorder the
   already-selected candidates best-first + suggest a short spoken hook per
   candidate, and writes `work/rankings/job-<id>.json`. Reads per-rank
   transcripts from `work/transcripts/job-<id>-rank-<n>.json` (format
   version 1) when present. Advice-only (never changes job status/rights/
   upload state); deterministic score-order fallback on ANY AI failure, with
   the reason recorded. Ranking report schema: `method`
   (`ai`|`deterministic-fallback`), per-candidate `new_rank`/`original_rank`/
   `hook`/`ai_reason`.
   - REVIEWED 2026-08-19: all 14 checklist items PASS except item 6's
     "missing transcript" clause (missing transcript is treated as OPTIONAL
     input, AI still ranks on signals - matches handoff "if already stored";
     operator accepted by saying "merge on green").
   - CI blocker fixed in `1bcc45e`: `test_rejects_zero_top` asserted the
     literal substring "--top" in typer's colorized "Invalid value" message,
     which CI (ANSI color enabled) splits with escape codes; now asserts on
     `click.unstyle(result.output)`.
   - RESUME: check CI run `32293904605` (in flight at last check) →
     expected outcome = only pre-existing `test_run_production_corrupt_
     captioned_artifact_is_rebuilt_not_reused` fails (fails on base too;
     resolved by PR #20's decode-integrity). If so, **merge PR #21** into
     `feat/initial-engine` (operator said "merge on green"), then re-run
     `production-status` if desired. Do NOT start PR 2 until merged.
3. **PR 2 (NOT started): AI hook integration.** Burn the PR-1 hook as the
   OPENING caption (captioner `segments_to_srt`/`burn_captions` `hook_text`)
   and use it in `build_production_metadata`; persist ASR transcripts to
   `work/transcripts/job-<id>-rank-<n>.json` in the format PR-1's
   `highlight_ranking.load_transcript()` reads (format version 1:
   `{"format_version":1,"segments":[...]}`), so PR 1 can consume them on
   re-runs. Fallback = no hook (PR-1 reports `hook: null`). Must NOT touch
   rights/upload/budget gates.
4. **PR 3 (NOT started): posting-time recommendation.** Read-only report from
   `youtube_videos` (published_at + view_count) suggesting best posting
   windows. No scheduler, no upload authority.

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
