"""
File loader utilities.
Handles PDF (via pdfplumber) and DOCX (via python-docx) extraction.
Returns plain text for downstream LLM processing.
"""

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
        return "\n\n".join(pages)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes using python-docx."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error(f"DOCX extraction failed: {e}")
        return ""


def extract_text_from_file(file_bytes: bytes, filename: str) -> str:
    """
    Route to the correct extractor based on file extension.
    Returns empty string on failure (never raises — caller handles empty gracefully).
    """
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(file_bytes)
    elif ext in (".txt", ".md", ".csv"):
        try:
            return file_bytes.decode("utf-8", errors="replace")
        except Exception:
            return ""
    else:
        logger.warning(f"Unsupported file type: {ext}")
        return ""


def extract_text_from_json(data: dict) -> str:
    """
    Flatten a LinkedIn-exported JSON profile into readable text
    for the profile parser agent.
    """
    parts = []
    if name := data.get("name") or data.get("firstName", "") + " " + data.get("lastName", ""):
        parts.append(f"Name: {name.strip()}")
    if headline := data.get("headline"):
        parts.append(f"Headline: {headline}")
    if summary := data.get("summary"):
        parts.append(f"Summary: {summary}")

    # Work experience
    positions = data.get("positions", {})
    if isinstance(positions, dict):
        positions = positions.get("values", [])
    for pos in positions:
        title = pos.get("title", "")
        company = pos.get("company", {}).get("name", "") if isinstance(pos.get("company"), dict) else pos.get("company", "")
        parts.append(f"Work: {title} at {company}")

    # Education
    education = data.get("educations", {})
    if isinstance(education, dict):
        education = education.get("values", [])
    for edu in education:
        school = edu.get("schoolName", "")
        degree = edu.get("degree", "")
        field = edu.get("fieldOfStudy", "")
        parts.append(f"Education: {degree} {field} at {school}")

    # Skills
    skills = data.get("skills", {})
    if isinstance(skills, dict):
        skills = skills.get("values", [])
    skill_names = [s.get("skill", {}).get("name", "") if isinstance(s, dict) else str(s) for s in skills]
    if skill_names:
        parts.append(f"Skills: {', '.join(filter(None, skill_names))}")

    return "\n".join(parts)
