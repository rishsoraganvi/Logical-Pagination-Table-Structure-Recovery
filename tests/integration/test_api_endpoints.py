"""
Integration tests for API endpoints.
"""
import pytest
import requests


class TestAPIEndpoints:
    def test_health_endpoint(self):
        """Test the health endpoint."""
        response = requests.get("http://localhost:8000/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        # Note: gpu and ollama fields might be False in test environment

    def test_pipeline_run_endpoint_no_file(self):
        """Test pipeline run endpoint with no file."""
        response = requests.post("http://localhost:8000/pipeline/run")
        # Should return 422 (Unprocessable Entity) for missing file
        assert response.status_code == 422

    def test_pipeline_status_endpoint_nonexistent_job(self):
        """Test status endpoint with non-existent job ID."""
        response = requests.get("http://localhost:8000/pipeline/status/nonexistent-job-id")
        assert response.status_code == 404

    def test_pipeline_result_endpoint_nonexistent_job(self):
        """Test result endpoint with non-existent job ID."""
        response = requests.get("http://localhost:8000/pipeline/result/nonexistent-job-id")
        assert response.status_code == 404