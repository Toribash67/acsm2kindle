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
