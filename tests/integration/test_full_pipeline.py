"""
Integration tests for full pipeline.
These tests require running services and would typically be run in a test environment.
"""
import pytest
import requests
import time
from pathlib import Path


class TestFullPipeline:
    @pytest.mark.integration
    def test_pipeline_health(self):
        """Test that all services are healthy."""
        services = [
            ("http://localhost:8000/health", "api"),
            ("http://localhost:8001/health", "ocr-worker"),
            ("http://localhost:8002/health", "tatr-worker"),
        ]

        for url, service_name in services:
            try:
                response = requests.get(url, timeout=5)
                assert response.status_code == 200
                data = response.json()
                assert data.get("status") == "ok"
            except requests.exceptions.RequestException:
                pytest.fail(f"Service {service_name} at {url} is not healthy")

    @pytest.mark.integration
    def test_end_to_end_processing(self, sample_pdf_path):
        """Test end-to-end processing of a sample PDF."""
        # Skip if sample PDF doesn't exist
        if not sample_pdf_path.exists():
            pytest.skip("Sample PDF not available for integration testing")

        # Submit job
        with open(sample_pdf_path, "rb") as f:
            files = {"file": (sample_pdf_path.name, f, "application/pdf")}
            response = requests.post("http://localhost:8000/pipeline/run", files=files)

        assert response.status_code == 200
        job_data = response.json()
        job_id = job_data["job_id"]

        # Poll for completion
        max_attempts = 30
        for _ in range(max_attempts):
            response = requests.get(f"http://localhost:8000/pipeline/status/{job_id}")
            assert response.status_code == 200
            status_data = response.json()

            if status_data["stage"] == "done":
                break
            elif status_data["stage"] == "failed":
                pytest.fail(f"Pipeline failed: {status_data.get('error_message', 'Unknown error')}")

            time.sleep(2)
        else:
            pytest.fail("Pipeline did not complete within expected time")

        # Get results
        response = requests.get(f"http://localhost:8000/pipeline/result/{job_id}")
        assert response.status_code == 200
        result_data = response.json()

        # Basic assertions
        assert "documents" in result_data
        assert "tables" in result_data
        assert "metrics" in result_data
        assert isinstance(result_data["documents"], list)
        assert isinstance(result_data["tables"], list)