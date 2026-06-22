"""
Pipeline runner that orchestrates all stages.
"""
import asyncio
from pathlib import Path

from api.config import get_settings
from api.models import StageEnum
from api.pipeline.job_store import JobStore

# Import stage modules (will be implemented)
from . import stage0_ingestion
from . import stage1_fingerprint
from . import stage2_boundary
from . import stage3_label
from . import stage4_tables
from . import stage5_validate


class PipelineRunner:
    def __init__(self):
        self.settings = get_settings()
        self.job_store = JobStore()

    async def run(self, job_id: str, pdf_path: Path) -> None:
        """
        Run the complete pipeline for a job.
        Each stage updates the job state in Redis.
        """
        try:
            # Stage 0: Ingestion
            await self.job_store.update_job_stage(job_id, StageEnum.ingestion)
            records = await stage0_ingestion.run(job_id, pdf_path, self.settings)
            await self.job_store.update_job_progress(job_id, len(records))

            # Stage 1: Fingerprinting
            await self.job_store.update_job_stage(job_id, StageEnum.fingerprint)
            fingerprints = stage1_fingerprint.run(records)
            await self.job_store.update_job_progress(job_id, len(fingerprints))

            # Stage 2: Boundary Detection
            await self.job_store.update_job_stage(job_id, StageEnum.boundary)
            candidates = stage2_boundary.run(fingerprints)
            await self.job_store.update_job_progress(job_id, len(candidates))

            # Stage 3: Labeling
            await self.job_store.update_job_stage(job_id, StageEnum.label)
            labeled = await stage3_label.run(candidates, records, fingerprints, self.settings)
            await self.job_store.update_job_progress(job_id, len(labeled))

            # Stage 4: Table Extraction
            await self.job_store.update_job_stage(job_id, StageEnum.table)
            tables = await stage4_tables.run(labeled, pdf_path, records, self.settings)

            # Stage 5: Validation & Assembly
            await self.job_store.update_job_stage(job_id, StageEnum.validate)
            documents, tables = stage5_validate.run(labeled, tables)
            await self._write_results(job_id, documents, tables)

            # Mark job as done
            await self.job_store.set_job_done(job_id)

        except Exception as e:
            # Mark job as failed
            await self.job_store.set_job_failed(job_id, StageEnum.validate, str(e))
            raise

    async def _write_results(self, job_id: str, documents: list, tables: list) -> None:
        """Write final results to files."""
        job_dir = Path(self.settings.DATA_DIR) / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # Write documents.json
        documents_path = job_dir / "documents.json"
        import json
        with open(documents_path, "w") as f:
            json.dump(documents, f, indent=2, default=str)

        # Write tables.json
        tables_path = job_dir / "tables.json"
        with open(tables_path, "w") as f:
            json.dump(tables, f, indent=2, default=str)

        # Write metrics.json (placeholder - would be populated with actual metrics)
        metrics_path = job_dir / "metrics.json"
        metrics = {
            "wall_clock_seconds": 0.0,  # Would be calculated
            "gpu_minutes": 0.0,
            "llm_calls": 0,
            "vlm_escalations": 0,
            "pages_native_text": 0,
            "pages_ocr": 0,
            "pages_failed_ocr": 0,
            "segments_low_confidence": 0,
            "tables_unreconciled": 0,
        }
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)