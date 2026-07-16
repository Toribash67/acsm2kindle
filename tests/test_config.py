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
