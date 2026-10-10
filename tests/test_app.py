import unittest

from app import app, get_db_connection


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


if __name__ == "__main__":
    unittest.main()
