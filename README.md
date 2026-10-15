# Aptivo

A simple AI-assisted job application system inspired by the product mockups in the documentation folder.

## Features

- Landing page and product-style marketing UX
- Multi-step application wizard
- Job description intake with optional file upload
- OCR fallback for scanned PDFs, plus a standalone OCR command-line tool
- CV/resume analysis and keyword matching
- Cover letter generation tailored to the job role
- SQLite storage for local development, with PostgreSQL support for deployment

## Running locally

1. Create a virtual environment if needed.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt / py -3 -m pip install -r requirements.txt
   ```
3. Start the app:
   ```bash
   python app.py
   ```
4. Open http://localhost:5000

## Run with Docker

Build and start the container:

```bash
docker build -t aptivo .
docker run --name aptivo -p 5000:10000 aptivo
```

Open http://localhost:5000. The image includes Tesseract OCR and runs Flask with Gunicorn. This initial container setup stores SQLite data and uploads inside the container; they are not persistent across container removal or redeployment. Configure persistent storage in the deployment setup before using it for real applications.

### Database configuration

By default, Aptivo uses local SQLite (`applications.db`). To use PostgreSQL, set `DATABASE_URL` to the database connection URL. On Render, add the Postgres database's internal connection URL as the web service's `DATABASE_URL` environment variable. Aptivo creates the application table on startup. Keep the variable secret and do not commit it to the repository.

When deploying with PostgreSQL, also set `SECRET_KEY` in the Render web service's environment variables. Generate a strong value with `python -c "import secrets; print(secrets.token_hex(32))"`. Local SQLite development uses a development-only fallback; Aptivo refuses to start with `DATABASE_URL` if `SECRET_KEY` is missing.

### Render preview deployment

The repository includes a `render.yaml` Blueprint for a free preview. Push the repository to GitHub, then in Render choose **New > Blueprint** and select the repository. Render creates a Docker web service and a free Postgres database, then connects them with `DATABASE_URL` and generates `SECRET_KEY`.

This free Postgres database expires after 30 days, and the free web service can sleep while idle. The app currently has no user authentication, so its dashboard and application records are not private. Use synthetic test documents only; do not upload real CVs or personal information. Upgrade storage and add authentication before a production launch.

### OCR setup

OCR uses the free Tesseract engine. Install the Python dependencies from `requirements.txt`, then install Tesseract OCR on the machine running Aptivo. On Windows, the UB Mannheim installer is available at <https://github.com/UB-Mannheim/tesseract/wiki>.

If Tesseract is not on `PATH`, set `TESSERACT_CMD` to its executable path before starting Aptivo. In PowerShell, for example:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
python app.py
```

Scanned or image-only PDF pages are OCR'd automatically when normal PDF text extraction finds fewer than 40 characters on a page. Text-based PDFs continue to use the existing text extractor.

The OCR engine can also be used independently from the command line:

```powershell
python ocr_tool.py path\to\scan.pdf --output extracted.txt
python ocr_tool.py path\to\scan.png
```

Use `--lang` to select an installed Tesseract language, such as `--lang eng`.

## Notes

This MVP focuses on the UX and workflow described in the project brief. The matching logic is heuristic and designed to be easy to replace with a real AI or API service later.
