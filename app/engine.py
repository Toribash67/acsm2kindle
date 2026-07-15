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
