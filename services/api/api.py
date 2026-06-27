"""
FastAPI application factory and configuration.
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routers import health, pipeline

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Loan Document IDP Pipeline",
        description="Intelligent Document Processing for loan document analysis",
        version="0.1.0",
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["health"])
    app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])

    return app

# Create app instance
app = create_app()