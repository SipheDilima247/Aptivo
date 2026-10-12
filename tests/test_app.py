import unittest
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

from app import OCREngineUnavailable, app, extract_file_text, get_db_connection


class CoverLetterPdfExportTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with get_db_connection() as conn:
            conn.execute(
                "DELETE FROM applications WHERE company = ? AND role = ?",
                ("Acme", "Product Manager"),
            )
            conn.execute(
                """
                INSERT INTO applications (company, role, job_description, cv_text, cover_letter, match_score, summary, strengths, gaps)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Acme",
                    "Product Manager",
                    "Need product manager with analytics and strategy",
                    "Product manager with analytics and strategy",
                    "Dear Hiring Manager,\n\nI am excited to apply.",
                    88,
                    "Strong alignment",
                    "experience; analytics",
                    "strategy",
                ),
            )
            conn.commit()

    def test_cover_letter_download_returns_pdf(self):
        with get_db_connection() as conn:
            app_id = conn.execute(
                "SELECT id FROM applications WHERE company = ? AND role = ? ORDER BY id DESC LIMIT 1",
                ("Acme", "Product Manager"),
            ).fetchone()[0]

        response = self.client.get(f"/download/{app_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn(b"%PDF", response.data[:4])

    def test_cv_download_returns_pdf(self):
        with get_db_connection() as conn:
            app_id = conn.execute(
                "SELECT id FROM applications WHERE company = ? AND role = ? ORDER BY id DESC LIMIT 1",
                ("Acme", "Product Manager"),
            ).fetchone()[0]

        response = self.client.get(f"/download-cv/{app_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn(b"%PDF", response.data[:4])


class PdfUploadFeedbackTests(unittest.TestCase):
    def test_text_empty_pdfs_show_extraction_feedback(self):
        pdf_buffer = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(pdf_buffer)
        pdf_data = pdf_buffer.getvalue()

        with patch("app.ocr_pdf_pages", return_value={0: ""}):
            response = app.test_client().post(
                "/submit",
                data={
                    "job_file": (BytesIO(pdf_data), "job.pdf"),
                    "cv_file": (BytesIO(pdf_data), "cv.pdf"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"check that OCR is installed", response.data)

    def test_pdf_extraction_uses_ocr_for_text_empty_pages(self):
        pdf_buffer = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(pdf_buffer)
        upload = FileStorage(stream=BytesIO(pdf_buffer.getvalue()), filename="scan.pdf")

        with patch("app.ocr_pdf_pages", return_value={0: "Recognized scanned document text"}):
            extracted = extract_file_text(upload)

        self.assertEqual(extracted, "Recognized scanned document text")

    def test_missing_ocr_engine_shows_setup_message(self):
        pdf_buffer = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(pdf_buffer)
        pdf_data = pdf_buffer.getvalue()

        with patch("app.ocr_pdf_pages", side_effect=OCREngineUnavailable("Tesseract OCR is not installed.")):
            response = app.test_client().post(
                "/submit",
                data={"job_file": (BytesIO(pdf_data), "scan.pdf")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tesseract OCR is not installed.", response.data)


if __name__ == "__main__":
    unittest.main()
