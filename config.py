import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    DATABASE = os.path.join(BASE_DIR, "instance", "resume_ai.db")
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    ALLOWED_EXTENSIONS = {"pdf", "docx"}
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
    MATCH_THRESHOLD = 40  # % match score required to "qualify" for a job
