# TechSpec.md — Loan Document IDP Pipeline

**Project:** Logical Pagination & Table Structure Recovery
**Stack:** Python 3.11, FastAPI, Docker Compose, PaddleOCR, pdfplumber, Table Transformer, Ollama (Llama-3.2-3B + Qwen2-VL-7B)
**Target hardware:** Vultr Cloud GPU — NVIDIA A16, 16 GB VRAM, Ubuntu 22.04

---

## 1. Service Topology

The system is split into five long-lived Docker services. GPU services share one NVIDIA device; the orchestrator and CPU services never touch the GPU.

```
┌──────────────────────────────────────────────────────────┐
│  Docker Compose (on Vultr A16 host)                       │
│                                                           │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │  ocr-worker │   │ tatr-worker  │   │  llm-worker  │  │
│  │  PaddleOCR  │   │ Table Trans- │   │  Ollama      │  │
│  │  EasyOCR    │   │ former (TATR)│   │  3B + 7B VLM │  │
│  │  GPU: yes   │   │  GPU: yes    │   │  GPU: yes    │  │
│  └──────┬──────┘   └──────┬───────┘   └──────┬───────┘  │
│         │                 │                   │           │
│         └────────┬────────┘                   │           │
│                  ▼                             │           │
│  ┌────────────────────────┐                   │           │
│  │    api (FastAPI)        │◄──────────────────┘           │
│  │    orchestrator         │                               │
│  │    CPU only, port 8000  │                               │
│  └────────────┬───────────┘                               │
│               │                                           │
│  ┌────────────▼───────────┐                               │
│  │   redis (job queue)     │                               │
│  │   CPU only, port 6379   │                               │
│  └────────────────────────┘                               │
└──────────────────────────────────────────────────────────┘
```

All inter-service communication is HTTP/REST on the internal Docker network (`loan-net`). No service exposes ports externally except the `api` on `0.0.0.0:8000` (scoped behind SSH tunnel on the demo box).

---

## 2. Technology Versions

| Component | Package / Image | Version Pin | Notes |
|---|---|---|---|
| Python runtime | `python` | 3.11-slim | All services |
| FastAPI | `fastapi` | 0.111.x | Async, with `uvicorn[standard]` |
| pydantic | `pydantic` | 2.x | For all request/response models |
| pypdf | `pypdf` | 4.x | Text-layer detection and extraction |
| pdfplumber | `pdfplumber` | 0.11.x | Native table extraction |
| pdf2image | `pdf2image` | 1.17.x | Page rasterization (wraps poppler) |
| OpenCV | `opencv-python-headless` | 4.9.x | Layout fingerprinting |
| sentence-transformers | `sentence-transformers` | 3.x | Header embedding (all-MiniLM-L6-v2) |
| PaddleOCR | `paddlepaddle-gpu` + `paddleocr` | 2.7.x | GPU-batched OCR on scanned pages |
| Table Transformer | `transformers` + TATR weights | HF `microsoft/table-transformer-structure-recognition` | Scanned table region + cell detection |
| Ollama | `ollama/ollama` Docker image | latest | Hosts 3B labeler + 7B escalation VLM |
| LLM labeler | `llama3.2:3b` via Ollama | Q4_K_M GGUF | Segment type labeling — text-only |
| Escalation VLM | `qwen2-vl:7b` via Ollama | Q4_K_M GGUF | Low-confidence scanned segments only |
| Redis | `redis:7-alpine` | 7.x | Job queue for OCR + TATR batches |
| numpy | `numpy` | 1.26.x | Feature vector math |
| scikit-learn | `scikit-learn` | 1.4.x | Cosine similarity, change-point |
| ruptures | `ruptures` | 1.1.x | PELT change-point detection |
| httpx | `httpx` | 0.27.x | Async HTTP calls to worker services |
| structlog | `structlog` | 24.x | Structured JSON logging |

---

## 3. API Contract — Orchestrator (FastAPI)

Base URL (local via SSH tunnel): `http://localhost:8000`

### 3.1 POST `/pipeline/run`

Accepts a PDF, runs the full 5-stage pipeline asynchronously, returns a job ID.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | `UploadFile` | Yes | The loan PDF, up to 2,000 pages |
| `job_id` | `string` | No | Client-supplied idempotency key; auto-generated if absent |

**Response 202:**
```json
{
  "job_id": "j_a1b2c3d4",
  "status": "queued",
  "page_count": 161,
  "estimated_seconds": 120
}
```

**Response 400:** if the file is not a PDF or exceeds 500 MB.

---

### 3.2 GET `/pipeline/status/{job_id}`

**Response 200:**
```json
{
  "job_id": "j_a1b2c3d4",
  "status": "running",           // queued | running | done | failed
  "stage": "ocr",               // ingestion | ocr | fingerprint | boundary | label | table | validate
  "pages_processed": 47,
  "pages_total": 161,
  "elapsed_seconds": 34
}
```

---

### 3.3 GET `/pipeline/result/{job_id}`

Available only when `status == "done"`.

**Response 200:**
```json
{
  "job_id": "j_a1b2c3d4",
  "documents": [ ...document instances... ],
  "tables": [ ...recovered tables... ],
  "metrics": {
    "wall_clock_seconds": 98,
    "gpu_minutes": 1.3,
    "llm_calls": 12,
    "pages_native_text": 31,
    "pages_ocr": 130
  }
}
```

---

### 3.4 GET `/health`

Used by Docker healthcheck.

**Response 200:** `{"status": "ok", "gpu": true, "ollama": true}`

---

## 4. Internal Worker APIs

Workers are plain FastAPI apps on the Docker-internal network; never exposed externally.

### 4.1 OCR Worker — `http://ocr-worker:8001`

**POST `/ocr/batch`**

```json
// request
{
  "job_id": "j_a1b2c3d4",
  "pages": [
    {"page_num": 1, "image_path": "/data/jobs/j_a1b2c3d4/pages/001.jpg"}
  ]
}

// response
{
  "results": [
    {
      "page_num": 1,
      "text": "STATEMENT OF ACCOUNT\n...",
      "blocks": [
        {"bbox": [x1, y1, x2, y2], "text": "...", "confidence": 0.97}
      ]
    }
  ]
}
```

### 4.2 TATR Worker — `http://tatr-worker:8002`

**POST `/table/detect`**

```json
// request
{
  "job_id": "j_a1b2c3d4",
  "page_num": 3,
  "image_path": "/data/jobs/j_a1b2c3d4/pages/003.jpg",
  "ocr_blocks": [ ...from ocr worker... ]
}

// response
{
  "tables": [
    {
      "bbox": [x1, y1, x2, y2],
      "rows": [
        {"cells": [{"col_idx": 0, "text": "06/08/2023"}, ...]}
      ],
      "header_fingerprint": "DATE|DESCRIPTION|WITHDRAWALS|DEPOSITS|BALANCE"
    }
  ]
}
```

### 4.3 LLM Worker — `http://ollama:11434` (Ollama native API)

Used via `POST /api/generate`. The orchestrator owns all prompt construction; the LLM
worker is vanilla Ollama with no custom wrapper.

---

## 5. Data Flow Between Stages

```
Stage 0: PDF in  →  PageRecord[]   (page_num, text, image_path, source: native|ocr)
Stage 1: PageRecord[]  →  PageFingerprint[]  (header_text, footer_text, embed_vec, layout_vec)
Stage 2: PageFingerprint[]  →  CandidateSegment[]  (start_page, end_page, similarity_score)
Stage 3: CandidateSegment[]  →  LabeledSegment[]   (doc_type, distinguishing_attr, confidence)
Stage 4: LabeledSegment[]  →  RecoveredTable[]     (rows, header_fp, page_span, totals)
Stage 5: LabeledSegment[] + RecoveredTable[]  →  documents.json + tables.json
```

All intermediate objects are persisted under `/data/jobs/{job_id}/` as newline-delimited
JSON files so the pipeline is resumable (re-run from the failed stage without re-doing
all earlier stages).

---

## 6. Performance Requirements

| Metric | Target (161-page sample) | Target (2,000-page projection) |
|---|---|---|
| End-to-end wall clock | < 3 min on A16 | < 30 min on A16 |
| OCR throughput | ≥ 5 pages/sec (GPU batch) | same |
| LLM calls | < 25 (one per segment) | < 200 |
| Peak VRAM usage | < 14 GB | < 14 GB (single A16 slice) |
| API response time for `/status` | < 50 ms | < 50 ms |
| `documents.json` Boundary F1 | ≥ 0.90 | ≥ 0.85 |
| Table cell accuracy (TEDS) | ≥ 0.85 | ≥ 0.80 |
| Reconciliation pass rate | ≥ 0.95 | ≥ 0.90 |

---

## 7. Confidence Scoring

Every `LabeledSegment` and `RecoveredTable` carries a `confidence` float (0–1).
It is the product of sub-scores, not an LLM self-rating:

```
segment_confidence = boundary_score × type_score × attribute_score

boundary_score   = 1 - (avg_similarity_within / similarity_at_boundary)
type_score       = LLM token-probability of the top predicted doc_type label (from logprobs)
attribute_score  = regex_match_score on the distinguishing attribute extraction
```

Segments with `confidence < 0.70` are flagged in the output and in the API metrics
rather than silently accepted.

---

## 8. GPU Memory Layout (A16, 16 GB slice)

| Model in use | VRAM footprint (Q4_K_M) | When active |
|---|---|---|
| PaddleOCR PP-OCRv4 | ~1.5 GB | Stage 0 OCR batch |
| TATR structure model | ~0.4 GB | Stage 4 scanned tables |
| Llama-3.2-3B (Ollama) | ~2.0 GB | Stage 3 labeling |
| Qwen2-VL-7B (Ollama) | ~4.5 GB | Stage 3 escalation only |
| **Max concurrent** | **~6.5 GB** | OCR + TATR simultaneously |
| **Peak (escalation)** | **~7.0 GB** | Llama + Qwen2-VL overlap |

Services run sequentially per job within each worker, so the 3B and 7B models are never
both hot at the same time in practice. Well within the 16 GB slice.

---

## 9. Logging & Observability

- All services use `structlog` emitting JSON to stdout; collected by Docker.
- Every pipeline run logs: `job_id`, `stage`, `page_range`, `duration_ms`, `llm_calls`,
  `ocr_pages`, `confidence_min/max`.
- `GET /pipeline/result/{job_id}` response includes a `metrics` block (see §3.3).
- No external telemetry; all logs stay on-box for data-confidentiality compliance.

---

## 10. Security & Data Confidentiality

- The instance is accessed only via SSH key; no password auth.
- Port 8000 is **not** open in the Vultr firewall; demo access is via SSH tunnel only.
- All PII (borrower names, SSNs, account numbers) stays on the A16 box and in
  `/data/jobs/` — never sent to any external API or hosted model endpoint.
- Job data under `/data/jobs/{job_id}/` is deleted on `DELETE /pipeline/job/{job_id}`.
