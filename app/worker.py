import threading
import queue
import logging

from app.pipeline import run_pipeline

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, store, settings):
        self.store = store
        self.settings = settings
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, job_id, source_path):
        self._q.put((job_id, source_path))

    def join_pending(self):
        self._q.join()

    def _loop(self):
        while True:
            job_id, source_path = self._q.get()
            try:
                run_pipeline(job_id, source_path, self.store, self.settings)
            except Exception:
                logger.exception("pipeline crashed for job %s", job_id)
            finally:
                self._q.task_done()
