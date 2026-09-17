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

# Flat, de-duplicated, lower-cased master list, longest-first so
# multi-word skills (e.g. "machine learning") are matched before
# shorter substrings collide.
ALL_SKILLS = sorted(
    {s.lower() for group in SKILL_TAXONOMY.values() for s in group},
    key=len,
    reverse=True,
)

DEGREE_KEYWORDS = [
    "ph.d", "phd", "doctorate", "master of", "m.sc", "msc", "m.tech",
    "mba", "bachelor of", "b.sc", "bsc", "b.tech", "b.e.", "bachelor of engineering",
    "bachelor of technology", "bachelor of science", "bachelor of arts",
    "associate degree", "diploma", "high school"
]
