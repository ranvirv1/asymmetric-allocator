# Deploy the dashboard — view & refresh picks from your phone

The dashboard (`webapp.py`) normally runs on your laptop at `127.0.0.1`. To open it
on your **phone with the laptop off**, it has to live on an always-on host in the
cloud. This guide gets you there in ~10 minutes, free, and ends with a one-tap app
icon on your home screen.

What you get: a private HTTPS URL where you can read this week's book and tap
**Refresh data** to rebuild the picks — the rebuild runs *on the server*, so your
laptop never needs to be on.

---

## What you need first

- A free **Render** account: https://render.com (sign in with GitHub).
- Your API keys (same ones as local — free tiers are fine):
  - `FRED_API_KEY` — https://fred.stlouisfed.org/docs/api/api_key.html
  - `FMP_API_KEY` — https://site.financialmodelingprep.com/developer/docs
  - `FINNHUB_API_KEY` — optional.
- A username + password you'll make up to lock the site (`APP_USER` / `APP_PASSWORD`).

> **Why a password?** The URL is on the public internet. Without `APP_USER` +
> `APP_PASSWORD` set, anyone who finds it can see your book and trigger refreshes.
> The app stays open only when those two are unset (i.e. local dev).

---

## Deploy on Render (recommended, free)

1. Push this branch to GitHub (already done if you're reading this in the PR).
2. In Render: **New +  →  Blueprint**, and select this repository.
3. Render reads `render.yaml` and asks for the secret values. Fill in:
   `FRED_API_KEY`, `FMP_API_KEY`, (optional `FINNHUB_API_KEY`), and your
   `APP_USER` / `APP_PASSWORD`.
4. Click **Apply**. First build takes a few minutes (it installs pandas etc.).
5. Open the `https://asymmetric-allocator-XXXX.onrender.com` URL it gives you,
   sign in with the user/password you chose, then tap **Refresh data**. The first
   refresh pulls all market data (a few minutes); after that the book renders.

### Add it to your phone home screen (the "easy access" bit)
- **iPhone (Safari):** open the URL → Share → **Add to Home Screen**.
- **Android (Chrome):** open the URL → ⋮ menu → **Add to Home screen / Install app**.

You'll get an "A" app icon that opens the dashboard full-screen, no address bar.

---

## Good to know about the free tier

- **It sleeps after ~15 min idle.** The first visit after a nap takes ~1 minute to
  wake (you'll see a spinner), then it's instant. Fine for a weekly check.
- **Disk is ephemeral.** When the instance sleeps/redeploys, the cached data and the
  last report are wiped, so the next visit needs a fresh **Refresh data**. To keep
  them between visits, add a Render **Disk** (paid) and set two env vars to point at
  it: `DATA_DIR=/var/data` and `REPORTS_DIR=/var/data/reports` (the app and engine
  both honour these). Mount the disk at `/var/data`.
- **Memory:** the free instance is 512 MB. The S&P-500 refresh fits, but if a build
  ever gets OOM-killed, bump to a paid instance.

### Keep it auto-fresh (optional)
Want the book rebuilt every Monday without tapping anything? Add a Render **Cron
Job** service in the same repo with the command:

    python scripts/weekly_run.py noopen safe

and a schedule of `0 11 * * 1` (Mon 11:00 UTC). It writes to the same place the web
service reads. (Needs the persistent disk above so the web service sees the result.)

---

## Other hosts (Docker)

A `Dockerfile` is included, so anything that runs a container works too —
Fly.io, Railway, Google Cloud Run, a VPS. The container serves on `$PORT` (or 8765)
via gunicorn. Pass the same env vars (`FRED_API_KEY`, `FMP_API_KEY`, `APP_USER`,
`APP_PASSWORD`, optionally `DATA_DIR` / `REPORTS_DIR`). Example:

    docker build -t allocator .
    docker run -p 8765:8765 \
      -e FRED_API_KEY=... -e FMP_API_KEY=... \
      -e APP_USER=you -e APP_PASSWORD=secret \
      allocator

---

## Just want it on your phone at home (no cloud)

If "laptop off" isn't a hard requirement, you can skip hosting: run it on your
laptop bound to your LAN and open it from your phone on the same Wi-Fi.

    # PowerShell, from the project root
    $env:HOST = "0.0.0.0"
    .\.venv\Scripts\python.exe webapp.py

Find your laptop's local IP (`ipconfig` → IPv4, e.g. `192.168.1.42`) and visit
`http://192.168.1.42:8765` on your phone. Works only while the laptop is on and
you're on the same network — which is why the Render path above is the real answer
to "independent of my laptop."
