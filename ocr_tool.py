import argparse
import sys
from pathlib import Path

from ocr_engine import OCREngineUnavailable, ocr_file


def main():
    parser = argparse.ArgumentParser(description="Extract text from scanned PDFs and images.")
    parser.add_argument("input", type=Path, help="PDF or image file to OCR")
    parser.add_argument("-o", "--output", type=Path, help="Write OCR text to this file")
    parser.add_argument("--lang", default="eng", help="Tesseract language code (default: eng)")
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"Input file does not exist: {args.input}")

    try:
        text = ocr_file(args.input, args.lang)
    except OCREngineUnavailable as error:
        print(error, file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())