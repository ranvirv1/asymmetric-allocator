# Asymmetric Allocator — container image for always-on cloud hosting.
# Build:  docker build -t allocator .
# Run:    docker run -p 8765:8765 -e PORT=8765 \
#           -e FRED_API_KEY=... -e FMP_API_KEY=... \
#           -e APP_USER=you -e APP_PASSWORD=secret allocator
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install deps first so they cache across code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
# Install the `allocator` package so `import allocator` works in the refresh subprocess.
RUN pip install -e .

# One worker keeps the in-memory job state + background refresh thread coherent;
# threads let the report serve while the status endpoint is polled. The refresh
# itself runs as a detached subprocess, so the request timeout never kills it.
# Shell form so $PORT (injected by the host) is expanded; defaults to 8765 locally.
CMD gunicorn webapp:app --bind 0.0.0.0:${PORT:-8765} --workers 1 --threads 4 --timeout 120
