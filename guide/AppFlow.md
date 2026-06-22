# AppFlow.md — Application Flow

**Project:** Loan Document IDP Pipeline

Describes every data movement from PDF upload to final JSON output. Read alongside
`TechSpec.md` for API shapes and `Schema.md` for data structures.

---

## 1. Top-Level Request Lifecycle

```
Client (curl / demo UI)
        │
        │  POST /pipeline/run   (multipart PDF)
        ▼
  ┌─────────────┐
  │   FastAPI   │──► save PDF → /data/jobs/{job_id}/input.pdf
  │  (api svc)  │──► create JobRecord in Redis (status=queued)
  └──────┬──────┘
         │ 202 → {job_id, status: queued}
         │
         │  [background task spawned]
         ▼
  ┌─────────────────────────────────────────────────┐
  │                Pipeline Runner                   │
  │  Stage 0 → Stage 1 → Stage 2 → Stage 3          │
  │  → Stage 4 → Stage 5                            │
  │                                                  │
  │  Writes progress to Redis after every stage.    │
  └─────────────────────────────────────────────────┘
         │
         │  GET /pipeline/status/{job_id}   (polling)
         │◄── {stage, pages_processed, status}
         │
         │  GET /pipeline/result/{job_id}   (when done)
         │◄── {documents[], tables[], metrics{}}
```

---

## 2. Stage 0 — Ingestion & Triage

**Input:** `/data/jobs/{job_id}/input.pdf`
**Output:** `page_records.ndjson` — one `PageRecord` per page

```
for page_num in 1..N:
    ┌──────────────────────────────────────────┐
    │  Extract text with pypdf                  │
    │  char_count = len(text.strip())           │
    └──────────────────┬───────────────────────┘
                       │
          ┌────────────┴───────────────┐
          │ char_count > 30?            │
          ├─ YES ──────────────────────►  source = "native_text"
          │                               text = pypdf text
          │                               skip rasterization
          │
          └─ NO  ──────────────────────►  rasterize page to JPEG
                                          (pdf2image, 150 DPI)
                                          save to /data/jobs/{jid}/pages/{N:04d}.jpg
                                          push to OCR queue
```

**OCR Queue flush** (after all pages are triaged):

```
OCR batch (up to 16 pages per HTTP call to ocr-worker)
    POST http://ocr-worker:8001/ocr/batch
    ──► returns PageOCRResult[] with text + bbox blocks
    ──► merged back into PageRecord for each page
```

**After Stage 0:**
- Every page has `text` (from native extraction or OCR).
- Every scanned page has `image_path` set.
- `page_records.ndjson` written to disk.
- Redis: `stage = "ocr_done"`, `pages_processed = N`.

---

## 3. Stage 1 — Per-Page Fingerprinting

**Input:** `page_records.ndjson`
**Output:** `page_fingerprints.ndjson` — one `PageFingerprint` per page

For every page (CPU only, no network calls):

```
1. Header zone  = first 15% of page height
   footer zone  = last  15% of page height

2. header_text  = extract lines whose bbox.y1 < page_h * 0.15
   footer_text  = extract lines whose bbox.y1 > page_h * 0.85

3. layout_vec (6-dim, from OpenCV on rasterized page or synthetic from native text):
     - line_density   : total detected horizontal lines / page_h
     - col_count      : estimated column count from x-gap histogram
     - whitespace_ratio: white pixels / total pixels  (0–1)
     - table_present  : 1 if grid cells detected by OpenCV, else 0
     - text_density   : char_count / (page_w * page_h)
     - ink_coverage   : 1 - whitespace_ratio  (alias for blank-page detection)

4. embed_vec (384-dim):
     normalized_header = re.sub(r'[^a-z0-9 ]', '', header_text.lower()).strip()
     if normalized_header:
         embed_vec = SentenceTransformer('all-MiniLM-L6-v2').encode(normalized_header)
     else:
         embed_vec = zeros(384)

5. is_near_blank = (ink_coverage < 0.05)  ← used in Stage 2 trailer-page logic
```

`PageFingerprint` = `{page_num, header_text, footer_text, embed_vec, layout_vec, is_near_blank}`

---

## 4. Stage 2 — Boundary Detection

**Input:** `page_fingerprints.ndjson` (ordered by page_num)
**Output:** `candidate_segments.ndjson` — list of `CandidateSegment`

### 4a. Similarity sequence

```
for i in 1..N-1:
    sim[i] = cosine_similarity(embed_vec[i-1], embed_vec[i])
             * (1 - euclidean_distance(layout_vec[i-1], layout_vec[i]) / max_layout_dist)
```

`sim[]` is a 1D signal of page-to-page continuity. A drop below threshold `T_sim = 0.45`
is a candidate boundary.

### 4b. Change-point detection (ruptures PELT)

```python
algo = ruptures.Pelt(model="rbf").fit(sim_signal)
change_points = algo.predict(pen=3)   # pen tuned on sample file
```

Each change point → a candidate segment boundary.

### 4c. Near-blank trailer folding

```
for each near_blank page:
    if page is a candidate segment start:
        remove the boundary — fold this page into the preceding segment
```

### 4d. Same-type run splitting

After initial segmentation, for any run of consecutive segments that share the same
`header_text` fingerprint within cosine similarity > 0.90 (visually identical headers):

```
for segment in same_header_run:
    attr = extract_distinguishing_attribute(segment.first_page)
    // attr = statement_period | tax_year | pay_period | account_number
    if attr != prev_attr:
        keep the boundary (different instance, same type)
    else:
        merge the segments (same instance continued)
```

`extract_distinguishing_attribute` uses regex patterns:
- Bank statement: `r'(\d{2}/\d{2}/\d{4})\s*[–-]\s*(\d{2}/\d{2}/\d{4})'` (period)
- Tax form (W-2, 1040, Sch C): `r'(?:tax year|year)\s*(\d{4})'`
- Paystub: `r'(\d{2}/\d{2}/\d{4})\s*[–-]\s*(\d{2}/\d{2}/\d{4})'` (pay period)
- LOE: `r're:\s*(.+)'` (subject line)

---

## 5. Stage 3 — Segment Labeling (LLM)

**Input:** `candidate_segments.ndjson`
**Output:** `labeled_segments.ndjson` — adds `doc_type`, `distinguishing_attribute`, `confidence`

For each segment, the orchestrator builds a short prompt from the first page's
`header_text`, `footer_text` (header only — never footer alone), and up to 400 chars of
body text from the first page.

### 5a. LLM call (text-only, 3B labeler)

```
POST http://ollama:11434/api/generate
{
  "model": "llama3.2:3b",
  "prompt": "<system>...\n<user>Classify this document segment...\n{{header_text}}\n{{body_snippet}}",
  "stream": false,
  "options": {"temperature": 0, "num_predict": 80}
}
```

Expected response: a JSON block with `doc_type` and `distinguishing_attribute`.

### 5b. Escalation to VLM

Triggered when:
- `segment.source == "ocr"` AND
- `ocr_confidence_avg < 0.75` (degraded scan) AND
- LLM responded with `doc_type == "unknown"` or `confidence < 0.60`

```
POST http://ollama:11434/api/generate
{
  "model": "qwen2-vl:7b",
  "prompt": "...",
  "images": [base64(first_page_image)]
}
```

### 5c. Boundary confirmation

The LLM is also asked (in the same prompt): "Does the text above represent the start of
a new document, or a continuation of a previous one?" If it says "continuation" and the
similarity signal was low-confidence, the boundary is tentatively merged and the merged
segment is re-labeled. Prevents false positives from degraded OCR on continuation pages.

---

## 6. Stage 4 — Table Recovery

**Input:** `labeled_segments.ndjson` + per-page data
**Output:** `raw_tables.ndjson` — one entry per logical (possibly multi-page) table

### 6a. Per-page table extraction

**Native-text pages:**
```python
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[page_num - 1]
    tables = page.extract_tables(table_settings={
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 5
    })
```

**Scanned pages:**
```
POST http://tatr-worker:8002/table/detect
{image_path, ocr_blocks}
──► returns table region bbox + row/cell structure
```

### 6b. Multi-page table stitching

After all pages in a segment are processed:

```
tables_in_segment = all per-page tables, ordered by page_num
for i in 1..len(tables)-1:
    if header_fingerprint(tables[i]) ≈ header_fingerprint(tables[i-1]):
        // continuation — drop the repeated header row, append rows
        merged_table.rows += tables[i].rows[1:]   // skip row 0 (header)
    else:
        // new table — close the current, start a new one
        finalize(merged_table)
        merged_table = tables[i]
```

`header_fingerprint` = `"|".join([col.lower().strip() for col in header_row])`

### 6c. Totals handling

```
for each row in table.rows:
    if row matches TOTALS_PATTERN:
        // r'^\s*totals?\s*$' case-insensitive in col 0
        if row == last_row:
            table.reported_total = parse_numeric(row)
            table.rows.remove(row)   // not a data row
        else:
            table.rows.remove(row)   // mid-table subtotal, discard
```

### 6d. Reconciliation check

```
computed = sum(row.withdrawal for row in table.rows if row.withdrawal)
table.reconciled = abs(computed - table.reported_total.withdrawals) < 0.01
```

---

## 7. Stage 5 — Validation & Assembly

**Input:** `labeled_segments.ndjson` + `raw_tables.ndjson`
**Output:** `documents.json` + `tables.json`

### 7a. Span coverage check

```
covered_pages = set()
for seg in segments:
    if seg.start_page > seg.end_page:
        raise ValidationError(...)
    overlap = covered_pages & set(range(seg.start_page, seg.end_page+1))
    if overlap:
        raise ValidationError(f"Pages {overlap} assigned to multiple segments")
    covered_pages.update(...)

if covered_pages != set(range(1, total_pages+1)):
    missing = set(range(1, total_pages+1)) - covered_pages
    log.warning("unassigned_pages", pages=list(missing))
    // attach to nearest preceding segment, flag low confidence
```

### 7b. Confidence gate

Segments with `confidence < 0.70` get `"review_required": true` in the output.

### 7c. Serialization

Segments → `documents.json`, tables → `tables.json`.
`metrics{}` block assembled from counters accumulated across all stages.

---

## 8. Error & Retry Flow

```
Stage fails:
    ──► log error with stage, page_range, exception
    ──► Redis: status = "failed", failed_stage = "ocr"
    ──► GET /pipeline/status returns {status: failed, failed_stage, error_message}

POST /pipeline/retry/{job_id}:
    ──► re-reads intermediate files from disk up to the failed stage
    ──► resumes from that stage (does not re-run earlier stages)
```

OCR worker or TATR worker timeout (> 30s per page):
- Page is re-queued once.
- On second timeout: page is marked `confidence = 0.0`, `text = ""`, `source = "failed_ocr"`.
- Pipeline continues; the page is included in the segment but flagged.
