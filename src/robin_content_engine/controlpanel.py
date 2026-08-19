"""Robin Content Engine - local ops dashboard.

A small FastAPI app (loopback only) that renders a one-page dashboard and
delegates every action to the shared ops_actions module - the SAME
implementation the studio API (api.py) exposes under /api/production/*, so
there is exactly one copy of each operator action.

Binds to 127.0.0.1 only (loopback) - never expose this over a network.
Long-running actions (scan/run/import) run synchronously in the request;
the dashboard shows their result as text.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import ops_actions
from .config import Settings

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robin Content Engine — Control Panel</title>
<style>
  :root { --bg:#0d1117; --card:#161b27; --line:#232a3b; --accent:#3fb950; --muted:#8b96ad; --err:#f87171; --warn:#d29922; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,'Segoe UI',sans-serif; background:var(--bg); color:#e6edf3; }
  header { padding:14px 22px; border-bottom:1px solid var(--line); display:flex; gap:14px; align-items:center; flex-wrap:wrap; }
  header h1 { font-size:17px; margin:0; font-weight:600; }
  .pill { padding:3px 10px; border-radius:999px; font-size:12px; background:var(--card); border:1px solid var(--line); color:var(--muted); }
  .pill.ok { background:#10261a; border-color:#1f4d2f; color:var(--accent); }
  .pill.bad { background:#2a1212; border-color:#5c2424; color:var(--err); }
  main { padding:20px 22px; display:grid; grid-template-columns: 300px 1fr; gap:18px; max-width:1500px; margin:0 auto; }
  @media (max-width: 900px) { main { grid-template-columns: 1fr; } }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:14px; }
  .card h2 { font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:0 0 10px; }
  .btn { display:block; width:100%; margin-bottom:7px; padding:10px 12px; border:0; border-radius:8px;
         background:#212a3a; color:#e6edf3; font-size:13px; cursor:pointer; text-align:left; }
  .btn:hover { background:#2b3650; }
  .btn.primary { background:#14402a; color:#7ee2a8; }
  .btn.primary:hover { background:#1a5236; }
  .btn.warn { background:#44350f; color:#e3c77a; }
  .btn.warn:hover { background:#57450f; }
  .btn.small { width:auto; display:inline-block; padding:4px 10px; margin:0; font-size:12px; }
  .btn:disabled { opacity:.5; cursor:wait; }
  .counts { display:grid; grid-template-columns: repeat(3,1fr); gap:8px; margin-bottom:10px; }
  .count { text-align:center; background:var(--line); border-radius:10px; padding:8px 4px; }
  .count b { display:block; font-size:19px; font-weight:700; }
  .count span { font-size:10.5px; color:var(--muted); }
  .input { width:100%; margin-bottom:7px; padding:9px 10px; border:1px solid var(--line); border-radius:8px;
           background:#0d1117; color:#e6edf3; font-size:13px; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; }
  th, td { text-align:left; padding:7px 9px; border-bottom:1px solid var(--line); white-space:nowrap; }
  th { color:var(--muted); font-weight:500; }
  td.t { max-width:300px; overflow:hidden; text-overflow:ellipsis; }
  .st { font-weight:600; }
  .st-pending { color:#8b949e; } .st-packaged { color:#58a6ff; } .st-uploaded_private { color:var(--accent); }
  .st-awaiting_rights { color:var(--warn); } .st-inactive { color:var(--muted); } .st-rejected { color:var(--err); }
  .log { background:#0a0d13; border:1px solid var(--line); border-radius:10px; padding:12px; margin-top:12px;
         font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; white-space:pre-wrap;
         max-height:340px; overflow:auto; color:#c9d4e6; }
  .log.error { color:var(--err); }
  .corr { font-size:12px; padding:7px 0; border-bottom:1px solid var(--line); }
  .corr b { display:block; }
  .muted { color:var(--muted); font-size:12px; }
  .help { display:none; grid-column:1 / -1; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px;
          margin-bottom:18px; font-size:13px; line-height:1.55; }
  .help.open { display:block; }
  .help h3 { margin:14px 0 6px; font-size:13px; color:var(--accent); }
  .help ol, .help ul { margin:4px 0 10px; padding-left:20px; }
  .help table { margin:6px 0 12px; }
  .help code { background:var(--line); padding:1px 6px; border-radius:6px; font-size:12px; }
  .helpbtn { margin-left:auto; background:var(--line); color:#e6edf3; border:0; border-radius:999px;
             padding:6px 14px; font-size:12px; cursor:pointer; }
  .helpbtn:hover { background:#2b3650; }
</style>
</head>
<body>
<header>
  <h1>Robin Content Engine — Control Panel</h1>
  <span id="srv" class="pill">…</span>
  <span id="auth" class="pill">…</span>
  <span id="db" class="pill">…</span>
  <span id="lang" class="pill">…</span>
  <button id="helpBtn" class="helpbtn" onclick="toggleHelp()">How to use</button>
</header>
<main>
  <div id="help" class="help">
    <h3>1. Open it</h3>
    <p>Double-click the <b>Robin Content Engine</b> icon on your desktop. It starts the app and opens this page.</p>
    <h3>2. Your normal routine (2 steps)</h3>
    <ol>
      <li>Record gameplay, then click <b>Scan captures folder</b> to add the new clip.</li>
      <li>Click <b>Approve</b> next to the new clip (under <b>Awaiting rights</b>), then click <b>Process + upload next job</b>.</li>
    </ol>
    <h3>3. What each button does</h3>
    <table>
      <tr><th>Button</th><th>What it does</th></tr>
      <tr><td><b>Scan captures folder</b></td><td>Finds new clips you recorded and adds them to the queue</td></tr>
      <tr><td><b>Refresh channel snapshot</b></td><td>Re-checks your YouTube channel (do after uploads)</td></tr>
      <tr><td><b>Process + upload next job</b></td><td>Makes the Short and uploads it (max 4/day for safety)</td></tr>
      <tr><td><b>Process next job (no upload)</b></td><td>Just makes the Short, doesn't upload</td></tr>
      <tr><td><b>Make all private uploads public</b></td><td>Publishes any private videos</td></tr>
      <tr><td><b>Build metadata fix plan</b></td><td>Finds videos with wrong/missing titles</td></tr>
      <tr><td><b>Apply metadata fixes</b></td><td>Writes the corrected titles (use after Build plan)</td></tr>
      <tr><td><b>Import a channel video as Short</b></td><td>Paste a video ID (e.g. <code>Yn0uEqzUHJ8</code>), click Download + queue — cuts the best moment into a Short</td></tr>
    </table>
    <h3>4. The queue</h3>
    <p><b>Awaiting rights</b> = new clips needing your OK (click <b>Approve</b>). <b>Eligible / Packaged</b> = ready to upload. <b>Uploaded</b> = done. The <b>Result</b> box shows what each action did — red text = the reason it failed.</p>
    <h3>5. Pending corrections</h3>
    <p>Shows fixes waiting to be written (e.g. mislabeled videos). They apply automatically when YouTube's daily quota resets, or use <b>Apply metadata fixes</b>.</p>
    <p style="color:var(--muted)">Everything else runs automatically on schedule. You only need steps 1-2 to add new clips.</p>
  </div>
  <div>
    <div class="card"><h2>Channel</h2>
      <div class="counts" id="counts"></div>
    </div>
    <div class="card"><h2>Actions</h2>
      <button class="btn" onclick="act('scan')">Scan captures folder</button>
      <button class="btn" onclick="act('sync')">Refresh channel snapshot</button>
      <button class="btn primary" onclick="act('runonce')">Process + upload next job</button>
      <button class="btn primary" onclick="act('runonce_noupload')">Process next job (no upload)</button>
      <button class="btn warn" onclick="act('makepublic')">Make all private uploads public</button>
      <button class="btn warn" onclick="act('metafix')">Build metadata fix plan</button>
      <button class="btn warn" onclick="act('metafix_apply')">Apply metadata fixes (up to 20)</button>
    </div>
    <div class="card"><h2>Import a channel video as Short</h2>
      <input id="vid" class="input" placeholder="YouTube video ID (e.g. Yn0uEqzUHJ8)">
      <button class="btn primary" onclick="importVideo(false)">Download + queue (no upload)</button>
      <button class="btn primary" onclick="importVideo(true)">Download + process + upload</button>
    </div>
    <div class="card"><h2>Pending corrections</h2><div id="plan">Loading…</div></div>
  </div>
  <div>
    <div class="card"><h2>Queue</h2>
      <div style="overflow:auto"><table><thead><tr><th>#</th><th>Source</th><th>Status</th><th></th></tr></thead>
      <tbody id="jobs"></tbody></table></div>
    </div>
    <div class="card"><h2>Long videos (Short candidates)</h2>
      <div style="overflow:auto; max-height:220px"><table><thead><tr><th>Video</th><th>Length</th><th>Views</th><th></th></tr></thead>
      <tbody id="long"></tbody></table></div>
    </div>
    <div class="card"><h2>Result</h2><div id="log" class="log">Ready.</div></div>
  </div>
</main>
<script>
async function j(url, opts){ const r = await fetch(url, opts||{}); let d; try { d = await r.json(); } catch { d = {detail: await r.text()}; }
 if (!r.ok) throw new Error((d && (d.detail || d.message)) || r.status); return d; }
function log(text, isErr){ const el = document.getElementById('log'); el.className = 'log' + (isErr ? ' error' : ''); el.textContent = text; }
function fmtLen(s){ return Math.floor(s/60) + ':' + String(s%60).padStart(2,'0'); }
async function refresh(){
  try {
    const s = await j('/api/status');
    const c = s.counts;
    document.getElementById('counts').innerHTML =
      [['awaiting_rights','Awaiting rights'],['rights_approved_eligible','Eligible'],['packaged','Packaged'],
       ['uploaded_private','Uploaded'],['inactive','Inactive'],['ambiguous','Ambiguous']]
      .map(([k,label]) => `<div class="count"><b>${c[k] ?? 0}</b><span>${label}</span></div>`).join('');
    const rows = s.jobs.map(x => {
      const ap = (x.state === 'awaiting_rights')
        ? `<button class="btn small primary" onclick="approveJob(${x.job_id})">Approve</button>`
        : '';
      return `<tr><td>#${x.job_id}</td><td class="t">${(x.source_title||'').slice(0,50)}</td>` +
             `<td class="st st-${x.state}">${x.state}</td><td>${ap}</td></tr>`;
    }).join('');
    document.getElementById('jobs').innerHTML = rows || '<tr><td colspan="4" class="muted">Queue is empty</td></tr>';
    document.getElementById('srv').textContent = 'online'; document.getElementById('srv').className = 'pill ok';
    const sys = await j('/api/system');
    document.getElementById('auth').textContent = sys.youtube_authenticated ? 'YouTube: on' : 'YouTube: off';
    document.getElementById('auth').className = 'pill ' + (sys.youtube_authenticated ? 'ok' : 'bad');
    document.getElementById('db').textContent = 'DB: ' + sys.database;
    document.getElementById('db').className = 'pill ' + (sys.database === 'connected' ? 'ok' : 'bad');
    document.getElementById('lang').textContent = 'Meta: ' + sys.metadata_language;
  } catch (e) { log('Refresh failed: ' + e.message, true); }
  try {
    const p = await j('/api/plan');
    document.getElementById('plan').innerHTML = p.pending.length
      ? p.pending.map(x => `<div class="corr"><b>${x.video_id} → ${(x.new_title||'(pending generation)').slice(0,50)}</b>${x.detail||''}</div>`).join('')
      : '<div class="muted">No pending corrections.</div>';
  } catch (e) {}
  try {
    const l = await j('/api/long-videos?limit=12&min_seconds=60');
    document.getElementById('long').innerHTML = (l.videos||[]).map(v =>
      `<tr><td class="t">${(v.title||'').slice(0,45)}</td><td>${fmtLen(v.duration_seconds)}</td><td>${v.view_count||0}</td>` +
      `<td><button class="btn small" onclick="importThis('${v.video_id}')">Short</button></td></tr>`).join('')
      || '<tr><td colspan="4" class="muted">No long videos in snapshot (run Refresh channel snapshot).</td></tr>';
  } catch (e) {}
}
async function act(name){
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  log('Running ' + name + ' …');
  try {
    const r = await j('/api/action/' + name, { method:'POST', headers:{'Content-Type':'application/json'},
      body: name.startsWith('metafix_apply') ? JSON.stringify({apply:true}) : '{}' });
    log(r.output || r.message || 'OK', !r.ok);
  } catch (e) { log('ERROR: ' + e.message, true); }
  document.querySelectorAll('button').forEach(b => b.disabled = false);
  refresh();
}
async function approveJob(id){
  log('Approving rights for job #' + id + ' …');
  try {
    const r = await j('/api/action/approve', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({job_id:id}) });
    log(r.output || 'OK', !r.ok);
  } catch (e) { log('ERROR: ' + e.message, true); }
  refresh();
}
async function importVideo(upload){
  const vid = document.getElementById('vid').value.trim();
  if (!vid) { log('Enter a YouTube video ID first.', true); return; }
  log((upload ? 'Importing + uploading ' : 'Importing ') + vid + ' …');
  try {
    const r = await j('/api/action/import', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({video_id:vid, apply:upload}) });
    log(r.output || 'OK', !r.ok);
  } catch (e) { log('ERROR: ' + e.message, true); }
  refresh();
}
function importThis(id){ document.getElementById('vid').value = id; importVideo(false); }
function toggleHelp(){ const h = document.getElementById('help'); h.classList.toggle('open');
  document.getElementById('helpBtn').textContent = h.classList.contains('open') ? 'Hide help' : 'How to use'; }
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


def create_control_panel(*, settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else Settings()  # type: ignore[call-arg]
    app = FastAPI(title="Robin Content Engine Control Panel", version="1.0")

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> str:
        return _DASHBOARD_HTML

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        return ops_actions.system_info(app_settings)

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return ops_actions.status(app_settings)

    @app.get("/api/plan")
    def plan() -> dict[str, Any]:
        return ops_actions.metadata_plan_status(app_settings)

    @app.get("/api/long-videos")
    def long_videos(limit: int = 30, min_seconds: int = 60) -> dict[str, Any]:
        return ops_actions.long_videos(app_settings, limit=limit, min_seconds=min_seconds)

    @app.post("/api/action/scan")
    def action_scan() -> dict[str, Any]:
        return ops_actions.scan(app_settings)

    @app.post("/api/action/sync")
    def action_sync() -> dict[str, Any]:
        return ops_actions.sync(app_settings)

    @app.post("/api/action/approve")
    def action_approve(payload: ActionRequest) -> dict[str, Any]:
        if not payload.job_id:
            return {"ok": False, "output": "job_id is required"}
        return ops_actions.approve(app_settings, payload.job_id, payload.note)

    @app.post("/api/action/runonce")
    def action_runonce() -> dict[str, Any]:
        return ops_actions.run_once(app_settings, upload=True)

    @app.post("/api/action/runonce_noupload")
    def action_runonce_noupload() -> dict[str, Any]:
        return ops_actions.run_once(app_settings, upload=False)

    @app.post("/api/action/makepublic")
    def action_makepublic() -> dict[str, Any]:
        return ops_actions.make_public(app_settings)

    @app.post("/api/action/metafix")
    def action_metafix(payload: ActionRequest) -> dict[str, Any]:
        return ops_actions.metadata_fix(app_settings, apply=payload.apply)

    @app.post("/api/action/import")
    def action_import(payload: ActionRequest) -> dict[str, Any]:
        if not payload.video_id:
            return {"ok": False, "output": "video_id is required"}
        return ops_actions.import_video(app_settings, payload.video_id, upload=payload.apply)

    return app


# Module-level app instance for `uvicorn robin_content_engine.controlpanel:app`.
app = create_control_panel()
