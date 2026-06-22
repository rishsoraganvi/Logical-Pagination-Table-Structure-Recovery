# Loan Document IDP Pipeline

Intelligent Document Processing pipeline for loan document analysis, specifically designed to:
- Recover logical pagination (document boundaries) from scanned loan files up to 2,000 pages
- Extract and structure table data from those documents
- Run efficiently on cloud GPU instances (target: Vultr A16)

## Architecture

This system uses a microservices architecture with:
- **API service** (FastAPI): Orchestrates the pipeline
- **OCR worker**: GPU-accelerated text recognition (PaddleOCR)
- **TATR worker**: GPU-accelerated table structure recognition (Microsoft Table Transformer)
- **Ollama service**: Local LLM/VLM inference for document labeling
- **Redis**: Job state management
- **PostgreSQL**: (Not shown in compose - may be added later)

## Pipeline Stages

1. **Ingestion & Triage**: Split PDF, detect text layer, dispatch OCR for scanned pages
2. **Fingerprinting**: Compute lightweight features for each page (header/text, layout)
3. **Boundary Detection**: Find document boundaries using change-point detection
4. **Segment Labeling**: Label document segments using LLM (with VLM escalation for low-confidence scans)
5. **Table Extraction & Recovery**: Extract tables (native + scanned) and stitch multi-page tables
6. **Validation & Assembly**: Validate outputs, compute metrics, produce final JSON

## Setup

See [EnvSetup.md](docs/EnvSetup.md) for detailed setup instructions.

## Development

For local development, use `docker-compose.override.yml` which mounts source code for hot reload.

Note: Local development on limited VRAM hardware may require running services sequentially to avoid OOM.

## Deployment

Target deployment: Vultr Cloud GPU — NVIDIA A16 (single-GPU slice, 16GB VRAM)

See [docs/vultr-deployment-runbook.md] for production deployment instructions.