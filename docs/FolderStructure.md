# FolderStructure.md — Repository Layout

**Project:** Loan Document IDP Pipeline

Every file and directory listed here must exist in the repo. Files marked `[generated]`
are not committed — they are created at runtime.

---

```
loan-doc-pipeline/
│
├── docker-compose.yml                  # Defines all 5 services + shared volumes
├── docker-compose.override.yml         # Local dev overrides (volume mounts for hot reload)
├── .env.example                        # Template — copy to .env and fill in
├── .env                                # Actual secrets — gitignored
├── .gitignore
├── README.md
│
├── docs/                               # All planning documents
│   ├── prd.md
│   ├── TechSpec.md
│   ├── AppFlow.md
│   ├── Design.md
│   ├── Schema.md
│   ├── ImplementationPlan.md
│   ├── Rules.md
│   ├── FolderStructure.md
│   ├── EnvSetup.md
│   └── vultr-deployment-runbook.md
│
├── data/                               # Runtime data root — gitignored
│   └── jobs/                           # [generated] One subdir per pipeline run
│       └── {job_id}/                   # [generated]
│           ├── input.pdf               # [generated] Uploaded PDF
│           ├── pages/                  # [generated] Rasterized page JPEGs
│           │   ├── 0001.jpg
│           │   └── ...
│           ├── page_records.ndjson     # [generated] Stage 0 output
│           ├── page_fingerprints.ndjson # [generated] Stage 1 output
│           ├── similarity_signal.json  # [generated] Stage 2 intermediate
│           ├── candidate_segments.ndjson # [generated] Stage 2 output
│           ├── labeled_segments.ndjson # [generated] Stage 3 output
│           ├── raw_tables.ndjson       # [generated] Stage 4 output
│           ├── documents.json          # [generated] Stage 5 final output
│           ├── tables.json             # [generated] Stage 5 final output
│           └── metrics.json            # [generated] Stage 5 metrics
│
├── models/                             # Downloaded model weights — gitignored (too large)
│   ├── all-MiniLM-L6-v2/              # sentence-transformers model cache
│   └── tatr/                           # TATR model weights cache
│
├── services/
│   │
│   ├── api/                            # FastAPI orchestrator (CPU service)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                     # App entry point, router registration
│   │   ├── config.py                   # Settings (pydantic-settings, reads .env)
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py             # POST /pipeline/run, GET /status, GET /result
│   │   │   └── health.py               # GET /health
│   │   ├── pipeline/
│   │   │   ├── __init__.py
│   │   │   ├── runner.py               # PipelineRunner class (orchestrates all stages)
│   │   │   ├── job_store.py            # Redis read/write helpers for job state
│   │   │   └── stages/
│   │   │       ├── __init__.py
│   │   │       ├── stage0_ingestion.py # PDF split, native text extraction, OCR dispatch
│   │   │       ├── stage1_fingerprint.py # Header/layout/embedding fingerprinting
│   │   │       ├── stage2_boundary.py  # Similarity signal, PELT, same-type splitting
│   │   │       ├── stage3_label.py     # LLM prompting, response parsing, escalation
│   │   │       ├── stage4_tables.py    # pdfplumber + TATR dispatch + stitching
│   │   │       └── stage5_validate.py  # Coverage check, serialization, metrics
│   │   ├── models/                     # Pydantic models (matches Schema.md)
│   │   │   ├── __init__.py
│   │   │   ├── job.py                  # JobRecord, PipelineStatusResponse, PipelineRunResponse
│   │   │   ├── page.py                 # PageRecord, OCRBlock, PageFingerprint
│   │   │   ├── segment.py              # CandidateSegment, LabeledSegment
│   │   │   ├── document.py             # DocumentInstance, DocTypeEnum, DistinguishingAttribute
│   │   │   └── table.py                # RecoveredTable, TableRow, TableCell, ReconciliationResult
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── pdf_utils.py            # pypdf helpers, page count, text extraction
│   │       ├── image_utils.py          # pdf2image rasterization, OpenCV layout features
│   │       ├── text_utils.py           # Header/footer zone extraction, normalization, regex patterns
│   │       └── numeric_utils.py        # Currency string → float parsing (Rule R-34)
│   │
│   ├── ocr-worker/                     # PaddleOCR GPU service
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                     # FastAPI app, POST /ocr/batch, GET /health
│   │   └── ocr_engine.py               # PaddleOCR init (once at startup) + batch inference
│   │
│   ├── tatr-worker/                    # Table Transformer GPU service
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                     # FastAPI app, POST /table/detect, GET /health
│   │   ├── tatr_engine.py              # TATR model init + inference + cell extraction
│   │   └── cell_mapper.py              # Map OCR blocks onto TATR cell bboxes (IoU matching)
│   │
│   └── ollama/                         # Not a custom service — uses upstream image
│       └── modelfile/
│           ├── llama3.2-3b.modelfile   # Optional: customise system prompt baked in
│           └── qwen2-vl-7b.modelfile
│
├── scripts/
│   ├── pull_models.sh                  # Pull Ollama models + download HF weights at deploy time
│   ├── smoke_test.sh                   # Quick end-to-end test: upload doc_000.pdf, poll, check output
│   ├── benchmark.sh                    # Time the full pipeline run, save metrics to benchmark.json
│   └── cleanup_jobs.sh                 # Delete all job data under data/jobs/ (between runs)
│
└── tests/
    ├── conftest.py                     # Shared fixtures: sample PDF path, mock OCR responses
    ├── unit/
    │   ├── test_stage0_ingestion.py    # Text-layer detection, near-blank detection
    │   ├── test_stage1_fingerprint.py  # Header zone extraction, embed_vec shape, layout_vec values
    │   ├── test_stage2_boundary.py     # Similarity signal, PELT output, same-type splitting
    │   ├── test_stage3_label.py        # Prompt building, JSON parsing, escalation trigger
    │   ├── test_stage4_tables.py       # Totals removal, header folding, reconciliation
    │   └── test_numeric_utils.py       # Currency parsing edge cases (negatives, commas)
    └── integration/
        ├── test_full_pipeline.py       # Upload doc_000.pdf, poll to completion, assert outputs
        └── test_api_endpoints.py       # Health, status, result endpoint contract tests
```

---

## Key Invariants

- `services/api/` is the only service that reads/writes `/data/jobs/`. Worker services
  receive paths as arguments and read/write only those specific files.
- `models/` is mounted as a read-only volume into `tatr-worker`. The model is downloaded
  once by `scripts/pull_models.sh`, not at container startup.
- `data/` is a bind mount shared across all services so workers can read JPEGs written by
  the api service.
- `.env` is never committed. `docker-compose.yml` reads only from `.env` via
  `env_file: .env`. No secrets are hardcoded anywhere.
- All Pydantic model definitions live in `services/api/models/` and are the single
  source of truth. Workers have their own minimal request/response schemas that don't
  import from the api service.
