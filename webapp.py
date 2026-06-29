"""Live site for the Asymmetric Allocator (M9 web).

Local:  $env:PYTHONUTF8=1 ; .venv\\Scripts\\python.exe webapp.py
        then open http://127.0.0.1:8765

Cloud:  gunicorn webapp:app   (binds the platform's $PORT)
        Deploy anywhere always-on so you can view + refresh from your phone with
        the laptop off — see DEPLOY.md. Set APP_USER/APP_PASSWORD to password-gate
        the public URL.

The control bar flips the Safe/Returns dial and refreshes; the report rebuilds in
the background and reloads when done.
"""
from __future__ import annotations

import base64
import hmac
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

ROOT = Path(__file__).resolve().parent
# Use the interpreter actually running this process (the venv locally, the system
# Python in a container) — never a hardcoded path, which broke on non-Windows hosts.
PY = sys.executable
RUNNER = ROOT / "scripts" / "weekly_run.py"
# Honour the same DATA_DIR/REPORTS_DIR overrides the engine uses (persistent disk).
LATEST = Path(os.getenv("REPORTS_DIR") or ROOT / "reports") / "latest.html"

app = Flask(__name__)
JOB = {"running": False, "mode": "safe", "phase": "", "last": None, "log": ""}

# Optional HTTP Basic Auth. When APP_USER + APP_PASSWORD are set (always set them
# for a public deploy), every route requires them. Unset locally = open, as before.
_AUTH_USER = os.getenv("APP_USER")
_AUTH_PASS = os.getenv("APP_PASSWORD")


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
    # constant-time compare to avoid leaking length/contents via timing
    return hmac.compare_digest(user, _AUTH_USER) and hmac.compare_digest(pw, _AUTH_PASS)


@app.before_request
def _gate():
    if not _authorized():
        return Response(
            "Authentication required.", 401,
            {"WWW-Authenticate": 'Basic realm="Asymmetric Allocator"'},
        )


def _run(mode: str, full: bool) -> None:
    JOB.update(running=True, mode=mode, phase=("full data refresh" if full else "rebuild"))
    flags = ["noopen", mode]
    if not full:
        flags.append("norefresh")
    env = {**os.environ, "PYTHONUTF8": "1"}
    # Make `import allocator` resolve even if the package wasn't pip-installed.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH", "")]))
    try:
        r = subprocess.run([str(PY), str(RUNNER), *flags], cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=1500)
        JOB["log"] = ((r.stdout or "") + (r.stderr or ""))[-2000:]
    except Exception as e:  # noqa: BLE001
        JOB["log"] = f"ERROR: {e}"
    JOB.update(running=False, phase="", last=time.time())


@app.route("/report")
def report():
    if LATEST.exists():
        return send_file(LATEST)
    return ("<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<body style='background:#0a0b0d;color:#8b8f98;font-family:monospace;padding:40px'>"
            "No report yet &mdash; tap <b>Refresh data</b> above.</body>")


@app.route("/api/rebuild", methods=["POST"])
def rebuild():
    if JOB["running"]:
        return jsonify(ok=False, msg="already running")
    mode = "returns" if request.args.get("mode") == "returns" else "safe"
    full = request.args.get("full", "0") == "1"
    threading.Thread(target=_run, args=(mode, full), daemon=True).start()
    return jsonify(ok=True)


@app.route("/api/status")
def status():
    return jsonify(running=JOB["running"], mode=JOB["mode"], phase=JOB["phase"],
                   log=JOB["log"][-600:])


# --- PWA: lets you "Add to Home Screen" for a one-tap, full-screen app icon ----
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
    return jsonify({
        "name": "Asymmetric Allocator",
        "short_name": "Allocator",
        "display": "standalone",
        "background_color": "#0a0b0d",
        "theme_color": "#111317",
        "start_url": "/",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
    })


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
#refresh:disabled{opacity:.5;cursor:default}
#status{color:#8b8f98;font-size:12px;margin-left:auto}
.spin{color:#d29922}
iframe{border:0;width:100%;height:calc(100% - 54px);background:#0a0b0d}
@media (max-width:560px){#status{margin-left:0;width:100%;order:9}iframe{height:calc(100% - 96px)}}
</style></head><body>
<div id="bar">
  <span class="title">Asymmetric Allocator</span>
  <span style="color:#8b8f98;font-size:12px">mode</span>
  <div class="seg">
    <button id="safe" class="on safe" onclick="setMode('safe')">Safe</button>
    <button id="returns" onclick="setMode('returns')">Returns</button>
  </div>
  <button id="refresh" onclick="rebuild(true)">&#8635; Refresh data</button>
  <span id="status"></span>
</div>
<iframe id="rpt" src="/report"></iframe>
<script>
let MODE='safe', poll=null;
function setMode(m){ if(m===MODE) return; MODE=m;
  document.getElementById('safe').classList.toggle('on', m==='safe');
  document.getElementById('returns').classList.toggle('on', m==='returns');
  document.getElementById('returns').classList.toggle('returns', m==='returns');
  rebuild(false);
}
function rebuild(full){
  fetch('/api/rebuild?mode='+MODE+'&full='+(full?1:0), {method:'POST'}).then(r=>r.json()).then(j=>{
    if(!j.ok) return;
    document.getElementById('refresh').disabled = true;
    setStatus(full ? 'refreshing data + rebuilding (a few min)…' : 'switching to '+MODE+' mode…', true);
    if(poll) clearInterval(poll);
    poll = setInterval(check, 1500);
  });
}
function check(){
  fetch('/api/status').then(r=>r.json()).then(j=>{
    if(!j.running){
      clearInterval(poll); poll=null;
      document.getElementById('refresh').disabled = false;
      setStatus('updated '+new Date().toLocaleTimeString(), false);
      document.getElementById('rpt').src = '/report?t='+Date.now();
    }
  });
}
function setStatus(t, spin){ const s=document.getElementById('status'); s.textContent=t; s.className=spin?'spin':''; }
</script></body></html>"""


@app.route("/")
def index():
    return _INDEX


if __name__ == "__main__":
    import webbrowser
    port = int(os.getenv("PORT", "8765"))
    # Localhost by default; set HOST=0.0.0.0 to reach it from other devices on your LAN.
    host = os.getenv("HOST", "127.0.0.1")
    url = f"http://{host}:{port}"
    print(f"Asymmetric Allocator site -> {url}  (Ctrl+C to stop)")
    if host in ("127.0.0.1", "localhost"):
        threading.Timer(1.3, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False)
