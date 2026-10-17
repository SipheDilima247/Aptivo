import os
import re
import sqlite3
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from datetime import timedelta
from uuid import uuid4

from docx import Document
from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from werkzeug.utils import secure_filename

from ocr_engine import OCREngineUnavailable, ocr_pdf_pages

app = Flask(__name__)


def get_secret_key():
    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key
    if os.environ.get("DATABASE_URL"):
        raise RuntimeError("Set SECRET_KEY when DATABASE_URL is configured.")
    return "aptivo-local-development-only"


app.config["SECRET_KEY"] = get_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def get_anonymous_owner_id():
    owner_id = session.get("anonymous_owner_id")
    if owner_id is None:
        owner_id = str(uuid4())
        session["anonymous_owner_id"] = owner_id
    session.permanent = True
    return owner_id


def get_db_connection():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return psycopg.connect(database_url, row_factory=dict_row, connect_timeout=10)

    conn = sqlite3.connect("applications.db")
    conn.row_factory = sqlite3.Row
    return conn


def execute_query(conn, statement, parameters=()):
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(statement, parameters)
    return conn.execute(statement.replace("?", "%s"), parameters)


def init_db():
    with get_db_connection() as conn:
        id_column = (
            "INTEGER PRIMARY KEY AUTOINCREMENT"
            if isinstance(conn, sqlite3.Connection)
            else "BIGSERIAL PRIMARY KEY"
        )
        execute_query(
            conn,
            f"""
            CREATE TABLE IF NOT EXISTS applications (
                id {id_column},
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
                owner_id TEXT,
                learning_consent BOOLEAN NOT NULL DEFAULT FALSE,
                learning_recorded BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )

        if isinstance(conn, sqlite3.Connection):
            columns = [row[1] for row in conn.execute("PRAGMA table_info(applications)").fetchall()]
            migrations = {
                "tailored_cv": "TEXT",
                "owner_id": "TEXT",
                "learning_consent": "BOOLEAN NOT NULL DEFAULT FALSE",
                "learning_recorded": "BOOLEAN NOT NULL DEFAULT FALSE",
            }
            for column, definition in migrations.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE applications ADD COLUMN {column} {definition}")
        else:
            execute_query(
                conn,
                "ALTER TABLE applications ADD COLUMN IF NOT EXISTS tailored_cv TEXT",
            )
            execute_query(conn, "ALTER TABLE applications ADD COLUMN IF NOT EXISTS owner_id TEXT")
            execute_query(
                conn,
                "ALTER TABLE applications ADD COLUMN IF NOT EXISTS learning_consent BOOLEAN NOT NULL DEFAULT FALSE",
            )
            execute_query(
                conn,
                "ALTER TABLE applications ADD COLUMN IF NOT EXISTS learning_recorded BOOLEAN NOT NULL DEFAULT FALSE",
            )

        execute_query(
            conn,
            """
            CREATE TABLE IF NOT EXISTS cv_style_feedback (
                feature TEXT PRIMARY KEY,
                observations BIGINT NOT NULL DEFAULT 0
            )
            """,
        )

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
    return [token.rstrip(".") for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+.#/-]{2,}", text.lower())]


def normalize_skills(text):
    words = [word for word in tokenize(text) if len(word) > 2]
    stop_words = {
        "the", "and", "with", "your", "into", "this", "that", "from", "will",
        "have", "been", "they", "them", "their", "about", "over", "under", "role",
        "job", "company", "candidate", "position", "experience", "applications",
        "strong", "skills", "team", "work", "working", "using", "across", "through",
        "ensure", "build", "support", "deliver", "develop", "create", "including",
        "using", "business", "customer", "products", "project", "projects", "for",
        "looking", "seeking", "required", "requirements", "preferred", "responsibilities"
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


def get_cv_style_preferences(min_observations=5):
    with get_db_connection() as conn:
        rows = execute_query(
            conn,
            "SELECT feature, observations FROM cv_style_feedback",
        ).fetchall()
    counts = {row["feature"]: row["observations"] for row in rows}
    total_observations = counts.get("cv_observations", 0)
    if total_observations < min_observations:
        return set()
    return {
        feature
        for feature in {"action_led_opening", "bullet_format", "first_person_voice", "quantified_results"}
        if counts.get(feature, 0) >= min_observations
        and counts[feature] / total_observations >= 0.6
    }


def select_relevant_cv_evidence(job_description, cv_text, limit=3, style_preferences=None):
    job_keywords = set(extract_job_keywords(job_description))
    if not job_keywords or not cv_text.strip():
        return []

    style_preferences = style_preferences or set()
    ranked_segments = []
    segments = re.split(r"(?<=[.!?])\s+|\n+", cv_text.strip())
    for position, raw_segment in enumerate(segments):
        cleaned_segment = raw_segment.strip().lstrip("-*• ").strip()
        if len(cleaned_segment) < 8:
            continue
        matched_keywords = job_keywords.intersection(normalize_skills(cleaned_segment))
        if matched_keywords:
            style_score = 0
            is_bullet = bool(re.match(r"^\s*[-*•]\s+", raw_segment))
            uses_first_person = bool(re.search(r"\b(?:I|my|me|we|our)\b", cleaned_segment, re.IGNORECASE))
            opening = re.match(r"^(?:[-*•]\s*)?([A-Za-z]+)\b", cleaned_segment)
            if "bullet_format" in style_preferences and is_bullet:
                style_score += 1
            if "first_person_voice" in style_preferences and uses_first_person:
                style_score += 1
            if (
                "action_led_opening" in style_preferences
                and opening
                and opening.group(1).lower() in {
                    "analyzed", "automated", "built", "created", "delivered", "designed",
                    "developed", "improved", "increased", "launched", "led", "managed",
                    "reduced", "implemented", "organized", "optimized", "coordinated",
                }
            ):
                style_score += 1
            if (
                "quantified_results" in style_preferences
                and re.search(r"\b\d+(?:[,.]\d+)*(?:%|\+)?\b", cleaned_segment)
            ):
                style_score += 1
            ranked_segments.append((len(matched_keywords), style_score, position, cleaned_segment))

    ranked_segments.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [segment for _, _, _, segment in ranked_segments[:limit]]


def extract_cv_style_signals(cv_text):
    lines = [line.strip() for line in cv_text.splitlines() if line.strip()]
    if not lines:
        return set()

    signals = set()
    if any(re.match(r"^[-*•]\s+", line) for line in lines):
        signals.add("bullet_format")
    if re.search(r"\b(?:I|my|me|we|our)\b", cv_text, re.IGNORECASE):
        signals.add("first_person_voice")
    if re.search(r"\b\d+(?:[,.]\d+)*(?:%|\+)?\b", cv_text):
        signals.add("quantified_results")

    action_verbs = {
        "analyzed", "automated", "built", "created", "delivered", "designed",
        "developed", "improved", "increased", "launched", "led", "managed",
        "reduced", "implemented", "organized", "optimized", "coordinated",
    }
    for line in lines:
        match = re.match(r"^(?:[-*•]\s*)?([A-Za-z]+)\b", line)
        if match and match.group(1).lower() in action_verbs:
            signals.add("action_led_opening")
            break

    return signals


def extract_user_edited_cv_text(previous_cv, updated_cv):
    previous_lines = previous_cv.splitlines()
    updated_lines = updated_cv.splitlines()
    changes = SequenceMatcher(None, previous_lines, updated_lines, autojunk=False)
    edited_lines = []
    for operation, _, _, updated_start, updated_end in changes.get_opcodes():
        if operation in {"insert", "replace"}:
            edited_lines.extend(updated_lines[updated_start:updated_end])
    return "\n".join(edited_lines)


def record_cv_style_feedback(conn, cv_text):
    style_signals = extract_cv_style_signals(cv_text)
    execute_query(
        conn,
        """
        INSERT INTO cv_style_feedback (feature, observations)
        VALUES (?, 1)
        ON CONFLICT(feature) DO UPDATE
        SET observations = cv_style_feedback.observations + 1
        """,
        ("cv_observations",),
    )
    for feature in style_signals:
        execute_query(
            conn,
            """
            INSERT INTO cv_style_feedback (feature, observations)
            VALUES (?, 1)
            ON CONFLICT(feature) DO UPDATE
            SET observations = cv_style_feedback.observations + 1
            """,
            (feature,),
        )
    return style_signals


def generate_cover_letter(company, role, job_description, cv_text, strengths=None, applicant_name=""):
    style_preferences = get_cv_style_preferences()
    cv_keywords = set(normalize_skills(cv_text))
    requested_keywords = strengths or extract_job_keywords(job_description)
    supported_keywords = [keyword for keyword in requested_keywords if keyword in cv_keywords]
    relevant_evidence = select_relevant_cv_evidence(
        job_description,
        cv_text,
        style_preferences=style_preferences,
    )

    if relevant_evidence:
        evidence_paragraph = (
            "Relevant details already present in my CV include:\n"
            + "\n".join(f"- {evidence}" for evidence in relevant_evidence)
        )
    else:
        evidence_paragraph = (
            "The supplied CV does not show a specific example that directly matches this posting. "
            "I have kept this draft general rather than claiming experience that is not in the CV; "
            "add a relevant example before sending."
        )

    if supported_keywords:
        focus_paragraph = (
            "The posting emphasizes "
            f"{', '.join(supported_keywords[:5])}, which also appear in my CV."
        )
    else:
        focus_paragraph = f"I am interested in the {role} opportunity at {company}."

    return (
        "Dear Hiring Manager,\n\n"
        f"I am applying for the {role} opportunity at {company}. {focus_paragraph}\n\n"
        f"{evidence_paragraph}\n\n"
        f"I would welcome the opportunity to discuss how these examples relate to the needs of the role. "
        f"Thank you for considering my application.\n\n"
        f"Kind regards,\n\n"
        f"{applicant_name.strip() or 'Your Name'}"
    )


def tailor_cv_to_job(job_description, cv_text):
    style_preferences = get_cv_style_preferences()
    source_cv = cv_text.strip()
    relevant_evidence = select_relevant_cv_evidence(
        job_description,
        source_cv,
        limit=5,
        style_preferences=style_preferences,
    )

    if relevant_evidence:
        relevance_section = (
            "Relevant details selected from your CV:\n"
            + "\n".join(f"- {evidence}" for evidence in relevant_evidence)
        )
    else:
        relevance_section = (
            "No direct examples matching this job description were found in the CV. "
            "Review and tailor the original wording manually."
        )

    if not source_cv:
        return relevance_section
    return f"{relevance_section}\n\nOriginal CV (wording preserved):\n{source_cv}"


def build_document_pdf(document_title, document_text, company, role, include_document_title=True):
    buffer = BytesIO()
    story = []
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    title_style.leading = 22
    heading_style = styles["Heading2"]

    story.append(Paragraph(f"{company} - {role}", title_style))
    story.append(Spacer(1, 10))
    if include_document_title:
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
    get_anonymous_owner_id()
    return render_template("application.html")


@app.route("/dashboard")
def dashboard():
    owner_id = get_anonymous_owner_id()
    with get_db_connection() as conn:
        rows = execute_query(
            conn,
            "SELECT * FROM applications WHERE owner_id = ? ORDER BY id DESC LIMIT 5",
            (owner_id,),
        ).fetchall()
    return render_template("dashboard.html", applications=rows)


@app.route("/submit", methods=["POST"])
def submit_application():
    owner_id = get_anonymous_owner_id()
    applicant_name = request.form.get("applicant_name", "").strip()
    company = request.form.get("company", "Your Company").strip() or "Your Company"
    role = request.form.get("role", "Role").strip() or "Role"
    job_description = request.form.get("job_description", "").strip()
    cv_text = request.form.get("cv_text", "").strip()
    cover_letter_text = request.form.get("cover_letter_text", "").strip()
    learning_consent = request.form.get("learning_consent") == "yes"

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
            applicant_name=applicant_name,
        )

    tailored_cv = tailor_cv_to_job(job_description, cv_text)

    with get_db_connection() as conn:
        insert_statement = """
            INSERT INTO applications (company, role, job_description, cv_text, tailored_cv, cover_letter, match_score, summary, strengths, gaps, owner_id, learning_consent, learning_recorded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if not isinstance(conn, sqlite3.Connection):
            insert_statement += " RETURNING id"
        cursor = execute_query(
            conn,
            insert_statement,
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
                owner_id,
                learning_consent,
                False,
            ),
        )
        app_id = (
            cursor.lastrowid
            if isinstance(conn, sqlite3.Connection)
            else cursor.fetchone()["id"]
        )
        conn.commit()

    return redirect(url_for("result", application_id=app_id))


@app.route("/result/<int:application_id>")
def result(application_id):
    owner_id = get_anonymous_owner_id()
    with get_db_connection() as conn:
        application = execute_query(
            conn,
            "SELECT * FROM applications WHERE id = ? AND owner_id = ?",
            (application_id, owner_id),
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
    owner_id = get_anonymous_owner_id()
    with get_db_connection() as conn:
        application = execute_query(
            conn,
            "SELECT * FROM applications WHERE id = ? AND owner_id = ?",
            (application_id, owner_id),
        ).fetchone()
        if application is None:
            return redirect(url_for("index"))

        tailored_cv = request.form.get("tailored_cv")
        cover_letter = request.form.get("cover_letter")

        if tailored_cv is not None:
            execute_query(
                conn,
                "UPDATE applications SET tailored_cv = ? WHERE id = ? AND owner_id = ?",
                (tailored_cv, application_id, owner_id),
            )
        if cover_letter is not None:
            execute_query(
                conn,
                "UPDATE applications SET cover_letter = ? WHERE id = ? AND owner_id = ?",
                (cover_letter, application_id, owner_id),
            )
        if (
            tailored_cv is not None
            and application["learning_consent"]
            and not application["learning_recorded"]
            and tailored_cv != application["tailored_cv"]
        ):
            user_edited_cv = extract_user_edited_cv_text(application["tailored_cv"], tailored_cv)
            if user_edited_cv.strip():
                record_cv_style_feedback(conn, user_edited_cv)
                execute_query(
                    conn,
                    "UPDATE applications SET learning_recorded = ? WHERE id = ? AND owner_id = ?",
                    (True, application_id, owner_id),
                )
        conn.commit()

    return redirect(url_for("result", application_id=application_id))


@app.route("/download/<int:application_id>", methods=["GET", "POST"])
def download_cover_letter(application_id):
    owner_id = get_anonymous_owner_id()
    with get_db_connection() as conn:
        application = execute_query(
            conn,
            "SELECT * FROM applications WHERE id = ? AND owner_id = ?",
            (application_id, owner_id),
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
    owner_id = get_anonymous_owner_id()
    with get_db_connection() as conn:
        application = execute_query(
            conn,
            "SELECT * FROM applications WHERE id = ? AND owner_id = ?",
            (application_id, owner_id),
        ).fetchone()

    if application is None:
        return redirect(url_for("index"))

    tailored_cv = request.form.get("tailored_cv") if request.method == "POST" else application["tailored_cv"]
    safe_company = re.sub(r"[^a-zA-Z0-9]+", "-", application["company"]).strip("-") or "company"
    safe_role = re.sub(r"[^a-zA-Z0-9]+", "-", application["role"]).strip("-") or "role"
    pdf_bytes = build_document_pdf(
        "Tailored CV",
        tailored_cv,
        application["company"],
        application["role"],
        include_document_title=False,
    )

    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{safe_company}-{safe_role}-tailored-cv.pdf",
    )


init_db()


@app.route("/healthz")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
