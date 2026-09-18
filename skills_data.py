# Curated skill taxonomy used by the extraction / matching engine.
# Organized by category purely for maintainability; matching is flat.

SKILL_TAXONOMY = {
    "Programming Languages": [
        "python", "java", "javascript", "typescript", "c++", "c#", "c",
        "go", "golang", "rust", "ruby", "php", "swift", "kotlin", "scala",
        "r", "matlab", "perl", "sql", "bash", "shell scripting"
    ],
    "Web Development": [
        "html", "css", "react", "react.js", "angular", "vue", "vue.js",
        "node.js", "nodejs", "express.js", "django", "flask", "fastapi",
        "spring boot", "asp.net", "next.js", "redux", "tailwind css",
        "bootstrap", "jquery", "rest api", "graphql", "webpack"
    ],
    "Data & AI": [
        "machine learning", "deep learning", "natural language processing",
        "nlp", "computer vision", "data analysis", "data science",
        "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras",
        "data visualization", "tableau", "power bi", "statistics",
        "big data", "hadoop", "spark", "etl"
    ],
    "Databases": [
        "mysql", "postgresql", "mongodb", "sqlite", "oracle", "redis",
        "elasticsearch", "cassandra", "firebase", "dynamodb", "database design"
    ],
    "Cloud & DevOps": [
        "aws", "azure", "gcp", "google cloud", "docker", "kubernetes",
        "ci/cd", "jenkins", "terraform", "ansible", "git", "github",
        "gitlab", "linux", "devops", "microservices", "serverless"
    ],
    "Project & Soft Skills": [
        "project management", "agile", "scrum", "kanban", "jira",
        "communication", "leadership", "team management", "problem solving",
        "time management", "stakeholder management", "product management"
    ],
    "Mobile": [
        "android", "ios", "react native", "flutter", "swift ui", "xamarin"
    ],
    "Design": [
        "figma", "adobe xd", "photoshop", "illustrator", "ui/ux design",
        "user research", "wireframing", "prototyping"
    ],
    "Security": [
        "cybersecurity", "penetration testing", "network security",
        "information security", "encryption", "owasp"
    ],
    "Business": [
        "excel", "financial analysis", "accounting", "sales",
        "marketing", "seo", "content marketing", "digital marketing",
        "salesforce", "sap", "crm"
    ],
}

# Canonical aliases map: common variations/abbreviations -> standardized canonical skill name
CANONICAL_SKILL_MAP = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "postgres": "postgresql",
    "psql": "postgresql",
    "reactjs": "react",
    "react.js": "react",
    "nodejs": "node.js",
    "node": "node.js",
    "vuejs": "vue",
    "vue.js": "vue",
    "angularjs": "angular",
    "angular.js": "angular",
    "aws cloud": "aws",
    "amazon web services": "aws",
    "gcp": "google cloud",
    "k8s": "kubernetes",
    "ml": "machine learning",
    "dl": "deep learning",
    "cv": "computer vision",
    "nlp": "natural language processing",
    "golang": "go",
    "tf": "tensorflow",
    "scikit learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "cpp": "c++",
    "c-sharp": "c#",
    "csharp": "c#",
    "rest": "rest api",
    "restful": "rest api",
    "restful api": "rest api",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "ui/ux": "ui/ux design",
    "ux/ui": "ui/ux design",
    "ui ux": "ui/ux design",
    "db": "database design",
    "mongo": "mongodb",
    "k8": "kubernetes",
    "docker containers": "docker",
    "nextjs": "next.js",
    "next": "next.js",
}

def normalize_skill(s: str) -> str:
    """Normalize any skill string to its canonical taxonomy form."""
    if not s:
        return ""
    cleaned = s.strip().lower()
    return CANONICAL_SKILL_MAP.get(cleaned, cleaned)

# Flat, de-duplicated, lower-cased master list, longest-first so
# multi-word skills (e.g. "machine learning") are matched before
# shorter substrings collide.
ALL_SKILLS = sorted(
    {normalize_skill(s) for group in SKILL_TAXONOMY.values() for s in group} | set(CANONICAL_SKILL_MAP.keys()),
    key=len,
    reverse=True,
)

DEGREE_KEYWORDS = [
    "ph.d", "phd", "doctorate", "master of", "m.sc", "msc", "m.tech",
    "mba", "bachelor of", "b.sc", "bsc", "b.tech", "b.e.", "bachelor of engineering",
    "bachelor of technology", "bachelor of science", "bachelor of arts",
    "associate degree", "diploma", "high school"
]

DEGREE_FIELDS = [
    "Computer Science", "Information Technology", "Computer Engineering",
    "Data Science", "Artificial Intelligence", "Electrical Engineering",
    "Electronics and Communication", "Mechanical Engineering", "Civil Engineering",
    "Business Administration", "Mathematics", "Statistics", "Physics",
    "Software Engineering", "Information Systems"
]

# Standard Target Role Profiles for Gap Analysis
ROLE_PROFILES = {
    "Full Stack Engineer": {
        "required_skills": ["javascript", "react", "node.js", "python", "sql", "git"],
        "recommended_skills": ["typescript", "docker", "rest api", "aws", "postgresql"],
        "min_experience": 2
    },
    "Backend Developer": {
        "required_skills": ["python", "sql", "rest api", "git", "database design"],
        "recommended_skills": ["django", "fastapi", "docker", "redis", "postgresql", "microservices"],
        "min_experience": 2
    },
    "Frontend Engineer": {
        "required_skills": ["html", "css", "javascript", "react", "git"],
        "recommended_skills": ["typescript", "tailwind css", "redux", "next.js", "webpack"],
        "min_experience": 2
    },
    "Data Scientist / AI Engineer": {
        "required_skills": ["python", "machine learning", "pandas", "numpy", "statistics"],
        "recommended_skills": ["deep learning", "tensorflow", "pytorch", "scikit-learn", "sql"],
        "min_experience": 3
    },
    "DevOps & Cloud Engineer": {
        "required_skills": ["docker", "kubernetes", "aws", "ci/cd", "linux"],
        "recommended_skills": ["terraform", "ansible", "python", "git", "bash"],
        "min_experience": 3
    },
    "Mobile Developer": {
        "required_skills": ["react native", "javascript", "rest api", "git"],
        "recommended_skills": ["typescript", "android", "ios", "redux"],
        "min_experience": 2
    }
}

