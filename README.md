# acsm2kindle

Upload an Adobe `.acsm`, get a DRM-free EPUB delivered to your Kindle.
Personal-use format-shifting of books you own. Runs behind Tailscale.

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
6. `docker compose up -d`
7. In nginx-proxy-manager, add a proxy host on the tailnet pointing at
   `acsm2kindle:8000`. Do not expose it publicly.

## Manual integration checklist (real end-to-end)

- [ ] Upload a real purchased `.acsm` at the web page.
- [ ] Library row moves `queued → fulfilling → decrypting → sending → done`.
- [ ] The `data/library/` folder contains a DRM-free `.epub`.
- [ ] The book appears on the Kindle within a few minutes.
- [ ] `download` link returns the EPUB.
- [ ] Break SMTP creds → upload → row shows `error` with a message → fix creds
      → `resend` → `done`.

## Notes on the base image

The Dockerfile pins `bcliang/docker-libgourou:ubuntu` explicitly rather than
`:latest`. Two things discovered while packaging this (see
`.superpowers/sdd/task-9-report.md` for the full verification log):

- Upstream's `:latest` tag currently resolves to the Alpine build, which has
  no `apt-get` for the `python3` install step below it in the Dockerfile.
- The base image's own `ENTRYPOINT` is a hardcoded
  `acsmdownloader → adept_remove` pipeline script
  (`/home/libgourou/entrypoint.sh`) that treats `CMD[0]` as an `.acsm`
  filename. The Dockerfile resets it with `ENTRYPOINT []` so `CMD` runs
  `uvicorn` directly instead of being swallowed as an argument to that
  script.
