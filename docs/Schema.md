# Schema.md — Data Models & JSON Schemas

**Project:** Loan Document IDP Pipeline

All Python types use Pydantic v2 syntax. JSON schemas are the serialized form of the
same models. Internal pipeline objects (never returned to the API caller) are marked
`[internal]`.

---

## 1. API Request / Response Models

### 1.1 PipelineRunResponse

```python
class PipelineRunResponse(BaseModel):
    job_id: str                  # e.g. "j_a1b2c3d4"
    status: str                  # "queued"
    page_count: int
    estimated_seconds: int
```

### 1.2 PipelineStatusResponse

```python
class StageEnum(str, Enum):
    ingestion   = "ingestion"
    ocr         = "ocr"
    fingerprint = "fingerprint"
    boundary    = "boundary"
    label       = "label"
    table       = "table"
    validate    = "validate"
    done        = "done"
    failed      = "failed"

class PipelineStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    stage: StageEnum
    pages_processed: int
    pages_total: int
    elapsed_seconds: float
    failed_stage: Optional[str] = None
    error_message: Optional[str] = None
```

### 1.3 PipelineResultResponse

```python
class PipelineResultResponse(BaseModel):
    job_id: str
    documents: list[DocumentInstance]
    tables: list[RecoveredTable]
    metrics: PipelineMetrics
```

### 1.4 PipelineMetrics

```python
class PipelineMetrics(BaseModel):
    wall_clock_seconds: float
    gpu_minutes: float
    llm_calls: int
    vlm_escalations: int
    pages_native_text: int
    pages_ocr: int
    pages_failed_ocr: int
    segments_low_confidence: int    # confidence < 0.70
    tables_unreconciled: int        # reported_total != computed_total
```

---

## 2. Core Output Models

### 2.1 DocumentInstance

Primary output. One instance per logical document recovered from the file.

```python
class DistinguishingAttribute(BaseModel):
    # At most one of these groups is populated, depending on doc_type.
    # All others are None.
    statement_period_start: Optional[str] = None   # ISO 8601 date, e.g. "2023-06-08"
    statement_period_end: Optional[str] = None
    account_number_last4: Optional[str] = None
    tax_year: Optional[int] = None
    pay_period_start: Optional[str] = None
    pay_period_end: Optional[str] = None
    pay_date: Optional[str] = None
    employer_name: Optional[str] = None
    subject: Optional[str] = None                  # For LOE / email
    form_number: Optional[str] = None              # e.g. "1040", "W-2", "1008"

class DocumentInstance(BaseModel):
    doc_id: str                                    # "doc_0001", "doc_0002", ...
    doc_type: DocTypeEnum
    start_page: int                                # 1-indexed, inclusive
    end_page: int                                  # 1-indexed, inclusive
    page_count: int                                # end_page - start_page + 1
    distinguishing_attribute: DistinguishingAttribute
    confidence: float                              # 0.0–1.0
    source: Literal["native_text", "ocr", "mixed"]
    review_required: bool                          # True if confidence < 0.70
    llm_label: str                                 # Raw LLM output before parsing
```

### 2.2 DocTypeEnum

```python
class DocTypeEnum(str, Enum):
    # Tax documents
    form_1040                   = "form_1040"
    form_1040_schedule_c        = "form_1040_schedule_c"
    form_1040_schedule_e        = "form_1040_schedule_e"
    form_w2                     = "form_w2"
    form_1099                   = "form_1099"

    # Bank / financial
    bank_statement              = "bank_statement"
    verification_of_deposit     = "verification_of_deposit"

    # Employment
    paystub                     = "paystub"
    written_voe                 = "written_voe"

    # Loan origination
    loan_application_urla       = "loan_application_urla"
    loan_estimate               = "loan_estimate"
    closing_disclosure          = "closing_disclosure"
    loan_summary_dashboard      = "loan_summary_dashboard"
    underwriting_findings_du    = "underwriting_findings_du"
    form_1008_uw_transmittal    = "form_1008_uw_transmittal"

    # Property / legal
    purchase_sale_agreement     = "purchase_sale_agreement"
    psa_addendum                = "psa_addendum"
    security_deed               = "security_deed"
    title_commitment            = "title_commitment"

    # Correspondence
    letter_of_explanation       = "letter_of_explanation"
    email_correspondence        = "email_correspondence"

    # Other
    consumer_account_terms      = "consumer_account_terms"
    earnings_statement          = "earnings_statement"
    unknown                     = "unknown"
```

### 2.3 RecoveredTable

```python
class TableCell(BaseModel):
    col_idx: int
    text: str
    numeric_value: Optional[float] = None          # Parsed if text looks like a number

class TableRow(BaseModel):
    row_idx: int
    row_type: Literal["header", "data", "total", "subtotal", "blank"]
    cells: list[TableCell]

class ReconciliationResult(BaseModel):
    reconciled: bool
    computed_withdrawals: Optional[float] = None
    computed_deposits: Optional[float] = None
    reported_withdrawals: Optional[float] = None
    reported_deposits: Optional[float] = None
    reported_ending_balance: Optional[float] = None
    delta_withdrawals: Optional[float] = None      # computed - reported; None if not applicable

class RecoveredTable(BaseModel):
    table_id: str                                  # "doc_0003_t1", "doc_0003_t2", ...
    doc_id: str                                    # Parent DocumentInstance
    schema_type: TableSchemaEnum
    page_span: tuple[int, int]                     # (first_page, last_page) — may span multiple
    header_fingerprint: str                        # "DATE|DESCRIPTION|WITHDRAWALS|DEPOSITS|BALANCE"
    columns: list[str]                             # Ordered column names
    rows: list[TableRow]                           # Data rows only (totals removed)
    reported_total: Optional[dict[str, float]] = None
    reconciliation: Optional[ReconciliationResult] = None
    extraction_method: Literal["pdfplumber", "camelot", "tatr", "mixed"]
    confidence: float
```

### 2.4 TableSchemaEnum

```python
class TableSchemaEnum(str, Enum):
    bank_statement_transactions     = "bank_statement_transactions"
    paystub_earnings                = "paystub_earnings"
    paystub_deductions              = "paystub_deductions"
    paystub_ytd_summary             = "paystub_ytd_summary"
    closing_disclosure_costs        = "closing_disclosure_costs"
    underwriting_findings           = "underwriting_findings"
    credit_liabilities              = "credit_liabilities"
    vod_account_summary             = "vod_account_summary"
    generic                         = "generic"
```

---

## 3. Internal Pipeline Models `[internal]`

These are not serialized to the final API response but are written to intermediate
`.ndjson` files for pipeline resumability.

### 3.1 PageRecord `[internal]`

```python
class PageRecord(BaseModel):
    job_id: str
    page_num: int                                  # 1-indexed
    source: Literal["native_text", "ocr", "failed_ocr"]
    text: str                                      # Full page text after OCR or native extraction
    char_count: int
    image_path: Optional[str] = None              # Absolute path to rasterized JPEG; None for native
    ocr_blocks: Optional[list[OCRBlock]] = None   # bbox-level OCR output; None for native
    ocr_confidence_avg: Optional[float] = None
```

### 3.2 OCRBlock `[internal]`

```python
class OCRBlock(BaseModel):
    bbox: tuple[float, float, float, float]        # (x1, y1, x2, y2) in pixels
    text: str
    confidence: float
```

### 3.3 PageFingerprint `[internal]`

```python
class PageFingerprint(BaseModel):
    page_num: int
    header_text: str
    footer_text: str
    embed_vec: list[float]                         # 384-dim all-MiniLM-L6-v2 embedding
    layout_vec: list[float]                        # 6-dim [line_density, col_count, whitespace_ratio,
                                                   #        table_present, text_density, ink_coverage]
    is_near_blank: bool                            # ink_coverage < 0.05
```

### 3.4 CandidateSegment `[internal]`

```python
class CandidateSegment(BaseModel):
    seg_id: str
    start_page: int
    end_page: int
    avg_similarity: float                          # Within-segment average similarity
    boundary_score: float                          # Similarity drop at start_page
    header_fingerprint_hash: str                   # For same-type run grouping
    distinguishing_attribute_raw: Optional[str]   # Raw regex match
```

### 3.5 LabeledSegment `[internal]`

```python
class LabeledSegment(BaseModel):
    seg_id: str
    start_page: int
    end_page: int
    doc_type: DocTypeEnum
    distinguishing_attribute: DistinguishingAttribute
    confidence: float
    boundary_score: float
    type_score: float
    attribute_score: float
    source: Literal["native_text", "ocr", "mixed"]
    llm_model_used: str                            # "llama3.2:3b" or "qwen2-vl:7b"
    llm_raw_response: str
    review_required: bool
```

---

## 4. Intermediate File Formats

All files under `/data/jobs/{job_id}/`:

| File | Format | Contains |
|---|---|---|
| `input.pdf` | Binary | Original uploaded PDF |
| `pages/{N:04d}.jpg` | JPEG | Rasterized page image (scanned pages only) |
| `page_records.ndjson` | NDJSON | One `PageRecord` per line |
| `page_fingerprints.ndjson` | NDJSON | One `PageFingerprint` per line |
| `similarity_signal.json` | JSON | `{"values": [0.92, 0.88, ..., 0.12, ...]}` — 1 float per page-pair |
| `candidate_segments.ndjson` | NDJSON | One `CandidateSegment` per line |
| `labeled_segments.ndjson` | NDJSON | One `LabeledSegment` per line |
| `raw_tables.ndjson` | NDJSON | One `RecoveredTable` per line (pre-reconciliation) |
| `documents.json` | JSON | Final `DocumentInstance[]` array |
| `tables.json` | JSON | Final `RecoveredTable[]` array |
| `metrics.json` | JSON | `PipelineMetrics` object |

---

## 5. Redis Job State Schema

Key: `job:{job_id}`  Type: Redis Hash

| Field | Type | Example |
|---|---|---|
| `status` | string | `"running"` |
| `stage` | string | `"ocr"` |
| `pages_total` | int | `161` |
| `pages_processed` | int | `47` |
| `started_at` | float | Unix timestamp |
| `updated_at` | float | Unix timestamp |
| `failed_stage` | string | `""` or stage name |
| `error_message` | string | `""` or error string |

Key: `ocr_queue:{job_id}` → Redis List of `page_num` integers (LPUSH / BRPOP).

---

## 6. LLM Prompt Template (Stage 3)

```
SYSTEM:
You are a document classifier for mortgage loan files.
Classify the document segment described below.
Respond ONLY with a JSON object. No explanation. No markdown.

USER:
Document header text (top of first page):
"""
{{header_text}}
"""

First 300 characters of body:
"""
{{body_snippet}}
"""

Respond with exactly this JSON structure:
{
  "doc_type": "<one of the DocTypeEnum values>",
  "distinguishing_attribute": {
    "statement_period_start": null,
    "statement_period_end": null,
    "account_number_last4": null,
    "tax_year": null,
    "pay_period_start": null,
    "pay_period_end": null,
    "pay_date": null,
    "employer_name": null,
    "subject": null,
    "form_number": null
  },
  "is_continuation": false,
  "confidence_hint": 0.95
}

Only populate fields relevant to this document type. Leave others null.
is_continuation: true only if this is CLEARLY a continuation page of a previous document, not a new one.
```
