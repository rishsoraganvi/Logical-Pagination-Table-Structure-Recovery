# ImplementationPlan.md — Detailed Build Plan

**Project:** Loan Document IDP Pipeline
**Timeline:** 3 days (hackathon sprint)
**Dev machine:** Dell Precision 5550, Quadro T1000 (4GB VRAM)
**Final run machine:** Vultr A16 (16GB VRAM)

Build the system **service by service, stage by stage** — not feature by feature. At the
end of each phase the system must be runnable end-to-end even if incomplete stages use
stub outputs.

---

## Day 1 AM — Ingestion, OCR, Fingerprinting (Stages 0–1)

### Task 1.1 — Project scaffold

1. Create the full folder structure (see `FolderStructure.md`).
2. Copy `docker-compose.yml` from the template in `EnvSetup.md`.
3. Verify `docker compose build` and `docker compose up` run without errors (services
   will return 503 until code is added).

### Task 1.2 — PDF Ingestion endpoint

File: `services/api/pipeline/stages/stage0_ingestion.py`

```python
async def run(job_id: str, pdf_path: Path, settings: Settings) -> list[PageRecord]:
    """
    Returns one PageRecord per page. Scanned pages have image_path set.
    Native pages have text set directly. OCR is dispatched but not awaited here.
    """
```

Implementation notes:
- Open PDF with `pypdf.PdfReader`.
- For each page, extract text with `page.extract_text()`. If `len(text.strip()) > 30`,
  it's native.
- For scanned pages, rasterize with `pdf2image.convert_from_path(pdf_path, dpi=150,
  first_page=n, last_page=n)` and save to `/data/jobs/{job_id}/pages/{n:04d}.jpg`.
- Write `PageRecord` objects to `page_records.ndjson` as you go (don't accumulate all
  in memory for 2,000 pages).

### Task 1.3 — OCR Worker

File: `services/ocr-worker/main.py`

```python
@app.post("/ocr/batch")
async def ocr_batch(req: OCRBatchRequest) -> OCRBatchResponse:
    """
    Receives up to 16 image paths. Returns OCR text + bbox blocks per page.
    Runs PaddleOCR with GPU.
    """
```

Implementation notes:
- Initialise `PaddleOCR(use_angle_cls=True, lang='en', use_gpu=True)` once at startup
  (takes ~5 seconds, must not reinitialise per request).
- Batch by calling `ocr.ocr(image_path)` per page — PaddleOCR v2.7 doesn't expose a
  true batch API, but GPU overlap helps when images are small JPEGs.
- Convert `result[i]` (list of `[[bbox], [text, confidence]]`) to `OCRBlock[]`.
- Return `PageOCRResult` per page.

**Test:** `curl -X POST http://localhost:8001/ocr/batch -F ...` with one of the sample
JPEGs from Stage 1.2. Should return recognizable text from a bank statement page.

### Task 1.4 — OCR batch dispatch in Stage 0

File: `services/api/pipeline/stages/stage0_ingestion.py` (extend)

```python
async def _dispatch_ocr_batches(
    scanned_pages: list[PageRecord],
    batch_size: int = 16
) -> dict[int, PageOCRResult]:
    """
    Chunks scanned pages into batches of 16, posts to ocr-worker,
    returns {page_num: OCRResult} dict.
    """
```

Use `httpx.AsyncClient` with a 60-second timeout per batch.

### Task 1.5 — Page Fingerprinting (Stage 1)

File: `services/api/pipeline/stages/stage1_fingerprint.py`

```python
def fingerprint_page(record: PageRecord) -> PageFingerprint:
```

Implementation notes:
- Load `all-MiniLM-L6-v2` once at module level:
  `_model = SentenceTransformer("all-MiniLM-L6-v2")`.
- Header zone: for native pages use line bbox from pypdf; for OCR pages filter
  `OCRBlock` items where `bbox[1] < page_height * 0.15`.
- Layout vector: if `image_path` is set, run OpenCV on the JPEG to compute
  `line_density` and `whitespace_ratio`. For native pages, synthesize from char counts.
- Near-blank: `ink_coverage < 0.05` → set `is_near_blank = True`.
- `embed_vec` = `_model.encode(normalized_header)` or zeros(384) if header is empty.

**Test:** Run fingerprinting on the first 20 pages of `doc_000.pdf`. Print header_text
for pages 1–5 (expect "LOAN SUMMARY DASHBOARD", "SCHEDULE C", "STATEMENT OF ACCOUNT"...).
Print `is_near_blank` for page 20 (expect True — the PNC disclosure page).

---

## Day 1 PM — Boundary Detection (Stage 2)

### Task 2.1 — Similarity signal

File: `services/api/pipeline/stages/stage2_boundary.py`

```python
def compute_similarity_signal(fingerprints: list[PageFingerprint]) -> list[float]:
    """
    Returns list of length N-1 where sim[i] = similarity between page i and i+1.
    Near-blank pages are forced to 1.0 (no boundary).
    """
```

Implementation notes:
- `sim[i] = cosine_similarity(fp[i].embed_vec, fp[i+1].embed_vec)` from sklearn.
- Multiply by `1 - clipped_layout_distance(fp[i].layout_vec, fp[i+1].layout_vec)`.
- If `fp[i+1].is_near_blank`: force `sim[i] = 1.0`.
- Save to `similarity_signal.json`.

### Task 2.2 — Change-point detection

```python
def detect_boundaries(sim_signal: list[float], pen: float = 3.0) -> list[int]:
    """
    Returns list of page numbers that are STARTS of new segments.
    Page 1 is always a start. All other starts come from PELT.
    """
```

```python
import ruptures as rpt
import numpy as np

arr = np.array(sim_signal).reshape(-1, 1)
algo = rpt.Pelt(model="rbf").fit(arr)
breakpoints = algo.predict(pen=pen)   # returns list of end indices
# Convert end-indices to start-page-numbers (ruptures convention: breakpoints are exclusive ends)
```

### Task 2.3 — Near-blank folding and same-type splitting

```python
def refine_segments(
    candidates: list[CandidateSegment],
    fingerprints: list[PageFingerprint]
) -> list[CandidateSegment]:
```

- Fold near-blank pages (see Design.md §11).
- Group consecutive segments with `cosine_similarity(header_embed_i, header_embed_j) > 0.90`.
- Within each group, run `extract_distinguishing_attribute` per segment and split on
  attribute change.

**Test:** Print the `CandidateSegment` list for `doc_000.pdf`. Should show ~12–15
segments with reasonable page ranges (e.g. pages 1 (Dashboard), 2 (Sched C),
3–19 (Chase stmt 1), 20 (near-blank folded into 3-19 or 20-35), etc.)

---

## Day 2 AM — Segment Labeling + Table Extraction (Stages 3–4)

### Task 3.1 — LLM prompt builder

File: `services/api/pipeline/stages/stage3_label.py`

```python
def build_label_prompt(seg: CandidateSegment, page_records: dict[int, PageRecord]) -> str:
```

- Pull `header_text` and `footer_text` from the fingerprint of `seg.start_page`.
- Pull first 300 chars of `page_records[seg.start_page].text` as `body_snippet`.
- Render the template from `Schema.md §6`.

### Task 3.2 — Ollama call + response parsing

```python
async def call_llm(prompt: str, model: str = "llama3.2:3b") -> dict:
    """
    POST to http://ollama:11434/api/generate.
    Returns parsed JSON from model response.
    Raises if JSON parse fails (log and return {"doc_type": "unknown", ...}).
    """
```

Implementation notes:
- Strip any ` ```json ``` ` wrappers before `json.loads()`.
- Validate the returned `doc_type` is a member of `DocTypeEnum`; if not, set `unknown`.
- Log `llm_model_used`, `prompt_tokens` (len(prompt)//4 estimate), `response_tokens`.

### Task 3.3 — Escalation logic

```python
async def label_segment(
    seg: CandidateSegment,
    page_records: dict[int, PageRecord],
    fingerprints: dict[int, PageFingerprint]
) -> LabeledSegment:
```

Escalation triggers (from Design.md §6):
1. OCR source AND avg OCR confidence < 0.75 AND LLM returned `unknown` or confidence < 0.60.
2. If escalation: rebuild prompt with base64 image, call `qwen2-vl:7b`.

### Task 3.4 — TATR Worker

File: `services/tatr-worker/main.py`

```python
@app.post("/table/detect")
async def detect_table(req: TATRRequest) -> TATRResponse:
```

Implementation notes:
- Load `AutoModelForObjectDetection.from_pretrained("microsoft/table-transformer-structure-recognition")` at startup.
- Resize image to 1000×1000 for TATR input.
- Post-process TATR output: extract rows by grouping cells with similar y-coordinates.
- Map OCR blocks onto detected cells by bbox overlap (IoU > 0.3 → cell text = OCR block text).

### Task 3.5 — pdfplumber native table extraction

File: `services/api/pipeline/stages/stage4_tables.py`

```python
def extract_native_tables(pdf_path: Path, page_num: int) -> list[RawPageTable]:
```

```python
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[page_num - 1]
    tables = page.extract_tables(table_settings={
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 5,
        "join_tolerance": 3
    })
    # Fallback to text-based strategy if tables is empty
    if not tables:
        tables = page.extract_tables(table_settings={
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
        })
```

### Task 3.6 — Multi-page stitching

```python
def stitch_tables(page_tables: dict[int, list[RawPageTable]]) -> list[RecoveredTable]:
    """
    Given {page_num: [tables on that page]}, merge continuation tables.
    Uses header_fingerprint matching to identify continuations.
    Returns final logical tables with all rows assembled.
    """
```

Implementation notes:
- `header_fingerprint(table) = "|".join(col.lower().strip() for col in table.rows[0].cells)`
- Two consecutive page-tables are continuations if `header_fingerprint_a == header_fingerprint_b`.
- Drop repeated header rows on continuation pages.
- Apply TOTALS_PATTERN matching and removal (see AppFlow.md §6c).
- Run reconciliation check (see AppFlow.md §6d).

---

## Day 2 PM — Validation, Assembly, API wiring (Stage 5)

### Task 5.1 — Span coverage validator

File: `services/api/pipeline/stages/stage5_validate.py`

```python
def validate_coverage(segments: list[LabeledSegment], total_pages: int) -> ValidationResult:
```

- Check for overlaps and gaps.
- Attach orphan pages to nearest preceding segment with `confidence *= 0.5`.
- Log all anomalies.

### Task 5.2 — Final serialization

```python
def assemble_output(
    segments: list[LabeledSegment],
    tables: list[RecoveredTable],
    metrics: PipelineMetrics
) -> tuple[list[DocumentInstance], list[RecoveredTable]]:
```

- Convert `LabeledSegment` → `DocumentInstance` (assign `doc_id` = `"doc_{i:04d}"`).
- Write `documents.json` and `tables.json`.

### Task 5.3 — Wire all stages into `PipelineRunner`

File: `services/api/pipeline/runner.py`

```python
class PipelineRunner:
    async def run(self, job_id: str, pdf_path: Path) -> None:
        await self._update_status(job_id, stage="ingestion")
        records = await stage0_ingestion.run(job_id, pdf_path)
        await self._update_status(job_id, stage="fingerprint")
        fingerprints = stage1_fingerprint.run(records)
        await self._update_status(job_id, stage="boundary")
        candidates = stage2_boundary.run(fingerprints)
        await self._update_status(job_id, stage="label")
        labeled = await stage3_label.run(candidates, records, fingerprints)
        await self._update_status(job_id, stage="table")
        tables = await stage4_tables.run(labeled, pdf_path, records)
        await self._update_status(job_id, stage="validate")
        docs, tables = stage5_validate.run(labeled, tables)
        await self._write_results(job_id, docs, tables)
        await self._update_status(job_id, stage="done")
```

### Task 5.4 — End-to-end test on doc_000.pdf

```bash
curl -X POST http://localhost:8000/pipeline/run \
  -F "file=@doc_000.pdf"
# Note job_id from response

# Poll
watch -n 2 "curl -s http://localhost:8000/pipeline/status/{job_id} | python3 -m json.tool"

# Inspect result
curl -s http://localhost:8000/pipeline/result/{job_id} | python3 -m json.tool | head -100
```

Expected: ~12–18 `DocumentInstance` records with correct page spans and doc types.
Expected: At least 5 `RecoveredTable` records (one per Chase statement), each with
`reconciled: true`.

---

## Day 3 AM — Deploy to Vultr A16

Follow `vultr-deployment-runbook.md` step by step:
1. Provision A16 instance.
2. Verify `nvidia-smi` + container GPU passthrough.
3. Clone repo, copy `.env`.
4. `docker compose build && docker compose up -d`.
5. Upload `doc_000.pdf` and run the full pipeline.
6. Capture timing: `time curl -X POST .../pipeline/run -F file=@doc_000.pdf`.
7. After run completes, collect `metrics.json` — this is the data for `prd.md §8`.

---

## Day 3 PM — Write-up and Demo Polish

### Metrics to collect and put in prd.md §8:

| Metric | Where to find it |
|---|---|
| Wall-clock time | `metrics.wall_clock_seconds` from result API |
| GPU utilization | `nvidia-smi dmon -s u` during the run |
| LLM calls | `metrics.llm_calls` |
| VLM escalations | `metrics.vlm_escalations` |
| Boundary F1 | Compare `documents.json` spans to ground truth (manual verification on sample) |
| Reconciliation pass rate | `(total_tables - metrics.tables_unreconciled) / total_tables` |

### Demo script:

1. Show `nvidia-smi` on the A16 box (proves GPU is active).
2. `curl -X POST /pipeline/run -F file=@doc_000.pdf` — live upload.
3. `watch` the status endpoint showing stage progression.
4. When done, `cat documents.json | python3 -m json.tool` — show the boundary list.
5. Show one reconciled Chase statement table from `tables.json` with `reconciled: true`.
6. Mention cost: "This entire run cost < $1 in GPU time."
