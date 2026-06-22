"""
Stage 5: Validation & Assembly
Validate segments and tables, assemble final output.
"""
from typing import List, Tuple
from api.models import LabeledSegment, RecoveredTable, DocumentInstance
from api.models.document import DocTypeEnum, DistinguishingAttribute
import json


def validate_coverage(segments: List[LabeledSegment], total_pages: int) -> Tuple[List[LabeledSegment], dict]:
    """
    Check for overlaps and gaps in segment coverage.
    Returns validated segments and validation metrics.
    """
    if not segments:
        return [], {"gaps": [], "overlaps": [], " coverage_percentage": 0.0}

    # Sort segments by start page
    sorted_segments = sorted(segments, key=lambda s: s.start_page)

    # Check for gaps and overlaps
    gaps = []
    overlaps = []
    validated_segments = []

    expected_page = 1  # Start with page 1

    for segment in sorted_segments:
        # Check for gap before this segment
        if segment.start_page > expected_page:
            gaps.append({
                "start": expected_page,
                "end": segment.start_page - 1,
                "missing_pages": segment.start_page - expected_page
            })

        # Check for overlap with previous segment
        if validated_segments and segment.start_page <= validated_segments[-1].end_page:
            overlap_start = max(expected_page, segment.start_page)
            overlap_end = min(validated_segments[-1].end_page, segment.end_page)
            if overlap_start <= overlap_end:
                overlaps.append({
                    "start": overlap_start,
                    "end": overlap_end,
                    "pages": overlap_end - overlap_start + 1
                })

        validated_segments.append(segment)
        expected_page = segment.end_page + 1

    # Check for gap at the end
    if expected_page <= total_pages:
        gaps.append({
            "start": expected_page,
            "end": total_pages,
            "missing_pages": total_pages - expected_page + 1
        })

    # Calculate coverage percentage
    covered_pages = sum(s.end_page - s.start_page + 1 for s in validated_segments)
    coverage_percentage = (covered_pages / total_pages) * 100 if total_pages > 0 else 0

    validation_metrics = {
        "gaps": gaps,
        "overlaps": overlaps,
        "coverage_percentage": coverage_percentage
    }

    return validated_segments, validation_metrics


def attach_orphan_pages(
    segments: List[LabeledSegment],
    total_pages: int
) -> List[LabeledSegment]:
    """
    Attach orphan pages (not covered by any segment) to nearest preceding segment.
    Reduces confidence for Segments that get orphan pages attached.
    """
    if not segments or total_pages == 0:
        return segments

    # Create a page ownership map
    page_owner = {}  # page_num -> segment_index
    for i, segment in enumerate(segments):
        for page_num in range(segment.start_page, segment.end_page + 1):
            page_owner[page_num] = i

    # Find orphan pages
    orphan_pages = []
    for page_num in range(1, total_pages + 1):
        if page_num not in page_owner:
            orphan_pages.append(page_num)

    # Attach each orphan to nearest preceding segment
    for orphan_page in orphan_pages:
        # Find nearest preceding segment
        preceding_segments = [
            (i, s) for i, s in enumerate(segments)
            if s.end_page < orphan_page
        ]

        if preceding_segments:
            # Get the closest preceding segment (largest end_page)
            closest_index, closest_segment = max(preceding_segments, key=lambda x: x[1].end_page)

            # Extend the segment to include this page
            # Create a new segment with extended range
            extended_segment = LabeledSegment(
                seg_id=closest_segment.seg_id,
                start_page=closest_segment.start_page,
                end_page=max(closest_segment.end_page, orphan_page),
                doc_type=closest_segment.doc_type,
                distinguishing_attribute=closest_segment.distinguishing_attribute,
                confidence=closest_segment.confidence * 0.5,  # Reduce confidence for orphan attachment
                boundary_score=closest_segment.boundary_score,
                type_score=closest_segment.type_score,
                attribute_score=closest_segment.attribute_score,
                source=closest_segment.source,
                llm_model_used=closest_segment.llm_model_used,
                llm_raw_response=closest_segment.llm_raw_response,
                review_required=closest_segment.review_required or (closest_segment.confidence * 0.5 < 0.70)
            )

            # Replace the original segment
            segments[closest_index] = extended_segment
        else:
            # No preceding segment - attach to first segment or create new one?
            # For simplicity, we'll skip this case (shouldn't happen with proper boundary detection)
            pass

    return segments


def assemble_output(
    segments: List[LabeledSegment],
    tables: List[RecoveredTable]
) -> Tuple[List[DocumentInstance], List[RecoveredTable]]:
    """
    Convert LabeledSegment -> DocumentInstance and finalize tables.
    """
    documents = []

    for i, segment in enumerate(segments):
        # Generate doc_id
        doc_id = f"doc_{i:04d}"

        # Convert distinguishing attribute to proper format
        # The distinguishing_attribute in LabeledSegment is already a dict
        # We need to convert it to DistinguishingAttribute model
        try:
            distinguishing_attr = DistinguishingAttribute(**segment.distinguishing_attribute)
        except Exception:
            # If conversion fails, use empty attribute
            distinguishing_attr = DistinguishingAttribute()

        document = DocumentInstance(
            doc_id=doc_id,
            doc_type=segment.doc_type,  # This should already be a valid DocTypeEnum string
            start_page=segment.start_page,
            end_page=segment.end_page,
            distinguishing_attribute=distinguishing_attr,
            confidence=segment.confidence,
            source=segment.source,
            review_required=segment.review_required,
            llm_label=segment.llm_raw_response
        )
        documents.append(document)

    # For tables, we would ideally update the doc_id to match actual documents
    # For now, we'll return tables as-is (they have placeholder doc_ids)
    final_tables = tables

    return documents, final_tables


def run(
    segments: List[LabeledSegment],
    tables: List[RecoveredTable]
) -> Tuple[List[DocumentInstance], List[RecoveredTable]]:
    """
    Run validation and assembly.
    """
    # We would need total_pages for validation - get it from segments
    total_pages = 0
    if segments:
        total_pages = max(s.end_page for s in segments)

    # Validate coverage
    validated_segments, validation_metrics = validate_coverage(segments, total_pages)

    # Attach orphan pages
    segments_with_orphans = attach_orphan_pages(validated_segments, total_pages)

    # Assemble final output
    documents, final_tables = assemble_output(segments_with_orphans, tables)

    # In a full implementation, we would add validation_metrics to the final metrics
    # For now, we just return the documents and tables

    return documents, final_tables