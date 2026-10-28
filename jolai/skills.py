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
    "LLMs": ["llm", "llms", "large language model", "large language models", "generative ai", "genai", "gen ai"],
    "AI Tools": ["chatgpt", "claude", "gemini", "copilot", "ai tools"],
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
    "Product Management": ["product management", "product manager", "roadmap", "roadmapping", "product lifecycle",
                           "product requirements", "prd", "user stories", "backlog"],
    "Agile": ["agile", "scrum", "kanban"],
    "Asana": ["asana", "monday.com", "trello", "smartsheet"],
    "Jira": ["jira"],
    "Excel": ["CS:Excel", "microsoft excel"],
    "Salesforce": ["salesforce"],
    "SEO": ["seo"],
    "Project Management": ["project management", "pmp"],
    "Leadership": ["led a team", "team lead", "mentored", "mentoring", "people management"],
    # Non-technical / business skills
    "Communication": ["communication skills", "written communication", "verbal communication", "public speaking",
                      "presentation skills", "presentations"],
    "Customer Service": ["customer service", "customer support", "customer success", "client relations",
                         "client services", "help desk", "helpdesk"],
    # Plain "sales" isn't enough: "analyzed sales data" is analysis, not selling.
    "Sales": ["sales experience", "sales targets", "sales quota", "quota", "b2b sales", "b2c sales", "inside sales",
              "field sales", "selling", "sold", "closing deals", "closed deals", "sales pipeline",
              "business development", "lead generation", "cold calling", "account executive",
              "sales representative"],
    "Marketing": ["marketing", "digital marketing", "email marketing", "campaigns", "brand marketing"],
    "Social Media": ["social media", "instagram", "tiktok", "community management"],
    "Content Writing": ["content writing", "content creation", "blog posts", "editing", "proofreading"],
    "Copywriting": ["copywriting", "copywriter"],
    "Operations": ["operations", "business operations"],
    "Recruiting": ["recruiting", "recruitment", "talent acquisition", "sourcing candidates"],
    "Accounting": ["accounting", "accounts payable", "accounts receivable", "invoicing", "payroll"],
    "Bookkeeping": ["bookkeeping", "quickbooks", "xero"],
    "HubSpot": ["hubspot"],
    "Zendesk": ["zendesk", "intercom", "freshdesk"],
    "Google Workspace": ["google workspace", "google sheets", "google docs", "g suite"],
    "Microsoft Office": ["microsoft office", "ms office", "powerpoint", "microsoft outlook", "microsoft word"],
    "Canva": ["canva"],
    "Event Planning": ["event planning", "event management"],
    "Research": ["research", "market research", "user research"],
    "Data Entry": ["data entry"],
    "Teaching": ["teaching", "tutoring", "training sessions", "curriculum"],
    # Strategy, analysis and project work
    "Product Strategy": ["product strategy", "go-to-market", "go to market", "gtm", "product vision",
                         "market sizing", "value proposition"],
    "Business Analysis": ["business analysis", "business analyst", "gap analysis", "business case",
                          "business cases"],
    "Requirements Analysis": ["requirements analysis", "requirements gathering", "business requirements",
                              "gathering requirements", "functional requirements"],
    "Strategy": ["business strategy", "strategic planning", "corporate strategy", "strategy consulting"],
    "Competitive Analysis": ["competitive analysis", "competitor analysis", "market analysis",
                             "competitive landscape"],
    "Financial Analysis": ["financial analysis", "financial analyst", "financial modelling", "financial modeling",
                           "p&l", "budgeting", "financial forecasting", "unit economics", "valuation"],
    "Data Visualization": ["data visualization", "data visualisation", "dashboards", "dashboard", "reporting"],
    "Business Intelligence": ["business intelligence"],
    "Data Analysis": ["data analysis", "data analytics", "analyzed data", "analysed data", "kpis", "kpi",
                      "metrics"],
    "Project Coordination": ["project coordination", "project coordinator", "coordinated", "coordinating"],
    "Program Management": ["program management", "programme management", "program manager", "pmo"],
    "Process Improvement": ["process improvement", "process optimization", "process optimisation",
                            "streamline", "streamlined", "standardized", "standardised", "workflow"],
    "Stakeholder Management": ["stakeholder management", "stakeholder engagement", "stakeholders",
                               "cross-functional", "cross functional"],
    "Partnerships": ["partnerships", "partnership", "strategic partnerships", "alliances", "channel partners"],
    "Account Management": ["account management", "key accounts", "key account", "client management"],
    "Vendor Management": ["vendor management", "supplier management", "supplier sourcing", "procurement",
                          "sourcing", "procure-to-pay", "p2p"],
    "Logistics": ["logistics", "supply chain", "shipments", "inventory"],
    "SAP": ["sap", "sap concur", "concur"],
    "Workshop Facilitation": ["workshops", "workshop", "facilitation", "facilitated"],
    "Change Management": ["change management"],
    "Miro": ["miro"],
    "Notion": ["notion"],
    "Adobe XD": ["adobe xd"],
    "Prototyping": ["prototyping", "prototypes", "wireframes", "wireframing"],
    "Retail": ["retail", "travel retail", "e-commerce", "ecommerce"],
    "Administration": ["administrative", "office management", "scheduling", "calendar management",
                       "executive assistant"],
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


# Skills that don't mean hands-on technical work. Used by filters.technical_score: a posting
# that lists lots of these is business-facing, one that lists lots of others is technical.
NON_TECHNICAL = {
    "Excel", "Salesforce", "SEO", "Agile", "Asana", "Jira", "Project Management", "Leadership",
    "Product Management", "UX Design", "Figma", "Tableau", "Power BI", "Looker", "Statistics", "A/B Testing",
    "Communication", "Customer Service", "Sales", "Marketing", "Social Media", "Content Writing", "Copywriting",
    "Operations", "Recruiting", "Accounting", "Bookkeeping", "HubSpot", "Zendesk", "Google Workspace",
    "Microsoft Office", "Canva", "Event Planning", "Research", "Data Entry", "Teaching", "Administration",
    "Product Strategy", "Business Analysis", "Requirements Analysis", "Strategy", "Competitive Analysis",
    "Financial Analysis", "Data Visualization", "Business Intelligence", "Data Analysis", "Project Coordination",
    "Program Management", "Process Improvement", "Stakeholder Management", "Partnerships", "Account Management",
    "Vendor Management", "Logistics", "SAP", "Workshop Facilitation", "Change Management", "Miro", "Notion",
    "Adobe XD", "Prototyping", "Retail", "AI Tools",
}
