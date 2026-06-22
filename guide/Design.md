# Design.md — Architecture & Design Decisions

**Project:** Loan Document IDP Pipeline

Documents every significant architectural decision, the alternatives considered, and the
reason the chosen approach was selected. Intended to prevent revisiting settled decisions
and to give Claude Code enough context to resolve ambiguity in implementation.

---

## 1. Core Design Principle: Compute Proportional to Uncertainty

The most important design decision is the cost model: **spend LLM/GPU compute in
proportion to how uncertain a page is, not in proportion to page count.**

A 2,000-page file that is 70% bank statement continuation pages is easy: the OCR result
and a 384-dim sentence embedding tell you with very high confidence that page 47 is the
same document as page 46. Calling a large VLM on page 47 is a waste.

The hard pages are: the first page of a new document type, a degraded scan where OCR
quality is low, and the boundary between two consecutive W-2s from different years with
nearly identical visual structure. These get more compute — and only these.

Every design decision below flows from this principle.

---

## 2. Why a 5-Stage Sequential Pipeline, Not a Single Model

**Alternative considered:** Run a single large multimodal model (GPT-4V, Claude 3 Sonnet)
over every page and ask it to output doc_type + table content in one pass.

**Rejected because:**
- Costs ~$0.01–0.03 per page at current API rates → $20–$60 for a 2,000-page file.
  The brief explicitly asks for an approach that doesn't depend on expensive hosted models.
- Running a 70B+ hosted VLM per page is latency-wise ~1–3 seconds per page →
  30–100 minutes for 2,000 pages at one-at-a-time rate.
- The expensive call happens even for the 80% of pages that are unambiguous.
- Breaks data confidentiality — all borrower PII leaves the box.

**Chosen approach:** A staged funnel where cheap classical tools handle the bulk and the
LLM is called once per *document instance* (not once per page), on a small text snippet
(not a full page image), using a local model (no external API).

---

## 3. Why PaddleOCR Over Tesseract

**Alternative:** Tesseract 5 (open-source, widely used, CPU-based).

**Chosen: PaddleOCR** for the following reasons:
- Significantly better accuracy on structured documents (bank statements, tax forms)
  compared to Tesseract on the same inputs — PaddleOCR's PP-OCRv4 model was
  trained on a wider variety of layouts including table-heavy documents.
- Native GPU acceleration (CUDA). Tesseract is CPU-only; on the A16, batching 16
  PaddleOCR pages in parallel is faster than 16 serial Tesseract calls on CPU.
- Better handling of mixed Latin + numeric content in financial documents.
- Single engine covering both text detection and recognition in one call.

EasyOCR is kept as a fallback option since it also supports GPU and is pip-installable
without Paddle's sometimes-tricky GPU build, but PaddleOCR is the primary.

---

## 4. Why sentence-transformers for Boundary Detection Instead of TF-IDF

**Alternative:** TF-IDF cosine similarity on raw page text.

**Problem with TF-IDF:** Two consecutive pages of a Chase bank statement share almost
all tokens (account holder name, "STATEMENT OF ACCOUNT", "Chase", column headers) →
high TF-IDF similarity even though there may be a statement period boundary. TF-IDF
over-represents term frequency; it can't distinguish "same document continuation" from
"new document of the same type."

**Chosen: sentence embeddings of the normalized header zone only.**
The header zone (top 15% of page) is where document identity lives. Normalizing to
lowercase alphanumeric and embedding with `all-MiniLM-L6-v2` (384 dims, 80MB, fast on
CPU) produces a semantic fingerprint that is stable within a document and shifts at
genuine boundaries. The embedding captures semantic meaning, not token frequency.

`all-MiniLM-L6-v2` is chosen specifically because it runs on CPU in < 10ms per page
and needs only ~80MB RAM — no GPU required, no latency hit.

---

## 5. Why Change-Point Detection (ruptures PELT) for Boundaries

**Alternative:** Per-page binary classifier (is this page a boundary start?).

**Problem:** Binary per-page classifiers treat each page independently. The boundary
signal is inherently a *sequence* property — similarity drops over a run of pages, not
at a single page. A binary classifier on page 32 alone doesn't know what pages 30–31
looked like.

**Chosen: PELT (Pruned Exact Linear Time) change-point detection** via the `ruptures`
library. PELT:
- Operates on the 1D similarity signal (one value per page-pair).
- Is globally optimal for a given penalty parameter `pen`.
- Is O(n log n) — fast even on 2,000-page sequences.
- Naturally handles heteroscedastic signals (the signal is noisier in text-dense pages
  vs near-blank pages).

The penalty `pen=3` was tuned on the sample file's known segment boundaries. A higher
penalty produces fewer change points (risk: merging real boundaries); a lower penalty
produces more (risk: false boundaries handled in Stage 3 anyway — the LLM confirms).
Since false positives are cheap and false negatives are expensive, the permissive
direction is preferred and Stage 3 acts as a filter.

---

## 6. Why the LLM Is Given Only Header Text, Not a Full Page Image

The LLM prompt in Stage 3 contains:
- `header_text` (< 200 chars)
- `footer_text` (< 100 chars, but see Rule R-03 in `Rules.md`)
- First 300 chars of body text from the first page of the segment

Total prompt token count: ~200–400 tokens. Completion: ~80 tokens.

**Alternative:** Pass the page image to the VLM for every segment.

**Rejected because:**
- A page image in base64 is ~1,500–3,000 tokens. Multiplied by 150 segments on a
  2,000-page file → 225,000–450,000 image tokens just for labeling, vs. ~60,000 for
  text-only prompts. Cost and latency difference: 4–8×.
- For text-only segments (native text pages), the header text alone is sufficient for
  classification with very high accuracy.
- Images are only used for escalation (< 10% of segments) when text signal is genuinely
  absent or degraded.

---

## 7. Why Redis for the Job Queue (Not Celery, Not RQ)

**Decision:** Use raw Redis lists with `LPUSH` / `BRPOP` for the OCR batch queue.

**Alternative:** Celery with Redis broker.

**Rejected because:** Celery adds a broker + a result backend + worker process management
layer that is valuable for long-running production workloads but is overhead for a
hackathon pipeline where there is one service doing all the heavy lifting. Raw Redis
queuing with a simple async consumer loop in each worker is 200 lines of code vs.
400+ for a properly configured Celery setup, with no difference in functionality at
this concurrency level.

**FastAPI background tasks** (without Redis) were also considered and rejected because
they block graceful shutdown and don't survive container restarts. Redis job records
survive restarts; the pipeline is resumable from the last completed stage.

---

## 8. Why pdfplumber Over Camelot for Native Table Extraction

**Alternative:** Camelot (lattice or stream mode).

**Both are valid.** pdfplumber is chosen as the primary because:
- Actively maintained with Python 3.11 support.
- Better at tables without visible grid lines (stream mode equivalent is the default).
- Returns bbox coordinates for every cell, which are needed to cross-reference with OCR
  block coordinates during multi-page stitching.
- Camelot is kept as a fallback in `rules.py` for pages where pdfplumber returns empty
  tables on a page that visually clearly has one.

---

## 9. Table Transformer (TATR) vs. Detectron2-based Models

**Alternative:** LayoutParser with Detectron2 + custom table layout model.

**Chosen: Microsoft Table Transformer (TATR)** because:
- Available as a standard HuggingFace `transformers` model — no detectron2 build
  complexity (detectron2 has notoriously painful CUDA build dependencies).
- TATR was fine-tuned specifically on PubTables-1M and financial document tables.
- Returns structured row/column grid output directly, not just bounding boxes.
- VRAM footprint ~0.4 GB — leaves plenty of headroom on the 16 GB A16 slice.

---

## 10. Single-Slice vs. Multi-Slice A16 Design

The A16 board has 4 GPU slices (each 16 GB). We are renting one slice.

**Not using multi-slice because:**
- The pipeline's VRAM peak is ~7 GB (Section 8 of TechSpec.md) — well within one slice.
- Multi-slice Vultr plans cost 2–4× more per hour.
- The A16 slices don't share memory (no NVLink); multi-slice would require model
  parallelism or pipelining code that is not worth the complexity at this scale.

**Future path to scale (not needed for this submission):** if throughput were the
constraint (e.g. 10 files in parallel), each file's pipeline would get its own slice
with no code changes.

---

## 11. Near-Blank Page Handling Design

Near-blank pages (`ink_coverage < 0.05`) are a common source of false boundaries —
OCR produces empty or near-empty text, similarity to the previous page drops to zero,
and the change-point detector fires.

**Design:** Near-blank pages are detected in Stage 1, flagged in `PageFingerprint`, and
**excluded from the similarity signal** in Stage 2. The similarity at a near-blank page
position is set to `1.0` (forced continuity), meaning the boundary detector will not
fire there. The page is then folded into whichever segment its surrounding pages belong
to during Stage 5 assembly.

This matches the observation in the sample file where a single-line disclosure page
appears at the end of several Chase statement runs.

---

## 12. Footer Text Exclusion From Classification

Observed in the sample file: a Chase-branded statement has footer text "PNC Bank –
Member FDIC…" — a different institution. This is a boilerplate watermark from the
scanning/printing vendor, not the document issuer.

**Design:** Footer text is extracted (for the similarity signal — it's stable within a
document and drops at boundaries) but is **never** passed to the LLM as a
classification signal. The LLM prompt contains `header_text` and `body_snippet` only.
Footer text is included in `PageFingerprint` for internal use, not in the LLM context.
