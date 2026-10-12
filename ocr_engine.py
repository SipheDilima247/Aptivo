import importlib
import os
import shutil
from pathlib import Path


class OCREngineUnavailable(RuntimeError):
    pass


def _load_engine():
    try:
        pdfium = importlib.import_module("pypdfium2")
        pytesseract = importlib.import_module("pytesseract")
        image_module = importlib.import_module("PIL.Image")
    except ImportError as error:
        raise OCREngineUnavailable(
            "OCR dependencies are missing. Run: python -m pip install -r requirements.txt"
        ) from error

    configured_path = os.environ.get("TESSERACT_CMD")
    if configured_path:
        pytesseract.pytesseract.tesseract_cmd = configured_path
    elif not shutil.which("tesseract"):
        candidates = (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Tesseract-OCR"
            / "tesseract.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
            / "Tesseract-OCR"
            / "tesseract.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                pytesseract.pytesseract.tesseract_cmd = str(candidate)
                break

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError as error:
        raise OCREngineUnavailable(
            "Tesseract OCR is not installed or not on PATH. Install Tesseract, "
            "or set TESSERACT_CMD to the full path of tesseract.exe."
        ) from error

    return pdfium, pytesseract, image_module


def ocr_pdf_pages(file_path, page_indexes, language="eng"):
    pdfium, pytesseract, _ = _load_engine()
    results = {}

    document = pdfium.PdfDocument(str(file_path))
    try:
        for page_index in page_indexes:
            if page_index < 0 or page_index >= len(document):
                raise ValueError(f"PDF page index out of range: {page_index}")

            page = document[page_index]
            bitmap = page.render(scale=200 / 72)
            image = bitmap.to_pil()
            try:
                results[page_index] = pytesseract.image_to_string(image, lang=language)
            finally:
                image.close()
                bitmap.close()
                page.close()
    finally:
        document.close()

    return results


def ocr_file(file_path, language="eng"):
    file_path = Path(file_path)
    if file_path.suffix.lower() == ".pdf":
        pdfium, _, _ = _load_engine()
        document = pdfium.PdfDocument(str(file_path))
        try:
            page_indexes = range(len(document))
        finally:
            document.close()
        return "\n".join(ocr_pdf_pages(file_path, page_indexes, language).values())

    _, pytesseract, image_module = _load_engine()
    with image_module.open(file_path) as image:
        return pytesseract.image_to_string(image, lang=language)