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
