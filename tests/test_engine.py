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
