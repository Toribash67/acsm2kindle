import os
from dataclasses import asdict

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import (
    HTMLResponse, RedirectResponse, JSONResponse, FileResponse,
)
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.jobs import JobStore, JobStatus
from app.validation import is_valid_acsm
from app.worker import Worker
from app.delivery import deliver

TEMPLATES = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


def create_app(settings=None, worker=None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = JobStore(settings.db_path)
    worker = worker or Worker(store, settings)
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    def upload_page(request: Request):
        return TEMPLATES.TemplateResponse("upload.html", {"request": request})

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        dest = os.path.join(settings.incoming_dir, os.path.basename(file.filename))
        with open(dest, "wb") as f:
            f.write(await file.read())
        if not is_valid_acsm(dest):
            os.remove(dest)
            raise HTTPException(status_code=400, detail="Not a valid .acsm file")
        job = store.create(os.path.basename(file.filename))
        worker.submit(job.id, dest)
        return RedirectResponse("/library", status_code=303)

    @app.get("/library", response_class=HTMLResponse)
    def library(request: Request):
        return TEMPLATES.TemplateResponse("library.html", {"request": request})

    @app.get("/api/jobs")
    def api_jobs():
        return JSONResponse([asdict(j) for j in store.list()])

    @app.get("/download/{job_id}")
    def download(job_id: int):
        job = store.get(job_id)
        if not job or not job.epub_path or not os.path.exists(job.epub_path):
            raise HTTPException(status_code=404, detail="No file")
        return FileResponse(job.epub_path,
                            filename=os.path.basename(job.epub_path))

    @app.post("/resend/{job_id}")
    def resend(job_id: int):
        job = store.get(job_id)
        if not job or not job.epub_path or not os.path.exists(job.epub_path):
            raise HTTPException(status_code=404, detail="No file to resend")
        store.update(job_id, status=JobStatus.SENDING, error="")
        try:
            deliver(job.epub_path, settings)
            store.update(job_id, status=JobStatus.DONE)
        except Exception as e:  # noqa: BLE001
            store.update(job_id, status=JobStatus.ERROR, error=str(e))
        return RedirectResponse("/library", status_code=303)

    return app


app = create_app() if os.environ.get("ACSM2KINDLE_AUTOSTART") else None
