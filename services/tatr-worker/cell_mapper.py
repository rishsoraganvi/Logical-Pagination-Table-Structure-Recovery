"""
Cell Mapper for TATR Worker
Maps OCR blocks onto TATR detected cell bboxes using IoU matching.
"""
from typing import List, Tuple, Dict, Optional
import numpy as np


def calculate_iou(bbox1: Tuple[float, float, float, float],
                  bbox2: Tuple[float, float, float, float]) -> float:
    """
    Calculate Intersection over Union (IoU) of two bounding boxes.
    Each bbox is (x1, y1, x2, y2).
    """
    # Determine intersection coordinates
    x1_intersect = max(bbox1[0], bbox2[0])
    y1_intersect = max(bbox1[1], bbox2[1])
    x2_intersect = min(bbox1[2], bbox2[2])
    y2_intersect = min(bbox1[3], bbox2[3])

    # Calculate intersection area
    if x2_intersect <= x1_intersect or y2_intersect <= y1_intersect:
        intersection_area = 0.0
    else:
        intersection_area = (x2_intersect - x1_intersect) * (y2_intersect - y1_intersect)

    # Calculate areas of each bbox
    bbox1_area = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    bbox2_area = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])

    # Calculate union area
    union_area = bbox1_area + bbox2_area - intersection_area

    # Avoid division by zero
    if union_area == 0.0:
        return 0.0

    return intersection_area / union_area


def map_ocr_to_tatr_cells(
    ocr_blocks: List[Dict],
    tatr_cells: List[Dict],
    iou_threshold: float = 0.3
) -> List[Dict]:
    """
    Map OCR blocks to TATR cells using IoU matching.
    Each OCR block is assigned to the cell with highest IoU above threshold.
    Returns list of enriched cell dicts with OCR text.
    """
    # Initialize cells with empty text
    mapped_cells = []
    for cell in tatr_cells:
        mapped_cell = cell.copy()
        mapped_cell["ocr_text"] = ""
        mapped_cell["ocr_confidence"] = 0.0
        mapped_cells.append(mapped_cell)

    # For each OCR block, find the best matching cell
    for ocr_block in ocr_blocks:
        ocr_bbox = tuple(ocr_block["bbox"])
        ocr_text = ocr_block["text"]
        ocr_confidence = ocr_block["confidence"]

        best_iou = 0.0
        best_cell_idx = -1

        # Find cell with highest IoU
        for i, cell in enumerate(tatr_cells):
            cell_bbox = tuple(cell["bbox"])
            iou = calculate_iou(ocr_bbox, cell_bbox)

            if iou > best_iou and iou >= iou_threshold:
                best_iou = iou
                best_cell_idx = i

        # Assign OCR text to best matching cell
        if best_cell_idx >= 0:
            # Append text (handle multiple OCR blocks mapping to same cell)
            if mapped_cells[best_cell_idx]["ocr_text"]:
                mapped_cells[best_cell_idx]["ocr_text"] += " " + ocr_text
            else:
                mapped_cells[best_cell_idx]["ocr_text"] = ocr_text

            # Keep highest confidence
            if ocr_confidence > mapped_cells[best_cell_idx]["ocr_confidence"]:
                mapped_cells[best_cell_idx]["ocr_confidence"] = ocr_confidence

    return mapped_cells


def extract_table_data(
    mapped_cells: List[Dict],
    tatr_table_info: Dict
) -> List[List[str]]:
    """
    Extract table data as a 2D list of strings from mapped cells.
    tatr_table_info should contain rows and cols count.
    """
    rows = tatr_table_info.get("rows", 0)
    cols = tatr_table_info.get("cols", 0)

    # Initialize empty table
    table = [["" for _ in range(cols)] for _ in range(rows)]

    # Fill table with OCR text from cells
    for cell in mapped_cells:
        row_idx = cell.get("row", 0)
        col_idx = cell.get("col", 0)
        text = cell.get("ocr_text", "")

        if 0 <= row_idx < rows and 0 <= col_idx < cols:
            table[row_idx][col_idx] = text

    return table


# Pydantic models for cell mapping (if needed)
from pydantic import BaseModel


class OCRBlock(BaseModel):
    bbox: List[float]  # [x1, y1, x2, y2]
    text: str
    confidence: float


class TATRCell(BaseModel):
    bbox: List[float]  # [x1, y1, x2, y2]
    row: int
    col: int


class MappedCell(BaseModel):
    bbox: List[float]  # [x1, y1, x2, y2]
    row: int
    col: int
    ocr_text: str
    ocr_confidence: float