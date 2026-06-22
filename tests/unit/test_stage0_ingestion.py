"""
Unit tests for Stage 0: Ingestion & Triage
"""
import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from services.api.pipeline.stage0_ingestion import run


class TestStage0Ingestion:
    @patch('services.api.pipeline.stage0_ingestion.pypdf.PdfReader')
    @patch('services.api.pipeline.stage0_ingestion.pdf2image.convert_from_path')
    def test_run_native_text_only(self, mock_convert, mock_pdf_reader):
        # Setup mocks
        mock_page = Mock()
        mock_page.extract_text.return_value = "This is plenty of text for native detection."

        mock_pdf_reader_instance = Mock()
        mock_pdf_reader_instance.pages = [mock_page]
        mock_pdf_reader.return_value = mock_pdf_reader_instance

        mock_convert.return_value = []  # No images needed for native text

        # Execute
        result = run("test_job", Path("dummy.pdf"), Mock())

        # Verify
        assert len(result) == 1
        assert result[0].source == "native_text"
        assert result[0].text == "This is plenty of text for native detection."
        assert result[0].image_path is None

    @patch('services.api.pipeline.stage0_ingestion.pypdf.PdfReader')
    @patch('services.api.pipeline.stage0_ingestion.pdf2image.convert_from_path')
    def test_run_scanned_text_only(self, mock_convert, mock_pdf_reader):
        # Setup mocks
        mock_page = Mock()
        mock_page.extract_text.return_value = ""  # No text -> scanned

        mock_pdf_reader_instance = Mock()
        mock_pdf_reader_instance.pages = [mock_page]
        mock_pdf_reader.return_value = mock_pdf_reader_instance

        # Mock image conversion
        mock_image = Mock()
        mock_convert.return_value = [mock_image]

        # Execute
        result = run("test_job", Path("dummy.pdf"), Mock())

        # Verify
        assert len(result) == 1
        assert result[0].source == "ocr"  # Will be updated after OCR dispatch
        assert result[0].text == ""
        assert result[0].image_path is not None