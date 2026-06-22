"""
Image utilities for PDF rasterization and OpenCV feature extraction.
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Optional
import pdf2image


def rasterize_page(
    pdf_path: Path,
    page_num: int,
    dpi: int = 150,
    output_dir: Optional[Path] = None
) -> Optional[Path]:
    """
    Rasterize a specific PDF page to JPEG.
    Returns path to the generated image, or None if failed.
    """
    try:
        images = pdf2image.convert_from_path(
            str(pdf_path),
            dpi=dpi,
            first_page=page_num,
            last_page=page_num,
            fmt="jpeg"
        )

        if images:
            image = images[0]
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                image_path = output_dir / f"{page_num:04d}.jpg"
                image.save(str(image_path), "JPEG")
                return image_path
            else:
                # Return temporary path - caller should handle cleanup
                import tempfile
                temp_dir = Path(tempfile.gettempdir())
                image_path = temp_dir / f"{pdf_path.stem}_{page_num:04d}.jpg"
                image.save(str(image_path), "JPEG")
                return image_path

        return None
    except Exception:
        return None


def extract_layout_features(image_path: Path) -> np.ndarray:
    """
    Extract layout features from an image using OpenCV.
    Returns 6-element array: [line_density, col_count, whitespace_ratio,
                             table_present, text_density, ink_coverage]
    """
    if not image_path.exists():
        return np.zeros(6)

    try:
        # Load image
        image = cv2.imread(str(image_path))
        if image is None:
            return np.zeros(6)

        height, width = image.shape[:2]

        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Threshold to get binary image
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Calculate ink coverage (proportion of non-white pixels)
        ink_coverage = np.sum(binary > 0) / (width * height)

        # Text density: approximate from ink coverage
        text_density = min(ink_coverage * 1.2, 1.0)  # Rough approximation

        # Whitespace ratio: inverse of ink coverage with smoothing
        whitespace_ratio = max(0.0, 1.0 - ink_coverage * 1.1)

        # Line density: estimate from horizontal projections
        horizontal_proj = np.sum(binary, axis=1)
        try:
            from scipy.signal import find_peaks
            peaks, _ = find_peaks(horizontal_proj, height=horizontal_proj.max()*0.1, distance=5)
            line_density = len(peaks) / height if height > 0 else 0
        except ImportError:
            # Fallback if scipy not available
            line_density = np.sum(horizontal_proj > horizontal_proj.mean()) / height

        # Column count: estimate from vertical projections
        vertical_proj = np.sum(binary, axis=0)
        try:
            peaks, _ = find_peaks(vertical_proj, height=vertical_proj.max()*0.1, distance=10)
            col_count = len(peaks)
        except ImportError:
            # Fallback if scipy not available
            col_count = np.sum(vertical_proj > vertical_proj.mean()) // max(width // 20, 1)

        # Table present: heuristic based on regular grid patterns
        table_present = 1.0 if (line_density > 0.01 and col_count > 1 and ink_coverage > 0.1) else 0.0

        # Normalize features to 0-1 range where appropriate
        return np.array([
            min(line_density, 1.0),  # Normalize line density
            min(float(col_count), 10.0) / 10.0,  # Normalize column count
            min(whitespace_ratio, 1.0),
            table_present,
            min(text_density, 1.0),
            min(ink_coverage, 1.0)
        ])
    except Exception:
        return np.zeros(6)