# Session Handoff — Robin Content Engine

_Updated: 2026-08-16. Read this first in a new session to resume instantly._

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

## Guardrails (do not remove)

- Rights gate: captures are never auto-approved; only owned/licensed content.
- Conservative game detection: bare "Black ops"/"Furniture" titles → neutral
  archive metadata (never guess the game).
- Daily upload cap + retry-safe handling of `uploadLimitExceeded`.
- Uploads go private-first, then flip public (`YOUTUBE_PUBLIC_AFTER_UPLOAD`).
- Channel ID pin: uploads abort if the authenticated channel mismatches.
