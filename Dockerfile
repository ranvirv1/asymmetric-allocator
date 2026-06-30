# Asymmetric Allocator — web viewer image (serves the dashboard, triggers builds).
# The heavy report build runs on GitHub Actions, so this image stays tiny and only
# needs the web deps. Build:  docker build -t allocator .
# Run:   docker run -p 8765:8765 -e GH_REPO=owner/repo -e GH_TOKEN=... \
#          -e APP_USER=you -e APP_PASSWORD=secret allocator
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-web.txt ./
RUN pip install -r requirements-web.txt

COPY webapp.py ./

# One worker keeps the in-memory job state coherent; threads let the report serve
# while the status endpoint is polled. Shell form so the host's $PORT is expanded.
CMD gunicorn webapp:app --bind 0.0.0.0:${PORT:-8765} --workers 1 --threads 4 --timeout 120
