# Aptivo

A simple AI-assisted job application system inspired by the product mockups in the documentation folder.

## Features

- Landing page and product-style marketing UX
- Multi-step application wizard
- Job description intake with optional file upload
- OCR fallback for scanned PDFs, plus a standalone OCR command-line tool
- CV/resume analysis and keyword matching
- Cover letter generation tailored to the job role
- Local SQLite storage for saved applications

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
