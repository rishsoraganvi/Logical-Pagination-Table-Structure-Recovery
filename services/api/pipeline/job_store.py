"""
Redis-based job state management.
"""
import json
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

from api.config import get_settings
from api.models import PipelineStatusResponse, StageEnum


class JobStore:
    def __init__(self):
        self.settings = get_settings()
        self.redis_client: Optional[redis.Redis] = None

    async def _get_redis(self) -> redis.Redis:
        if self.redis_client is None:
            self.redis_client = redis.from_url(self.settings.REDIS_URL)
        return self.redis_client

    async def create_job(self, job_id: str, pdf_path: str) -> None:
        """Create a new job record in Redis."""
        r = await self._get_redis()
        job_data = {
            "job_id": job_id,
            "pdf_path": pdf_path,
            "status": "queued",
            "stage": StageEnum.ingestion.value,
            "pages_total": 0,  # Will be updated during ingestion
            "pages_processed": 0,
            "started_at": datetime.utcnow().timestamp(),
            "updated_at": datetime.utcnow().timestamp(),
            "failed_stage": "",
            "error_message": "",
        }
        await r.hset(f"job:{job_id}", mapping=job_data)
        await r.expire(f"job:{job_id}", self.settings.JOB_TTL_SECONDS)

    async def get_job(self, job_id: str) -> Optional[dict]:
        """Get job record from Redis."""
        r = await self._get_redis()
        job_data = await r.hgetall(f"job:{job_id}")
        if not job_data:
            return None

        # Convert bytes to strings/appropriate types
        result = {}
        for key, value in job_data.items():
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            if isinstance(value, bytes):
                value_str = value.decode("utf-8")
                # Try to convert to int/float if possible
                if key_str in ["pages_total", "pages_processed"]:
                    try:
                        result[key_str] = int(value_str)
                    except ValueError:
                        result[key_str] = value_str
                elif key_str in ["started_at", "updated_at", "elapsed_seconds"]:
                    try:
                        result[key_str] = float(value_str)
                    except ValueError:
                        result[key_str] = value_str
                else:
                    result[key_str] = value_str
            else:
                result[key_str] = value
        return result

    async def update_job_stage(self, job_id: str, stage: StageEnum, pages_processed: int = 0) -> None:
        """Update job stage and progress."""
        r = await self._get_redis()
        await r.hset(
            f"job:{job_id}",
            mapping={
                "stage": stage.value,
                "status": "running",
                "pages_processed": pages_processed,
                "updated_at": datetime.utcnow().timestamp(),
            },
        )

    async def update_job_progress(self, job_id: str, pages_processed: int) -> None:
        """Update job progress."""
        r = await self._get_redis()
        await r.hset(
            f"job:{job_id}",
            mapping={
                "pages_processed": pages_processed,
                "updated_at": datetime.utcnow().timestamp(),
            },
        )

    async def set_job_failed(self, job_id: str, stage: StageEnum, error_message: str) -> None:
        """Mark job as failed."""
        r = await self._get_redis()
        await r.hset(
            f"job:{job_id}",
            mapping={
                "status": "failed",
                "stage": stage.value,
                "failed_stage": stage.value,
                "error_message": error_message,
                "updated_at": datetime.utcnow().timestamp(),
            },
        )

    async def set_job_done(self, job_id: str) -> None:
        """Mark job as done."""
        r = await self._get_redis()
        await r.hset(
            f"job:{job_id}",
            mapping={
                "status": "done",
                "stage": StageEnum.done.value,
                "updated_at": datetime.utcnow().timestamp(),
            },
        )