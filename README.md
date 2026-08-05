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

Run `schema.sql` in the Neon SQL editor, then add a local source video:

```sql
INSERT INTO video_queue (source_path, source_title, rights_confirmed)
VALUES ('C:/media/my-gameplay.mp4', 'My original Fortnite match', TRUE);
```

Run one job:

```bash
robin-engine run-once
```

The first YouTube upload requires a local OAuth browser flow. Keep `client_secret.json`, OAuth tokens, `.env`, and generated media out of Git.

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
- Temporary media: isolated under `work/` and removed after success
