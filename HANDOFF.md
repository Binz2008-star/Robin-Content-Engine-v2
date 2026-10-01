# Session Handoff — Robin Content Engine

_Updated: 2026-10-01. Read this first in a new session to resume instantly._
_Per-task detail lives in `AI_WORKSPACE/HANDOFF.md` (append-only) and
`AI_WORKSPACE/ACTIVE_TASKS.yaml` (registry)._

## What this system is

A production pipeline that turns **operator-owned gaming footage** into
auto-published YouTube Shorts: source footage → highlight selection → 9:16
reframe + captions → quality gate → AI metadata (Arabic or English) →
private-first upload → flip to public. **Owned/licensed content only - no
third-party content, no scraping, no Content-ID evasion, ever.**

## BIG CHANGE (2026-09-28): the operator PC is gone

Production used to run on the operator's Windows PC
(`X:\content engine\production`, Task Scheduler every ~2h, token.json and
`.env` on that disk). **That PC is no longer available.** Consequences:

- Nothing has been produced by the engine since mid-August. The queue holds
  131 `pending` jobs whose `source_path` points at files on that PC - they
  can never run again and should be treated as dead (do NOT feed them to
  `production-run-once`; it would quarantine them one by one).
- The PC-less replacement is the **cloud runner** (GitHub Actions + Google
  Drive + Neon), merged to `main` in PR #27 - see below. It is **not live
  yet**: it waits on the owner's one-time setup.

## Repos and branch strategy

- `main` is the trunk. New work branches from `main`.
- Remote: `https://github.com/Binz2008-star/Robin-Content-Engine-v2.git`
- CI (`.github/workflows/ci.yml`, 30 min): ruff + **blocking mypy** + full
  pytest on PRs and pushes to `main`. Scope guard runs on PRs.
- Database: Neon project `content-engine` (`snowy-rice-24899849`), tables
  `video_queue`, `youtube_channels`, `youtube_videos`, `oauth_tokens` (added
  2026-09-30; empty until the owner's one-time sign-in).

### Merge record

- 2026-08-19/20: PR #1 (trunk), #5 (governance), #20, #21, #22 (AI hook),
  #23 (mypy gate), #24 (posting-report), #25 (tags coercion, 2026-08-29).
- **2026-09-28: PR #26 → `main`, merge commit `2ceee2b`** (owner-authorized):
  - CI fix: `types-yt-dlp` 2026-09-12 renamed a private stub symbol and
    silently broke the mypy gate on `main`; now pinned exactly.
  - `robin-engine game-report`: read-only per-game performance report.
- **2026-09-30: PR #27 → `main`, merge commit `6802bfb`** (owner-authorized):
  the cloud runner - read-only download probe, Drive (Takeout) footage
  source incl. loose >4 GB videos, segment ledger, `drive-produce`, phone
  sign-in with encrypted token in Neon, daily workflow + DB daily cap, setup
  guide. Same day the owner-approved `oauth_tokens` table was added to
  production Neon (tested on a temporary branch first).

### Open PRs

- PRs #2/#3 (`feat/studio-*`): frozen since 2026-08-06. Open operator
  decision - revive as a separate repo or close. Do not merge as-is.

## Channel state (Neon snapshot 2026-08-28 + owner screenshot 2026-09-28)

- Robinzo `UCIcvbGsmSwMDXxjWXq4QG8A`: **29 subscribers, 227 videos**
  (snapshot said 27 / 204; it is a month stale - run `youtube-sync` once the
  cloud runner has credentials).
- Shorts carry ~81% of views; the 101 long videos have a median of **1 view**
  (they are the raw material for new Shorts).
- **Fortnite Shorts perform best** (top 3 videos = 36% of all views; two
  newer "Fortnite Highlight" Shorts ~1K views each).
- Conversion problem: ~0.5% of views became subscribers. 47 videos share 14
  duplicate titles. Posting stopped after a burst (82 uploads in August).
- Title audit: the 23 engine uploads match their capture names. 7 videos
  have junk titles ("Ggg", "Live PS4 Broadcast") but PS-native tags confirm
  the game - suggested titles were given to the owner. 180 titles cannot be
  verified without looking at frames.

## The cloud runner (PR #27) - how it works

Daily at 16:00 UTC (20:00 Dubai), `.github/workflows/daily-short.yml`:
1. `youtube-token-materialize` - decrypts the stored YouTube token (Neon
   `oauth_tokens`, Fernet, key HKDF-derived from the service-account key)
   into a 0600 temp `token.json`; refuses any channel but the pinned one.
2. `drive-produce --execute-private-upload`:
   - checks the daily cap **first**, counted from the DB (Asia/Dubai day) -
     runners have no persistent disk, so the old JSON budget cannot work;
   - downloads Takeout `.zip` parts from Drive (service account,
     `drive.readonly`), extracts videos (zip-slip safe), matches each file to
     its channel video (never guesses);
   - processes console-confirmed games first (Fortnite first), picks the
     first highlight window **not already used** (ledger in
     `video_queue.source_url` as `...watch?v=<id>#segment=<s>-<e>`);
   - runs the existing highlight → reframe → captions → quality gate →
     package pipeline, then publishes private-first and `mark_uploaded`.

Why Drive: YouTube blocks yt-dlp from cloud runners ("Sign in to confirm
you're not a bot" - probe run 36367070647, 0/10). Browser cookies were
rejected as a foundation (expiry, account risk).

**Safety switches (repository variables):** `CLOUD_RUNNER_ENABLED` must be
`true` or the workflow does nothing; `PUBLISH_PUBLIC` must be `true` for the
public flip (default private); `DAILY_SHORT_CAP` (default 1).

## IN-PROGRESS - resume here (2026-10-01)

**The cloud runner is LIVE.** Owner setup finished 2026-10-01 (from Cloud
Shell in GCP project `robin-content-engine`):
- GitHub secrets: `DATABASE_URL` (content-engine Neon), `GOOGLE_SERVICE_ACCOUNT_JSON`
  (`robin-drive-reader@robin-content-engine.iam.gserviceaccount.com`),
  `YOUTUBE_OAUTH_CLIENT_JSON` (TV-type client `robin-tv`), `DEEPSEEK_API_KEY` (unused).
- Variables: `YOUTUBE_EXPECTED_CHANNEL_ID`, `DRIVE_TAKEOUT_FOLDER_ID`,
  `CLOUD_RUNNER_ENABLED=true`, **`PUBLISH_PUBLIC=true`** (daily Shorts go public).
- Device sign-in done; encrypted token in Neon `oauth_tokens` (name `youtube`).
- Takeout folder shared with the service account (owner chose to keep the
  folder's "anyone with the link" access).
- First Short (manual run 36895571591): https://youtu.be/e1_0dgAMomM, private,
  from 3xyU0yJwNMw 1104-1129s; queue job 168 reconciled to `uploaded`.
- Merged: PR #28 (`d4a7b08`) - close-out + `record_direct_upload` fix.

Open items:
1. **PR #29 (no-AI Arabic titles, DeepSeek off)** - owner decision: do not use
   DeepSeek. Needs the owner's explicit merge approval once CI is green, and
   should land BEFORE the next scheduled run (16:00 UTC daily = 20:00 Dubai);
   otherwise that public Short gets the generic English title.
2. **OAuth consent screen still in Testing** -> the sign-in token expires
   7 days after 2026-10-01 (around 2026-10-08) and publishing stops. Fix:
   Branding -> home page `https://binz2008-star.github.io/`, privacy policy
   `https://binz2008-star.github.io/privacy.html`, authorised domain
   `binz2008-star.github.io` (owner created that public Pages repo) -> Save
   -> Audience -> Publish app; then re-run "YouTube sign-in (one-time)" once.
   Publish stayed disabled even after removing the declared sensitive scopes.
3. First private Short e1_0dgAMomM: owner to review/flip public in Studio.
4. Later: TikTok cross-posting (phase 4); vision-based game checks (new
   provider, owner approval); analysis cache never hits on runners
   (path+size+mtime key); runner processes loose videos in Drive order, not
   confirmed-game priority across files.

### Known issues / findings

- **Pre-existing:** 2 tests in `tests/test_database_integration.py` fail on
  `main` against a real Postgres (CI skips them - no test DB). Needs its own
  task.
- **Runner cost:** the highlight-analysis cache is keyed by path+size+mtime,
  so on a fresh runner download it never hits and a long video is analysed
  again each day it is used. Correct but slow; fix in `production_runner`.
- **Decided (owner, 2026-09-29): rights for own published uploads.** The
  owner approved treating the channel's OWN already-published uploads (and the
  owner's Takeout export of them) as owned footage, so `channel-import` and the
  cloud runner register them as rights-confirmed. Each job's rights note
  records the source video, the exact segment and the game evidence. This does
  NOT extend to local captures or any other footage: those still need the
  manual `rights-approve`.

## Guardrails — HARD

- NO third-party content harvesting (Pexels/Pixabay/Commons/scraping are
  rejected). Footage = the owner's captures or the owner's own uploads.
- `rights_confirmed` is never inferred by AI/heuristics; no
  `AUTO_CONFIRM_LOCAL_CAPTURES`. Sole exception, owner-approved 2026-09-29:
  the channel's own already-published uploads (see Known issues / findings).
- Upload cap + channel-ID pin stay hard-enforced.
- Uploads stay private-first → flip-to-public.
- A game is named in a title only on strong evidence: conservative
  `detect_game`; in the cloud runner only console-native (#PS4Live/#PS5Live)
  tags count - otherwise neutral "Archived gameplay".
- No AI "strategy controller" with authority over sourcing/approval/upload;
  AI only advises (ranking, hooks, metadata).
- Secrets/.env/tokens never printed, logged, or committed.

## Legacy (retired PC) - kept for reference only

- Paths: `X:\content engine\production\work\{highlights,ready,downloads,analysis}`,
  `ops\run_production_once.ps1`, control panel `ops\start_control_panel.cmd`
  (127.0.0.1:8765).
- Useful commands still valid anywhere with credentials: `production-status`,
  `youtube-sync`, `posting-report`, `game-report --format short`,
  `channel-metadata-fix --status`.
