# acsm2kindle

Upload an Adobe `.acsm`, get a DRM-free EPUB delivered to your Kindle.
Personal-use format-shifting of books you own. Runs behind Tailscale.

From your side it is one step: drop a DRM-protected `.acsm` on a web page, and
the book appears on your Kindle a few minutes later. Every finished DRM-free
EPUB also stays in a browsable library on the page as a backup.

---

## How the pipeline works

When you upload a file, it flows through these stages. The status shown in the
library page (and in `GET /api/jobs`) tracks exactly where a book is:

```
 upload .acsm
     │  POST /upload  — saved to /data/incoming, rejected (HTTP 400) unless it
     │                  parses as an ADEPT <fulfillmentToken> XML document
     ▼
 [queued]      a job row is created in SQLite and handed to the worker thread;
     │         the HTTP request returns immediately (the UI never blocks)
     ▼
 [fulfilling]  engine runs, in a fresh temp dir, with HOME pointed at the
     │         activation volume so libgourou finds your device keys:
     │            acsmdownloader -f <file.acsm>
     │         This contacts the bookstore's Adobe Content Server, redeems the
     │         fulfilment token, and downloads the *still-DRM-encrypted* EPUB.
     ▼
 [decrypting]  the encrypted book is stripped in place:
     │            adept_remove -f <encrypted.epub>
     │         The newest resulting .epub/.pdf is moved into /data/library.
     ▼
 [stored]      the EPUB's OPF metadata (dc:title / dc:creator) is read and the
     │         file is renamed to a sanitized "<Title>.epub"; the job row records
     │         title, author, and the library path.
     ▼
 [sending]     the finished EPUB is emailed as an attachment (see Delivery below)
     ▼
 [done]        the book is on its way to the Kindle and downloadable from the page
```

Any stage that fails moves the job to **[error]** with the underlying tool's
stderr captured into the job row and shown in the UI. The already-produced EPUB
(if any) stays in the library, and the **resend** button re-runs only the email
step — conversion is never repeated.

The conversion itself is done by a single command pair; there is no Adobe Digital
Editions and no Calibre in the loop for this path. The engine call
(`app/engine.py`) is deliberately defensive: it runs each libgourou tool in an
isolated temp directory and discovers the output by newest-modified file, so it
does not depend on exact output filenames.

### Delivery ("Send to Kindle")

`app/delivery.py` builds an RFC 5322 email with `email.message.EmailMessage`:

- **From:** `SENDER_EMAIL`   **To:** `KINDLE_EMAIL`   **Subject:** the EPUB filename
- The EPUB is attached with MIME type `application/epub+zip`.
- It connects to `SMTP_HOST:SMTP_PORT` (30 s timeout), upgrades with **STARTTLS**,
  authenticates with `SMTP_USER` / `SMTP_PASSWORD`, and sends.
- Files larger than **50 MB** (Amazon's Send-to-Kindle attachment limit) are
  rejected *before* a connection is opened.
- Any `SMTPException` or connection-level `OSError` (bad host, refused, timeout)
  is wrapped as a `DeliveryError` so the job is marked errored and can be resent.

Amazon receives the message at your `@kindle.com` address and delivers the EPUB
to your devices, converting it to Kindle format server-side.

---

## What it talks to (APIs, protocols, services)

| Boundary | Protocol / API | Used for |
|---|---|---|
| Adobe Content Server (the bookstore's fulfilment host) | **ADEPT** (Adobe's DRM protocol), spoken by **libgourou** over HTTPS | Redeeming the `.acsm` token, downloading the encrypted book, and one-time device activation |
| Adobe activation | `adept_activate -u <AdobeID> -p <pw>` (libgourou) | One-time: registers a virtual device tied to your Adobe ID; writes `device.xml`, `activation.xml`, `devicesalt` to `~/.adept` (persisted on the volume) |
| Mail server (e.g. Gmail) | **SMTP** with **STARTTLS** on port 587, LOGIN auth | Sending the finished EPUB as an email attachment |
| Amazon | **Send to Kindle** email ingest (`@kindle.com` + approved-sender list) | Delivering the EPUB onto the Kindle |
| Browser ↔ app | **HTTP** (FastAPI), fronted by nginx-proxy-manager on the tailnet | Upload, library view, downloads, status polling |
| Reverse proxy / network | **Tailscale** | The only access boundary — there is no login |

No third-party HTTP APIs with keys are involved: the only credentials are your
Adobe ID (activation only), your mail account, and Amazon's approved-sender list.

### HTTP endpoints

| Method & path | Purpose |
|---|---|
| `GET /` | Upload page (drop/pick an `.acsm`) |
| `POST /upload` | Save + validate the `.acsm`, create a job, enqueue it; 400 if not a valid ADEPT token; 303 redirect to `/library` |
| `GET /library` | Library/jobs page (polls `/api/jobs`) |
| `GET /api/jobs` | JSON list of all jobs (newest first) — id, source_name, status, title, author, epub_path, error, created_at |
| `GET /download/{job_id}` | Download the finished EPUB (404 if none) |
| `POST /resend/{job_id}` | Re-run only the email step for a job that has a stored EPUB |

---

## Architecture

Single Docker image, one process, no external services beyond the mail server.

```
app/
  config.py      Settings from environment; computes /data subpaths
  validation.py  is_valid_acsm() — checks the ADEPT fulfillmentToken root
  engine.py      process(): dispatch by extension; runs libgourou for .acsm
  metadata.py    extract_metadata() — title/author from the EPUB OPF
  delivery.py    deliver() — SMTP + STARTTLS with a 50 MB guard
  jobs.py        JobStatus, Job, JobStore — SQLite-backed job records
  pipeline.py    run_pipeline() — the synchronous engine→store→metadata→deliver chain
  worker.py      Worker — a daemon thread + queue, one job at a time
  main.py        FastAPI app + routes; module-level app gated on ACSM2KINDLE_AUTOSTART
  templates/     upload.html, library.html (library polls /api/jobs, escapes untrusted fields)
```

- **State is files on the `/data` volume plus one SQLite file** — no database
  server. The web request handler and the worker thread each open and close
  their own SQLite connection per call, so nothing crosses the thread boundary.
- **The worker runs one job at a time** (`queue.Queue` + a daemon thread). Its
  loop is crash-guarded: a failing job is logged and the thread keeps draining.
- **`app.main:app` is only constructed when `ACSM2KINDLE_AUTOSTART=1`** (set in
  the Dockerfile), so importing the module during tests has no side effects.

### Data layout on the volume

| Path | Contents |
|---|---|
| `/data/incoming/` | Uploaded `.acsm` files |
| `/data/library/`  | Finished DRM-free EPUBs (your backup) |
| `/data/config/`   | Adobe activation files under `.adept/` — **secret**, never committed |
| `/data/jobs.sqlite` | Job records / status |

---

## Configuration

All configuration is environment variables (see `.env.example`). Nothing
sensitive is committed; `.env` and `/data/config` are gitignored / volume-only.

| Variable | Meaning |
|---|---|
| `KINDLE_EMAIL` | Your Send-to-Kindle address (`something@kindle.com`) |
| `SENDER_EMAIL` | The From address; must be on Amazon's approved-sender list |
| `SMTP_HOST` / `SMTP_PORT` | Mail server (e.g. `smtp.gmail.com` / `587`) |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP login; for Gmail use an **app password**, not your account password |
| `DATA_DIR` | Volume root (default `/data`) |

Adobe ID credentials are needed **only** during one-time activation and are
never stored by the running app.

---

## One-time setup

1. Copy `.env.example` to `.env` and fill in Kindle + Gmail SMTP values.
2. Amazon → *Manage Your Content and Devices* → *Preferences* →
   *Personal Document Settings*: add your `SENDER_EMAIL` to the approved list,
   and copy your `@kindle.com` address into `KINDLE_EMAIL`.
3. Gmail → create an **app password**; put it in `SMTP_PASSWORD`.
4. `docker compose build`
5. Activate Adobe (once):
   ```bash
   docker compose run --rm -e HOME=/data/config acsm2kindle \
     adept_activate -u "ADOBE_EMAIL" -p "ADOBE_PASSWORD"
   ```
   This writes `device.xml`, `activation.xml`, `devicesalt` into
   `data/config/.adept/`. Books bought under an Adobe ID can only be decrypted
   with that same account's key, so activate with the account you buy under.
6. `docker compose up -d`
7. In nginx-proxy-manager, add a proxy host on the tailnet pointing at
   `acsm2kindle:8000`. Do not expose it publicly.

## Manual integration checklist (real end-to-end)

The conversion path can only be fully confirmed with a real purchase and real
Adobe credentials — run this once after setup:

- [ ] Upload a real purchased `.acsm` at the web page.
- [ ] Library row moves `queued → fulfilling → decrypting → sending → done`.
- [ ] The `data/library/` folder contains a DRM-free `.epub`.
- [ ] The book appears on the Kindle within a few minutes.
- [ ] `download` link returns the EPUB.
- [ ] Break SMTP creds → upload → row shows `error` with a message → fix creds
      → `resend` → `done`.

## Testing

The suite is hermetic — every external dependency (the libgourou binaries and
SMTP) is injected, so no real credentials or network are needed. The target host
has no `pip`, so tests run inside a container:

```bash
./scripts/test.sh            # whole suite
./scripts/test.sh tests/test_engine.py -v
```

## Security posture

- **No authentication.** Tailscale is the only access boundary — never expose
  the app publicly. The container binds `0.0.0.0:8000`; keep it on the tailnet.
- **No secrets in the repo.** Adobe device keys, the Gmail app password, and the
  Kindle address live only in `.env` and the `/data/config` volume.
- Uploaded filenames are reduced to their basename; untrusted EPUB metadata is
  escaped before it is rendered in the library page.

## Path B (not built)

Input other than `.acsm` — an already-downloaded but still-DRM'd `.epub`/`.pdf`
— is dispatched to a Calibre + DeDRM path that is intentionally a
`NotImplementedError` seam. The rest of the pipeline (library, metadata,
delivery) would be unchanged if it is added later.

## Notes on the base image

The Dockerfile pins `bcliang/docker-libgourou:ubuntu` explicitly rather than
`:latest`. Two things discovered while packaging this:

- Upstream's `:latest` tag currently resolves to the Alpine build, which has
  no `apt-get` for the `python3` install step below it in the Dockerfile.
- The base image's own `ENTRYPOINT` is a hardcoded
  `acsmdownloader → adept_remove` pipeline script
  (`/home/libgourou/entrypoint.sh`) that treats `CMD[0]` as an `.acsm`
  filename. The Dockerfile resets it with `ENTRYPOINT []` so `CMD` runs
  `uvicorn` directly instead of being swallowed as an argument to that
  script.
