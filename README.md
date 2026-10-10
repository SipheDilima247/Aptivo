# Aptivo

A simple AI-assisted job application system inspired by the product mockups in the documentation folder.

## Features

- Landing page and product-style marketing UX
- Multi-step application wizard
- Job description intake with optional file upload
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

## Notes

This MVP focuses on the UX and workflow described in the project brief. The matching logic is heuristic and designed to be easy to replace with a real AI or API service later.
