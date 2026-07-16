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
