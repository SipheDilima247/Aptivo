import os
import re
import sqlite3
from io import BytesIO
from pathlib import Path

from docx import Document
from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from werkzeug.utils import secure_filename

from ocr_engine import OCREngineUnavailable, ocr_pdf_pages

app = Flask(__name__)
app.config["SECRET_KEY"] = "aptivo-demo-secret"
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect("applications.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT,
                role TEXT,
                job_description TEXT,
                cv_text TEXT,
                tailored_cv TEXT,
                cover_letter TEXT,
                match_score INTEGER,
                summary TEXT,
                strengths TEXT,
                gaps TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        columns = [row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()]
        if "tailored_cv" not in columns:
            conn.execute("ALTER TABLE applications ADD COLUMN tailored_cv TEXT")

        conn.commit()


def extract_file_text(file_storage):
    if file_storage is None or not file_storage.filename:
        return ""

    filename = secure_filename(file_storage.filename)
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file_storage.save(file_path)

    suffix = Path(filename).suffix.lower()

    try:
        if suffix == ".pdf":
            try:
                reader = PdfReader(file_path)
                if reader.is_encrypted and not reader.decrypt(""):
                    return ""
                pages = [page.extract_text() or "" for page in reader.pages]
                pages_needing_ocr = [
                    index for index, text in enumerate(pages) if len(text.strip()) < 40
                ]
                if pages_needing_ocr:
                    ocr_results = ocr_pdf_pages(file_path, pages_needing_ocr)
                    for page_number, text in ocr_results.items():
                        if text.strip():
                            pages[page_number] = text
                return "\n".join(pages)
            except (FileNotDecryptedError, PdfReadError) as error:
                app.logger.warning("Unable to extract text from uploaded PDF %s: %s", filename, error)
                return ""
        if suffix == ".docx":
            doc = Document(file_path)
            return "\n".join(paragraph.text for paragraph in doc.paragraphs)
        if suffix in {".txt", ".md", ".rtf"}:
            return Path(file_path).read_text(encoding="utf-8", errors="ignore")
    finally:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass

    return ""


def tokenize(text):
    if not text:
        return []
    return re.findall(r"[a-zA-Z][a-zA-Z0-9+.#/-]{2,}", text.lower())


def normalize_skills(text):
    words = [word for word in tokenize(text) if len(word) > 2]
    stop_words = {
        "the", "and", "with", "your", "into", "this", "that", "from", "will",
        "have", "been", "they", "them", "their", "about", "over", "under", "role",
        "job", "company", "candidate", "position", "experience", "applications",
        "strong", "skills", "team", "work", "working", "using", "across", "through",
        "ensure", "build", "support", "deliver", "develop", "create", "including",
        "using", "business", "customer", "products", "project", "projects"
    }
    return [word for word in words if word not in stop_words]


def extract_job_keywords(job_description):
    tokens = normalize_skills(job_description)
    keywords = []
    seen = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            keywords.append(token)
    return keywords[:12]


def analyze_application(job_description, cv_text):
    job_keywords = extract_job_keywords(job_description)
    cv_tokens = set(normalize_skills(cv_text))
    matched = [keyword for keyword in job_keywords if keyword in cv_tokens]
    missing = [keyword for keyword in job_keywords if keyword not in cv_tokens]

    score = 0
    if job_keywords:
        score = max(35, min(99, round((len(matched) / len(job_keywords)) * 100)))

    strengths = [
        f"Strong alignment on {matched[0]}" if matched else "Relevant transferable experience",
        f"Evidence of {matched[1]} " if len(matched) > 1 else "Good communication and execution patterns",
    ]
    if not matched:
        strengths = ["Transferable experience across related work", "Clear potential for role adaptation"]

    summary = (
        f"This application aligns well with the role, with {len(matched)} of the key requirements currently reflected in the CV. "
        f"The strongest signals are in {', '.join(matched[:3]) if matched else 'core operational execution'} "
        f"and the remaining gaps are centered on {', '.join(missing[:3]) if missing else 'tailoring the message to the employer'} ."
    )

    return {
        "match_score": score,
        "strengths": strengths,
        "gaps": missing[:4],
        "summary": summary,
        "matched_keywords": matched,
        "job_keywords": job_keywords,
    }


def generate_cover_letter(company, role, job_description, cv_text, strengths=None):
    skills = extract_job_keywords(job_description)
    highlights = strengths or skills[:3]
    highlight_text = ", ".join(highlights) if highlights else "problem-solving, stakeholder engagement, and delivery"

    return (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to express my enthusiasm for the {role} opportunity at {company}. "
        f"I am excited by the chance to contribute my experience in {highlight_text} to a team focused on delivering meaningful results.\n\n"
        f"In my previous work, I have built a strong track record of translating goals into practical outcomes, working effectively across teams, and creating deliverables that support both customer value and business priorities. "
        f"I understand the importance of combining clear communication, thoughtful execution, and continuous improvement, and I believe these strengths align closely with the needs of this role.\n\n"
        f"I would welcome the opportunity to bring my background, work ethic, and adaptability to {company}. "
        f"Thank you for considering my application. I would be pleased to discuss how my experience and skills can help the team achieve its goals.\n\n"
        f"Kind regards,\n"
        f"A candidate ready to contribute"
    )


def tailor_cv_to_job(job_description, cv_text):
    keywords = extract_job_keywords(job_description)
    highlight_text = ", ".join(keywords[:5]) if keywords else "stakeholder management, analytics, strategy, and delivery"
    summary = (
        "Professional Summary:\n"
        f"Results-driven professional with experience in {highlight_text}. Brings a strong track record of stakeholder collaboration, operational delivery, and measurable business impact. Skilled at aligning team priorities with strategic objectives and translating requirements into clear, effective execution.\n\n"
        "Core Skills:\n"
        f"{highlight_text}\n\n"
        "Relevant Experience:\n"
    )

    if cv_text.strip():
        return summary + cv_text.strip()
    return summary + "Experienced professional with a proven ability to contribute to business goals, support cross-functional teams, and deliver measurable outcomes."


def build_document_pdf(document_title, document_text, company, role):
    buffer = BytesIO()
    story = []
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.leading = 22
    heading_style = styles["Heading2"]

    story.append(Paragraph(f"{company} - {role}", title_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph(document_title, heading_style))
    story.append(Spacer(1, 12))

    for block in document_text.strip().split("\n\n"):
        formatted_block = block.replace("\n", "<br />")
        story.append(Paragraph(formatted_block, styles["BodyText"]))
        story.append(Spacer(1, 12))

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=52,
        leftMargin=52,
        topMargin=52,
        bottomMargin=52,
    )
    document.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/features")
def features():
    return render_template("features.html")


@app.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@app.route("/application")
def application():
    return render_template("application.html")


@app.route("/dashboard")
def dashboard():
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY id DESC LIMIT 5"
        ).fetchall()
    return render_template("dashboard.html", applications=rows)


@app.route("/submit", methods=["POST"])
def submit_application():
    company = request.form.get("company", "Your Company").strip() or "Your Company"
    role = request.form.get("role", "Role").strip() or "Role"
    job_description = request.form.get("job_description", "").strip()
    cv_text = request.form.get("cv_text", "").strip()
    cover_letter_text = request.form.get("cover_letter_text", "").strip()

    uploaded_job = request.files.get("job_file")
    uploaded_cv = request.files.get("cv_file")
    uploaded_cover = request.files.get("cover_letter_file")

    try:
        job_description = job_description or extract_file_text(uploaded_job)
        cv_text = cv_text or extract_file_text(uploaded_cv)
        cover_letter_text = cover_letter_text or extract_file_text(uploaded_cover)
    except OCREngineUnavailable as error:
        flash(str(error), "error")
        return redirect(url_for("application"))

    if not job_description or not cv_text:
        if not job_description:
            flash(
                "We couldn't read the job description. Upload a text-based PDF or paste the text; "
                "if it is scanned, check that OCR is installed or paste the text.",
                "error",
            )
        if not cv_text:
            flash(
                "We couldn't read your CV. Upload a text-based PDF or paste the text; "
                "if it is scanned, check that OCR is installed or paste the text.",
                "error",
            )
        return redirect(url_for("application"))

    analysis = analyze_application(job_description, cv_text)
    if not cover_letter_text:
        cover_letter_text = generate_cover_letter(
            company,
            role,
            job_description,
            cv_text,
            analysis["matched_keywords"] or analysis["job_keywords"],
        )

    tailored_cv = tailor_cv_to_job(job_description, cv_text)

    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO applications (company, role, job_description, cv_text, tailored_cv, cover_letter, match_score, summary, strengths, gaps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company,
                role,
                job_description,
                cv_text,
                tailored_cv,
                cover_letter_text,
                analysis["match_score"],
                analysis["summary"],
                "; ".join(analysis["strengths"]),
                "; ".join(analysis["gaps"]),
            ),
        )
        app_id = cursor.lastrowid
        conn.commit()

    return redirect(url_for("result", application_id=app_id))


@app.route("/result/<int:application_id>")
def result(application_id):
    with get_db_connection() as conn:
        application = conn.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    if application is None:
        return redirect(url_for("index"))

    strengths = [item.strip() for item in application["strengths"].split("; ") if item.strip()]
    gaps = [item.strip() for item in application["gaps"].split("; ") if item.strip()]

    return render_template(
        "result.html",
        application=application,
        strengths=strengths,
        gaps=gaps,
    )


@app.route("/save-documents/<int:application_id>", methods=["POST"])
def save_documents(application_id):
    with get_db_connection() as conn:
        application = conn.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        if application is None:
            return redirect(url_for("index"))

        tailored_cv = request.form.get("tailored_cv")
        cover_letter = request.form.get("cover_letter")

        if tailored_cv is not None:
            conn.execute(
                "UPDATE applications SET tailored_cv = ? WHERE id = ?",
                (tailored_cv, application_id),
            )
        if cover_letter is not None:
            conn.execute(
                "UPDATE applications SET cover_letter = ? WHERE id = ?",
                (cover_letter, application_id),
            )
        conn.commit()

    return redirect(url_for("result", application_id=application_id))


@app.route("/download/<int:application_id>", methods=["GET", "POST"])
def download_cover_letter(application_id):
    with get_db_connection() as conn:
        application = conn.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    if application is None:
        return redirect(url_for("index"))

    cover_letter = request.form.get("cover_letter") if request.method == "POST" else application["cover_letter"]
    safe_company = re.sub(r"[^a-zA-Z0-9]+", "-", application["company"]).strip("-") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "-", application["role"]).strip("-") or "role"
    pdf_bytes = build_document_pdf("Cover Letter", cover_letter, application["company"], application["role"])

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{safe_company}-{safe_role}-cover-letter.pdf",
    )


@app.route("/download-cv/<int:application_id>", methods=["GET", "POST"])
def download_cv(application_id):
    with get_db_connection() as conn:
        application = conn.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()

    if application is None:
        return redirect(url_for("index"))

    tailored_cv = request.form.get("tailored_cv") if request.method == "POST" else application["tailored_cv"]
    safe_company = re.sub(r"[^a-zA-Z0-9]+", "-", application["company"]).strip("-") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "-", application["role"]).strip("-") or "role"
    pdf_bytes = build_document_pdf("Tailored CV", tailored_cv, application["company"], application["role"])

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{safe_company}-{safe_role}-tailored-cv.pdf",
    )


init_db()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
