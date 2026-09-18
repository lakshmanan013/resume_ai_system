"""
Resume parsing and AI/ML analysis engine.

Features:
- Validates MIME type and magic bytes (PDF / DOCX) up to 10MB.
- Detects scanned / image-only PDFs gracefully with human-friendly guidance.
- Uses spaCy for Named Entity Recognition (PERSON, ORG, DATE) and sentence segmentation.
- Custom EntityRuler for skill phrase detection beyond static keywords.
- Calculates total work experience from chronological date ranges (merging overlapping periods).
- Normalizes extracted skills to canonical taxonomy forms (e.g., 'JS' -> 'JavaScript').
- Provides Target Role Gap Analysis against industry job profiles.
"""

import os
import re
import datetime
from typing import Dict, List, Optional, Tuple, Any
import docx
import pdfplumber

import spacy
from spacy.pipeline import EntityRuler

from skills_data import (
    ALL_SKILLS,
    DEGREE_KEYWORDS,
    DEGREE_FIELDS,
    ROLE_PROFILES,
    normalize_skill,
)

# -----------------------------------------------------------------------------
# Regex matchers for contacts and dates
# -----------------------------------------------------------------------------
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3}[-.\s]?\d{3,4}")
YEARS_EXP_RE = re.compile(r"(\d+(?:\.\d+)?)\+?\s*(?:years|yrs)\b", re.IGNORECASE)

# Date interval matcher: e.g. "2018 - 2022", "Jan 2020 - Present", "04/2019 to 09/2021"
MONTHS = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_RANGE_RE = re.compile(
    rf"(?:({MONTHS}\.?\s+)?(\d{{4}})|(\d{{1,2}}/\d{{4}}))\s*(?:-|–|—|to)\s*(?:({MONTHS}\.?\s+)?(\d{{4}})|(\d{{1,2}}/\d{{4}})|(present|current|now))",
    re.IGNORECASE,
)

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}

HEADER_BLACKLIST = {
    "resume", "curriculum vitae", "cv", "profile", "summary",
    "contact", "contact info", "contact information", "about me",
    "personal details", "experience", "work experience", "education",
    "skills", "technical skills", "projects", "certifications",
    "objective", "career objective", "professional summary"
}

SECTION_HEADERS = {
    "experience": [
        "work experience", "professional experience", "employment history",
        "work history", "experience", "internships", "career history"
    ],
    "education": [
        "education", "academic background", "academic qualifications",
        "academic history", "degrees", "educational background"
    ],
    "skills": [
        "skills", "technical skills", "core competencies", "skills & tools",
        "technologies", "skill set", "technical proficiencies"
    ],
    "projects": [
        "projects", "academic projects", "key projects", "personal projects"
    ]
}


class ScannedResumeError(ValueError):
    """Raised when an uploaded document has near-zero extractable text (e.g. image-only PDF)."""
    pass


# -----------------------------------------------------------------------------
# spaCy Singleton Loader & Custom EntityRuler
# -----------------------------------------------------------------------------
_nlp_model = None

def get_spacy_nlp():
    """Lazily load spaCy model and attach custom skill EntityRuler."""
    global _nlp_model
    if _nlp_model is not None:
        return _nlp_model

    try:
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        # Fallback to English blank pipeline if model pack is not available
        nlp = spacy.blank("en")

    if "sentencizer" not in nlp.pipe_names and "parser" not in nlp.pipe_names:
        nlp.add_pipe("sentencizer")

    if "entity_ruler" not in nlp.pipe_names:
        try:
            ruler = nlp.add_pipe("entity_ruler", before="ner" if "ner" in nlp.pipe_names else None)
            patterns = [{"label": "SKILL", "pattern": skill} for skill in ALL_SKILLS]
            if hasattr(ruler, "add_patterns"):
                getattr(ruler, "add_patterns")(patterns)
        except Exception:
            pass

    _nlp_model = nlp
    return _nlp_model


# -----------------------------------------------------------------------------
# MIME & File Validation
# -----------------------------------------------------------------------------
def validate_resume_file(filename: str, allowed_extensions: set, filepath: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Validates file extension AND file signature / magic bytes.
    Accepts PDF and DOCX only, verifying true file structure.
    """
    if not filename or "." not in filename:
        return False, "File name must include a valid extension (.pdf or .docx)."

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in allowed_extensions:
        return False, f"Unsupported file type '.{ext}'. Only PDF and DOCX files are allowed."

    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, "rb") as f:
                header = f.read(1024)

            if ext == "pdf":
                if not header.startswith(b"%PDF-"):
                    return False, "Invalid PDF file: Missing standard %PDF file header."
            elif ext == "docx":
                # DOCX is a zip archive starting with PK\x03\x04
                if not header.startswith(b"PK\x03\x04"):
                    return False, "Invalid DOCX file: File is corrupted or not a valid Word document."
        except Exception as e:
            return False, f"Error validating file header: {e}"

    return True, None


# -----------------------------------------------------------------------------
# Text Extraction
# -----------------------------------------------------------------------------
def extract_text(filepath: str) -> str:
    """
    Extracts raw text from PDF or DOCX.
    Detects scanned or image-only documents and raises ScannedResumeError.
    """
    ext = filepath.rsplit(".", 1)[-1].lower()
    text = ""

    if ext == "pdf":
        with pdfplumber.open(filepath) as pdf:
            total_pages = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

            # Detect near-zero text in PDF (image-only or scanned)
            cleaned = text.strip()
            if len(cleaned) < 50:
                raise ScannedResumeError(
                    f"Uploaded PDF contains near-zero readable text ({len(cleaned)} characters found across {total_pages} page(s)). "
                    "It appears to be a scanned image or photograph. Please upload a searchable PDF with selectable text or a DOCX document."
                )

    elif ext == "docx":
        doc = docx.Document(filepath)
        text = "\n".join(p.text for p in doc.paragraphs)
        for table in doc.tables:
            for row in table.rows:
                text += "\n" + " ".join(cell.text for cell in row.cells)

        if len(text.strip()) < 30:
            raise ScannedResumeError(
                "Uploaded DOCX document contains insufficient readable text. Please check the document content."
            )
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    return text.strip()


# -----------------------------------------------------------------------------
# Sentence Segmentation & Section Splitting
# -----------------------------------------------------------------------------
def segment_resume_sections(text: str) -> Dict[str, str]:
    """
    Isolates key sections (experience, education, skills, projects, summary)
    using header heuristics and sentence / line segmentation.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sections: Dict[str, List[str]] = {
        "summary": [],
        "experience": [],
        "education": [],
        "skills": [],
        "projects": [],
        "general": []
    }

    current_section = "general"

    for line in lines:
        lower_line = line.lower().strip(":# -_")
        matched_header = None
        for sec_name, headers in SECTION_HEADERS.items():
            if lower_line in headers or any(lower_line == h for h in headers):
                matched_header = sec_name
                break

        if matched_header:
            current_section = matched_header
        else:
            sections[current_section].append(line)

    return {k: "\n".join(v) for k, v in sections.items()}


# -----------------------------------------------------------------------------
# Structured Field Extractors (Candidate Name, Contacts)
# -----------------------------------------------------------------------------
def extract_candidate_name(text: str, nlp: Optional[Any] = None) -> str:
    """Extract candidate name using spaCy NER with line-based heuristic fallbacks."""
    if nlp is None:
        nlp = get_spacy_nlp()

    first_lines = "\n".join(text.splitlines()[:15])
    doc = nlp(first_lines)

    # First look for PERSON entities in the top lines
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            cleaned = ent.text.strip()
            # Verify it's a realistic name
            if 2 <= len(cleaned.split()) <= 4 and not any(ch.isdigit() for ch in cleaned):
                if cleaned.lower() not in HEADER_BLACKLIST:
                    return cleaned.title()

    # Fallback to structural heuristic
    for line in text.splitlines()[:12]:
        cleaned = line.strip()
        if not cleaned or len(cleaned) > 50:
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

    return "Candidate"


def extract_email(text: str) -> Optional[str]:
    m = EMAIL_RE.search(text)
    return m.group(0).lower() if m else None


def extract_phone(text: str) -> Optional[str]:
    m = PHONE_RE.search(text)
    return m.group(0).strip() if m else None


# -----------------------------------------------------------------------------
# Work Experience & Date Range Parser
# -----------------------------------------------------------------------------
def _parse_year_month(month_str: Optional[str], year_str: Optional[str], slash_date: Optional[str]) -> Optional[float]:
    """Converts a month/year representation into a fractional decimal year (e.g. 2021.5)."""
    if slash_date:
        parts = slash_date.split("/")
        if len(parts) == 2:
            try:
                m = int(parts[0])
                y = int(parts[1])
                return y + (m - 1) / 12.0
            except ValueError:
                pass
    if year_str:
        try:
            y = int(year_str)
            m = 1
            if month_str:
                m_clean = month_str.strip()[:3].lower()
                m = MONTH_MAP.get(m_clean, 1)
            return y + (m - 1) / 12.0
        except ValueError:
            pass
    return None


def calculate_experience_from_date_ranges(experience_text: str, full_text: str) -> float:
    """
    Parses start and end date ranges from work history, merges overlapping spans,
    and accurately computes total aggregate experience in years.
    """
    target_text = f"{experience_text}\n{full_text}".strip()
    intervals: List[Tuple[float, float]] = []

    current_year = datetime.datetime.now().year + (datetime.datetime.now().month - 1) / 12.0

    for match in DATE_RANGE_RE.finditer(target_text):
        m1, y1, s1, m2, y2, s2, is_present = match.groups()
        start = _parse_year_month(m1, y1, s1)

        if is_present:
            end = current_year
        else:
            end = _parse_year_month(m2, y2, s2)

        if start and end and 1980 <= start <= current_year and start <= end <= (current_year + 1):
            intervals.append((start, end))

    if intervals:
        # Sort intervals by start date and merge overlapping intervals
        intervals.sort(key=lambda x: x[0])
        merged = [intervals[0]]
        for curr in intervals[1:]:
            prev_start, prev_end = merged[-1]
            if curr[0] <= prev_end:  # Overlapping or contiguous
                merged[-1] = (prev_start, max(prev_end, curr[1]))
            else:
                merged.append(curr)

        total_years = sum(end - start for start, end in merged)
        return round(max(0.5, total_years), 1)

    # Fallback to explicit mentions like "5+ years of experience"
    exp_matches = YEARS_EXP_RE.findall(full_text)
    if exp_matches:
        try:
            return round(max(float(m) for m in exp_matches), 1)
        except ValueError:
            pass

    return 0.0


# -----------------------------------------------------------------------------
# Work History & Organizations Extraction
# -----------------------------------------------------------------------------
def extract_work_history(experience_text: str, nlp: Any) -> List[Dict[str, Any]]:
    """Extracts organizations (employers), roles, and dates from work history."""
    if not experience_text.strip():
        return []

    entries = []
    doc = nlp(experience_text)

    # Find organizations
    orgs = [ent.text.strip() for ent in doc.ents if ent.label_ == "ORG" and len(ent.text.strip()) > 2]
    unique_orgs = []
    for org in orgs:
        if org not in unique_orgs and org.lower() not in HEADER_BLACKLIST:
            unique_orgs.append(org)

    lines = [l.strip() for l in experience_text.splitlines() if len(l.strip()) > 5]
    for i, line in enumerate(lines[:8]):
        matched_org = next((o for o in unique_orgs if o.lower() in line.lower()), None)
        entries.append({
            "title_or_line": line,
            "organization": matched_org or "Company / Client",
            "index": i + 1
        })

    return entries[:5]


# -----------------------------------------------------------------------------
# Education Details & Field of Study
# -----------------------------------------------------------------------------
def extract_education_details(education_text: str, full_text: str) -> Dict[str, Any]:
    """Identifies degree level, qualifications, and academic field of study."""
    search_text = education_text if len(education_text) > 50 else full_text
    found_degrees = []
    detected_field = None
    level = "Bachelor's Degree"

    lines = search_text.splitlines()
    for line in lines:
        cleaned = line.strip()
        lower_line = cleaned.lower()
        for kw in DEGREE_KEYWORDS:
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(kw) + r"(?![a-zA-Z0-9])"
            if re.search(pattern, lower_line):
                if cleaned not in found_degrees:
                    found_degrees.append(cleaned)
                if any(phd in lower_line for phd in ["ph.d", "phd", "doctorate"]):
                    level = "Doctorate (Ph.D)"
                elif any(m in lower_line for m in ["master", "m.sc", "msc", "m.tech", "mba"]):
                    level = "Master's Degree"
                elif any(b in lower_line for b in ["bachelor", "b.tech", "b.e.", "b.sc", "bsc"]):
                    level = "Bachelor's Degree"
                break

    # Identify field of study
    for field in DEGREE_FIELDS:
        if re.search(r"\b" + re.escape(field.lower()) + r"\b", search_text.lower()):
            detected_field = field
            break

    if not detected_field:
        detected_field = "Engineering / Science"

    return {
        "education_list": found_degrees[:5],
        "degree_level": level,
        "field_of_study": detected_field
    }


# -----------------------------------------------------------------------------
# Skill Extraction & Canonical Normalization
# -----------------------------------------------------------------------------
def extract_skills_nlp(text: str, nlp: Any) -> List[str]:
    """
    Extracts skills using spaCy NER/EntityRuler combined with boundary-checked taxonomy matching.
    Normalizes all found skills to canonical taxonomy forms (e.g. 'js' -> 'javascript').
    """
    doc = nlp(text[:15000])
    found_skills = set()

    # 1. Pull skills identified by spaCy EntityRuler / NER
    for ent in doc.ents:
        if ent.label_ in ("SKILL", "PRODUCT", "LANGUAGE"):
            normalized = normalize_skill(ent.text)
            if normalized in ALL_SKILLS:
                found_skills.add(normalized)

    # 2. Complete coverage check against taxonomy with boundary verification
    lower_text = " " + text.lower().replace("\n", " ") + " "
    for skill in ALL_SKILLS:
        pattern = r"(?<![a-zA-Z0-9+#.])" + re.escape(skill) + r"(?![a-zA-Z0-9+#])"
        if re.search(pattern, lower_text):
            found_skills.add(normalize_skill(skill))

    return sorted(list(found_skills))


# -----------------------------------------------------------------------------
# Target Role Gap Analysis
# -----------------------------------------------------------------------------
def compute_gap_analysis(candidate_skills: List[str], target_role: str = "Full Stack Engineer") -> Dict[str, Any]:
    """
    Computes a skills gap analysis against a designated target role profile.
    Surfaces present required skills, missing gaps, coverage %, and actionable recommendations.
    """
    profile = ROLE_PROFILES.get(target_role, ROLE_PROFILES["Full Stack Engineer"])
    req = set(profile["required_skills"])
    rec = set(profile["recommended_skills"])

    cand = set(candidate_skills)

    present_required = sorted(list(cand & req))
    missing_required = sorted(list(req - cand))
    present_recommended = sorted(list(cand & rec))
    missing_recommended = sorted(list(rec - cand))

    coverage_pct = round((len(present_required) / len(req) * 100.0) if req else 100.0, 1)

    recommendations = []
    if missing_required:
        recommendations.append(f"High Priority: Add core required skill(s) {', '.join(missing_required[:3])} to qualify for {target_role}.")
    if missing_recommended:
        recommendations.append(f"Competitive Advantage: Consider gaining exposure to {', '.join(missing_recommended[:2])}.")
    if not missing_required:
        recommendations.append(f"Outstanding! You possess all primary baseline requirements for {target_role}.")

    return {
        "target_role": target_role,
        "coverage_percentage": coverage_pct,
        "present_required": present_required,
        "missing_required": missing_required,
        "present_recommended": present_recommended,
        "missing_recommended": missing_recommended,
        "recommendations": recommendations,
        "min_experience_needed": profile.get("min_experience", 2)
    }


# -----------------------------------------------------------------------------
# Main Parsing Pipeline
# -----------------------------------------------------------------------------
def parse_resume(filepath: str, target_role: str = "Full Stack Engineer") -> Dict[str, Any]:
    """
    End-to-end resume ingestion and AI analysis pipeline.
    Produces comprehensive structured data for database persistence and job matching.
    """
    raw_text = extract_text(filepath)
    nlp = get_spacy_nlp()

    sections = segment_resume_sections(raw_text)
    candidate_name = extract_candidate_name(raw_text, nlp)
    email = extract_email(raw_text)
    phone = extract_phone(raw_text)

    skills = extract_skills_nlp(raw_text, nlp)
    experience_years = calculate_experience_from_date_ranges(sections["experience"], raw_text)
    education_data = extract_education_details(sections["education"], raw_text)
    work_history = extract_work_history(sections["experience"], nlp)

    gap_analysis = compute_gap_analysis(skills, target_role)

    # Named entities for audit inspection
    doc = nlp(raw_text[:5000])
    entities = [{"text": ent.text, "label": ent.label_} for ent in doc.ents if ent.label_ in ("PERSON", "ORG", "DATE", "GPE", "SKILL")][:25]

    structured_data = {
        "raw_text": raw_text,
        "name": candidate_name,
        "email": email,
        "phone": phone,
        "education": education_data["education_list"],
        "education_level": education_data["degree_level"],
        "field_of_study": education_data["field_of_study"],
        "work_history": work_history,
        "skills": skills,
        "experience_years": experience_years,
        "gap_analysis": gap_analysis,
        "entities": entities,
    }

    return structured_data


# Backwards compatibility aliases
def extract_education(text: str) -> List[str]:
    return extract_education_details(text, text)["education_list"]

guess_name = extract_candidate_name


# -----------------------------------------------------------------------------
# Top-level standalone skill and experience extractors (used by Adzuna pipeline)
# -----------------------------------------------------------------------------
def extract_skills(text: str) -> List[str]:
    """
    Extracts and normalizes canonical skills from unstructured job text or descriptions.
    Uses spaCy EntityRuler alongside comprehensive boundary-checked taxonomy matching.
    """
    if not text or not text.strip():
        return []
    nlp = get_spacy_nlp()
    return extract_skills_nlp(text, nlp)


def extract_experience_years(text: str) -> float:
    """
    Extracts minimum required experience years from free text using explicit 'X years' regex.
    Returns the minimum numeric experience requirement found or 0.0.
    """
    if not text or not text.strip():
        return 0.0
    matches = YEARS_EXP_RE.findall(text)
    if matches:
        try:
            return round(min(float(m) for m in matches), 1)
        except (ValueError, TypeError):
            pass
    return 0.0

