# Cloud runner setup (no PC) - one-time, from a phone

This replaces the retired PC. After these steps GitHub produces and publishes
one Short a day from the channel's own footage (Google Takeout in Drive).
Nothing publishes until the last step flips the safety switch.

> Never paste any key, JSON file or database URL into a chat. Only into the
> GitHub / Google screens below.

## 0. Before you start

- The Google Takeout export is in your Drive: the folder is called
  **"Takeout"** (done 2026-09-30).
- You are signed in to Google with the account that owns the Robinzo channel.

## 1. Google Cloud (console.cloud.google.com)

Use the same Google Cloud project the channel already uses for the YouTube API
(or create one).

1. **APIs & Services -> Library**: enable **YouTube Data API v3** and
   **Google Drive API**.
2. **APIs & Services -> OAuth consent screen**: if the app is in **Testing**,
   press **Publish app** (to "In production"). In Testing mode Google expires
   the sign-in after 7 days and publishing would stop. For your own channel the
   "unverified app" warning during sign-in is expected; continue past it.
3. **IAM & Admin -> Service Accounts -> Create service account**: name it
   `robin-drive-reader`, no roles, Done. Open it -> **Keys -> Add key -> JSON**.
   A `.json` file downloads. Copy the service account's **email**
   (`...@...iam.gserviceaccount.com`).
4. **APIs & Services -> Credentials -> Create credentials -> OAuth client ID**:
   type **TVs and Limited Input devices**, Create, then **Download JSON**.

## 2. Google Drive

1. Open the Takeout folder -> **Share** -> paste the service account email ->
   **Viewer** -> Send. (It can only read; it cannot change anything.)
2. Copy the folder link. The folder ID is the part after `/folders/`.

## 3. GitHub (Settings -> Secrets and variables -> Actions)

Repository: `Binz2008-star/Robin-Content-Engine-v2`.

**Secrets** (New repository secret):

| Name | Value |
|---|---|
| `DATABASE_URL` | Neon -> project `content-engine` -> Connect -> pooled connection string |
| `DEEPSEEK_API_KEY` | your DeepSeek API key |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | the whole content of the service-account `.json` (step 1.3) |
| `YOUTUBE_OAUTH_CLIENT_JSON` | the whole content of the OAuth client `.json` (step 1.4) |

**Variables** (Variables tab -> New repository variable):

| Name | Value |
|---|---|
| `YOUTUBE_EXPECTED_CHANNEL_ID` | `UCIcvbGsmSwMDXxjWXq4QG8A` |
| `DRIVE_TAKEOUT_FOLDER_ID` | the folder ID from step 2.2 |

Tip (Android): open the downloaded `.json` with a text viewer, select all,
copy, paste into the secret box.

## 4. Database table - DONE (2026-09-30)

The encrypted sign-in is stored in the `oauth_tokens` table, added to the
`content-engine` database on 2026-09-30 with your approval (tested on a
temporary Neon branch first). No existing data was changed. Nothing to do.

## 5. Sign in once

GitHub -> **Actions -> "YouTube sign-in (one-time)" -> Run workflow**. Open the
run: the summary shows a link and a code. Open the link on your phone, enter
the code, choose the **Robinzo** account, allow. The run ends with
"sign-in complete for 'Robinzo'". If you chose another account, nothing is
stored and it tells you so.

## 6. First test (private)

Add variable `CLOUD_RUNNER_ENABLED` = `true`, then **Actions -> "Daily Short"
-> Run workflow**. One Short is uploaded **private**. Check it in YouTube
Studio: right game, right title, good cut.

## 7. Go live

When the private test looks right, add variable `PUBLISH_PUBLIC` = `true`.
From then on up to three Shorts a day go public (12:00, 16:00, 20:00 Dubai).

| Variable | Meaning | Default |
|---|---|---|
| `CLOUD_RUNNER_ENABLED` | master switch - delete it to stop everything | off |
| `PUBLISH_PUBLIC` | flip uploads to public after the private upload | off (private) |
| `DAILY_SHORT_CAP` | max uploads per Dubai day (3 runs a day) | `3` |
| `YOUTUBE_METADATA_LANGUAGE` | `arabic` or `english` titles | `arabic` |

## Safety built in

- A Short names a game in its title only when the PlayStation's own share tags
  confirm it; otherwise the title is neutral.
- A moment of a video is never used twice (every used segment is recorded).
- Uploads always go out private first; the daily cap is counted in the
  database before any processing.
- The sign-in token is stored encrypted and only for the Robinzo channel.
