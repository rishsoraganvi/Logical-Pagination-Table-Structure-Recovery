"""
Health check endpoints.
"""
from fastapi import APIRouter

from api.models import HealthCheckResponse

router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """
    Health check endpoint.
    Returns basic service status and dependency health.
    """
    # In a real implementation, we would check dependencies like Redis, workers, etc.
    # For now, return a basic OK status
    return HealthCheckResponse(
        status="ok",
        gpu=False,  # Would be determined by actual GPU detection
        ollama=True,  # Would be determined by actual Ollama health check
    )