import sqlite3
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

import app as app_module
from app import (
    OCREngineUnavailable,
    app,
    build_document_pdf,
    extract_file_text,
    execute_query,
    extract_user_edited_cv_text,
    extract_job_keywords,
    generate_cover_letter,
    get_secret_key,
    get_cv_style_preferences,
    get_db_connection,
    tailor_cv_to_job,
)


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

    def test_cv_pdf_omits_document_title(self):
        pdf_bytes = build_document_pdf(
            "Tailored CV",
            "Candidate experience and skills",
            "Acme",
            "Product Manager",
            include_document_title=False,
        )
        from pypdf import PdfReader

        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)
        self.assertNotIn("Tailored CV", pdf_text)
        self.assertIn("Candidate experience and skills", pdf_text)

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


class GeneratedCoverLetterTests(unittest.TestCase):
    def test_job_keywords_drop_boilerplate_and_terminal_punctuation(self):
        keywords = extract_job_keywords(
            "Looking for Python data analysis and dashboard reporting experience."
        )

        self.assertEqual(keywords, ["python", "data", "analysis", "dashboard", "reporting"])

    def test_generated_letter_closes_with_applicant_name(self):
        cover_letter = generate_cover_letter(
            "Acme",
            "Product Manager",
            "Looking for product management experience",
            "Product manager with five years of experience",
            applicant_name="Sipho Dilima",
        )

        self.assertTrue(cover_letter.endswith("Kind regards,\n\nSipho Dilima"))

    def test_cover_letter_uses_cv_evidence_without_generic_claims(self):
        cover_letter = generate_cover_letter(
            "Example Co",
            "Data Analyst",
            "Looking for Python data analysis and dashboard reporting experience.",
            "Experience: Built Python dashboards for monthly sales reporting.\n"
            "Managed warehouse inventory for three years.",
            applicant_name="Sipho Dilima",
        )

        self.assertIn("Built Python dashboards for monthly sales reporting", cover_letter)
        self.assertNotIn("stakeholder collaboration", cover_letter)
        self.assertNotIn("measurable business impact", cover_letter)
        self.assertTrue(cover_letter.endswith("Kind regards,\n\nSipho Dilima"))

    def test_cover_letter_flags_missing_cv_evidence(self):
        cover_letter = generate_cover_letter(
            "Example Co",
            "Data Analyst",
            "Looking for Python data analysis experience.",
            "Managed warehouse inventory for three years.",
            applicant_name="Sipho Dilima",
        )

        self.assertIn("does not show a specific example", cover_letter)
        self.assertNotIn("my experience in Python", cover_letter)

    def test_tailored_cv_preserves_source_and_selects_relevant_evidence(self):
        source_cv = (
            "Experience: Built Python dashboards for monthly sales reporting.\n"
            "Managed warehouse inventory for three years."
        )

        tailored_cv = tailor_cv_to_job(
            "Looking for Python data analysis and dashboard reporting experience.",
            source_cv,
        )

        self.assertIn("Built Python dashboards for monthly sales reporting", tailored_cv)
        self.assertIn("Original CV (wording preserved)", tailored_cv)
        self.assertTrue(tailored_cv.endswith(source_cv))
        self.assertNotIn("measurable business impact", tailored_cv)


class DatabaseBackendTests(unittest.TestCase):
    def test_postgres_queries_use_psycopg_placeholders(self):
        class RecordingConnection:
            def execute(self, statement, parameters):
                return statement, parameters

        connection = RecordingConnection()
        statement, parameters = execute_query(
            connection,
            "SELECT * FROM applications WHERE id = ?",
            (12,),
        )

        self.assertEqual(statement, "SELECT * FROM applications WHERE id = %s")
        self.assertEqual(parameters, (12,))

    def test_postgres_requires_a_configured_secret_key(self):
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://example"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Set SECRET_KEY"):
                get_secret_key()

    def test_local_development_uses_development_secret(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_secret_key(), "aptivo-local-development-only")


class AnonymousDataAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = f"{self.temp_dir.name}/anonymous-tests.db"
        self.connections = []
        self.connection_patch = patch.object(
            app_module,
            "get_db_connection",
            side_effect=self.connect_to_test_database,
        )
        self.connection_patch.start()
        app_module.init_db()
        self.owner_id = "test-owner-a"
        self.client = app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["anonymous_owner_id"] = self.owner_id
            browser_session.permanent = True

    def tearDown(self):
        self.connection_patch.stop()
        for connection in self.connections:
            connection.close()
        self.temp_dir.cleanup()

    def connect_to_test_database(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        self.connections.append(connection)
        return connection

    def create_application(
        self,
        owner_id,
        learning_consent=False,
        cv_text="Original CV",
        tailored_cv="Original CV",
    ):
        with app_module.get_db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO applications (
                    company, role, job_description, cv_text, tailored_cv, cover_letter,
                    match_score, summary, strengths, gaps, owner_id, learning_consent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Private Co", "Analyst", "Data reporting", cv_text, tailored_cv,
                    "Original letter", 80, "summary", "analysis", "", owner_id,
                    learning_consent,
                ),
            )
            connection.commit()
            return cursor.lastrowid

    def test_learning_consent_is_optional_and_unchecked_by_default(self):
        response = self.client.get("/application")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="learning_consent"', html)
        self.assertIn("Opt in to help improve Aptivo", html)
        self.assertNotIn('name="learning_consent" type="checkbox" value="yes" checked', html)

    def test_other_browser_cannot_read_save_or_download_application(self):
        application_id = self.create_application(self.owner_id)
        other_client = app.test_client()
        with other_client.session_transaction() as browser_session:
            browser_session["anonymous_owner_id"] = "test-owner-b"
            browser_session.permanent = True

        owner_result = self.client.get(f"/result/{application_id}")
        other_result = other_client.get(f"/result/{application_id}")
        other_download = other_client.get(f"/download-cv/{application_id}")
        other_client.post(
            f"/save-documents/{application_id}",
            data={"cover_letter": "Unauthorized edit"},
        )
        with app_module.get_db_connection() as connection:
            saved_letter = connection.execute(
                "SELECT cover_letter FROM applications WHERE id = ?",
                (application_id,),
            ).fetchone()[0]

        self.assertEqual(owner_result.status_code, 200)
        self.assertEqual(other_result.status_code, 302)
        self.assertEqual(other_download.status_code, 302)
        self.assertEqual(saved_letter, "Original letter")

    def test_opted_in_saved_cv_adds_only_aggregate_style_signals_once(self):
        application_id = self.create_application(
            self.owner_id,
            learning_consent=True,
            cv_text="- Built dashboards with 25% improvement.",
            tailored_cv="Generated summary from Aptivo.",
        )
        edited_cv = "- Built dashboards with 25% improvement."

        self.client.post(
            f"/save-documents/{application_id}",
            data={"tailored_cv": edited_cv},
        )
        self.client.post(
            f"/save-documents/{application_id}",
            data={"tailored_cv": edited_cv},
        )
        with app_module.get_db_connection() as connection:
            feedback = {
                row["feature"]: row["observations"]
                for row in connection.execute(
                    "SELECT feature, observations FROM cv_style_feedback"
                ).fetchall()
            }

        self.assertEqual(feedback, {
            "action_led_opening": 1,
            "bullet_format": 1,
            "cv_observations": 1,
            "quantified_results": 1,
        })
        self.assertNotIn("dashboards", feedback)

    def test_unedited_generated_cv_does_not_enter_learning_counts(self):
        generated_cv = "Generated Aptivo summary with action-led wording."
        application_id = self.create_application(
            self.owner_id,
            learning_consent=True,
            cv_text="Source CV",
            tailored_cv=generated_cv,
        )
        self.client.post(
            f"/save-documents/{application_id}",
            data={"tailored_cv": generated_cv},
        )

        with app_module.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM cv_style_feedback"
            ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_only_added_or_replaced_cv_lines_are_extractable_for_learning(self):
        learned_text = extract_user_edited_cv_text(
            "Generated summary.\nOriginal experience line.",
            "Generated summary.\n- Built dashboards and improved output by 25%.",
        )

        self.assertEqual(learned_text, "- Built dashboards and improved output by 25%.")

    def test_non_opted_in_cv_does_not_add_learning_signals(self):
        application_id = self.create_application(
            self.owner_id,
            learning_consent=False,
            cv_text="- Built dashboards with 25% improvement.",
        )
        self.client.post(
            f"/save-documents/{application_id}",
            data={"tailored_cv": "- Built dashboards with 25% improvement."},
        )

        with app_module.get_db_connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM cv_style_feedback"
            ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_aggregate_style_preferences_change_future_evidence_order(self):
        with app_module.get_db_connection() as connection:
            connection.executemany(
                "INSERT INTO cv_style_feedback (feature, observations) VALUES (?, ?)",
                [
                    ("cv_observations", 5),
                    ("action_led_opening", 5),
                    ("quantified_results", 5),
                ],
            )
            connection.commit()

        self.assertEqual(
            get_cv_style_preferences(),
            {"action_led_opening", "quantified_results"},
        )
        cover_letter = generate_cover_letter(
            "Example Co",
            "Data Analyst",
            "Looking for analysis experience.",
            "Completed analysis of monthly records.\n"
            "Improved analysis turnaround by 25% through automation.",
            applicant_name="Test User",
        )

        metric_example = cover_letter.index("Improved analysis turnaround by 25%")
        general_example = cover_letter.index("Completed analysis of monthly records")
        self.assertLess(metric_example, general_example)

    def test_style_preferences_wait_for_minimum_sample(self):
        with app_module.get_db_connection() as connection:
            connection.executemany(
                "INSERT INTO cv_style_feedback (feature, observations) VALUES (?, ?)",
                [("cv_observations", 4), ("action_led_opening", 4)],
            )
            connection.commit()

        self.assertEqual(get_cv_style_preferences(), set())


if __name__ == "__main__":
    unittest.main()
