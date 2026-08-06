# Robin Engine Studio

Robin Engine Studio is the React/Vite control interface for Robin Content Engine v2.

## Operating modes

### Demo Mode

```env
VITE_DEMO_MODE=true
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

Demo Mode uses clearly labelled in-memory sample jobs. It does not connect to Neon, DeepSeek, MoviePy workers, neural TTS, Google Drive OAuth, or YouTube.

### Live API Mode

```env
VITE_DEMO_MODE=false
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

Live Mode never falls back silently to demo records. If the API is unavailable, the Studio displays an explicit offline, timeout, database-unavailable, or configuration-error state.

## Approved backend routes

- `GET /api/health`
- `GET /api/jobs`
- `POST /api/jobs`
- `POST /api/jobs/{id}/run`
- `POST /api/jobs/{id}/actions`
- `GET /api/system`

Script generation is not yet part of the approved live FastAPI contract. The Script Studio returns simulated content only in Demo Mode and reports HTTP-style status `501` in Live Mode until a backend route is implemented and reviewed.

## Safety rules

- The frontend never contains database credentials.
- Queue access occurs only through FastAPI.
- Every video requires confirmed ownership or licensing and a rights note.
- YouTube uploads remain Private by backend default.
- Google Drive selection remains a simulated UI until OAuth and backend ingestion are implemented.
- No Content ID evasion or third-party downloading is included.

## Local commands

Run from the repository root:

```bash
npm ci
npm run dev -- --host 0.0.0.0
npm run typecheck
npm run lint
npm run test
npm run build
```

The production Studio bundle is written to `dist/studio/`, so building the frontend does not delete unrelated root distribution artifacts.
