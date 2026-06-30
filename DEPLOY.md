# Deploy the dashboard — view & refresh picks from your phone

Goal: open the dashboard on your phone, tap **Refresh data**, and get this week's
book — **with your laptop off**.

## How it works (and why)

The report is cheap to *show* but expensive to *build* (it ranks the whole S&P 500
with pandas — that needs more memory than a small free web host has). So the work is
split:

```
 your phone ──HTTPS──> Render web app  ──triggers──> GitHub Actions (16 GB runner)
   (view + tap Refresh)   (free 512 MB,                 builds the book, no OOM,
                           just serves + shows            publishes report to the
                           live progress)                 `live-report` branch
                              ▲                                     │
                              └──────────── pulls the report ◀──────┘
```

The web app never builds anything, so it can't run out of memory. GitHub does the
heavy lifting on a 16 GB runner, for free.

---

## One-time setup (~15 min)

### 1. Add your API keys to GitHub Actions (not Render)

Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Secret | Where to get it |
| --- | --- |
| `FRED_API_KEY` | https://fred.stlouisfed.org/docs/api/api_key.html |
| `FMP_API_KEY` | https://site.financialmodelingprep.com/developer/docs |
| `FINNHUB_API_KEY` | optional — https://finnhub.io/dashboard |

### 2. Make sure the workflow is on `main`

The `build-report` workflow (`.github/workflows/build-report.yml`) must be on your
**default branch** for the Refresh button to trigger it. Merge this PR into `main`
(or merge the branch) before deploying. Then test it once by hand:
repo → **Actions → build-report → Run workflow**. It should finish green and create a
`live-report` branch containing `latest.html`.

### 3. Create a GitHub token for the web app

The Render app needs to start builds and read the published report. Create a
**fine-grained personal access token** (GitHub → Settings → Developer settings →
Fine-grained tokens):

- **Repository access:** only `asymmetric-allocator`.
- **Permissions:** **Actions → Read and write**, **Contents → Read-only**.

Copy the token (starts with `github_pat_…`).

### 4. Deploy the web app on Render (free)

1. [dashboard.render.com](https://dashboard.render.com) → sign in with GitHub →
   **New + → Blueprint** → pick this repo. It reads `render.yaml`.
2. Fill in the prompted values:
   - `GH_TOKEN` → the token from step 3.
   - `APP_USER` / `APP_PASSWORD` → make these up; they lock the site.
   - (`GH_REPO` / `GH_REF` are pre-filled.)
3. **Apply.** First build is quick now — the web image is tiny (no pandas).
4. Open the `https://asymmetric-allocator-XXXX.onrender.com` URL, sign in, and tap
   **Refresh data**. You'll see a live progress bar: *queued → building → done*
   (~3-5 min, it's really running on GitHub — there's a "view build ↗" link). When
   it finishes, the book appears.

### 5. Add it to your phone home screen
- **iPhone (Safari):** Share → **Add to Home Screen**.
- **Pixel / Android (Chrome):** ⋮ → **Add to Home screen / Install app**.

You get an "A" icon that opens the dashboard full-screen.

---

## Day-to-day

- **It auto-builds every Monday** (the workflow's schedule), so most of the time the
  latest book is already waiting — no tapping needed.
- **Tap Refresh** any time to rebuild now; the **Safe/Returns** toggle rebuilds in
  that mode. The progress bar + elapsed timer make it obvious it's working.
- **Free Render tier sleeps after ~15 min idle** → the first visit after a nap takes
  ~1 min to wake, then it's instant. The report itself is always current because
  GitHub builds it independently of whether the web app is awake.

---

## Other hosts (Docker)

A tiny `Dockerfile` (web deps only) is included, so Fly.io, Railway, Cloud Run, or a
VPS work too. Pass `GH_REPO`, `GH_TOKEN`, `APP_USER`, `APP_PASSWORD` (and optionally
`GH_REF`). The container serves on `$PORT`.

---

## Run it locally (no cloud)

With no `GH_REPO`/`GH_TOKEN` set, the app falls back to building on your own machine
in a subprocess — the original local experience:

    # PowerShell, from the project root (needs the full .venv + .env keys)
    .\.venv\Scripts\python.exe webapp.py        # http://127.0.0.1:8765

Set `HOST=0.0.0.0` to reach that local instance from your phone on the same Wi-Fi.
