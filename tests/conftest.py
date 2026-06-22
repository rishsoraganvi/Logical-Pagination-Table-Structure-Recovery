"""
Shared test fixtures and configuration.
"""
import pytest
import os
from pathlib import Path


@pytest.fixture
def sample_pdf_path():
    """Path to sample PDF document for testing."""
    # This would point to the actual sample PDF
    return Path("docs/../doc_000.pdf")


@pytest.fixture
def temp_output_dir(tmp_path):
    """Temporary directory for test outputs."""
    return tmp_path / "output"