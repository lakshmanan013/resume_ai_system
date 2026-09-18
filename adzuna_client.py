"""
Adzuna Jobs API Client & Ingestion Pipeline.

Features:
- Dedicated API client with custom AdzunaAPIError.
- Exponential backoff retry on timeouts and HTTP 5xx errors.
- In-memory response caching (15 min TTL) to respect free-tier rate limits (250 calls/day).
- HTML stripping and normalization into Resume AI 'jobs' table schema.
- Automatic skill & experience extraction using NLP pipeline (extract_skills, extract_experience_years).
- Safe UPSERT deduplication keyed on (source='adzuna', external_id).
- Non-destructive soft deactivation (is_active=0) for stale postings.
"""

import os
import re
import time
import html
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set
import requests

from config import Config
from resume_parser import extract_skills, extract_experience_years
import models

logger = logging.getLogger(__name__)

# Default target search categories for IT and software development
DEFAULT_SEARCH_QUERIES = [
    "python developer",
    "data analyst",
    "frontend developer",
    "full stack engineer",
    "devops engineer"
]


class AdzunaAPIError(Exception):
    """Raised when calls to the Adzuna Jobs API fail or return unexpected status."""
    pass


# In-memory query response cache: cache_key -> (timestamp, response_data)
_ADZUNA_CACHE: Dict[str, tuple[float, dict]] = {}


def _get_cache_key(query: str, location: str, country: str, page: int, results_per_page: int, sort_by: str = "date") -> str:
    return f"{country.strip().lower()}:{query.strip().lower()}:{location.strip().lower()}:{page}:{results_per_page}:{sort_by}"


def clear_adzuna_cache():
    """Flushes in-memory cache (useful in testing or manual full refreshes)."""
    global _ADZUNA_CACHE
    _ADZUNA_CACHE.clear()


def _clean_api_error_text(text: Optional[str], status_code: int = 500) -> str:
    """Strips HTML or cleans up error text for friendly logging and UI presentation."""
    if not text:
        status_map = {
            500: "Internal Server Error",
            502: "Bad Gateway (Upstream Server Down)",
            503: "Service Unavailable (Server Busy / Temporary Maintenance)",
            504: "Gateway Timeout"
        }
        return status_map.get(status_code, f"HTTP {status_code}")

    # Check for HTML error pages (e.g. Adzuna Chef error pages)
    if "<html" in text.lower() or "<body" in text.lower() or "<!doctype" in text.lower():
        title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            return f"Service Unavailable ({title})"
        return "Service Temporarily Unavailable"

    # Return trimmed plain text
    return text.strip()[:150]


def fetch_jobs(query: str = "", location: str = "", country: str = "in", page: int = 1, results_per_page: int = 50, sort_by: str = "date", bypass_cache: bool = False) -> dict:
    """
    Calls Adzuna search endpoint and returns raw JSON response.

    Rules & Constraints:
    - Sets 10-second request timeout.
    - Retries up to 2 times on timeout or 5xx server errors with exponential backoff.
    - Raises custom AdzunaAPIError on failure with clean human-readable diagnostics.
    - Respects Adzuna rate limits (250 calls/day) via TTL caching.
    """
    app_id = Config.ADZUNA_APP_ID or os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = Config.ADZUNA_APP_KEY or os.environ.get("ADZUNA_APP_KEY", "").strip()

    if not app_id or not app_key:
        raise AdzunaAPIError(
            "Adzuna API credentials are not configured. Set ADZUNA_APP_ID and ADZUNA_APP_KEY environment variables."
        )

    country_code = (country or Config.ADZUNA_COUNTRY or "in").strip().lower()
    page_num = max(1, page)
    page_size = min(50, max(1, results_per_page))

    # 1. Check in-memory cache to conserve quota unless bypass_cache is requested
    cache_key = _get_cache_key(query, location, country_code, page_num, page_size, sort_by)
    now = time.time()
    ttl = getattr(Config, "ADZUNA_CACHE_TTL_SECONDS", 900)

    if not bypass_cache and cache_key in _ADZUNA_CACHE:
        cached_time, cached_data = _ADZUNA_CACHE[cache_key]
        if (now - cached_time) < ttl:
            logger.debug("Adzuna cache hit for key: %s", cache_key)
            return cached_data

    # 2. Build endpoint & params
    base_url = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/{page_num}"
    params: Dict[str, Any] = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": page_size,
        "content-type": "application/json"
    }
    if query.strip():
        params["what"] = query.strip()
    if location.strip():
        params["where"] = location.strip()
    if sort_by:
        params["sort_by"] = sort_by

    # 3. Execute request with 10s timeout and exponential backoff retry (up to 2 retries)
    max_retries = 2
    last_err: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(base_url, params=params, timeout=10)
            if resp.status_code >= 500:
                # Server error, candidate for retry
                if attempt < max_retries:
                    backoff = 2.0 * (attempt + 1)
                    logger.warning(
                        "Adzuna upstream returned HTTP %d on attempt %d/%d for '%s'. Retrying in %.1fs...",
                        resp.status_code, attempt + 1, max_retries + 1, query or country_code, backoff
                    )
                    time.sleep(backoff)
                    continue
                err_clean = _clean_api_error_text(resp.text, resp.status_code)
                raise AdzunaAPIError(f"Adzuna API server error {resp.status_code}: {err_clean}")

            if resp.status_code == 401 or resp.status_code == 403:
                raise AdzunaAPIError(f"Adzuna API authentication failed ({resp.status_code}). Check your App ID and App Key.")

            if resp.status_code == 429:
                if attempt < max_retries:
                    backoff = 3.0 * (attempt + 1)
                    logger.warning("Adzuna rate limit (429) reached. Retrying in %.1fs...", backoff)
                    time.sleep(backoff)
                    continue
                raise AdzunaAPIError("Adzuna API rate limit exceeded (429). Daily or per-minute quota reached.")

            if not resp.ok:
                err_clean = _clean_api_error_text(resp.text, resp.status_code)
                raise AdzunaAPIError(f"Adzuna API returned HTTP {resp.status_code}: {err_clean}")

            data = resp.json()
            # Store in cache
            _ADZUNA_CACHE[cache_key] = (now, data)
            return data

        except requests.exceptions.Timeout as e:
            last_err = e
            if attempt < max_retries:
                backoff = 2.0 * (attempt + 1)
                logger.warning("Adzuna request timed out on attempt %d/%d. Retrying in %.1fs...", attempt + 1, max_retries + 1, backoff)
                time.sleep(backoff)
                continue
            raise AdzunaAPIError("Adzuna API request timed out after 10 seconds.") from e
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(2.0)
                continue
            raise AdzunaAPIError(f"Adzuna API network communication error: {str(e)}") from e
        except ValueError as e:
            raise AdzunaAPIError(f"Invalid JSON response from Adzuna API: {str(e)}") from e

    raise AdzunaAPIError(f"Adzuna API request failed after retries: {str(last_err)}")


def clean_html(raw_html: Optional[str]) -> str:
    """Removes HTML markup and unescapes entities from unstructured text."""
    if not raw_html:
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", raw_html)
    # Unescape entities (e.g. &amp;, &lt;)
    clean = html.unescape(clean)
    # Remove awkward spaces before punctuation caused by stripping tags
    clean = re.sub(r"\s+([,.:;!?])", r"\1", clean)
    # Collapse repeated whitespace
    return re.sub(r"\s+", " ", clean).strip()


def normalize_job(raw_job: dict) -> dict:
    """
    Maps a raw Adzuna job object into this application's job schema:
      title            <- raw_job["title"] (HTML stripped)
      company          <- raw_job["company"]["display_name"]
      location         <- raw_job["location"]["display_name"]
      description      <- raw_job["description"] (HTML stripped)
      source_url       <- raw_job["redirect_url"]
      external_id      <- raw_job["id"]
      salary_min/max   <- raw_job.get("salary_min"/"salary_max")
      posted_at        <- raw_job["created"]
      required_skills  <- [] (to be derived via enrich_job_with_skills)
      preferred_skills <- []
      min_experience   <- 0.0
      source           <- "adzuna"
    """
    raw_company = raw_job.get("company")
    company_name = "Unknown Company"
    if isinstance(raw_company, dict):
        company_name = raw_company.get("display_name") or "Unknown Company"
    elif isinstance(raw_company, str):
        company_name = raw_company

    raw_location = raw_job.get("location")
    location_name = "Remote"
    if isinstance(raw_location, dict):
        location_name = raw_location.get("display_name") or "Remote"
    elif isinstance(raw_location, str):
        location_name = raw_location

    title = clean_html(raw_job.get("title", "Untitled Position"))
    description = clean_html(raw_job.get("description", ""))

    external_id = str(raw_job.get("id", "")).strip()
    source_url = raw_job.get("redirect_url") or ""

    salary_min = None
    if raw_job.get("salary_min") is not None:
        try:
            salary_min = float(raw_job["salary_min"])
        except (ValueError, TypeError):
            salary_min = None

    salary_max = None
    if raw_job.get("salary_max") is not None:
        try:
            salary_max = float(raw_job["salary_max"])
        except (ValueError, TypeError):
            salary_max = None

    posted_at = raw_job.get("created") or ""
    contract_time = (raw_job.get("contract_time") or "").lower()
    job_type = "Full-Time" if "full" in contract_time else ("Part-Time" if "part" in contract_time else "Full-Time")

    return {
        "title": title,
        "company": company_name,
        "location": location_name,
        "description": description,
        "source_url": source_url,
        "external_id": external_id,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "posted_at": posted_at,
        "job_type": job_type,
        "seniority_level": "Mid-Level",
        "openings_count": 1,
        "source": "adzuna",
        "required_skills": [],
        "preferred_skills": [],
        "min_experience": 0.0,
    }


def enrich_job_with_skills(normalized_job: dict) -> dict:
    """
    Enriches unstructured Adzuna job descriptions with structured skills and
    experience constraints by running the same NLP extraction pipeline used for resumes.
    """
    text = normalized_job.get("description", "")
    full_text = f"{normalized_job.get('title', '')} {text}".strip()

    found_skills = extract_skills(full_text)
    min_exp = extract_experience_years(full_text)

    normalized_job["required_skills"] = found_skills
    normalized_job["preferred_skills"] = []
    normalized_job["min_experience"] = min_exp or 0.0

    if not found_skills:
        logger.warning(
            "Adzuna Job external_id=%s ('%s') extracted 0 canonical skills from description.",
            normalized_job.get("external_id"),
            normalized_job.get("title")
        )

    return normalized_job


def sync_jobs(queries: Optional[List[str]] = None, location: str = "", country: str = "in", max_pages: int = 1) -> dict:
    """
    Synchronizes job postings from the Adzuna API into the Resume AI database.

    Steps:
    1. Iterates target queries (defaults to IT / Tech roles).
    2. Fetches raw listings via fetch_jobs().
    3. Normalizes and enriches each result with canonical skills.
    4. UPSERTs into the `jobs` table keyed on (source='adzuna', external_id).
    5. Soft-deactivates stale listings (is_active=0).

    Guarantees:
    - Never wipes existing jobs if sync fails or network is down.
    - Catches query-level exceptions so one bad query does not abort the whole run.
    """
    if not Config.is_adzuna_configured():
        logger.info("Adzuna live sync skipped: Credentials not configured.")
        return {
            "success": False,
            "message": "Adzuna API credentials not configured (set ADZUNA_APP_ID and ADZUNA_APP_KEY).",
            "synced": 0,
            "errors": ["Missing credentials"]
        }

    search_queries = queries or DEFAULT_SEARCH_QUERIES
    synced_external_ids: Set[str] = set()
    total_synced = 0
    errors: List[str] = []

    for q in search_queries:
        for page in range(1, max_pages + 1):
            try:
                raw_data = fetch_jobs(query=q, location=location, country=country, page=page, results_per_page=20)
                results = raw_data.get("results", [])

                for item in results:
                    norm = normalize_job(item)
                    if not norm.get("external_id"):
                        continue

                    enriched = enrich_job_with_skills(norm)
                    models.upsert_job(enriched)

                    synced_external_ids.add(enriched["external_id"])
                    total_synced += 1

            except AdzunaAPIError as e:
                logger.error("Adzuna sync error for query '%s' (page %d): %s", q, page, str(e))
                errors.append(f"Query '{q}': {str(e)}")
            except Exception as e:
                logger.exception("Unexpected error syncing query '%s': %s", q, str(e))
                errors.append(f"Query '{q}': {str(e)}")

    # Soft-deactivate stale jobs that were not returned in this sync session (after 7 days)
    deactivated = 0
    if synced_external_ids:
        deactivated = models.soft_deactivate_stale_adzuna_jobs(synced_external_ids, cutoff_days=7)

    logger.info("Adzuna sync complete: %d jobs upserted, %d stale jobs deactivated.", total_synced, deactivated)

    return {
        "success": True,
        "synced": total_synced,
        "deactivated": deactivated,
        "queries_run": len(search_queries),
        "errors": errors,
        "message": f"Successfully synced {total_synced} live postings from Adzuna."
    }


def sync_live_adzuna_batch(query: str = "software engineer", count: int = 10, country: str = "in") -> dict:
    """
    Fetches the newest jobs from Adzuna for a specific query (sorted by date),
    enriches them with NLP canonical skills and experience constraints,
    and upserts them into the database. Returns newly added jobs.
    """
    if not Config.is_adzuna_configured():
        return {
            "success": False,
            "message": "Adzuna credentials not configured",
            "synced": 0,
            "new_count": 0,
            "new_jobs": []
        }

    try:
        raw_data = fetch_jobs(
            query=query,
            country=country,
            page=1,
            results_per_page=count,
            sort_by="date",
            bypass_cache=True
        )
        results = raw_data.get("results", [])
        total_synced = 0
        saved_jobs = []
        new_jobs = []

        for item in results:
            norm = normalize_job(item)
            if not norm.get("external_id"):
                continue
            enriched = enrich_job_with_skills(norm)
            upserted = models.upsert_job(enriched)
            total_synced += 1
            if upserted:
                saved_jobs.append(upserted)
                if upserted.get("is_new"):
                    new_jobs.append(upserted)

        logger.info(
            "Adzuna live batch synced & saved to DB: query='%s', processed=%d, saved=%d, new_jobs=%d",
            query, total_synced, len(saved_jobs), len(new_jobs)
        )

        return {
            "success": True,
            "query": query,
            "synced": total_synced,
            "saved_count": len(saved_jobs),
            "new_count": len(new_jobs),
            "saved_jobs": saved_jobs,
            "new_jobs": new_jobs,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except AdzunaAPIError as e:
        logger.warning("Adzuna API notice for '%s': %s (will auto-retry next cycle)", query, e)
        return {
            "success": False,
            "query": query,
            "error": str(e),
            "synced": 0,
            "new_count": 0,
            "new_jobs": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.exception("Unexpected error during sync_live_adzuna_batch for '%s': %s", query, e)
        return {
            "success": False,
            "query": query,
            "error": str(e),
            "synced": 0,
            "new_count": 0,
            "new_jobs": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

