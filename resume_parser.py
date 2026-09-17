"""
Resume parsing engine.

Extracts raw text from PDF / DOCX resumes and pulls out structured
information (contact details, education, skills, years of experience)
using a mix of regex heuristics and keyword matching against the
skill taxonomy. This is the "AI analysis" layer described in the
project spec: a lightweight, explainable NLP pipeline rather than a
black-box model, which keeps it dependency-free and fast.
"""
import os
import re
import docx
import pdfplumber

from skills_data import ALL_SKILLS, DEGREE_KEYWORDS

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3}[-.\s]?\d{3,4}")
YEARS_EXP_RE = re.compile(r"(\d+(?:\.\d+)?)\+?\s*(?:years|yrs)\b", re.IGNORECASE)


def extract_text(filepath):
    """Extract raw text from a PDF or DOCX file."""
    ext = filepath.rsplit(".", 1)[-1].lower()
    text = ""
    if ext == "pdf":
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    elif ext == "docx":
        doc = docx.Document(filepath)
        text = "\n".join(p.text for p in doc.paragraphs)
        for table in doc.tables:
            for row in table.rows:
                text += "\n" + " ".join(cell.text for cell in row.cells)
    else:
        raise ValueError("Unsupported file type: " + ext)
    return text.strip()


HEADER_BLACKLIST = {
    "resume", "curriculum vitae", "cv", "profile", "summary",
    "contact", "contact info", "contact information", "about me",
    "personal details", "experience", "work experience", "education",
    "skills", "technical skills", "projects", "certifications",
    "objective", "career objective", "professional summary"
}


def guess_name(text):
    """Heuristic: the first non-empty line that looks like a name
    (short, no digits, no @, not a section header, title-case-ish) is usually the candidate's name."""
    for line in text.splitlines()[:12]:
        cleaned = line.strip()
        if not cleaned or len(cleaned) > 60:
            continue
        if cleaned.lower() in HEADER_BLACKLIST:
            continue
        if EMAIL_RE.search(cleaned) or PHONE_RE.search(cleaned):
            continue
        if any(ch.isdigit() for ch in cleaned):
            continue
        if any(token in cleaned.lower() for token in ["http:", "https:", "www.", "github.com", "linkedin.com"]):
            continue
        words = cleaned.split()
        if 1 <= len(words) <= 4:
            return cleaned.title()
    return "Unknown"


def extract_email(text):
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def extract_phone(text):
    m = PHONE_RE.search(text)
    return m.group(0).strip() if m else None


def extract_education(text):
    found = []
    lines = text.splitlines()
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        lower_line = line_clean.lower()
        for kw in DEGREE_KEYWORDS:
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(kw) + r"(?![a-zA-Z0-9])"
            if re.search(pattern, lower_line):
                if line_clean not in found:
                    found.append(line_clean)
                break
    return found[:5]


def extract_experience_years(text):
    """Find explicit 'X years of experience' mentions; fall back to None."""
    matches = YEARS_EXP_RE.findall(text)
    if matches:
        try:
            return max(float(m) for m in matches)
        except ValueError:
            return None
    return None


def extract_skills(text):
    """Match resume text against the skill taxonomy.
    Uses word-boundary matching so 'r' or 'c' don't false-positive
    on arbitrary substrings, and is case-insensitive."""
    lower = " " + text.lower().replace("\n", " ") + " "
    found = []
    for skill in ALL_SKILLS:
        pattern = r"(?<![a-zA-Z0-9+#.])" + re.escape(skill) + r"(?![a-zA-Z0-9+#])"
        if re.search(pattern, lower):
            found.append(skill)
    # De-duplicate while preserving a readable, alphabetical order
    return sorted(set(found))


def parse_resume(filepath):
    """Full pipeline: extract text, then derive structured fields."""
    text = extract_text(filepath)
    if not text:
        raise ValueError("Could not extract any text from this file. "
                          "It may be a scanned image or corrupted.")
    return {
        "raw_text": text,
        "name": guess_name(text),
        "email": extract_email(text),
        "phone": extract_phone(text),
        "education": extract_education(text),
        "skills": extract_skills(text),
        "experience_years": extract_experience_years(text),
    }


def validate_resume_file(filename, allowed_extensions):
    if "." not in filename:
        return False, "File has no extension."
    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in allowed_extensions:
        return False, f"Unsupported file type '.{ext}'. Only PDF and DOCX are allowed."
    return True, None
