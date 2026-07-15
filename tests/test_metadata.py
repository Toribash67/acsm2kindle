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
