# Robin Engine Studio — Frontend Control Panel (v2)

Robin Engine Studio is the Web UI for managing the **Robin Life & Gaming** YouTube Shorts automated content engine pipeline.

---

## 🚀 Operating Modes

Robin Engine Studio supports two operational modes governed by environment variables:

### 1. Demo Mode (`VITE_DEMO_MODE=true`)
- Activated **only** when `VITE_DEMO_MODE` is strictly set to `'true'`.
- Uses client-side in-memory simulated storage for offline evaluation and UI prototyping.
- Allows operators to test enqueueing, script generation, video previewing, and pipeline actions without requiring a running FastAPI backend or Neon PostgreSQL database.

### 2. Live API Mode (`VITE_DEMO_MODE=false`)
- Connects directly to the real FastAPI Python backend specified by `VITE_API_BASE_URL`.
- If `VITE_DEMO_MODE` is not `'true'` and `VITE_API_BASE_URL` is missing, Studio displays a prominent **Configuration Error** state.
- Live network failures or backend 500 errors display explicit connection error states (**Backend Offline**, **Timed Out**, or **DB Unavailable**) and **never** fall back silently to mock demo data.

---

## ⚙️ Environment Configuration

Copy `.env.example` to `.env` inside `studio/` or configure environment variables at build/runtime:

```env
# Mandatory for Demo Mode (set strictly to 'true')
VITE_DEMO_MODE=true

# Mandatory for Live API Mode (e.g. http://localhost:8000/api)
VITE_API_BASE_URL=
```

### Environment Rules
| Variable | Value | Mode | Description |
|---|---|---|---|
| `VITE_DEMO_MODE` | `'true'` | Demo Mode | Activates in-memory simulated queue. |
| `VITE_DEMO_MODE` | `'false'` or empty | Live API Mode | Expects `VITE_API_BASE_URL` to be present. |
| `VITE_API_BASE_URL` | `http://...` | Live API Mode | Base URL for FastAPI backend endpoints. |

---

## 📡 Canonical Backend API Contracts

Studio interacts with the Python FastAPI backend (`src/robin_content_engine/`) using the following canonical API endpoints:

| Method | Endpoint | Description | Expected Payload / Response |
|---|---|---|---|
| `GET` | `/api/health` | Backend & Database Health Check | `{ "status": "ok", "database": "connected", "version": "1.0.0" }` |
| `GET` | `/api/jobs` | Fetch queue jobs & status counts | `{ "jobs": [...], "counts": { "pending": 0, "processing": 0, "rendered": 0, "uploaded": 0, "failed": 0, "quarantined": 0, "total": 0 } }` |
| `POST` | `/api/jobs` | Enqueue new gameplay video job | Body: `{ "source_title": "...", "source_path": "...", "rights_note": "...", "rights_confirmed": true }`<br>Returns: Enqueued `VideoJob` |
| `POST` | `/api/jobs/{id}/run` | Execute pipeline for job | Body: `{ "render_only": false }`<br>Returns: `{ "status": "success", "message": "...", "job": VideoJob }` |
| `POST` | `/api/jobs/{id}/actions` | Perform action on job | Body: `{ "action": "retry" \| "quarantine" }`<br>Returns: Updated `VideoJob` |
| `GET` | `/api/system` | System info & CLI tool states | `{ "app_name": "...", "version": "...", "python_version": "...", "database": "..." }` |
| `POST` | `/api/script/generate` | Generate DeepSeek AI script | Body: `{ "game_name": "...", "topic": "..." }`<br>Returns: `{ "title": "...", "description": "...", "tags": [...], "script": "..." }` |

---

## 🛠️ Local Development Commands

All commands should be run from the root workspace or within `studio/`:

```bash
# Run local Vite development server on port 3000
npm run dev --workspace studio

# Perform TypeScript type checking
npm run typecheck --workspace studio

# Run ESLint validation
npm run lint --workspace studio

# Run Vitest & React Testing Library contract test suite
npm run test --workspace studio

# Build studio SPA for production distribution
npm run build --workspace studio
```

---

## 🔒 YouTube Upload & Safety Guarantees

- **YouTube Upload Privacy**: Real uploads produced by the pipeline remain set to **Private** by backend default for copyright and content verification.
- **Copyright & Rights Confirmation**: All enqueued gameplay footage requires mandatory confirmation (`--confirm-rights`) and citation notes (`--rights-note`).
