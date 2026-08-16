# Robin Content Engine v2

A production-oriented Python pipeline for turning **original or properly licensed** gaming footage into narrated YouTube Shorts.

## Non-negotiable content rule

This project is not designed to bypass Content ID, copyright enforcement, or YouTube reused-content review. Every queued item must be owned by the channel or covered by a licence that permits editing and publishing. Visual adjustments exist for editorial quality and branding, not fingerprint evasion.

## MVP workflow

1. Claim one `pending` job from Neon PostgreSQL using an atomic row lock.
2. Reject jobs without an explicit rights confirmation.
3. Generate validated JSON metadata with DeepSeek: `title`, `description`, `tags`, and `script`.
4. Generate an Arabic UAE voiceover with Edge TTS.
5. Convert the source to a 9:16 Short, mix the voiceover, and preserve safe audio levels.
6. Upload as **private by default** through the YouTube Data API.
7. Store the YouTube ID, metadata, attempts, timestamps, and failure details.

## Repository layout

```text
src/robin_content_engine/
  ai_logic.py       DeepSeek metadata generation
  config.py         environment configuration
  database.py       Neon queue and job state transitions
  models.py         validated domain models
  pipeline.py       orchestration and cleanup
  tts.py            Edge TTS voice generation
  uploader.py       resumable YouTube upload
  video_editor.py   9:16 editorial transformation
  cli.py            command-line interface
schema.sql           PostgreSQL schema
.env.example         required configuration
```

## Local setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
copy .env.example .env       # Windows
# cp .env.example .env      # macOS/Linux
```

Run `schema.sql` in the Neon SQL editor. Then queue footage that you own or are licensed to publish:

```bash
robin-engine enqueue-local "C:\media\my-gameplay.mp4" ^
  --title "My original Fortnite match" ^
  --rights-note "Recorded by Robin for Robin Life & Gaming" ^
  --confirm-rights
```

On macOS/Linux, replace `^` with `\` for multiline commands.

Render one job without uploading:

```bash
robin-engine run-once --render-only
```

Process and upload one job:

```bash
robin-engine run-once
```

The first YouTube upload requires a local OAuth browser flow. Uploads default to
`private`. Keep `client_secret.json`, OAuth tokens, `.env`, and generated media out of Git.

## Channel operations

```bash
# List long-form (non-Short) channel videos as Short-extraction candidates
robin-engine channel-long-videos --min-seconds 60 --limit 20

# Download an own-channel video, cut its top highlight into a 9:16 Short,
# and publish it (uses YOUTUBE_AI_METADATA + YOUTUBE_PUBLIC_AFTER_UPLOAD).
# Requires the optional yt-dlp dependency (pip install -e ".[download]").
robin-engine channel-import <VIDEO_ID> [<VIDEO_ID> ...]

# Fix titles/descriptions/tags across the channel with AI Arabic metadata.
# Resumable + quota-aware: state lives in work/metadata_plan.json, so a
# quota-limited run resumes later instead of re-burning API quota.
robin-engine channel-metadata-fix --status
robin-engine channel-metadata-fix --limit 50
robin-engine channel-metadata-fix --apply --max-updates 20 --quota-budget 5000
```

Run `robin-engine youtube-sync` before `channel-metadata-fix` so the
discovery reads a fresh snapshot of titles/descriptions.

## Control panel (browser dashboard)

A loopback-only web dashboard lets you run the whole pipeline from a browser
instead of the command line. Double-click the desktop icon
**"Robin Content Engine"** (or run `ops\start_control_panel.cmd`) to start it
and open `http://127.0.0.1:8765`.

Buttons: scan captures, refresh the channel snapshot, process + upload the
next job, make private uploads public, fix channel metadata, import a channel
video as a Short, and approve rights directly from the queue table.

The same operations are exposed on the existing studio API under
`/api/production/*` (see `api.py`), sharing one implementation in
`ops_actions.py`.

## Development

```bash
ruff check .
pytest
```

## Initial safety defaults

- YouTube privacy: `private`
- Remote downloading: not enabled in the MVP
- Missing rights confirmation: job is quarantined
- Failed jobs: retain a bounded error message and increment attempts
- Generated voice files: removed after a successful upload
- Final rendered video: retained under `work/<job-id>/final.mp4`
