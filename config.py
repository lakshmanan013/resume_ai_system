import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "resume-ai-production-super-secret-key-2026")
    
    # Database Configuration (Default to MySQL database 'ai_resume')
    DB_TYPE = os.environ.get("DB_TYPE", "mysql")
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", 3306))
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "Vasanth@zenve")
    MYSQL_DB = os.environ.get("MYSQL_DB", "ai_resume")

    DATABASE = os.path.join(BASE_DIR, "instance", "resume_ai.db")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    ALLOWED_EXTENSIONS = {"pdf", "docx"}
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/octet-stream", # Some browsers send binary docx/pdf as octet-stream
    }
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
    MATCH_THRESHOLD = 40  # % match score required to "qualify" for a job

    # Security & Auth rules
    PASSWORD_MIN_LENGTH = 8
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15
    RESET_TOKEN_MAX_AGE = 3600  # 1 hour

    # ML Scoring Weights (Tunable & Explainable)
    WEIGHT_SEMANTIC = 0.60
    WEIGHT_REQUIRED_SKILLS = 0.30
    WEIGHT_EXPERIENCE = 0.10

    # TF-IDF Fallback Scoring Weights (When embeddings model is unavailable)
    FALLBACK_WEIGHT_TFIDF = 0.50
    FALLBACK_WEIGHT_REQUIRED_SKILLS = 0.40
    FALLBACK_WEIGHT_EXPERIENCE = 0.10

    # NLP & Embeddings Models
    EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
    SPACY_MODEL_NAME = "en_core_web_sm"

    # Adzuna Jobs API Configuration
    ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "a91087a5").strip()
    ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "0c9543003cc17c43a9a4bfb424f2a5e9").strip()
    ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "in").strip()
    ADZUNA_LIVE_SYNC_ENABLED = os.environ.get("ADZUNA_LIVE_SYNC_ENABLED", "true").lower() in ("true", "1", "yes")
    ADZUNA_CACHE_TTL_SECONDS = int(os.environ.get("ADZUNA_CACHE_TTL_SECONDS", 900))  # 15 minutes

    @classmethod
    def validate_adzuna_config(cls):
        """Fails loudly at startup if live sync is enabled but credentials are missing."""
        if cls.ADZUNA_LIVE_SYNC_ENABLED and (not cls.ADZUNA_APP_ID or not cls.ADZUNA_APP_KEY):
            raise RuntimeError(
                "ADZUNA_APP_ID and ADZUNA_APP_KEY environment variables are required when live sync is enabled "
                "(ADZUNA_LIVE_SYNC_ENABLED=true). Please set both environment variables or disable live sync."
            )

    @classmethod
    def is_adzuna_configured(cls) -> bool:
        """Returns True if valid Adzuna API credentials are provided."""
        return bool(cls.ADZUNA_APP_ID and cls.ADZUNA_APP_KEY)


# Run startup validation check for Adzuna configuration
Config.validate_adzuna_config()


