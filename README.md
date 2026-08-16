# Robin Content Engine v2

A production-oriented Python pipeline for turning **original or properly
licensed** gaming footage into narrated, auto-published YouTube Shorts.

## Non-negotiable content rule

This project is not designed to bypass Content ID, copyright enforcement, or
YouTube reused-content review. Every queued item must be owned by the channel
or covered by a licence that permits editing and publishing. The system only
ingests operator-confirmed local captures and the channel's **own** uploads
(`channel-import`) - there is no internet scraping or third-party content
ingestion. Visual adjustments exist for editorial quality and branding, not
fingerprint evasion.

## How it works

1. **Scan** the local capture directory (Xbox Game Bar / PS4 recordings) and
   register new clips as pending queue jobs - rights are NEVER auto-confirmed.
2. **Approve rights** per clip (CLI or the control-panel Approve button).
3. **Pick the best highlight** - deterministic scene/audio/motion scoring
   over a configurable window (`HIGHLIGHT_MIN_SECONDS`/`HIGHLIGHT_MAX_SECONDS`,
   default production 25-45s).
4. **Cut, reframe to 9:16, caption** (local faster-whisper ASR; uncaptioned
   fallback when no speech).
5. **Quality-gate and package** (duration/aspect/decodability/black-frame checks,
   SHA-256 manifest).
6. **Generate metadata** via DeepSeek - natural Gulf-Arabic or English-for-a-
   mixed-UAE/international audience (`YOUTUBE_METADATA_LANGUAGE`), with a
   deterministic safety validation (no clickbait, no unverifiable claims).
7. **Publish** - private-first, then flipped to public
   (`YOUTUBE_PUBLIC_AFTER_UPLOAD`), at most N times per day
   (`YOUTUBE_MAX_UPLOADS_PER_DAY`, ban-safety cap).

## Repository layout

```text
src/robin_content_engine/
  ai_logic.py         DeepSeek metadata generation + safety validation
  channel_import.py   download own-channel videos -> cut Shorts (yt-dlp)
  channel_metadata.py resumable, quota-aware channel metadata fixer
  cli.py              command-line interface
  config.py           environment configuration (pydantic-settings)
  controlpanel.py     loopback-only browser dashboard
  ops_actions.py      shared operator actions (panel + studio API)
  production_runner.py highlight -> reframe -> caption -> package orchestration
  publishing.py       package validation + private-first upload
  upload_budget.py    per-day upload cap (ban safety)
  uploader.py         resumable YouTube upload
  ...                 legacy ContentEngine pipeline (pipeline.py, tts.py, ...)
schema.sql           PostgreSQL schema
.env.example         required configuration
```

## Local setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate

pip install -e ".[dev]"
pip install -e ".[download]"        # only needed for channel-import (yt-dlp)
copy .env.example .env
```

Run `schema.sql` in the Neon SQL editor, then configure `.env` (database URL,
DeepSeek key, YouTube OAuth files, expected channel ID).

## Operation

### One-shot CLI

```bash
# Register new captures, approve rights, process + upload one job:
robin-engine capture-scan
robin-engine rights-list
robin-engine rights-approve <JOB_ID> --note "Recorded by Robin for Robin Life & Gaming"
robin-engine production-run-once --execute-private-upload
```

### Control panel (recommended)

A loopback-only web dashboard drives the whole pipeline from a browser.
Double-click the desktop icon **"Robin Content Engine"** (or run
`ops\start_control_panel.cmd`) and open `http://127.0.0.1:8765`. The panel has
a built-in **"How to use"** guide; it exposes scan, approve, process+upload,
make-public, metadata-fix, and channel-import actions, plus live queue status.

The same operations are exposed on the existing studio API under
`/api/production/*` (see `api.py`), sharing one implementation in
`ops_actions.py`.

### Channel operations (make Shorts from the channel's own long videos)

```bash
# List long-form (non-Short) channel videos as Short candidates
robin-engine channel-long-videos --min-seconds 60 --limit 20

# Download an own-channel video, cut its top highlight into a 9:16 Short,
# and queue it (add --execute-private-upload to publish immediately).
robin-engine channel-import <VIDEO_ID> [<VIDEO_ID> ...] --no-upload

# Fix titles/descriptions/tags across the channel with AI metadata.
# Resumable + quota-aware: state lives in work/metadata_plan.json.
robin-engine channel-metadata-fix --status
robin-engine channel-metadata-fix --limit 50
robin-engine channel-metadata-fix --apply --max-updates 20 --quota-budget 5000
```

Run `robin-engine youtube-sync` before `channel-metadata-fix` so discovery
reads a fresh snapshot. Imported source titles are normalized via conservative
game detection: a recognized game becomes `<Game> gameplay`, and ambiguous
default capture names (e.g. "Black ops", "Furniture") become neutral
"Archived gameplay" so the AI can never mislabel a clip.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | - | Neon PostgreSQL connection |
| `DEEPSEEK_API_KEY` | - | AI metadata/script generation |
| `YOUTUBE_AI_METADATA` | false | Use DeepSeek metadata for uploads |
| `YOUTUBE_METADATA_LANGUAGE` | arabic | `arabic` or `english` (mixed UAE/international) |
| `YOUTUBE_PUBLIC_AFTER_UPLOAD` | false | Flip each upload to public after private upload |
| `YOUTUBE_MAX_UPLOADS_PER_DAY` | 4 | Ban-safety cap on automatic uploads per day |
| `YOUTUBE_EXPECTED_CHANNEL_ID` | - | Channel pin - uploads abort on mismatch |
| `HIGHLIGHT_MIN_SECONDS` | 15 | Highlight window floor (production 25) |
| `HIGHLIGHT_MAX_SECONDS` | 60 | Highlight window ceiling (production 45) |
| `CAPTURE_SOURCE_DIR` | - | Local capture directory to scan |

## Automation & ban-safety

- The scheduled task runs `ops\run_production_once.ps1` automatically. Set the
  Windows Task Scheduler interval to your cadence (e.g. every 6 hours).
- Only ONE job is processed per run (FIFO), only rights-confirmed, owned or
  licensed footage is ever published.
- `YOUTUBE_MAX_UPLOADS_PER_DAY` caps automatic uploads per calendar day. When
  the cap is reached the pipeline still scans/processes/packages the next job
  but defers the publish to the next day - protecting the channel from
  spam-bot signals and staying inside YouTube's API quota.
- Uploads go out private-first and are flipped to public only afterwards.

## Development

```bash
ruff check .
pytest
```

## Initial safety defaults

- YouTube privacy: `private`, flipped to public only when configured.
- Rights missing: job quarantined (auto-confirm never happens).
- Failed jobs: bounded error message + attempts counter.
- Generated voice files: removed after a successful upload.
- Final rendered video: retained under `work/<job-id>/final.mp4`.
