# Session Handoff — Robin Content Engine

_Updated: 2026-09-03. Read this first in a new session to resume instantly._

## MAJOR CHANGES (2026-09-03): Auto-publish enabled + High quality encoding + Local Ollama integration

**Auto-publish enabled** — `YOUTUBE_PUBLIC_AFTER_UPLOAD=True`:

- Clips now automatically become public after successful private upload
- No manual "make-public" step required for each clip
- Improves workflow efficiency for immediate channel visibility

**High quality encoding settings** — Video bitrate increased from 4000k to 8000k:

- Video bitrate: 8000k (previously 4000k) for better visual quality
- Audio bitrate: 192k for improved audio quality
- Encoding preset: medium (balance between quality and speed)
- FFmpeg params: `-movflags +faststart -tune film -b:v 8000k -b:a 192k`

**Local Ollama integration** — qwen2.5:7b model:

- AI metadata generation uses local Ollama instead of DeepSeek API
- Model: qwen2.5.5:7b running at `http://127.0.0.1:11434/v1`
- Fallback to deterministic English if Ollama unavailable
- Ops scripts pre-configured for local model usage

**Multi-directory scanning** — Expanded capture source support:

- Scans parent directory `C:\Users\loyal\Videos\Captures` and all subdirectories
- Monitors: Call of Duty, cod24-cod, Call of Duty Black Ops 6, Fortnite
- Total discovered: 43 videos across all directories

## What this system is

A production pipeline that turns **operator-owned gaming footage** into auto-published YouTube Shorts: capture-scan → rights approval → highlight selection → 9:16 reframe + captions → quality gate → AI metadata (Arabic or English) → private-first upload → flip to public. **Owned/licensed content only - no internet scraping, ever.**

## Repos (same GitHub remote, different branches)

- Production (active): `X:\content engine\production` — branch `feat/highlight-ai-ranking`
- Legacy v2: `X:\content engine\Robin-Content-Engine-v2` — branch `feat/vertical-captions-mvp`
- Remote: `https://github.com/Binz2008-star/Robin-Content-Engine-v2.git`
- All work is committed and pushed to `feat/highlight-ai-ranking`.

## Current state (snapshot)

- **Queue: 71 jobs total** — 66 uploaded, 5 pending
- **Daily upload cap: 4/day** (`YOUTUBE_MAX_UPLOADS_PER_DAY=4`); reached 4/4 today. Uploads resume tomorrow.
- **Video quality:** 9:16 reframe delivers **1080x1920** (lanczos upscale, CRF 18), quality gate requires >=1080x1920
- **High quality encoding:** 8000k video bitrate + 192k audio bitrate for optimal quality
- **AI Model:** Local Ollama (qwen2.5:7b), running at `http://127.0.0.1:11434/v1`
- **Auto-publish:** Enabled (`YOUTUBE_PUBLIC_AFTER_UPLOAD=True`) — clips automatically become public
- **YouTube Channel:** Robin (UCIcvbGsmSwMDXxjWXq4QG8A) — authenticated
- **Panel:** Available at 127.0.0.1:8765 via `ops/start_control_panel.cmd`

## Key paths

- Finished Shorts: `production\work\highlights\`
- Publish packages: `production\work\ready\`
- Analysis cache: `production\work\analysis\`
- Upload budget: `production\work\upload_budget.json` (today: 4/4, cap reached)
- Daily production driver: `daily_production_runner.py` (OpenCode `/python` path)
- Windows Task Scheduler: `Robin_Daily_Production` (daily at 09:00)
- Scheduled task launcher: `ops\run_production_once.ps1` (legacy, every ~2h)
- Panel launcher: `ops/start_control_panel.cmd`

## Useful commands (run from `production`)

```powershell
$env:ROBIN_APP_ROOT="X:\content engine\production"
$env:PYTHONPATH="X:\content engine\production\src"
$env:DEEPSEEK_API_KEY="not-needed"
$env:DEEPSEEK_BASE_URL="http://127.0.0.1:11434/v1"
$env:DEEPSEEK_MODEL="qwen2.5:7b"
$env:YOUTUBE_PUBLIC_AFTER_UPLOAD=True
$env:YOUTUBE_EXPECTED_CHANNEL_ID="UCIcvbGsmSwMDXxjWXq4QG8A"
# Daily driver:
python daily_production_runner.py
# Or via Windows Task Scheduler:
schtasks /Run /TN "Robin_Daily_Production"
# Legacy:
robin-engine production-run-once --execute-private-upload
```

## IN-PROGRESS WORK — resume here in a new session

1. **Daily driver** (this session): created `daily_production_runner.py`, set up Windows Task Scheduler `Robin_Daily_Production`, uploaded 3 Shorts PRIVATE, cap reached 4/4, remaining jobs `154, 156, 159, 164, 165` pending for tomorrow's run.

2. **Ollama restoration**: `http://127.0.0.1:11434` now reachable; AI metadata generation can use local LLM instead of deterministic English fallback.

3. **TTS integration**: Phase 2 — not integrated in modern production path (ASR caption burn-in only). Separate legacy pipeline exists but does not do highlight selection/reframe.

4. **PRs awaiting review** (from prior session):
   - PR #20: `feat/quality-gate-decode-integrity` — full-decode every artifact, reject corrupt files. Tests + ruff green. Base for later PRs.
   - PR #21: `feat/highlight-ai-ranking` — AI-assisted candidate ranking. Advice-only; deterministic score-order fallback on any AI failure.
   - PR 2: AI hook integration (burn hook as opening caption).
   - PR 3: posting-time recommendation report.

## Guardrails — HARD (a prior draft was reverted for violating these)

- Sourcing stays 100% local. capture_scan.py must NEVER gain internet/HTTP fetch. NO third-party content harvesting.
- rights_confirmed is a MANUAL operator action ONLY. NO auto-approve path, NO AI/heuristic approval.
- Upload cap + channel-ID pin stay hard-enforced; no configurable off switch.
- Uploads stay private-first → flip-to-public.
- NO "AI Strategy Controller" with authority to decide which jobs get sourced/approved/uploaded. AI may only advise.
- Secrets/.env never printed, logged, or committed.

## Guardrails (do not remove)

- Rights gate: captures are never auto-approved; only owned/licensed content.
- Conservative game detection: bare "Black ops"/"Furniture" titles → neutral archive metadata.
- Daily upload cap + retry-safe handling of `uploadLimitExceeded`.
- Uploads go private-first, then flip public (`YOUTUBE_PUBLIC_AFTER_UPLOAD`).
- Channel ID pin: uploads abort if the authenticated channel mismatches.
