"""
Stage 2: Boundary Detection
Similarity signal, PELT change-point detection, same-type splitting.
"""
from typing import List
import numpy as np
import ruptures as rpt
from sklearn.metrics.pairwise import cosine_similarity

from api.models import CandidateSegment, PageFingerprint


def compute_similarity_signal(fingerprints: List[PageFingerprint]) -> List[float]:
    """
    Returns list of length N-1 where sim[i] = similarity between page i and i+1.
    Near-blank pages are forced to 1.0 (no boundary).
    """
    if len(fingerprints) < 2:
        return []

    similarities = []

    for i in range(len(fingerprints) - 1):
        fp_curr = fingerprints[i]
        fp_next = fingerprints[i + 1]

        # If next page is near-blank, force similarity to 1.0 (no boundary)
        if fp_next.is_near_blank:
            similarities.append(1.0)
            continue

        # Compute cosine similarity of embeddings
        embed_sim = cosine_similarity(
            [fp_curr.embed_vec], [fp_next.embed_vec]
        )[0][0]

        # Compute layout distance (1 - normalized layout similarity)
        layout_curr = np.array(fp_curr.layout_vec)
        layout_next = np.array(fp_next.layout_vec)
        layout_dist = np.linalg.norm(layout_curr - layout_next) / np.sqrt(6)  # Normalize by dimension
        layout_sim = max(0.0, 1.0 - layout_dist)

        # Combined similarity: embed_sim * layout_sim
        similarity = embed_sim * layout_sim
        similarities.append(similarity)

    return similarities


def detect_boundaries(sim_signal: List[float], pen: float = 3.0) -> List[int]:
    """
    Returns list of page numbers that are STARTS of new segments.
    Page 1 is always a start. All other starts come from PELT.
    """
    if len(sim_signal) == 0:
        return [1]  # Only one page

    # Convert similarity signal to cost array (1 - similarity for change detection)
    # We want to detect drops in similarity, so we use (1 - sim) as the cost
    cost_array = np.array([1.0 - s for s in sim_signal]).reshape(-1, 1)

    # Apply PELT algorithm
    algo = rpt.Pelt(model="rbf").fit(cost_array)
    breakpoints = algo.predict(pen=pen)  # Returns list of end indices (exclusive)

    # Convert breakpoints to start page numbers
    # Page 1 is always a start
    starts = [1]

    # Each breakpoint is the exclusive end of a segment
    # So the next segment starts at breakpoint + 1 (1-indexed)
    for bp in breakpoints[:-1]:  # Exclude the last breakpoint (which is len(sim_signal))
        if bp < len(sim_signal):  # Valid breakpoint
            starts.append(bp + 1)  # Convert to 1-indexed page number

    return starts


def refine_segments(
    candidates: List[CandidateSegment],
    fingerprints: List[PageFingerprint]
) -> List[CandidateSegment]:
    """
    - Fold near-blank pages (see Design.md §11).
    - Group consecutive segments with cosine_similarity(header_embed_i, header_embed_j) > 0.90.
    - Within each group, run extract_distinguishing_attribute per segment and split on attribute change.
    """
    # For now, return candidates as-is (simplified implementation)
    # In a full implementation, this would:
    # 1. Fold near-blank pages into preceding segments
    # 2. Group segments by header similarity
    # 3. Extract distinguishing attributes and split on changes
    return candidates


def extract_distinguishing_attribute(segment_text: str) -> dict:
    """
    Extract distinguishing attribute from segment text (statement period, tax year, etc.)
    This is a simplified implementation - in reality would use regex patterns per doc type.
    """
    # Placeholder implementation
    import re

    # Look for common patterns
    patterns = {
        "statement_period_start": r"(?:statement\s+period\s+from|period\s+starting)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
        "statement_period_end": r"(?:statement\s+period\s+to|period\s+ending)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
        "account_number_last4": r"(?:account\s+#?|acct\s*#?)[\s:]*[^\d]*(\d{4})",
        "tax_year": r"(?:tax\s+year|year)[\s:]*(\d{4})",
        "pay_period_start": r"(?:pay\s+period\s+from|period\s+starting)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
        "pay_period_end": r"(?:pay\s+period\s+to|period\s+ending)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
        "pay_date": r"(?:pay\s+date|date\s+paid)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
        "employer_name": r"(?:employer|company)[\s:]*([^\n\r]+)",
        "subject": r"(?:subject|re:)[\s:]*([^\n\r]+)",
        "form_number": r"(?:form\s*#?|irs\s*form)[\s:]*(\d+[A-Z]*)",
    }

    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, segment_text, re.IGNORECASE)
        if match:
            result[key] = match.group(1)
        else:
            result[key] = None

    return result