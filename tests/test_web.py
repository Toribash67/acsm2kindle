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
