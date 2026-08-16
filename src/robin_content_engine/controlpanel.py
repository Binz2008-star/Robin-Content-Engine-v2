"""Robin Content Engine - local control panel.

A small FastAPI app that exposes the same operations as the CLI as simple
HTTP endpoints plus a one-page dashboard, so the operator can drive the
pipeline from a browser instead of the command line.

Binds to 127.0.0.1 only (loopback) - never expose this over a network.
Long-running actions (scan/run/import) run synchronously in the request;
the dashboard shows their result as text.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .ai_logic import ContentGenerator
from .capture_scan import scan_captures
from .channel_import import import_video_as_short, list_long_videos
from .channel_metadata import ChannelMetadataError, ChannelMetadataFixer
from .config import Settings
from .database import JobRepository
from .production_runner import (
    build_production_metadata,
    production_status,
    run_production_once,
)
from .publishing import PublishingError, dry_run, execute_private_upload
from .uploader import YouTubeUploader
from .youtube_auth import AuthState, YouTubeAuth

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Robin Content Engine - Control Panel</title>
<style>
  :root { --bg:#0f1420; --card:#1a2233; --accent:#4ade80; --muted:#8b96ad; --err:#f87171; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,sans-serif; background:var(--bg); color:#e5e9f0; }
  header { padding:16px 24px; border-bottom:1px solid #263047; display:flex; gap:16px; align-items:center; }
  header h1 { font-size:18px; margin:0; }
  .pill { padding:4px 10px; border-radius:999px; font-size:12px; background:#263047; color:var(--muted); }
  .pill.ok { background:#143b28; color:var(--accent); }
  .pill.bad { background:#3b1414; color:var(--err); }
  main { padding:24px; display:grid; grid-template-columns: 320px 1fr; gap:24px; max-width:1400px; margin:0 auto; }
  .card { background:var(--card); border:1px solid #263047; border-radius:12px; padding:16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:0 0 12px; }
  .btn { display:block; width:100%; margin-bottom:8px; padding:10px 12px; border:0; border-radius:8px;
         background:#263047; color:#e5e9f0; font-size:13px; cursor:pointer; text-align:left; }
  .btn:hover { background:#2f3c5c; }
  .btn.primary { background:#14633b; }
  .btn.primary:hover { background:#187a48; }
  .btn.warn { background:#7a5214; }
  .btn.warn:hover { background:#96641a; }
  .btn:disabled { opacity:.5; cursor:wait; }
  .counts { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px; }
  .count { flex:1; min-width:70px; text-align:center; background:#263047; border-radius:8px; padding:8px 4px; }
  .count b { display:block; font-size:20px; }
  .count span { font-size:11px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid #263047; white-space:nowrap; }
  th { color:var(--muted); font-weight:500; }
  td.t { max-width:280px; overflow:hidden; text-overflow:ellipsis; }
  .st { font-weight:600; }
  .log { background:#0b0f18; border:1px solid #263047; border-radius:8px; padding:12px; margin-top:12px;
         font-family:ui-monospace,monospace; font-size:12px; white-space:pre-wrap; max-height:320px; overflow:auto; color:#c8d2e5; }
  .log.error { color:var(--err); }
</style>
</head>
<body>
<header>
  <h1>Robin Content Engine — Control Panel</h1>
  <span id="srv" class="pill"></span>
  <span id="auth" class="pill"></span>
  <span id="db" class="pill"></span>
</header>
<main>
  <div>
    <div class="card" style="margin-bottom:16px"><h2>Channel</h2>
      <div class="counts" id="counts"></div>
    </div>
    <div class="card"><h2>Actions</h2>
      <button class="btn" onclick="act('scan')">Scan captures folder (register new)</button>
      <button class="btn" onclick="act('sync')">Refresh channel snapshot (youtube-sync)</button>
      <button class="btn primary" onclick="act('runonce')">Process + upload next job</button>
      <button class="btn primary" onclick="act('runonce_noupload')">Process next job (no upload)</button>
      <button class="btn warn" onclick="act('makepublic')">Make all private uploads public</button>
      <button class="btn warn" onclick="act('metafix')">Fix channel metadata (plan only)</button>
      <button class="btn warn" onclick="act('metafix_apply')">Fix channel metadata (apply up to 20)</button>
      <button class="btn" onclick="refresh()">Refresh status</button>
    </div>
  </div>
  <div>
    <div class="card" style="margin-bottom:16px"><h2>Queue</h2>
      <table id="jobs"><tbody></tbody></table>
    </div>
    <div class="card"><h2>Result</h2>
      <div id="log" class="log">Ready.</div>
    </div>
  </div>
</main>
<script>
async function j(url, opts){ const r = await fetch(url, opts||{}); let d; try { d = await r.json(); } catch { d = {detail: await r.text()}; }
 if (!r.ok) throw new Error((d && (d.detail || d.message)) || r.status); return d; }
async function refresh(){
  try {
    const s = await j('/api/status');
    const c = s.counts;
    document.getElementById('counts').innerHTML =
      ['awaiting_rights','rejected','rights_approved_eligible','packaged','uploaded_private','inactive','ambiguous']
      .map(k => `<div class="count"><b>${c[k] ?? 0}</b><span>${k.replace(/_/g,' ')}</span></div>`).join('');
    const rows = s.jobs.slice(0, 25).map(x => `<tr><td>#${x.job_id}</td><td class="t">${(x.source_title||'').slice(0,45)}</td><td class="st st-${x.state}">${x.state}</td></tr>`).join('');
    document.getElementById('jobs').innerHTML = rows.length ? rows : '<tr><td>Empty</td></tr>';
    document.getElementById('srv').className = 'pill ok'; document.getElementById('srv').textContent = 'online';
    const sys = await j('/api/system');
    document.getElementById('auth').className = 'pill ' + (sys.youtube_authenticated ? 'ok' : 'bad');
    document.getElementById('auth').textContent = sys.youtube_authenticated ? 'YouTube: on' : 'YouTube: off';
    document.getElementById('db').className = 'pill ' + (sys.database === 'connected' ? 'ok' : 'bad');
    document.getElementById('db').textContent = 'DB: ' + sys.database;
  } catch (e) { log('Refresh failed: ' + e.message, true); }
}
async function act(name){
  const btn = document.querySelectorAll('button'); btn.forEach(b => b.disabled = true);
  log('Running ' + name + ' ...');
  try {
    const r = await j('/api/action/' + name, { method:'POST', headers:{'Content-Type':'application/json'},
      body: name.startsWith('metafix_apply') ? JSON.stringify({apply:true}) : '{}' });
    log(r.output || r.message || 'OK');
  } catch (e) { log('ERROR: ' + e.message, true); }
  btn.forEach(b => b.disabled = false);
  refresh();
}
function log(text, isErr){ const el = document.getElementById('log'); el.className = 'log' + (isErr ? ' error' : ''); el.textContent = text; }
setInterval(refresh, 30000); refresh();
</script>
</body>
</html>
"""


class ActionRequest(BaseModel):
    apply: bool = False
    note: str | None = None
    video_id: str | None = None
    job_id: int | None = None


def create_control_panel(*, settings: Settings | None = None, host: str = "127.0.0.1") -> FastAPI:
    app_settings = settings if settings is not None else Settings()  # type: ignore[call-arg]
    app = FastAPI(title="Robin Content Engine Control Panel", version="1.0")

    def _repo() -> JobRepository:
        return JobRepository(app_settings.database_url, app_settings.max_job_attempts)

    def _auth() -> YouTubeAuth:
        return YouTubeAuth(app_settings.youtube_client_secret_file, app_settings.youtube_token_file)

    def _generator() -> ContentGenerator:
        return ContentGenerator(
            app_settings.deepseek_api_key,
            app_settings.deepseek_base_url,
            app_settings.deepseek_model,
        )

    def _wrap(fn: Any) -> dict[str, Any]:
        try:
            return {"ok": True, "output": fn()}
        except Exception as exc:  # surface operator-safe message
            return {"ok": False, "output": f"{type(exc).__name__}: {exc}"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _DASHBOARD_HTML

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        token_ok = False
        try:
            state = _auth().state()
            token_ok = state == AuthState.AUTHENTICATED
        except Exception:
            pass
        db_ok = False
        try:
            with _repo().running() as repo:
                db_ok = bool(repo.ping())
        except Exception:
            pass
        return {
            "youtube_authenticated": token_ok,
            "database": "connected" if db_ok else "unavailable",
            "metadata_language": getattr(app_settings, "youtube_metadata_language", "arabic"),
            "highlight_min_seconds": app_settings.highlight_min_seconds,
            "highlight_max_seconds": app_settings.highlight_max_seconds,
        }

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        with _repo().running() as repo:
            report = production_status(repo, app_settings)
        return {
            "counts": {
                "awaiting_rights": report.awaiting_rights,
                "rejected": report.rejected,
                "rights_approved_eligible": report.rights_approved_eligible,
                "processing": report.processing,
                "packaged": report.packaged,
                "uploaded_private": report.uploaded_private,
                "ambiguous": report.ambiguous,
                "inactive": report.inactive,
            },
            "jobs": [
                {
                    "job_id": job.job_id,
                    "source_title": job.source_title,
                    "state": job.state,
                }
                for job in report.jobs
            ],
        }

    @app.post("/api/action/scan")
    def action_scan() -> dict[str, Any]:
        def run() -> str:
            with _repo().running() as repo:
                result = scan_captures(app_settings.capture_source_dir, repo)
            return (
                f"Videos discovered: {result.videos_discovered}\n"
                f"New captures registered: {result.new_registered}\n"
                f"Already known: {result.already_known}\n"
                f"Skipped unstable: {result.skipped_unstable}"
            )

        return _wrap(run)

    @app.post("/api/action/sync")
    def action_sync() -> dict[str, Any]:
        def run() -> str:
            from .youtube_sync import YouTubeChannelSync

            sync = YouTubeChannelSync(_auth(), app_settings.youtube_expected_channel_id)
            snapshot = sync.fetch_snapshot()
            from .channel_repository import ChannelRepository

            with ChannelRepository(app_settings.database_url).running() as repo:
                stored = repo.save_snapshot(snapshot)
            return f"Snapshot refreshed: {stored} videos stored."

        return _wrap(run)

    @app.post("/api/action/approve")
    def action_approve(payload: ActionRequest) -> dict[str, Any]:
        if not payload.job_id:
            return {"ok": False, "output": "job_id is required"}
        note = payload.note or "Approved from the control panel by the operator."

        def run() -> str:
            with _repo().running() as repo:
                approved = repo.approve_rights(payload.job_id, note)
            if approved is None:
                raise HTTPException(409, "job is not reviewable")
            return f"Rights approved for job {payload.job_id} (status={approved['status']})."

        return _wrap(run)

    @app.post("/api/action/runonce")
    def action_runonce(payload: ActionRequest) -> dict[str, Any]:
        def run() -> str:
            return _run_production_once(upload=not payload.apply or True)

        return _wrap(run)

    @app.post("/api/action/runonce_noupload")
    def action_runonce_noupload() -> dict[str, Any]:
        return _wrap(lambda: _run_production_once(upload=False))

    def _run_production_once(*, upload: bool) -> str:
        repo = _repo()
        once = run_production_once(repo, app_settings)
        lines = []
        lines.append(f"Capture scan: {once.capture_scan.new_registered} new registered.")
        for skipped in once.skipped:
            lines.append(f"Skipped job {skipped.job_id}: {skipped.reason}")
        if once.terminal_failure is not None:
            lines.append(f"Job {once.terminal_failure.job_id} failed permanently: {once.terminal_failure.reason}")
            return "\n".join(lines)
        if once.selected_job_id is None:
            lines.append("NO ELIGIBLE JOB")
            return "\n".join(lines)
        result = once.run
        assert result is not None
        lines.append(
            f"Job {result.job_id}: {result.source_title} | rank {result.rank} | "
            f"window {result.start_seconds:.0f}s-{result.end_seconds:.0f}s | "
            f"quality gate {'PASS' if result.quality_gate.passed else 'FAIL'}"
        )
        if not result.quality_gate.passed:
            return "\n".join(lines)
        assert result.package is not None
        lines.append(f"Package: {result.package.package_dir}")
        if not upload:
            title, description, _tags = build_production_metadata(result.source_title, app_settings)
            dry_run(result.package.package_dir, title, description, [], app_settings)
            lines.append("PUBLISH DRY RUN PASS (no upload)")
            return "\n".join(lines)
        title, description, tags = build_production_metadata(result.source_title, app_settings)
        lines.append(f"Title: {title}")
        upload_result = execute_private_upload(
            result.package.package_dir, title, description, tags, app_settings, _auth(), YouTubeUploader
        )
        lines.append(f"UPLOAD SUCCESS — video ID {upload_result.youtube_id}")
        return "\n".join(lines)

    @app.post("/api/action/makepublic")
    def action_makepublic() -> dict[str, Any]:
        def run() -> str:
            import psycopg
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            auth = _auth()
            credentials = auth.load_credentials()
            identity = auth.fetch_channel_identity(credentials)
            if (
                app_settings.youtube_expected_channel_id
                and identity.channel_id != app_settings.youtube_expected_channel_id
            ):
                raise PublishingError("channel mismatch")
            youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            with psycopg.connect(app_settings.database_url) as conn:
                rows = conn.execute(
                    "SELECT video_id, title FROM youtube_videos "
                    "WHERE is_current = TRUE AND privacy_status = 'private'"
                ).fetchall()
            made = 0
            for video_id, _title in rows:
                youtube.videos().update(
                    part="status",
                    body={"id": video_id, "status": {"privacyStatus": "public"}},
                ).execute()
                made += 1
            return f"Made {made} private video(s) public."

        return _wrap(run)

    @app.post("/api/action/metafix")
    def action_metafix(payload: ActionRequest) -> dict[str, Any]:
        def run() -> str:
            fixer = ChannelMetadataFixer(app_settings, _auth(), _generator())
            discovered = fixer.discover()
            lines = [f"Videos needing metadata fixes: {len(discovered)}"]
            generated = 0
            for entry in fixer.plan.pending():
                if entry.new_title is not None:
                    continue
                try:
                    fixer.generate_for(entry)
                    generated += 1
                except ChannelMetadataError as exc:
                    lines.append(f"  generation failed {entry.video_id}: {exc}")
            lines.append(f"Generated: {generated}")
            if payload.apply:
                applied, failed, failures = fixer.apply(max_updates=20)
                lines.append(f"Applied: {applied}, failed: {failed}")
                for vid, err in failures:
                    lines.append(f"  {vid}: {err}")
            else:
                lines.append("Plan built (not applied). Use apply to write to YouTube.")
            return "\n".join(lines)

        return _wrap(run)

    @app.post("/api/action/import")
    def action_import(payload: ActionRequest) -> dict[str, Any]:
        if not payload.video_id:
            return {"ok": False, "output": "video_id is required"}

        def run() -> str:
            repo = _repo()
            job_id, result = import_video_as_short(
                payload.video_id, repo, app_settings, rank=1
            )
            lines = [
                f"Imported {payload.video_id} as job {job_id}.",
                f"Window: {result.start_seconds:.0f}s-{result.end_seconds:.0f}s | "
                f"quality gate {'PASS' if result.quality_gate.passed else 'FAIL'}",
            ]
            if payload.apply and result.quality_gate.passed and result.package is not None:
                title, description, tags = build_production_metadata(
                    result.source_title, app_settings
                )
                upload_result = execute_private_upload(
                    result.package.package_dir, title, description, tags,
                    app_settings, _auth(), YouTubeUploader,
                )
                lines.append(f"UPLOAD SUCCESS — video ID {upload_result.youtube_id}")
            else:
                lines.append("Not uploaded (queued for the next scheduled run).")
            return "\n".join(lines)

        return _wrap(run)

    @app.get("/api/long-videos")
    def long_videos(limit: int = 30, min_seconds: int = 60) -> dict[str, Any]:
        videos = list_long_videos(app_settings, min_seconds=min_seconds, limit=limit)
        return {"videos": videos}

    return app
