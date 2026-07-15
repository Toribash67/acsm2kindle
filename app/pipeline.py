import os
import shutil

from app.engine import process, EngineError
from app.metadata import extract_metadata
from app.delivery import deliver, DeliveryError
from app.jobs import JobStatus


def run_pipeline(job_id, source_path, store, settings, *,
                 engine_process=process, extract=extract_metadata,
                 deliver_fn=deliver):
    try:
        store.update(job_id, status=JobStatus.FULFILLING)
        epub = engine_process(source_path, settings.library_dir,
                              settings.config_dir)

        store.update(job_id, status=JobStatus.DECRYPTING)
        md = extract(epub)

        # Rename to a human title if we got one and there is no collision.
        titled = _titled_path(settings.library_dir, md["title"], epub)
        if titled != epub and not os.path.exists(titled):
            shutil.move(epub, titled)
            epub = titled

        store.update(job_id, status=JobStatus.STORED, title=md["title"],
                     author=md["author"], epub_path=epub)

        store.update(job_id, status=JobStatus.SENDING)
        deliver_fn(epub, settings)

        store.update(job_id, status=JobStatus.DONE)
    except (EngineError, DeliveryError) as e:
        store.update(job_id, status=JobStatus.ERROR,
                     error=getattr(e, "stderr", "") or str(e))
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        store.update(job_id, status=JobStatus.ERROR, error=str(e))


def _titled_path(library_dir, title, current):
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    if not safe:
        return current
    ext = os.path.splitext(current)[1]
    return os.path.join(library_dir, safe + ext)
