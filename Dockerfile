# AccessPilot public demo (web/). Runs on any Docker host; set up for Hugging Face Spaces
# (port 7860, user 1000). See web/README.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# The package and its browser first: this layer only changes when accesspilot/ does.
COPY pyproject.toml README.md LICENSE ./
COPY accesspilot ./accesspilot
# Playwright's bundled node driver needs libatomic1, which python:slim does not ship.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && pip install . \
 && python -m playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY web ./web

# The sample reports are real scans of the demo shop, run while the image is built.
RUN python -m web.samples /app/web/samples

RUN useradd --create-home --uid 1000 user && chown -R user /app
USER user

ENV HOST=0.0.0.0 \
    PORT=7860 \
    DEMO_SAMPLES_DIR=/app/web/samples \
    DEMO_LIVE_DIR=/tmp/accesspilot-live
EXPOSE 7860
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz')"
CMD ["python", "-m", "web"]
