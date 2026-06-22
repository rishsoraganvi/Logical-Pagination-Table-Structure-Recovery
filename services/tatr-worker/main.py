"""
TATR Worker Service
Provides GPU-accelerated table structure recognition using Microsoft Table Transformer.
"""
import uvicorn
from fastapi import FastAPI
from tatr_engine import TATRRequest, TATRResponse, TATREngine

app = FastAPI(title="TATR Worker", version="0.1.0")

# Initialize TATR engine once at startup
tatr_engine = TATREngine()


@app.post("/table/detect", response_model=TATRResponse)
async def detect_table(request: TATRRequest) -> TATRResponse:
    """
    Receives an image path. Returns table structure detection results.
    Runs Table Transformer with GPU.
    """
    try:
        result = tatr_engine.detect_table(request.image_path)
        return TATRResponse(**result)
    except Exception as e:
        # Return error response
        return TATRResponse(
            success=False,
            error=str(e),
            tables=[]
        )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tatr-worker"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)