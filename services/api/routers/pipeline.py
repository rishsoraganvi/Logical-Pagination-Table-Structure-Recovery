"""
Pipeline endpoints for running document processing jobs.
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.models import PipelineRunResponse, PipelineStatusResponse
from api.pipeline.job_store import JobStore
from api.pipeline.runner import PipelineRunner

router = APIRouter()
job_store = JobStore()
pipeline_runner = PipelineRunner()


@router.post("/run", response_model=PipelineRunResponse)
async def run_pipeline(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> PipelineRunResponse:
    """
    Submit a PDF file for processing.
    Returns a job ID for tracking progress.
    """
    settings = get_settings()

    # Validate file size
    contents = await file.read()
    if len(contents) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {settings.MAX_UPLOAD_MB}MB",
        )

    # Generate job ID
    job_id = str(uuid.uuid4())

    # Save uploaded file
    job_dir = Path(settings.DATA_DIR) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / "input.pdf"
    with open(pdf_path, "wb") as f:
        f.write(contents)

    # Create job record
    await job_store.create_job(job_id, str(pdf_path))

    # Start processing in background
    background_tasks.add_task(pipeline_runner.run, job_id, pdf_path)

    return PipelineRunResponse(job_id=job_id)


@router.get("/status/{job_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(job_id: str) -> PipelineStatusResponse:
    """
    Get the current status of a processing job.
    """
    job_record = await job_store.get_job(job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    return PipelineStatusResponse(
        job_id=job_record.job_id,
        stage=job_record.stage,
        progress=job_record.progress,
        error=job_record.error,
    )


@router.get("/result/{job_id}")
async def get_pipeline_result(job_id: str):
    """
    Get the result of a completed processing job.
    Returns documents.json and tables.json.
    """
    job_record = await job_store.get_job(job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_record.stage != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not complete. Current stage: {job_record.stage}",
        )

    job_dir = Path(settings.DATA_DIR) / job_id
    documents_path = job_dir / "documents.json"
    tables_path = job_dir / "tables.json"
    metrics_path = job_dir / "metrics.json"

    if not documents_path.exists() or not tables_path.exists():
        raise HTTPException(status_code=404, detail="Result files not found")

    # Read and return the results
    import json

    with open(documents_path) as f:
        documents = json.load(f)
    with open(tables_path) as f:
        tables = json.load(f)
    with open(metrics_path) as f:
        metrics = json.load(f)

    return JSONResponse(
        content={
            "documents": documents,
            "tables": tables,
            "metrics": metrics,
        }
    )