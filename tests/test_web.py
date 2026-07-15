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


def test_download_returns_file(tmp_path):
    client, s, worker = _client(tmp_path)
    epub = os.path.join(s.library_dir, "book.epub")
    with open(epub, "wb") as f:
        f.write(b"PK\x03\x04 clean epub")
    job = worker.store.create("book.acsm")
    worker.store.update(job.id, status=JobStatus.DONE, epub_path=epub)

    r = client.get(f"/download/{job.id}")
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04 clean epub"


def test_download_404_when_no_file(tmp_path):
    client, s, worker = _client(tmp_path)
    job = worker.store.create("book.acsm")  # no epub_path
    assert client.get(f"/download/{job.id}").status_code == 404
    assert client.get("/download/9999").status_code == 404


def test_resend_redelivers(tmp_path, monkeypatch):
    client, s, worker = _client(tmp_path)
    epub = os.path.join(s.library_dir, "book.epub")
    with open(epub, "wb") as f:
        f.write(b"PK\x03\x04 clean epub")
    job = worker.store.create("book.acsm")
    worker.store.update(job.id, status=JobStatus.ERROR, epub_path=epub)

    sent = {}
    monkeypatch.setattr("app.main.deliver", lambda path, settings: sent.setdefault("path", path))

    r = client.post(f"/resend/{job.id}", follow_redirects=False)
    assert r.status_code == 303
    assert sent["path"] == epub
    assert worker.store.get(job.id).status == JobStatus.DONE


def test_resend_404_when_no_file(tmp_path):
    client, s, worker = _client(tmp_path)
    job = worker.store.create("book.acsm")  # no epub_path
    assert client.post(f"/resend/{job.id}", follow_redirects=False).status_code == 404
