"""
OCR Worker Service
Provides GPU-accelerated OCR using PaddleOCR.
"""
import uvicorn
from fastapi import FastAPI
from ocr_engine import OCRBatchRequest, OCRBatchResponse, OCREngine

app = FastAPI(title="OCR Worker", version="0.1.0")

# Initialize OCR engine once at startup
ocr_engine = OCREngine()


@app.post("/ocr/batch", response_model=OCRBatchResponse)
async def ocr_batch(request: OCRBatchRequest) -> OCRBatchResponse:
    """
    Receives up to 16 image paths. Returns OCR text + bbox blocks per page.
    Runs PaddleOCR with GPU.
    """
    results = {}
    for page_num, image_path in request.image_paths.items():
        try:
            result = ocr_engine.ocr(image_path)
            results[page_num] = result
        except Exception as e:
            # Return error result for failed OCR
            results[page_num] = {
                "error": str(e),
                "text": "",
                "blocks": [],
                "confidence_avg": 0.0
            }

    return OCRBatchResponse(results=results)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "ocr-worker"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)