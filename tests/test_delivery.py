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


def test_deliver_wraps_connection_error(tmp_path):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"PK\x03\x04 content")

    def refusing_factory(host, port):
        raise ConnectionRefusedError("connection refused")

    with pytest.raises(delivery.DeliveryError):
        delivery.deliver(str(epub), settings(tmp_path), smtp_factory=refusing_factory)


def test_deliver_rejects_oversize_file(tmp_path, monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(delivery, "MAX_ATTACHMENT_BYTES", 10)
    epub = tmp_path / "big.epub"
    epub.write_bytes(b"0" * 50)
    with pytest.raises(delivery.DeliveryError):
        delivery.deliver(str(epub), settings(tmp_path), smtp_factory=FakeSMTP)
    assert FakeSMTP.instances == []
