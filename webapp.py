"""Local live site for the Asymmetric Allocator (M9 web).

Run:  $env:PYTHONUTF8=1 ; .venv\\Scripts\\python.exe webapp.py
Then open http://127.0.0.1:8765 in any browser. The control bar lets you flip the Safe/Returns
dial and refresh; the report rebuilds in the background and reloads when done. Fully outside
Claude — data + keys stay on your machine.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_file

ROOT = Path(__file__).resolve().parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
RUNNER = ROOT / "scripts" / "weekly_run.py"
LATEST = ROOT / "reports" / "latest.html"

app = Flask(__name__)
JOB = {"running": False, "mode": "safe", "phase": "", "last": None, "log": ""}


def _run(mode: str, full: bool) -> None:
    JOB.update(running=True, mode=mode, phase=("full data refresh" if full else "rebuild"))
    flags = ["noopen", mode]
    if not full:
        flags.append("norefresh")
    env = {**os.environ, "PYTHONUTF8": "1"}
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
    return ("<body style='background:#0a0b0d;color:#8b8f98;font-family:monospace;padding:40px'>"
            "No report yet &mdash; click <b>Refresh data</b> above.</body>")


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


_INDEX = """<!doctype html><html><head><meta charset="utf-8"><title>Asymmetric Allocator</title>
<style>
html,body{margin:0;height:100%;background:#0a0b0d;font-family:'DM Mono',ui-monospace,monospace}
#bar{display:flex;align-items:center;gap:14px;height:54px;padding:0 18px;background:#111317;border-bottom:1px solid #1e2128;color:#e8e6e1;font-size:13px}
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
  document.getElementById('safe').className = 'on safe'.replace('on ', m==='safe'?'on ':'');
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
    import threading
    import webbrowser
    url = "http://127.0.0.1:8765"
    print(f"Asymmetric Allocator site -> {url}  (Ctrl+C to stop)")
    threading.Timer(1.3, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=8765, debug=False)
