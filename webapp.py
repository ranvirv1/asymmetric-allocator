"""Live site for the Asymmetric Allocator (M9 web).

Two ways to refresh the book:

  * Cloud (default on a host): "Refresh data" triggers the GitHub Actions
    `build-report` workflow, which builds on a 16 GB runner (no OOM) and publishes
    the report to the `live-report` branch. This app polls the run and shows live
    progress, then serves the published report. Set GH_TOKEN + GH_REPO to enable.

  * Local (no GitHub config): falls back to building in a subprocess on this
    machine, exactly as before — handy for `python webapp.py` offline.

Local:  $env:PYTHONUTF8=1 ; .venv\\Scripts\\python.exe webapp.py   -> http://127.0.0.1:8765
Cloud:  gunicorn webapp:app   (serves $PORT). See DEPLOY.md.

Set APP_USER/APP_PASSWORD to password-gate the public URL.
"""
from __future__ import annotations

import base64
import calendar
import hmac
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, send_file

ROOT = Path(__file__).resolve().parent
PY = sys.executable
RUNNER = ROOT / "scripts" / "weekly_run.py"
LATEST = Path(os.getenv("REPORTS_DIR") or ROOT / "reports") / "latest.html"

# --- GitHub build config (cloud path) -----------------------------------------
GH_TOKEN = os.getenv("GH_TOKEN")
GH_REPO = os.getenv("GH_REPO")                       # "owner/repo"
GH_REF = os.getenv("GH_REF", "main")                 # branch the workflow lives on
WORKFLOW_FILE = os.getenv("WORKFLOW_FILE", "build-report.yml")
REPORT_BRANCH = os.getenv("REPORT_BRANCH", "live-report")
GH_API = "https://api.github.com"
USE_GITHUB = bool(GH_TOKEN and GH_REPO)

app = Flask(__name__)
JOB = {"running": False, "mode": "safe", "phase": "idle", "since": None,
       "run_id": None, "run_url": None, "started": None, "last": None, "error": None}

_AUTH_USER = os.getenv("APP_USER")
_AUTH_PASS = os.getenv("APP_PASSWORD")


# --- auth ---------------------------------------------------------------------
def _authorized() -> bool:
    if not (_AUTH_USER and _AUTH_PASS):
        return True  # auth disabled (local dev)
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Basic "):
        return False
    try:
        user, _, pw = base64.b64decode(hdr[6:]).decode("utf-8").partition(":")
    except Exception:  # noqa: BLE001
        return False
    return hmac.compare_digest(user, _AUTH_USER) and hmac.compare_digest(pw, _AUTH_PASS)


@app.before_request
def _gate():
    if not _authorized():
        return Response("Authentication required.", 401,
                        {"WWW-Authenticate": 'Basic realm="Asymmetric Allocator"'})


# --- GitHub helpers -----------------------------------------------------------
def _gh(method: str, path: str, **kw) -> requests.Response:
    headers = {"Authorization": f"Bearer {GH_TOKEN}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    headers.update(kw.pop("headers", {}))
    return requests.request(method, f"{GH_API}{path}", headers=headers, timeout=20, **kw)


def _dispatch_build(mode: str) -> tuple[bool, str]:
    """Kick off the GitHub Actions build. Returns (ok, message)."""
    try:
        r = _gh("POST", f"/repos/{GH_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches",
                json={"ref": GH_REF, "inputs": {"mode": mode}})
    except requests.RequestException as e:
        return False, f"network error reaching GitHub: {e}"
    if r.status_code == 204:
        return True, "dispatched"
    if r.status_code == 404:
        return False, ("workflow not found — make sure build-report.yml is on the "
                       f"'{GH_REF}' branch and GH_REPO is correct")
    if r.status_code in (401, 403):
        return False, "GitHub rejected the token (needs Actions: read+write on this repo)"
    return False, f"GitHub returned {r.status_code}: {r.text[:160]}"


def _find_run() -> dict | None:
    """Newest workflow_dispatch run created at/after this refresh started."""
    try:
        r = _gh("GET", f"/repos/{GH_REPO}/actions/workflows/{WORKFLOW_FILE}/runs",
                params={"event": "workflow_dispatch", "per_page": 10})
        r.raise_for_status()
    except requests.RequestException:
        return None
    cutoff = (JOB["since"] or 0) - 120  # allow for clock skew between us and GitHub
    runs = sorted(r.json().get("workflow_runs", []), key=lambda x: x["id"], reverse=True)
    for run in runs:
        created = _epoch(run.get("created_at"))
        if created is None or created >= cutoff:
            return run
    return None


def _epoch(iso: str | None) -> float | None:
    if not iso:
        return None
    try:  # GitHub timestamps are UTC ("...Z"); timegm reads the struct as UTC.
        return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return None


def _pull_published_report() -> bool:
    """Download latest.html from the live-report branch into the local cache."""
    try:
        r = _gh("GET", f"/repos/{GH_REPO}/contents/latest.html",
                params={"ref": REPORT_BRANCH},
                headers={"Accept": "application/vnd.github.raw"})
    except requests.RequestException:
        return False
    if r.status_code != 200:
        return False
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_bytes(r.content)
    return True


# --- local subprocess fallback (offline dev) ----------------------------------
def _run_local(mode: str, full: bool) -> None:
    JOB.update(running=True, mode=mode, phase=("full data refresh" if full else "rebuild"),
               started=time.time(), error=None)
    flags = ["noopen", mode]
    if not full:
        flags.append("norefresh")
    env = {**os.environ, "PYTHONUTF8": "1"}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH", "")]))
    try:
        r = subprocess.run([str(PY), str(RUNNER), *flags], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=1500)
        if r.returncode != 0:
            JOB["error"] = ((r.stdout or "") + (r.stderr or ""))[-300:] or "build failed"
    except Exception as e:  # noqa: BLE001
        JOB["error"] = f"ERROR: {e}"
    JOB.update(running=False, phase="idle", last=time.time())


# --- routes -------------------------------------------------------------------
@app.route("/report")
def report():
    if not LATEST.exists() and USE_GITHUB:
        _pull_published_report()  # cold start: grab whatever GitHub last built
    if LATEST.exists():
        return send_file(LATEST)
    return ("<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<body style='background:#0a0b0d;color:#8b8f98;font-family:monospace;padding:40px'>"
            "No report yet &mdash; tap <b>Refresh data</b> above to build this week's book.</body>")


@app.route("/api/rebuild", methods=["POST"])
def rebuild():
    if JOB["running"]:
        return jsonify(ok=False, msg="already running")
    mode = "returns" if request.args.get("mode") == "returns" else "safe"
    if USE_GITHUB:
        JOB.update(since=time.time(), run_id=None, run_url=None, error=None)
        ok, msg = _dispatch_build(mode)
        if not ok:
            JOB.update(running=False, phase="idle")
            return jsonify(ok=False, msg=msg)
        JOB.update(running=True, mode=mode, phase="queued", started=time.time())
        return jsonify(ok=True, where="github")
    # local fallback
    full = request.args.get("full", "0") == "1"
    threading.Thread(target=_run_local, args=(mode, full), daemon=True).start()
    return jsonify(ok=True, where="local")


@app.route("/api/status")
def status():
    if JOB["running"] and USE_GITHUB:
        _poll_github()
    elapsed = int(time.time() - JOB["started"]) if (JOB["running"] and JOB["started"]) else 0
    return jsonify(running=JOB["running"], mode=JOB["mode"], phase=JOB["phase"],
                   elapsed=elapsed, run_url=JOB["run_url"], error=JOB["error"],
                   last=JOB["last"])


def _poll_github() -> None:
    run = _find_run()
    if run is None:
        JOB["phase"] = "queued — GitHub is starting the build"
        return
    JOB.update(run_id=run["id"], run_url=run.get("html_url"))
    st, concl = run.get("status"), run.get("conclusion")
    if st == "queued":
        JOB["phase"] = "queued on GitHub"
    elif st == "in_progress":
        JOB["phase"] = "building — fetching prices, ranking the S&P 500"
    elif st == "completed":
        if concl == "success":
            JOB["phase"] = "publishing report" if not _pull_published_report() else "done"
            JOB.update(running=False, last=time.time())
        else:
            JOB.update(running=False, phase="failed", error=f"GitHub build {concl}")


# --- PWA ----------------------------------------------------------------------
_ICON = ("<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'>"
         "<rect width='512' height='512' rx='96' fill='#0a0b0d'/>"
         "<text x='50%' y='54%' font-family='Georgia,serif' font-style='italic' "
         "font-size='300' fill='#d29922' text-anchor='middle' dominant-baseline='middle'>A</text>"
         "</svg>")


@app.route("/icon.svg")
def icon():
    return Response(_ICON, mimetype="image/svg+xml")


@app.route("/manifest.webmanifest")
def manifest():
    return jsonify({"name": "Asymmetric Allocator", "short_name": "Allocator",
                    "display": "standalone", "background_color": "#0a0b0d",
                    "theme_color": "#111317", "start_url": "/",
                    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})


_INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Asymmetric Allocator</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon.svg">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#111317">
<style>
html,body{margin:0;height:100%;background:#0a0b0d;font-family:'DM Mono',ui-monospace,monospace}
#bar{display:flex;align-items:center;gap:12px;min-height:54px;padding:8px 14px;background:#111317;border-bottom:1px solid #1e2128;color:#e8e6e1;font-size:13px;flex-wrap:wrap}
.title{font-style:italic;font-family:Georgia,serif;font-size:18px;color:#e8e6e1}
.seg{display:flex;border:1px solid #1e2128;border-radius:7px;overflow:hidden}
.seg button{background:#0a0b0d;color:#8b8f98;border:0;padding:7px 14px;cursor:pointer;font-family:inherit;font-size:12.5px}
.seg button.on{background:#1a1d24;color:#e8e6e1}
.seg button.on.returns{color:#3fb950}.seg button.on.safe{color:#d29922}
#refresh{background:#0a0b0d;color:#58a6ff;border:1px solid #1e2128;border-radius:7px;padding:7px 14px;cursor:pointer;font-family:inherit;font-size:12.5px}
#refresh:disabled{opacity:.6;cursor:default}
#status{color:#8b8f98;font-size:12px;margin-left:auto;display:flex;align-items:center;gap:8px}
#status a{color:#58a6ff;text-decoration:none}
.dot{width:8px;height:8px;border-radius:50%;background:#3fb950;flex:0 0 auto}
.dot.run{background:#d29922;animation:pulse 1s infinite}
.dot.err{background:#f85149}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
/* progress bar under the control bar while a build runs */
#prog{height:3px;width:100%;background:transparent;overflow:hidden}
#prog.show{background:#1a1d24}
#prog.show>span{display:block;height:100%;width:35%;background:linear-gradient(90deg,transparent,#58a6ff,transparent);animation:slide 1.2s linear infinite}
@keyframes slide{from{transform:translateX(-120%)}to{transform:translateX(400%)}}
iframe{border:0;width:100%;height:calc(100% - 57px);background:#0a0b0d}
@media (max-width:560px){#status{margin-left:0;width:100%;order:9}iframe{height:calc(100% - 99px)}}
</style></head><body>
<div id="bar">
  <span class="title">Asymmetric Allocator</span>
  <span style="color:#8b8f98;font-size:12px">mode</span>
  <div class="seg">
    <button id="safe" class="on safe" onclick="setMode('safe')">Safe</button>
    <button id="returns" onclick="setMode('returns')">Returns</button>
  </div>
  <button id="refresh" onclick="rebuild()">&#8635; Refresh data</button>
  <span id="status"><span class="dot" id="dot"></span><span id="msg">ready</span></span>
</div>
<div id="prog"><span></span></div>
<iframe id="rpt" src="/report"></iframe>
<script>
let MODE='safe', poll=null, t0=0;
function setMode(m){ if(m===MODE||document.getElementById('refresh').disabled) return; MODE=m;
  document.getElementById('safe').classList.toggle('on', m==='safe');
  document.getElementById('returns').classList.toggle('on', m==='returns');
  document.getElementById('returns').classList.toggle('returns', m==='returns');
  rebuild();
}
function fmt(s){ s=s||0; const m=Math.floor(s/60); return m+':'+String(s%60).padStart(2,'0'); }
function ui(running, msg, url, err){
  document.getElementById('refresh').disabled = running;
  document.getElementById('prog').className = running ? 'show' : '';
  const dot = document.getElementById('dot');
  dot.className = 'dot' + (running ? ' run' : (err ? ' err' : ''));
  let html = (msg||'');
  if(url) html += " &middot; <a href='"+url+"' target='_blank' rel='noopener'>view build &#8599;</a>";
  document.getElementById('msg').innerHTML = html;
}
function rebuild(){
  fetch('/api/rebuild?mode='+MODE, {method:'POST'}).then(r=>r.json()).then(j=>{
    if(!j.ok){ ui(false, '⚠ '+(j.msg||'could not start'), null, true); return; }
    t0 = Date.now();
    ui(true, 'starting…', null, false);
    if(poll) clearInterval(poll);
    poll = setInterval(check, 3000); check();
  }).catch(()=>ui(false,'⚠ network error',null,true));
}
function check(){
  fetch('/api/status').then(r=>r.json()).then(j=>{
    if(j.running){
      const el = j.elapsed || Math.floor((Date.now()-t0)/1000);
      ui(true, (j.phase||'building')+' · '+fmt(el), j.run_url, false);
    } else {
      clearInterval(poll); poll=null;
      if(j.error){ ui(false, '⚠ '+j.error, j.run_url, true); }
      else {
        ui(false, 'updated '+new Date().toLocaleTimeString([], {hour:'numeric',minute:'2-digit'}), j.run_url, false);
        document.getElementById('rpt').src = '/report?t='+Date.now();
      }
    }
  }).catch(()=>{});
}
</script></body></html>"""


@app.route("/")
def index():
    return _INDEX


if __name__ == "__main__":
    import webbrowser
    port = int(os.getenv("PORT", "8765"))
    host = os.getenv("HOST", "127.0.0.1")
    url = f"http://{host}:{port}"
    print(f"Asymmetric Allocator site -> {url}  ({'GitHub build' if USE_GITHUB else 'local build'})")
    if host in ("127.0.0.1", "localhost"):
        threading.Timer(1.3, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)
