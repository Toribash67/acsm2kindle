# acsm2kindle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Tailscale-only web app where uploading an Adobe `.acsm` produces a DRM-free EPUB that is emailed to the owner's Kindle and kept in a browsable library.

**Architecture:** Single Python (FastAPI) service in one Docker image based on `bcliang/docker-libgourou`, so the libgourou utils (`acsmdownloader`, `adept_remove`, `adept_activate`) are available on `PATH`. A background worker thread runs a synchronous pipeline (engine → store → metadata → deliver) per job. State is files on a mounted `/data` volume plus a SQLite job database. No login — Tailscale is the boundary.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, Jinja2 templates, stdlib `smtplib`/`sqlite3`/`xml.etree`, libgourou utils (system binaries), Docker + docker-compose (Dockge).

## Global Constraints

- **No secrets in the repo.** All credentials come from environment variables (`.env`, gitignored). `.env.example` holds placeholders only.
- **Config volume:** libgourou reads device files from `~/.adept`; the app sets `HOME` to the config dir so activation persists on the `/data` volume.
- **Engine for path A only.** `.acsm` inputs are built now. `.epub`/`.pdf` (path B, Calibre+DeDRM) must raise a clear `NotImplementedError` behind the same dispatch — do not implement it.
- **Single-user, single job at a time.** No auth, no multi-job concurrency, no distributed queue (YAGNI).
- **Data dir default:** `/data`, overridable by env `DATA_DIR`. Subdirs: `incoming/`, `library/`, `config/`, and `jobs.sqlite`.
- **Send-to-Kindle attachment limit:** flag EPUBs larger than 50 MB before sending.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

```
acsm2kindle/
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md                      # includes one-time setup + manual integration checklist
  .env.example                   # (exists)
  .gitignore                     # (exists)
  app/
    __init__.py
    config.py                    # Settings from env
    validation.py                # is_valid_acsm()
    engine.py                    # process(): dispatch by extension; libgourou runner
    metadata.py                  # extract_metadata() from EPUB OPF
    delivery.py                  # deliver() via SMTP
    jobs.py                      # JobStatus, Job, JobStore (SQLite)
    pipeline.py                  # run_pipeline(): synchronous orchestration
    worker.py                    # Worker: background thread + queue
    main.py                      # FastAPI routes + startup wiring
    templates/
      upload.html
      library.html
  tests/
    conftest.py
    test_config.py
    test_validation.py
    test_engine.py
    test_metadata.py
    test_delivery.py
    test_jobs.py
    test_pipeline.py
    test_web.py
    fixtures/
      sample.acsm                # minimal valid ADEPT fulfillmentToken XML
      not-acsm.xml               # valid XML, wrong root
      sample.epub                # tiny valid EPUB with title/author
```

---

## Task 1: Project scaffold + config

**Files:**
- Create: `requirements.txt`, `app/__init__.py`, `app/config.py`, `tests/conftest.py`, `tests/test_config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `app.config.Settings` (dataclass) with fields `kindle_email: str`, `sender_email: str`, `smtp_host: str`, `smtp_port: int`, `smtp_user: str`, `smtp_password: str`, `data_dir: str`, and read-only computed props `incoming_dir`, `library_dir`, `config_dir`, `db_path` (all `str`); `app.config.get_settings() -> Settings` reads from `os.environ`; `Settings.ensure_dirs() -> None` creates the subdirs.

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
jinja2==3.1.*
python-multipart==0.0.*
pytest==8.*
httpx==0.27.*
```

- [ ] **Step 2: Create empty `app/__init__.py` and `tests/conftest.py`**

`app/__init__.py`: empty file.

`tests/conftest.py`:
```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 3: Write the failing test** in `tests/test_config.py`

```python
import os
from app.config import get_settings


def test_settings_read_from_env_and_compute_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KINDLE_EMAIL", "me@kindle.com")
    monkeypatch.setenv("SENDER_EMAIL", "me@gmail.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pw")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    s = get_settings()

    assert s.kindle_email == "me@kindle.com"
    assert s.smtp_port == 587
    assert s.incoming_dir == os.path.join(str(tmp_path), "incoming")
    assert s.library_dir == os.path.join(str(tmp_path), "library")
    assert s.config_dir == os.path.join(str(tmp_path), "config")
    assert s.db_path == os.path.join(str(tmp_path), "jobs.sqlite")

    s.ensure_dirs()
    assert os.path.isdir(s.incoming_dir)
    assert os.path.isdir(s.library_dir)
    assert os.path.isdir(s.config_dir)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 5: Implement `app/config.py`**

```python
import os
from dataclasses import dataclass


@dataclass
class Settings:
    kindle_email: str
    sender_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    data_dir: str

    @property
    def incoming_dir(self) -> str:
        return os.path.join(self.data_dir, "incoming")

    @property
    def library_dir(self) -> str:
        return os.path.join(self.data_dir, "library")

    @property
    def config_dir(self) -> str:
        return os.path.join(self.data_dir, "config")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "jobs.sqlite")

    def ensure_dirs(self) -> None:
        for d in (self.incoming_dir, self.library_dir, self.config_dir):
            os.makedirs(d, exist_ok=True)


def get_settings() -> Settings:
    return Settings(
        kindle_email=os.environ.get("KINDLE_EMAIL", ""),
        sender_email=os.environ.get("SENDER_EMAIL", ""),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        data_dir=os.environ.get("DATA_DIR", "/data"),
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add requirements.txt app/__init__.py app/config.py tests/conftest.py tests/test_config.py
git commit -m "feat: project scaffold and env-based settings"
```

---

## Task 2: `.acsm` validation

**Files:**
- Create: `app/validation.py`, `tests/fixtures/sample.acsm`, `tests/fixtures/not-acsm.xml`, `tests/test_validation.py`
- Test: `tests/test_validation.py`

**Interfaces:**
- Produces: `app.validation.is_valid_acsm(path: str) -> bool` — returns True only if the file parses as XML whose root tag is `fulfillmentToken` in the ADEPT namespace (`http://ns.adobe.com/adept`).

- [ ] **Step 1: Create fixture `tests/fixtures/sample.acsm`**

```xml
<fulfillmentToken xmlns="http://ns.adobe.com/adept" fulfillmentType="buy">
  <resourceItemInfo>
    <resource>urn:uuid:00000000-0000-0000-0000-000000000000</resource>
  </resourceItemInfo>
</fulfillmentToken>
```

- [ ] **Step 2: Create fixture `tests/fixtures/not-acsm.xml`**

```xml
<html xmlns="http://www.w3.org/1999/xhtml"><body>not a book</body></html>
```

- [ ] **Step 3: Write the failing test** in `tests/test_validation.py`

```python
import os
from app.validation import is_valid_acsm

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_accepts_real_acsm():
    assert is_valid_acsm(os.path.join(FIX, "sample.acsm")) is True


def test_rejects_other_xml():
    assert is_valid_acsm(os.path.join(FIX, "not-acsm.xml")) is False


def test_rejects_non_xml(tmp_path):
    p = tmp_path / "junk.acsm"
    p.write_text("this is not xml at all")
    assert is_valid_acsm(str(p)) is False
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.validation'`

- [ ] **Step 5: Implement `app/validation.py`**

```python
import xml.etree.ElementTree as ET

ADEPT_NS = "http://ns.adobe.com/adept"


def is_valid_acsm(path: str) -> bool:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return False
    return root.tag == f"{{{ADEPT_NS}}}fulfillmentToken"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_validation.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add app/validation.py tests/test_validation.py tests/fixtures/sample.acsm tests/fixtures/not-acsm.xml
git commit -m "feat: validate ADEPT .acsm files"
```

---

## Task 3: Engine (dispatch + libgourou runner)

**Files:**
- Create: `app/engine.py`, `tests/test_engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `app.engine.EngineError(Exception)` with attribute `.stderr: str`.
  - `app.engine.process(input_file: str, out_dir: str, config_dir: str, runner=_default_runner) -> str` — dispatches by extension. `.acsm` → runs the libgourou pipeline via `runner` and returns the path to the DRM-free `.epub` inside `out_dir`. `.epub`/`.pdf` → raises `NotImplementedError("path B (Calibre/DeDRM) not implemented")`. Unknown extension → raises `EngineError`.
  - `runner` signature: `runner(args: list[str], cwd: str, config_dir: str) -> subprocess.CompletedProcess`. Injectable so tests never call real binaries.

- [ ] **Step 1: Write the failing test** in `tests/test_engine.py`

```python
import os
import pytest
from app import engine


def make_fake_runner(epub_bytes=b"PK\x03\x04 fake epub"):
    """Fake libgourou: acsmdownloader drops book.epub; adept_remove rewrites it."""
    def runner(args, cwd, config_dir):
        prog = os.path.basename(args[0])
        if prog == "acsmdownloader":
            with open(os.path.join(cwd, "book.epub"), "wb") as f:
                f.write(b"ENCRYPTED")
        elif prog == "adept_remove":
            target = args[-1]
            with open(target, "wb") as f:
                f.write(epub_bytes)
        import subprocess
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return runner


def test_process_acsm_returns_epub(tmp_path):
    acsm = tmp_path / "in.acsm"
    acsm.write_text("<fulfillmentToken/>")
    out = tmp_path / "out"
    out.mkdir()

    result = engine.process(str(acsm), str(out), str(tmp_path / "cfg"),
                            runner=make_fake_runner())

    assert result.endswith(".epub")
    assert os.path.dirname(result) == str(out)
    assert open(result, "rb").read() == b"PK\x03\x04 fake epub"


def test_process_epub_is_path_b_not_implemented(tmp_path):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"x")
    with pytest.raises(NotImplementedError):
        engine.process(str(epub), str(tmp_path), str(tmp_path))


def test_runner_failure_raises_engine_error(tmp_path):
    acsm = tmp_path / "in.acsm"
    acsm.write_text("<fulfillmentToken/>")

    def failing_runner(args, cwd, config_dir):
        import subprocess
        raise engine.EngineError("boom")
    with pytest.raises(engine.EngineError):
        engine.process(str(acsm), str(tmp_path), str(tmp_path),
                       runner=failing_runner)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.engine'`

- [ ] **Step 3: Implement `app/engine.py`**

```python
import os
import glob
import shutil
import subprocess
import tempfile


class EngineError(Exception):
    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr or message


def _default_runner(args, cwd, config_dir):
    """Run a libgourou util. HOME=config_dir so it finds ~/.adept device files."""
    env = dict(os.environ)
    env["HOME"] = config_dir
    proc = subprocess.run(
        args, cwd=cwd, env=env,
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise EngineError(
            f"{os.path.basename(args[0])} failed (exit {proc.returncode})",
            stderr=proc.stderr,
        )
    return proc


def _newest(cwd, *exts):
    files = []
    for ext in exts:
        files += glob.glob(os.path.join(cwd, f"*{ext}"))
    if not files:
        raise EngineError(f"engine produced no {exts} output")
    return max(files, key=os.path.getmtime)


def _process_acsm(input_file, out_dir, config_dir, runner):
    work = tempfile.mkdtemp(prefix="acsm2kindle-")
    try:
        # 1. Fulfill + download the (still DRM'd) book into the work dir.
        runner(["acsmdownloader", "-f", input_file, "-o", "book"],
               cwd=work, config_dir=config_dir)
        encrypted = _newest(work, ".epub", ".pdf")
        # 2. Strip ADEPT DRM in place.
        runner(["adept_remove", "-f", encrypted],
               cwd=work, config_dir=config_dir)
        decrypted = _newest(work, ".epub", ".pdf")
        # 3. Move the finished file into out_dir.
        base = os.path.splitext(os.path.basename(input_file))[0]
        dest = os.path.join(out_dir, base + os.path.splitext(decrypted)[1])
        shutil.move(decrypted, dest)
        return dest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def process(input_file, out_dir, config_dir, runner=_default_runner):
    ext = os.path.splitext(input_file)[1].lower()
    if ext == ".acsm":
        return _process_acsm(input_file, out_dir, config_dir, runner)
    if ext in (".epub", ".pdf"):
        raise NotImplementedError("path B (Calibre/DeDRM) not implemented")
    raise EngineError(f"unsupported input type: {ext}")
```

> **Implementer note:** `acsmdownloader`/`adept_remove` flags (`-f`, `-o`) are verified against the container in Task 8's smoke test. The runner is defensive (temp dir + newest-file discovery), so exact output filenames don't matter. If the container's `--help` shows different flags, adjust the two `runner([...])` arg lists and re-run this task's tests.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/engine.py tests/test_engine.py
git commit -m "feat: engine with acsm dispatch and injectable libgourou runner"
```

---

## Task 4: EPUB metadata extraction

**Files:**
- Create: `app/metadata.py`, `tests/fixtures/sample.epub`, `tests/test_metadata.py`
- Test: `tests/test_metadata.py`

**Interfaces:**
- Produces: `app.metadata.extract_metadata(epub_path: str) -> dict` returning `{"title": str, "author": str}`. Reads `META-INF/container.xml` → OPF → `dc:title` / `dc:creator`. On any failure, falls back to `{"title": <filename stem>, "author": ""}`.

- [ ] **Step 1: Build the EPUB fixture** with a script step

Run this exact Python to create `tests/fixtures/sample.epub`:
```python
python - <<'PY'
import os, zipfile
FIX = "tests/fixtures"
os.makedirs(FIX, exist_ok=True)
container = '''<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>'''
opf = '''<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Test Book</dc:title>
    <dc:creator>Ada Author</dc:creator>
  </metadata>
</package>'''
with zipfile.ZipFile(os.path.join(FIX, "sample.epub"), "w") as z:
    z.writestr("mimetype", "application/epub+zip")
    z.writestr("META-INF/container.xml", container)
    z.writestr("content.opf", opf)
print("wrote", os.path.join(FIX, "sample.epub"))
PY
```

- [ ] **Step 2: Write the failing test** in `tests/test_metadata.py`

```python
import os
from app.metadata import extract_metadata

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_extracts_title_and_author():
    md = extract_metadata(os.path.join(FIX, "sample.epub"))
    assert md["title"] == "The Test Book"
    assert md["author"] == "Ada Author"


def test_falls_back_to_filename_on_bad_epub(tmp_path):
    p = tmp_path / "My Book.epub"
    p.write_bytes(b"not a zip")
    md = extract_metadata(str(p))
    assert md["title"] == "My Book"
    assert md["author"] == ""
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.metadata'`

- [ ] **Step 4: Implement `app/metadata.py`**

```python
import os
import zipfile
import xml.etree.ElementTree as ET

CONTAINER = "META-INF/container.xml"
DC = "http://purl.org/dc/elements/1.1/"
CN = "urn:oasis:names:tc:opendocument:xmlns:container"


def extract_metadata(epub_path: str) -> dict:
    stem = os.path.splitext(os.path.basename(epub_path))[0]
    try:
        with zipfile.ZipFile(epub_path) as z:
            container = ET.fromstring(z.read(CONTAINER))
            rootfile = container.find(f".//{{{CN}}}rootfile")
            opf_path = rootfile.get("full-path")
            opf = ET.fromstring(z.read(opf_path))
            title = opf.findtext(f".//{{{DC}}}title") or stem
            author = opf.findtext(f".//{{{DC}}}creator") or ""
            return {"title": title.strip(), "author": author.strip()}
    except Exception:
        return {"title": stem, "author": ""}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add app/metadata.py tests/test_metadata.py tests/fixtures/sample.epub
git commit -m "feat: extract title/author from EPUB OPF"
```

---

## Task 5: Email delivery

**Files:**
- Create: `app/delivery.py`, `tests/test_delivery.py`
- Test: `tests/test_delivery.py`

**Interfaces:**
- Consumes: `app.config.Settings`.
- Produces:
  - `app.delivery.DeliveryError(Exception)`.
  - `app.delivery.MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024`.
  - `app.delivery.deliver(epub_path: str, settings, smtp_factory=smtplib.SMTP) -> None`. Builds an email from `settings.sender_email` to `settings.kindle_email` with the EPUB attached, connects via `smtp_factory(host, port)`, STARTTLS, login, send. Raises `DeliveryError` if the file exceeds `MAX_ATTACHMENT_BYTES` (before connecting) or on SMTP failure. `smtp_factory` is injectable for tests.

- [ ] **Step 1: Write the failing test** in `tests/test_delivery.py`

```python
import os
import pytest
from app import delivery
from app.config import Settings


def settings(tmp_path):
    return Settings(
        kindle_email="me@kindle.com", sender_email="me@gmail.com",
        smtp_host="smtp.test", smtp_port=587, smtp_user="me@gmail.com",
        smtp_password="pw", data_dir=str(tmp_path),
    )


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in = None
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, pw):
        self.logged_in = (user, pw)

    def send_message(self, msg):
        self.sent = msg


def test_deliver_sends_with_attachment(tmp_path):
    FakeSMTP.instances = []
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"PK\x03\x04 content")

    delivery.deliver(str(epub), settings(tmp_path), smtp_factory=FakeSMTP)

    smtp = FakeSMTP.instances[-1]
    assert smtp.started_tls is True
    assert smtp.logged_in == ("me@gmail.com", "pw")
    assert smtp.sent["To"] == "me@kindle.com"
    assert smtp.sent["From"] == "me@gmail.com"
    attachments = [p for p in smtp.sent.iter_attachments()]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "book.epub"


def test_deliver_rejects_oversize_file(tmp_path, monkeypatch):
    monkeypatch.setattr(delivery, "MAX_ATTACHMENT_BYTES", 10)
    epub = tmp_path / "big.epub"
    epub.write_bytes(b"0" * 50)
    with pytest.raises(delivery.DeliveryError):
        delivery.deliver(str(epub), settings(tmp_path), smtp_factory=FakeSMTP)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_delivery.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.delivery'`

- [ ] **Step 3: Implement `app/delivery.py`**

```python
import os
import smtplib
from email.message import EmailMessage

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


class DeliveryError(Exception):
    pass


def deliver(epub_path, settings, smtp_factory=smtplib.SMTP):
    size = os.path.getsize(epub_path)
    if size > MAX_ATTACHMENT_BYTES:
        raise DeliveryError(
            f"file is {size} bytes, over the {MAX_ATTACHMENT_BYTES}-byte "
            "Send-to-Kindle limit"
        )
    msg = EmailMessage()
    msg["From"] = settings.sender_email
    msg["To"] = settings.kindle_email
    msg["Subject"] = os.path.basename(epub_path)
    msg.set_content("Sent by acsm2kindle.")
    with open(epub_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application", subtype="epub+zip",
            filename=os.path.basename(epub_path),
        )
    try:
        with smtp_factory(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except smtplib.SMTPException as e:
        raise DeliveryError(f"SMTP send failed: {e}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_delivery.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/delivery.py tests/test_delivery.py
git commit -m "feat: email delivery to Kindle with size guard"
```

---

## Task 6: Job store (SQLite)

**Files:**
- Create: `app/jobs.py`, `tests/test_jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Produces:
  - `app.jobs.JobStatus` — str-valued enum: `QUEUED`, `FULFILLING`, `DECRYPTING`, `STORED`, `SENDING`, `DONE`, `ERROR`.
  - `app.jobs.Job` — dataclass: `id: int`, `source_name: str`, `status: str`, `title: str`, `author: str`, `epub_path: str`, `error: str`, `created_at: str`.
  - `app.jobs.JobStore(db_path: str)` with: `create(source_name: str) -> Job`; `update(job_id: int, **fields) -> None` (allowed fields: status, title, author, epub_path, error); `get(job_id: int) -> Job | None`; `list() -> list[Job]` (newest first).

- [ ] **Step 1: Write the failing test** in `tests/test_jobs.py`

```python
from app.jobs import JobStore, JobStatus


def test_create_get_update_list(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite"))

    job = store.create("mybook.acsm")
    assert job.id > 0
    assert job.source_name == "mybook.acsm"
    assert job.status == JobStatus.QUEUED

    store.update(job.id, status=JobStatus.DONE, title="T", author="A",
                 epub_path="/data/library/mybook.epub")
    got = store.get(job.id)
    assert got.status == JobStatus.DONE
    assert got.title == "T"
    assert got.epub_path == "/data/library/mybook.epub"

    store.create("second.acsm")
    listed = store.list()
    assert len(listed) == 2
    assert listed[0].source_name == "second.acsm"  # newest first


def test_get_missing_returns_none(tmp_path):
    store = JobStore(str(tmp_path / "jobs.sqlite"))
    assert store.get(999) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.jobs'`

- [ ] **Step 3: Implement `app/jobs.py`**

```python
import sqlite3
from dataclasses import dataclass


class JobStatus:
    QUEUED = "queued"
    FULFILLING = "fulfilling"
    DECRYPTING = "decrypting"
    STORED = "stored"
    SENDING = "sending"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: int
    source_name: str
    status: str
    title: str
    author: str
    epub_path: str
    error: str
    created_at: str


_ALLOWED = {"status", "title", "author", "epub_path", "error"}


class JobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    epub_path TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_job(self, row) -> Job:
        return Job(**{k: row[k] for k in Job.__annotations__})

    def create(self, source_name: str) -> Job:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO jobs (source_name, status) VALUES (?, ?)",
                (source_name, JobStatus.QUEUED),
            )
            return self.get(cur.lastrowid)

    def update(self, job_id: int, **fields) -> None:
        cols = [k for k in fields if k in _ALLOWED]
        if not cols:
            return
        assignments = ", ".join(f"{k} = ?" for k in cols)
        values = [fields[k] for k in cols] + [job_id]
        with self._conn() as c:
            c.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)

    def get(self, job_id: int):
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def list(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
            return [self._row_to_job(r) for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/jobs.py tests/test_jobs.py
git commit -m "feat: SQLite-backed job store"
```

---

## Task 7: Pipeline orchestration

**Files:**
- Create: `app/pipeline.py`, `tests/test_pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `app.engine.process`, `app.metadata.extract_metadata`, `app.delivery.deliver`, `app.jobs.JobStore`/`JobStatus`, `app.config.Settings`, `app.engine.EngineError`, `app.delivery.DeliveryError`.
- Produces: `app.pipeline.run_pipeline(job_id: int, source_path: str, store: JobStore, settings: Settings, *, engine_process=process, extract=extract_metadata, deliver_fn=deliver) -> None`. Runs the full chain synchronously, updating job status at each stage. On `EngineError` or `DeliveryError` or any exception, sets `status=ERROR` and writes the message (engine stderr if present) to `error`. Dependencies are injectable for tests.

- [ ] **Step 1: Write the failing test** in `tests/test_pipeline.py`

```python
import os
from app.pipeline import run_pipeline
from app.jobs import JobStore, JobStatus
from app.engine import EngineError
from app.config import Settings


def _settings(tmp_path):
    s = Settings(kindle_email="me@kindle.com", sender_email="me@gmail.com",
                 smtp_host="h", smtp_port=587, smtp_user="u", smtp_password="p",
                 data_dir=str(tmp_path))
    s.ensure_dirs()
    return s


def test_happy_path_stores_and_delivers(tmp_path):
    s = _settings(tmp_path)
    store = JobStore(s.db_path)
    job = store.create("book.acsm")
    src = os.path.join(s.incoming_dir, "book.acsm")
    open(src, "w").write("<fulfillmentToken/>")

    delivered = {}

    def fake_engine(input_file, out_dir, config_dir, **kw):
        dest = os.path.join(out_dir, "book.epub")
        open(dest, "wb").write(b"clean epub")
        return dest

    def fake_extract(path):
        return {"title": "Book", "author": "Auth"}

    def fake_deliver(path, settings, **kw):
        delivered["path"] = path

    run_pipeline(job.id, src, store, s, engine_process=fake_engine,
                 extract=fake_extract, deliver_fn=fake_deliver)

    done = store.get(job.id)
    assert done.status == JobStatus.DONE
    assert done.title == "Book"
    assert os.path.dirname(done.epub_path) == s.library_dir
    assert delivered["path"] == done.epub_path


def test_engine_error_marks_job_error_with_stderr(tmp_path):
    s = _settings(tmp_path)
    store = JobStore(s.db_path)
    job = store.create("book.acsm")
    src = os.path.join(s.incoming_dir, "book.acsm")
    open(src, "w").write("<fulfillmentToken/>")

    def boom(input_file, out_dir, config_dir, **kw):
        raise EngineError("fulfillment failed", stderr="E_ADEPT_CORE ...")

    run_pipeline(job.id, src, store, s, engine_process=boom)

    failed = store.get(job.id)
    assert failed.status == JobStatus.ERROR
    assert "E_ADEPT_CORE" in failed.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Implement `app/pipeline.py`**

```python
import os
import shutil

from app.engine import process, EngineError
from app.metadata import extract_metadata
from app.delivery import deliver, DeliveryError
from app.jobs import JobStatus


def run_pipeline(job_id, source_path, store, settings, *,
                 engine_process=process, extract=extract_metadata,
                 deliver_fn=deliver):
    try:
        store.update(job_id, status=JobStatus.FULFILLING)
        epub = engine_process(source_path, settings.library_dir,
                              settings.config_dir)

        store.update(job_id, status=JobStatus.DECRYPTING)
        md = extract(epub)

        # Rename to a human title if we got one and there is no collision.
        titled = _titled_path(settings.library_dir, md["title"], epub)
        if titled != epub and not os.path.exists(titled):
            shutil.move(epub, titled)
            epub = titled

        store.update(job_id, status=JobStatus.STORED, title=md["title"],
                     author=md["author"], epub_path=epub)

        store.update(job_id, status=JobStatus.SENDING)
        deliver_fn(epub, settings)

        store.update(job_id, status=JobStatus.DONE)
    except (EngineError, DeliveryError) as e:
        store.update(job_id, status=JobStatus.ERROR,
                     error=getattr(e, "stderr", "") or str(e))
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        store.update(job_id, status=JobStatus.ERROR, error=str(e))


def _titled_path(library_dir, title, current):
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    if not safe:
        return current
    ext = os.path.splitext(current)[1]
    return os.path.join(library_dir, safe + ext)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: synchronous conversion+delivery pipeline with error capture"
```

---

## Task 8: Worker thread + FastAPI web layer

**Files:**
- Create: `app/worker.py`, `app/main.py`, `app/templates/upload.html`, `app/templates/library.html`, `tests/test_web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `app.pipeline.run_pipeline`, `app.jobs.JobStore`/`JobStatus`, `app.config.get_settings`/`Settings`, `app.validation.is_valid_acsm`.
- Produces:
  - `app.worker.Worker(store, settings)` with `submit(job_id: int, source_path: str) -> None` (enqueues; a daemon thread calls `run_pipeline`) and `join_pending()` for tests (blocks until the queue drains).
  - `app.main.create_app(settings=None, worker=None) -> FastAPI`. Routes:
    - `GET /` → upload page (`upload.html`).
    - `POST /upload` (multipart `file`) → save to `incoming/`, reject non-`.acsm` via `is_valid_acsm` with HTTP 400, else create job + `worker.submit`, redirect to `/library` (303).
    - `GET /library` → `library.html` listing `store.list()`.
    - `GET /api/jobs` → JSON list of jobs (for polling).
    - `GET /download/{job_id}` → FileResponse of the job's `epub_path` (404 if missing).
    - `POST /resend/{job_id}` → re-run `deliver` for a `DONE`/`ERROR` job that has an `epub_path`; redirect to `/library`.

- [ ] **Step 1: Write the failing test** in `tests/test_web.py`

```python
import io
import os
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.jobs import JobStore, JobStatus


class SyncWorker:
    """Runs the pipeline inline so tests are deterministic."""
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.submitted = []

    def submit(self, job_id, source_path):
        self.submitted.append((job_id, source_path))
        self.store.update(job_id, status=JobStatus.DONE,
                          epub_path=os.path.join(self.settings.library_dir,
                                                 "out.epub"))

    def join_pending(self):
        pass


def _client(tmp_path):
    s = Settings(kindle_email="me@kindle.com", sender_email="me@gmail.com",
                 smtp_host="h", smtp_port=587, smtp_user="u", smtp_password="p",
                 data_dir=str(tmp_path))
    s.ensure_dirs()
    worker = SyncWorker(JobStore(s.db_path), s)
    app = create_app(settings=s, worker=worker)
    return TestClient(app), s, worker


def test_upload_valid_acsm_creates_job(tmp_path):
    client, s, worker = _client(tmp_path)
    acsm = b'<fulfillmentToken xmlns="http://ns.adobe.com/adept"/>'
    r = client.post("/upload",
                    files={"file": ("book.acsm", io.BytesIO(acsm), "application/xml")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert len(worker.submitted) == 1
    jobs = client.get("/api/jobs").json()
    assert jobs[0]["source_name"] == "book.acsm"


def test_upload_rejects_non_acsm(tmp_path):
    client, s, worker = _client(tmp_path)
    r = client.post("/upload",
                    files={"file": ("x.acsm", io.BytesIO(b"<html/>"), "application/xml")})
    assert r.status_code == 400
    assert worker.submitted == []


def test_library_page_renders(tmp_path):
    client, s, worker = _client(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/library").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement `app/worker.py`**

```python
import threading
import queue

from app.pipeline import run_pipeline


class Worker:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, job_id, source_path):
        self._q.put((job_id, source_path))

    def join_pending(self):
        self._q.join()

    def _loop(self):
        while True:
            job_id, source_path = self._q.get()
            try:
                run_pipeline(job_id, source_path, self.store, self.settings)
            finally:
                self._q.task_done()
```

- [ ] **Step 4: Implement templates**

`app/templates/upload.html`:
```html
<!doctype html>
<html><head><meta charset="utf-8"><title>acsm2kindle</title>
<style>body{font-family:system-ui;max-width:640px;margin:3rem auto;padding:0 1rem}
form{border:2px dashed #888;padding:2rem;border-radius:8px;text-align:center}
a{display:inline-block;margin-top:1rem}</style></head>
<body>
<h1>Send a book to Kindle</h1>
<form action="/upload" method="post" enctype="multipart/form-data">
  <p>Drop or choose an <code>.acsm</code> file.</p>
  <input type="file" name="file" accept=".acsm" required>
  <p><button type="submit">Convert &amp; send</button></p>
</form>
<a href="/library">View library &rarr;</a>
</body></html>
```

`app/templates/library.html`:
```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Library</title>
<style>body{font-family:system-ui;max-width:820px;margin:3rem auto;padding:0 1rem}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;padding:.5rem;text-align:left}
.error{color:#b00}.done{color:#080}</style>
<script>
async function refresh(){
  const r = await fetch('/api/jobs'); const jobs = await r.json();
  const rows = jobs.map(j => `<tr>
    <td>${j.title || j.source_name}</td>
    <td class="${j.status}">${j.status}${j.error ? ' — '+j.error : ''}</td>
    <td>${j.epub_path ? `<a href="/download/${j.id}">download</a>` : ''}</td>
    <td>${j.epub_path ? `<form method="post" action="/resend/${j.id}"><button>resend</button></form>` : ''}</td>
  </tr>`).join('');
  document.getElementById('rows').innerHTML = rows;
}
setInterval(refresh, 3000); window.onload = refresh;
</script></head>
<body>
<h1>Library</h1><a href="/">&larr; Upload another</a>
<table><thead><tr><th>Book</th><th>Status</th><th>File</th><th></th></tr></thead>
<tbody id="rows"></tbody></table>
</body></html>
```

- [ ] **Step 5: Implement `app/main.py`**

```python
import os
from dataclasses import asdict

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, FileResponse,
)
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.jobs import JobStore, JobStatus
from app.validation import is_valid_acsm
from app.worker import Worker
from app.delivery import deliver

TEMPLATES = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


def create_app(settings=None, worker=None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = JobStore(settings.db_path)
    worker = worker or Worker(store, settings)
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def upload_page(request: Request):
        return TEMPLATES.TemplateResponse("upload.html", {"request": request})

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        dest = os.path.join(settings.incoming_dir, os.path.basename(file.filename))
        with open(dest, "wb") as f:
            f.write(await file.read())
        if not is_valid_acsm(dest):
            os.remove(dest)
            raise HTTPException(status_code=400, detail="Not a valid .acsm file")
        job = store.create(os.path.basename(file.filename))
        worker.submit(job.id, dest)
        return RedirectResponse("/library", status_code=303)

    @app.get("/library", response_class=HTMLResponse)
    def library(request: Request):
        return TEMPLATES.TemplateResponse("library.html", {"request": request})

    @app.get("/api/jobs")
    def api_jobs():
        return JSONResponse([asdict(j) for j in store.list()])

    @app.get("/download/{job_id}")
    def download(job_id: int):
        job = store.get(job_id)
        if not job or not job.epub_path or not os.path.exists(job.epub_path):
            raise HTTPException(status_code=404, detail="No file")
        return FileResponse(job.epub_path,
                            filename=os.path.basename(job.epub_path))

    @app.post("/resend/{job_id}")
    def resend(job_id: int):
        job = store.get(job_id)
        if not job or not job.epub_path or not os.path.exists(job.epub_path):
            raise HTTPException(status_code=404, detail="No file to resend")
        store.update(job_id, status=JobStatus.SENDING, error="")
        try:
            deliver(job.epub_path, settings)
            store.update(job_id, status=JobStatus.DONE)
        except Exception as e:  # noqa: BLE001
            store.update(job_id, status=JobStatus.ERROR, error=str(e))
        return RedirectResponse("/library", status_code=303)

    return app


app = create_app() if os.environ.get("ACSM2KINDLE_AUTOSTART") else None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_web.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add app/worker.py app/main.py app/templates/ tests/test_web.py
git commit -m "feat: background worker and FastAPI web layer"
```

---

## Task 9: Docker packaging, compose, README + manual verification

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `README.md`
- Modify: none

**Interfaces:**
- Consumes: everything above. Produces a runnable container image and the documented one-time setup + integration checklist.

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
# libgourou utils (acsmdownloader, adept_activate, adept_remove) live in
# /usr/local/bin of this image; it is Ubuntu-based (Alpine build segfaults).
FROM bcliang/docker-libgourou:latest

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app/ ./app/

ENV DATA_DIR=/data
# Module-level `app` in app/main.py is built only when this is set (keeps
# pytest imports side-effect-free); the container opts in.
ENV ACSM2KINDLE_AUTOSTART=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  acsm2kindle:
    build: .
    container_name: acsm2kindle
    restart: unless-stopped
    env_file: .env
    environment:
      DATA_DIR: /data
    volumes:
      - ./data:/data
    ports:
      - "8000:8000"   # front with nginx-proxy-manager on the tailnet only
```

- [ ] **Step 3: Build the image and run the engine smoke test**

Run:
```bash
docker compose build
docker compose run --rm acsm2kindle acsmdownloader --help
docker compose run --rm acsm2kindle adept_remove --help
```
Expected: each prints usage/options without error. **If the flags differ from `-f`/`-o` used in `app/engine.py`, update `app/engine.py` and re-run `pytest tests/test_engine.py`.**

- [ ] **Step 4: Verify the web app boots**

Run:
```bash
docker compose up -d
curl -sf http://localhost:8000/ | grep -q "Send a book to Kindle" && echo "OK web up"
docker compose logs --tail 20 acsm2kindle
```
Expected: prints `OK web up`. If the container exits, check `docker compose logs` — the most likely cause is `ACSM2KINDLE_AUTOSTART` not being set so `app` is `None`; confirm the `ENV` line from Step 1 is present and rebuild.

- [ ] **Step 5: Perform the one-time Adobe activation**

Run (replace with real Adobe ID; this writes device files into `./data/config/.adept`):
```bash
docker compose run --rm -e HOME=/data/config acsm2kindle \
  adept_activate -u "YOUR_ADOBE_EMAIL" -p "YOUR_ADOBE_PASSWORD"
ls data/config/.adept   # expect: activation.xml  device.xml  devicesalt
```
Expected: the three device files exist on the mounted volume.

- [ ] **Step 6: Write `README.md`** documenting setup and the manual integration checklist

````markdown
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
````

- [ ] **Step 7: Commit**

```bash
git add Dockerfile docker-compose.yml README.md
git commit -m "feat: docker packaging, compose, and setup/verification docs"
```

---

## Self-Review Notes

- **Spec coverage:** upload+validate (T2,T8), libgourou engine path A + path-B seam (T3), library storage (T7), metadata (T4), SMTP delivery + resend (T5,T8), job status UI + polling (T6,T8), Tailscale/no-auth + Dockge packaging (T9), error capture with stderr (T3,T7), 50 MB guard (T5), one-time Adobe/Amazon/Gmail setup (T9 README). All spec sections map to a task.
- **Path B** is explicitly a `NotImplementedError` (Global Constraints + T3), matching the "seam only" scope.
- **Type consistency:** `process(input_file, out_dir, config_dir, runner=...)`, `extract_metadata(epub_path)->dict`, `deliver(epub_path, settings, smtp_factory=...)`, `JobStore.create/update/get/list`, `run_pipeline(job_id, source_path, store, settings, *, engine_process, extract, deliver_fn)`, `Worker.submit(job_id, source_path)` are used identically across tasks.
- **Known verify-at-build risk:** exact libgourou util flags and the uvicorn factory CMD are validated in T9 Steps 3–4 with explicit fix instructions, not left as guesses.
