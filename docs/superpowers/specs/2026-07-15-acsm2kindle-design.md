# acsm2kindle — Design

**Date:** 2026-07-15
**Status:** Approved (brainstorming), pending implementation plan

## Goal

A self-hosted web app, reachable only over Tailscale, that turns a purchased
Adobe-DRM book into a DRM-free EPUB on the owner's Kindle with a single upload.
From the user's perspective: drop an `.acsm` file on a page, and the book later
appears on the Kindle. The finished DRM-free EPUBs are also kept in a browsable
library on the page (backup + re-send).

This is a personal-use tool for format-shifting legally purchased content to the
owner's own device.

## Scope

- **Path A (build now):** input is an Adobe `.acsm` fulfillment ticket. A headless
  libgourou-based engine fulfills it, downloads the DRM'd EPUB, and strips the
  ADEPT DRM in one step — no Adobe Digital Editions and no Calibre needed.
- **Path B (later, seam only):** input is an already-downloaded DRM'd `.epub`/`.pdf`.
  Handled by Calibre + DeDRM behind the same interface. Not built now, but the
  engine dispatch is designed so it slots in without touching the rest.

## One-time setup (documented in README, not code)

1. **Adobe activation** — run the engine's activate command once with the owner's
   Adobe ID; it writes device/activation files into the config volume, authorizing
   this box.
2. **Amazon** — add the sending Gmail address to Amazon's *Approved Personal
   Document E-mail List*; record the target `@kindle.com` address.
3. **Gmail** — generate an app password for SMTP sending.

All three feed the app as **environment variables / mounted secrets**. None are
committed to the repo. The repo is safe to make public.

## Architecture

Single Docker image, one Dockge compose stack (matches the host's existing setup):

- **Python 3 + FastAPI** — minimal server-rendered UI + JSON endpoints.
- **libgourou (via the `knock` wrapper)** baked into the image = the path-A engine.
- **In-process background worker** — one job at a time (sufficient for a single
  user); uploads return immediately, UI never blocks.
- **State = files on a mounted volume**, no database server:
  - `/data/incoming` — uploaded `.acsm`
  - `/data/library`  — finished DRM-free `.epub` (the backup)
  - `/data/config`   — Adobe activation files (secret, gitignored, volume-only)
  - `/data/jobs.sqlite` — job records / status

### Configuration (env vars, via Dockge `.env`)

- `KINDLE_EMAIL` — target `@kindle.com` address
- `SENDER_EMAIL` — the approved Gmail sender
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (app password)
- Adobe ID credentials are needed **only** at activation time, not at runtime.

## Data flow

```
upload .acsm ─► validate (real ADEPT fulfillment token?)
            ─► queue job ─► worker:
                 engine(acsm) ─► DRM-free epub          [status: fulfilling → decrypting]
                 store in /library + read title/author  [status: stored]
                 deliver(epub) ─► SMTP ─► @kindle.com    [status: sending → done]
```

## Web UI

Two views, server-rendered, polling for status:

- **Upload** — drag/drop or pick an `.acsm`, submit.
- **Library / jobs** — table of books: title, status
  (`queued → fulfilling → decrypting → sending → done` / `error`), timestamp,
  **download** link, **resend to Kindle** button.

**Auth:** none. Tailscale is the security boundary and this is single-user. The app
binds so it is only reachable on the tailnet (behind nginx-proxy-manager, like the
host's other apps).

## Engine seam (path B readiness)

A single interface `process(input_file) -> epub_path`, dispatched by extension:

- `.acsm`        → **A-engine** (libgourou / knock) — built now.
- `.epub`/`.pdf` → **B-engine** (Calibre + DeDRM) — added later.

Downstream (store in library, read metadata, deliver) is identical for both, so
adding path B is an isolated change.

## Error handling

- Reject uploads that are not a valid ADEPT `.acsm` before queueing.
- Each pipeline step is wrapped; on failure → `status: error` with the engine's
  captured stderr shown in the UI; the input file stays for **retry**.
- Surface common Adobe cases clearly: "already fulfilled on another device",
  "loan/subscription expired", "device not activated".
- SMTP failure keeps the EPUB in the library and offers **resend** (delivery is
  decoupled from conversion).
- Flag EPUBs over Amazon's Send-to-Kindle attachment limit (~50 MB).

## Testing

- **Unit:**
  - `.acsm` validation (accept real ADEPT token, reject junk/other XML).
  - Metadata extraction (title/author from EPUB OPF).
  - Engine dispatch selection by extension.
  - `deliver()` against a mock SMTP server, using a fixture EPUB from a fake engine.
- **Manual integration:** an end-to-end checklist (real `.acsm` + real Adobe creds
  → book arrives on Kindle), since a genuine run needs a real purchase.

## Non-goals (YAGNI)

- Multi-user accounts / login.
- Multi-job concurrency / distributed queue.
- Calibre library management features.
- Building path B now.
