# Rules.md — Business Rules & Decision Logic

**Project:** Loan Document IDP Pipeline

Rules are labelled `R-NN` for traceability. Claude Code must implement every rule
marked **[HARD]** exactly as written. Rules marked **[SOFT]** are defaults that may be
tuned with evidence.

---

## Category A — Ingestion Rules

### R-01 [HARD] Native-text threshold
A page is considered native-text if `len(page.extract_text().strip()) > 30`.
Exactly 30 characters or fewer → treat as scanned and queue for OCR.
Rationale: some pages have sparse text (a logo caption, a page number) that would
confuse pdfplumber; the 30-char threshold reliably catches true native-text pages
from the sample file while routing all genuinely scanned pages to OCR.

### R-02 [HARD] Rasterization DPI
All pages rasterized for OCR are rendered at exactly **150 DPI**.
This produces 1275×1650 pixel images matching the sample file's embedded JPEGs.
Do not increase to 300 DPI without also adjusting TATR input resize and bbox scaling.

### R-03 [HARD] Footer exclusion from LLM input
The `footer_text` field is extracted for internal use (similarity signal) but is
**never included in the LLM classification prompt**. The prompt contains only
`header_text` and `body_snippet`.
Rationale: sample file shows footer boilerplate naming "PNC Bank – Member FDIC" on
Chase-branded pages — footer text is unreliable for institution/type classification.

### R-04 [HARD] OCR retry policy
If an OCR batch call returns HTTP 5xx or times out (> 30 seconds):
- Retry once after a 2-second backoff.
- On second failure: mark each page in the batch as `source = "failed_ocr"`, set
  `text = ""`, `ocr_confidence_avg = 0.0`. Pipeline continues; these pages are
  included in their segment with `confidence *= 0.5`.
- **Never block the pipeline indefinitely** waiting for an OCR worker.

---

## Category B — Boundary Detection Rules

### R-10 [HARD] Near-blank page forced continuity
If `PageFingerprint.is_near_blank == True` (ink_coverage < 0.05), the similarity
score at that position is forced to `1.0`. Change-point detection will never fire a
boundary at a near-blank page. The page is folded into the preceding segment.

### R-11 [HARD] Page 1 is always a segment start
The first page of the file always begins a new segment. Do not apply boundary
detection at position 0.

### R-12 [SOFT] Boundary similarity threshold
Default change-point penalty: `pen = 3.0` (ruptures PELT). May be tuned between
`2.0` (more boundaries, higher recall) and `5.0` (fewer boundaries, higher precision)
based on measured F1 on the sample file. The direction to tune toward is **higher
recall** (more false positives) because Stage 3 LLM confirmation absorbs false
positives cheaply; missed real boundaries are never recovered.

### R-13 [HARD] Same-type run minimum split attribute
Two consecutive segments of the same `doc_type` must be split into separate instances
**only** if a distinguishing attribute is successfully extracted from each and the
attributes differ. If attribute extraction fails for either segment, **do not split** —
treat as one segment with `confidence *= 0.6` and `review_required = True`.
Exception: if `doc_type == "bank_statement"` and the statement period end date of
segment N equals or precedes the start date of segment N+1, the two must be split.

### R-14 [HARD] Layout-only boundary override
If `layout_vec` changes sharply (Euclidean distance > 0.60 in normalized space) even
when `embed_vec` similarity is still high (> 0.80), treat this as a candidate boundary
anyway. This catches e.g. the transition from a text-dense bank statement to a form-style
tax document where the header text may briefly repeat from a cover page.

---

## Category C — Segment Labeling Rules

### R-20 [HARD] LLM temperature
All Ollama calls use `temperature: 0`. Classification is deterministic; sampling is not
appropriate here.

### R-21 [HARD] `unknown` doc_type handling
If the LLM returns `doc_type = "unknown"` or a value not in `DocTypeEnum`:
1. Log the raw response.
2. Set `doc_type = "unknown"`, `confidence = 0.3`, `review_required = True`.
3. **Do not retry** with the same model and same prompt (it already gave its best).
4. If `source == "ocr"` and `ocr_confidence_avg >= 0.75`, retry with the 7B VLM.
5. If still `unknown` after escalation, keep `unknown` and continue.

### R-22 [HARD] `is_continuation` boundary reversal
If the LLM returns `"is_continuation": true` for a candidate segment start:
1. Check: is the similarity score at this boundary between 0.35 and 0.55 (borderline)?
   - If yes: merge this segment with the preceding one. Re-run attribute extraction on
     the merged segment.
   - If no (score < 0.35 — strong boundary signal): **ignore** the LLM's
     `is_continuation` assertion. The visual signal overrides.
2. After merging, re-label the merged segment with a new LLM call.
3. Maximum 1 merge per segment — do not cascade merges indefinitely.

### R-23 [SOFT] LLM confidence calibration
The LLM's `"confidence_hint"` field from the response is used only as a secondary
signal. The primary `confidence` is computed from `boundary_score × type_score ×
attribute_score` (see TechSpec.md §7). If `confidence_hint < 0.50` and the computed
confidence is > 0.70, log a calibration warning but use the computed score.

### R-24 [HARD] VLM escalation rate cap
VLM (Qwen2-VL-7B) escalation is capped at **20 segments per job** to protect against
a pathologically degraded file consuming hours of GPU time. If the cap is hit, remaining
eligible segments are labeled with the 3B model result only, `review_required = True`.

---

## Category D — Table Extraction Rules

### R-30 [HARD] Totals row identification
A row is identified as a totals/subtotal row if:
- Column 0 (or 1) matches `r'^\s*totals?\s*$'` (case-insensitive), OR
- Column 0 is empty AND the row contains at least two cells with the same numeric value
  as the sum of the column above it.

Totals rows are **removed from `table.rows`** and stored in `table.reported_total` only.
They are not summed across pages.

### R-31 [HARD] Repeated header folding
A row is identified as a repeated header if its cell texts match the `header_fingerprint`
of the table (case-insensitive, stripped). Such rows are removed from continuation pages.
If more than 5% of data rows also match the header fingerprint pattern (unlikely but
possible in sparse tables), log a warning and do NOT fold those rows.

### R-32 [HARD] Continuation detection threshold
Two consecutive page-tables are considered continuations if their `header_fingerprint`
values are exactly equal (after lowercasing and stripping). If they differ by more than
one column name, they are separate tables.
If they differ by exactly one column name: treat as continuation with `confidence *= 0.85`
and log a column-drift warning (see edge case in prd.md §9).

### R-33 [SOFT] pdfplumber vs. Camelot fallback
Use pdfplumber as the primary extractor. If pdfplumber returns 0 tables on a native-text
page, retry with Camelot in lattice mode, then stream mode. If both return 0 tables and
TATR reports a table region exists on the page image, log a table-extraction failure and
set `extraction_method = "failed"` for that page's contribution to the table.

### R-34 [HARD] Numeric cell parsing
When parsing a cell that should contain a numeric value (column name contains
"AMOUNT", "WITHDRAWAL", "DEPOSIT", "BALANCE", "PAYMENT", or similar):
- Strip `$`, `,`, and whitespace.
- Handle `(1,234.56)` as `-1234.56` (parentheses = negative).
- If parse fails, set `numeric_value = None` — never coerce non-numeric text to 0.

### R-35 [HARD] Reconciliation tolerance
The reconciliation check passes if:
`abs(computed_withdrawals - reported_withdrawals) <= max(0.01, reported_withdrawals * 0.0001)`
i.e. within 1 cent or 0.01% (floating-point tolerance). Not a strict equality check.
If the table has no `reported_total` (e.g. a fee schedule with no totals row),
`reconciliation = None` — this is not a failure.

---

## Category E — Confidence & Review Rules

### R-40 [HARD] `review_required` flag
`review_required = True` whenever ANY of the following:
- `segment.confidence < 0.70`
- `doc_type == "unknown"`
- `source == "failed_ocr"` (any page in segment)
- `is_continuation` was overridden by the visual signal (R-22)
- Page span coverage gap detected in Stage 5 (orphan pages attached)

### R-41 [HARD] Confidence floor
No `DocumentInstance` or `RecoveredTable` shall have `confidence < 0.0` or `> 1.0`.
Clamp before serialization: `confidence = max(0.0, min(1.0, confidence))`.

### R-42 [SOFT] Confidence weight distribution
Default weights for segment confidence:
- `boundary_score`: 0.35
- `type_score`: 0.45
- `attribute_score`: 0.20

If the doc_type is in `{"bank_statement", "paystub"}` (same-type run types), increase
`attribute_score` weight to 0.35 and decrease `type_score` to 0.30, since the attribute
is what distinguishes instances within the run.

---

## Category F — Output Rules

### R-50 [HARD] doc_id format
`doc_id` values are `"doc_{N:04d}"` starting from `"doc_0001"`, ordered by `start_page`
ascending. They are stable within a single pipeline run but **not** stable across runs
(don't use them as permanent identifiers in downstream systems).

### R-51 [HARD] Page numbering
All page numbers in the output are **1-indexed** and refer to physical PDF pages (not
logical document pages). The first page of a PDF is page 1.

### R-52 [HARD] `documents.json` ordering
The `documents` array in the output must be sorted by `start_page` ascending.

### R-53 [HARD] Empty table list
If a `DocumentInstance` contains no tables (e.g. a legal instrument with no structured
data), the `tables.json` simply has no entries referencing that `doc_id`. Do not emit
an empty table object.

### R-54 [HARD] Job data retention
Job data under `/data/jobs/{job_id}/` is retained until explicitly deleted via
`DELETE /pipeline/job/{job_id}`. The pipeline does not auto-delete completed job data.
The demo box has limited disk; the operator (Rishabh) is responsible for cleanup between
test runs.
