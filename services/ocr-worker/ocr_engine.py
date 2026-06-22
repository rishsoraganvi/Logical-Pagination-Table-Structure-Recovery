"""
OCR Engine using PaddleOCR with GPU acceleration.
"""
from typing import Dict, List, Tuple, Optional
import numpy as np
from paddleocr import PaddleOCR


class OCRBlock:
    def __init__(self, bbox: Tuple[float, float, float, float], text: str, confidence: float):
        self.bbox = bbox
        self.text = text
        self.confidence = confidence


class OCREngine:
    def __init__(self):
        # Initialize PaddleOCR with GPU
        # use_angle_cls=True for better accuracy on rotated text
        # lang='en' for English
        # use_gpu=True for GPU acceleration
        self.ocr = PaddleOCR(
            use_angle_cls=True,
            lang='en',
            use_gpu=True,
            show_log=False  # Disable verbose logging
        )

    def ocr(self, image_path: str) -> dict:
        """
        Perform OCR on a single image.
        Returns dict with text, blocks, and average confidence.
        """
        # Run OCR
        result = self.ocr.ocr(image_path, cls=True)

        # Process results
        if not result or result[0] is None:
            return {
                "text": "",
                "blocks": [],
                "confidence_avg": 0.0
            }

        # Extract text and bounding boxes
        text_lines = []
        blocks = []
        confidences = []

        for line in result[0]:
            if line is not None:
                bbox, (text, confidence) = line
                if text and confidence > 0.1:  # Filter low confidence detections
                    text_lines.append(text)
                    blocks.append({
                        "bbox": bbox,
                        "text": text,
                        "confidence": confidence
                    })
                    confidences.append(confidence)

        # Calculate average confidence
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Join text lines
        full_text = " ".join(text_lines)

        return {
            "text": full_text,
            "blocks": blocks,
            "confidence_avg": avg_confidence
        }


# Pydantic models for request/response
from pydantic import BaseModel
from typing import Dict


class OCRBatchRequest(BaseModel):
    image_paths: Dict[int, str]  # page_num -> image_path


class OCRBatchResponse(BaseModel):
    results: Dict[int, dict]  # page_num -> OCR result