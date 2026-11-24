# AccessPilot public demo

A hosted, user-facing version of AccessPilot: a landing page that explains the problem,
two sample reports to browse, and live scans anyone can start from a web address.

```bash
pip install -e . && python -m playwright install chromium
python -m web          # http://localhost:7860 (builds the sample reports on first start, ~30 s)
```

## What is in here

| File | What |
| --- | --- |
| `app.py` | The server (standard library only): pages, JSON API, scan queue, report files. |
| `guard.py` | Limits for anonymous visitors: public-address check (SSRF) and rate limits. |
| `shop.py` | *Maison Céleste*, a fictional shop with typical theme defects, in a `before` and an `after` version. |
| `samples.py` | Scans both shop versions with the real crawler and writes the sample reports. |
| `static/` | The front end: plain HTML, CSS and JavaScript, no build step. |

The sample numbers are never hand-written: the Docker build runs `python -m web.samples`, which
serves the demo shop on a loopback port, scans it, and relabels its address as
`maison-celeste.example` (a reserved domain) in the reports.

## Limits on live scans

The local `accesspilot ui` trusts its user; this server does not.

- Up to 8 pages, one level of links, 2 pages per template, 90 s budget; robots.txt always honoured.
- One scan at a time, a queue of 4; 3 scans per visitor per hour, 150 per day for everyone.
  The same address scanned again within 30 minutes reuses the earlier result.
- Only public addresses on ports 80/443. The host must resolve to globally routable IPs only, and
  every request the browser makes is checked again (plus where each navigation landed after
  redirects), so a scan cannot be pointed at the host's private network or cloud metadata.
- Live results are reachable only through their random link, never listed, deleted after 6 hours.
- `POST /api/scan` requires `Content-Type: application/json`, so other websites cannot start scans
  from their visitors' browsers. Strict Content-Security-Policy on every response.

Settings (environment variables): `PORT`, `HOST`, `DEMO_MAX_PAGES`, `DEMO_TIME_BUDGET_S`,
`DEMO_SCANS_PER_HOUR`, `DEMO_SCANS_PER_DAY`, `DEMO_QUEUE`, `DEMO_KEEP_HOURS`,
`DEMO_TRUST_PROXY_HOPS` (how many proxies sit in front: the visitor's IP is read that many
entries from the right of `X-Forwarded-For`; 0 ignores the header), `DEMO_SAMPLES_DIR`,
`DEMO_LIVE_DIR`, `ACCESSPILOT_CHROMIUM`.

## Deploy for free on Hugging Face Spaces

Spaces run Docker images for free (2 vCPU, 16 GB RAM, enough for Chromium). A free Space sleeps
after 48 hours without visitors and takes about a minute to wake up.

1. Create a Hugging Face account, then **New Space**: name it (for example `accesspilot`),
   SDK **Docker**, template **Blank**, hardware **CPU basic (free)**, visibility **Public**.
2. Create an access token at <https://huggingface.co/settings/tokens> with **Write** access.
3. In the GitHub repository, **Settings → Secrets and variables → Actions**:
   - secret `HF_TOKEN` = the token,
   - variable `HF_SPACE` = `your-hf-username/accesspilot`.
4. **Actions → Deploy demo → Run workflow** (it also runs on every push to `main` that touches
   the app). The Space builds the image (about 5 minutes the first time) and goes live at
   `https://your-hf-username-accesspilot.hf.space`.

Any other Docker host works the same way: `docker build -t accesspilot-demo . && docker run -p 7860:7860 accesspilot-demo`.
Render's and Fly's free/small tiers have 256–512 MB of RAM, which is tight for Chromium.
