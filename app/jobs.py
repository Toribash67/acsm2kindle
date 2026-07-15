import contextlib
import sqlite3
from dataclasses import dataclass


class JobStatus:
    QUEUED = "queued"
    FULFILLING = "fulfilling"
    DECRYPTING = "decrypting"
    STORED = "stored"
    SENDING = "sending"
    DONE = "done"
    ERROR = "error"


@dataclass
class Job:
    id: int
    source_name: str
    status: str
    title: str
    author: str
    epub_path: str
    error: str
    created_at: str


_ALLOWED = {"status", "title", "author", "epub_path", "error"}


class JobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with contextlib.closing(self._conn()) as c, c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    author TEXT DEFAULT '',
                    epub_path TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                )"""
            )

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_job(self, row) -> Job:
        return Job(**{k: row[k] for k in Job.__annotations__})

    def create(self, source_name: str) -> Job:
        with contextlib.closing(self._conn()) as c, c:
            cur = c.execute(
                "INSERT INTO jobs (source_name, status) VALUES (?, ?)",
                (source_name, JobStatus.QUEUED),
            )
            job_id = cur.lastrowid
        return self.get(job_id)

    def update(self, job_id: int, **fields) -> None:
        cols = [k for k in fields if k in _ALLOWED]
        if not cols:
            return
        assignments = ", ".join(f"{k} = ?" for k in cols)
        values = [fields[k] for k in cols] + [job_id]
        with contextlib.closing(self._conn()) as c, c:
            c.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)

    def get(self, job_id: int):
        with contextlib.closing(self._conn()) as c, c:
            row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return self._row_to_job(row) if row else None

    def list(self):
        with contextlib.closing(self._conn()) as c, c:
            rows = c.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
            return [self._row_to_job(r) for r in rows]
