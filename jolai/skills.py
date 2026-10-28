"""Skill vocabulary and detection.

Each canonical skill maps to a list of aliases. Aliases are matched case-insensitively
with boundaries that respect symbols like "C++", "C#" and ".NET". Aliases wrapped in
``CS:`` are matched case-sensitively (for short, ambiguous names like "Go").
"""

from __future__ import annotations

import re
from functools import lru_cache

SKILLS: dict[str, list[str]] = {
    # Languages
    "Python": ["python"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript"],
    "Go": ["golang", "CS:Go"],
    "Rust": ["rust"],
    "C": ["CS:C"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "csharp"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Kotlin": ["kotlin"],
    "Swift": ["CS:Swift"],
    "Scala": ["scala"],
    "R": ["r programming", "r language", "rstudio"],
    "SQL": ["sql"],
    "Bash": ["bash", "shell scripting"],
    "Elixir": ["elixir"],
    "Haskell": ["haskell"],
    "MATLAB": ["matlab"],
    "Solidity": ["solidity"],
    # Web / frameworks
    "React": ["react", "react.js", "reactjs"],
    "React Native": ["react native"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular"],
    "Svelte": ["svelte"],
    "Next.js": ["next.js", "nextjs"],
    "Node.js": ["node.js", "nodejs"],
    "Express": ["express.js", "expressjs"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Spring": ["spring boot", "spring framework"],
    "Rails": ["ruby on rails", "rails"],
    ".NET": [".net", "dotnet", "asp.net"],
    "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "restful", "rest apis"],
    "gRPC": ["grpc"],
    "HTML/CSS": ["html", "css", "tailwind", "sass"],
    # Data / ML
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision"],
    "LLMs": ["llm", "llms", "large language model", "large language models", "generative ai", "genai"],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "Spark": ["spark", "pyspark"],
    "Hadoop": ["hadoop"],
    "Airflow": ["airflow"],
    "dbt": ["dbt"],
    "Kafka": ["kafka"],
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery"],
    "Databricks": ["databricks"],
    "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"],
    "Looker": ["looker"],
    "Statistics": ["statistics", "statistical"],
    "A/B Testing": ["a/b testing", "ab testing", "experimentation"],
    "ETL": ["etl", "elt", "data pipelines", "data pipeline"],
    # Databases
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "opensearch"],
    "DynamoDB": ["dynamodb"],
    "Cassandra": ["cassandra"],
    # Cloud / infra
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud"],
    "Azure": ["azure"],
    "Docker": ["docker", "containers"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"],
    "Ansible": ["ansible"],
    "CI/CD": ["ci/cd", "continuous integration", "github actions", "jenkins", "circleci"],
    "Linux": ["linux", "unix"],
    "Microservices": ["microservices", "microservice"],
    "Distributed Systems": ["distributed systems", "distributed system"],
    "Observability": ["observability", "prometheus", "grafana", "datadog"],
    "Security": ["security", "appsec", "infosec"],
    "Networking": ["networking", "tcp/ip"],
    "Git": ["git"],
    # Mobile
    "iOS": ["ios"],
    "Android": ["android"],
    # Product / design / other
    "Figma": ["figma"],
    "UX Design": ["ux", "user experience", "ux design"],
    "Product Management": ["product management", "roadmap", "product strategy"],
    "Agile": ["agile", "scrum", "kanban"],
    "Jira": ["jira"],
    "Excel": ["CS:Excel", "microsoft excel"],
    "Salesforce": ["salesforce"],
    "SEO": ["seo"],
    "Project Management": ["project management", "pmp"],
    "Leadership": ["led a team", "team lead", "mentored", "mentoring", "people management"],
}


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern]]:
    compiled = []
    for canonical, aliases in SKILLS.items():
        ci, cs = [], []
        for alias in aliases:
            (cs if alias.startswith("CS:") else ci).append(re.escape(alias.removeprefix("CS:")))
        # Boundaries: not preceded/followed by word chars or symbols that continue a token.
        left, right = r"(?<![\w+#.])", r"(?![\w+#]|\.\w)"
        if ci:
            compiled.append((canonical, re.compile(left + "(?:" + "|".join(ci) + ")" + right, re.I)))
        if cs:
            compiled.append((canonical, re.compile(left + "(?:" + "|".join(cs) + ")" + right)))
    return compiled


def extract_skills(text: str) -> set[str]:
    found = set()
    for canonical, pattern in _patterns():
        if pattern.search(text):
            found.add(canonical)
    # "C" alone is very noisy (e.g. "Series C", "C-suite"); only keep it next to other languages.
    if "C" in found and not re.search(r"(?<![\w+#])C(?:\s*/\s*C\+\+|,\s*C\+\+|\s+programming|\s+language)", text):
        found.discard("C")
    return found


def canonicalize(skill: str) -> str:
    """Map a user-supplied skill name onto the vocabulary when possible."""
    lowered = skill.strip().lower()
    for canonical, aliases in SKILLS.items():
        if lowered == canonical.lower() or lowered in (a.removeprefix("CS:").lower() for a in aliases):
            return canonical
    return skill.strip()
