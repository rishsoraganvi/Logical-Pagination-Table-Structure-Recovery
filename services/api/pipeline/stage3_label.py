"""
Stage 3: Segment Labeling
LLM prompting, response parsing, escalation logic.
"""
import asyncio
import base64
import json
from typing import Dict, List

import httpx

from api.config import get_settings
from api.models import CandidateSegment, LabeledSegment, PageRecord, PageFingerprint
from api.models.document import DocTypeEnum


def build_label_prompt(seg: CandidateSegment, page_records: Dict[int, PageRecord]) -> str:
    """
    Build the prompt for LLM labeling based on segment header/body.
    """
    # Get header text from the first page of the segment
    first_page_record = page_records.get(seg.start_page)
    if not first_page_record:
        # Fallback if page record not found
        header_text = ""
        body_snippet = ""
    else:
        # For simplicity, we'll use the full text as body snippet
        # In a real implementation, we'd extract header/footer properly
        header_text = first_page_record.text[:200]  # Approximate header
        body_snippet = first_page_record.text[:300]  # First 300 chars as body

    # Build prompt according to Schema.md template
    prompt = f"""SYSTEM:
You are a document classifier for mortgage loan files.
Classify the document segment described below.
Respond ONLY with a JSON object. No explanation. No markdown.

USER:
Document header text (top of first page):
"""
"{header_text}"
"

First 300 characters of body:
"""
"{body_snippet}"
"

Respond with exactly this JSON structure:
{{
  "doc_type": "<one of the DocTypeEnum values>",
  "distinguishing_attribute": {{
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
  }},
  "is_continuation": false,
  "confidence_hint": 0.95
}}

Only populate fields relevant to this document type. Leave others null.
is_continuation: true only if this is CLEARLY a continuation page of a previous document, not a new one.
"""
    return prompt


async def call_llm(prompt: str, model: str = "llama3.2:3b", settings) -> dict:
    """
    POST to http://ollama:11434/api/generate.
    Returns parsed JSON from model response.
    Raises if JSON parse fails (log and return {{"doc_type": "unknown", ...}}).
    """
    url = f"{settings.OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

            # Extract the generated text
            generated_text = result.get("response", "")

            # Try to parse JSON from the response
            # Strip any markdown code block wrappers
            cleaned_text = generated_text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()

            # Parse JSON
            try:
                parsed = json.loads(cleaned_text)
                # Validate doc_type
                if "doc_type" in parsed:
                    try:
                        DocTypeEnum(parsed["doc_type"])
                    except ValueError:
                        parsed["doc_type"] = "unknown"
                else:
                    parsed["doc_type"] = "unknown"
                return parsed
            except json.JSONDecodeError:
                # If JSON parsing fails, return unknown
                return {
                    "doc_type": "unknown",
                    "distinguishing_attribute": {
                        "statement_period_start": None,
                        "statement_period_end": None,
                        "account_number_last4": None,
                        "tax_year": None,
                        "pay_period_start": None,
                        "pay_period_end": None,
                        "pay_date": None,
                        "employer_name": None,
                        "subject": None,
                        "form_number": None
                    },
                    "is_continuation": False,
                    "confidence_hint": 0.0
                }
    except Exception as e:
        # On any error, return unknown
        print(f"LLM call failed: {e}")
        return {
            "doc_type": "unknown",
            "distinguishing_attribute": {
                "statement_period_start": None,
                "statement_period_end": None,
                "account_number_last4": None,
                "tax_year": None,
                "pay_period_start": None,
                "pay_period_end": None,
                "pay_date": None,
                "employer_name": None,
                "subject": None,
                "form_number": None
            },
            "is_continuation": False,
            "confidence_hint": 0.0
        }


async def label_segment(
    seg: CandidateSegment,
    page_records: Dict[int, PageRecord],
    fingerprints: Dict[int, PageFingerprint],
    settings
) -> LabeledSegment:
    """
    Label a single segment using LLM, with escalation to VLM if needed.
    """
    # Build prompt for text-based labeling
    prompt = build_label_prompt(seg, page_records)

    # Call LLM
    llm_response = await call_llm(prompt, settings.LLM_MODEL, settings)

    # Determine if escalation is needed
    needs_escalation = False
    source = "native_text"  # Default, would need to be determined from page records

    # Check if we need to escalate (simplified logic)
    # In reality, we'd check OCR confidence, etc.
    if llm_response.get("doc_type") == "unknown" or llm_response.get("confidence_hint", 0) < 0.60:
        needs_escalation = True

    # If escalation needed and we have OCR data, call VLM
    if needs_escalation and source == "ocr":
        # For now, we'll skip VLM implementation and use LLM result
        # In a full implementation, we'd:
        # 1. Get the image for the segment's first page
        # 2. Encode it as base64
        # 3. Call qwen2-vl:7b with image + prompt
        llm_response = await call_llm(prompt, settings.VLM_MODEL, settings)
        llm_model_used = settings.VLM_MODEL
    else:
        llm_model_used = settings.LLM_MODEL

    # Create LabeledSegment
    # Convert distinguishing_attribute dict to proper format
    distinguishing_attribute = llm_response.get("distinguishing_attribute", {})
    # Ensure all expected keys are present
    default_attrs = {
        "statement_period_start": None,
        "statement_period_end": None,
        "account_number_last4": None,
        "tax_year": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "pay_date": None,
        "employer_name": None,
        "subject": None,
        "form_number": None
    }
    # Merge with defaults, preferring values from response
    for key in default_attrs:
        if key not in distinguishing_attribute:
            distinguishing_attribute[key] = None

    labeled_seg = LabeledSegment(
        seg_id=seg.seg_id,
        start_page=seg.start_page,
        end_page=seg.end_page,
        doc_type=llm_response.get("doc_type", "unknown"),
        distinguishing_attribute=distinguishing_attribute,
        confidence=llm_response.get("confidence_hint", 0.5),
        boundary_score=seg.boundary_score,
        type_score=0.0,  # Would be calculated in full implementation
        attribute_score=0.0,  # Would be calculated in full implementation
        source=source,
        llm_model_used=llm_model_used,
        llm_raw_response=json.dumps(llm_response),
        review_required=llm_response.get("confidence_hint", 0.5) < settings.LOW_CONFIDENCE_THRESHOLD
    )

    return labeled_seg


async def run(
    candidates: List[CandidateSegment],
    page_records: Dict[int, PageRecord],
    fingerprints: Dict[int, PageFingerprint],
    settings
) -> List[LabeledSegment]:
    """
    Label all segments.
    """
    # Process segments concurrently (but limit concurrency to avoid overwhelming Ollama)
    semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent LLM calls

    async def label_with_semaphore(seg):
        async with semaphore:
            return await label_segment(seg, page_records, fingerprints, settings)

    tasks = [label_with_semaphore(seg) for seg in candidates]
    labeled_segments = await asyncio.gather(*tasks)

    return labeled_segments