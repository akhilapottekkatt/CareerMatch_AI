"""
resume_parser.py
================
Standard Gemini AI resume parser for public use.
Works for any resume from any person, any country.

Features:
- Gemini AI parsing     → full structured extraction
- Local regex fallback  → works without API too
- Experience calculator → calculates years from date ranges
- Cache system          → never parse same resume twice
- DB ready              → standardized JSON for MongoDB storage
"""

import os
import re
import json
import uuid
import hashlib
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

CACHE_FILE = "resume_cache.json"


# ═══════════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════════


def _get_cache() -> dict:
    """Load cached results from disk."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: dict):
    """Save results to cache file."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _hash_text(text: str) -> str:
    """MD5 hash of resume text — used as unique cache key."""
    return hashlib.md5(text[:2000].encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# KNOWN SKILLS — universal, not region specific
# ═══════════════════════════════════════════════════════════════════

KNOWN_SKILLS = {
    # Programming Languages
    "python",
    "java",
    "javascript",
    "typescript",
    "c++",
    "c#",
    "c",
    "ruby",
    "php",
    "swift",
    "kotlin",
    "go",
    "rust",
    "scala",
    "r",
    "matlab",
    "bash",
    "shell",
    "powershell",
    "perl",
    "dart",
    "lua",
    "haskell",
    "elixir",
    "clojure",
    "groovy",
    "objective-c",
    "cobol",
    # Web Frameworks
    "django",
    "flask",
    "fastapi",
    "react",
    "angular",
    "vue",
    "nextjs",
    "nodejs",
    "express",
    "spring",
    "laravel",
    "asp.net",
    "rails",
    "nuxtjs",
    "gatsby",
    "svelte",
    "phoenix",
    "gin",
    "echo",
    # Frontend
    "html",
    "css",
    "bootstrap",
    "tailwind",
    "jquery",
    "redux",
    "webpack",
    "babel",
    "sass",
    "less",
    "material ui",
    "chakra ui",
    # Databases
    "mysql",
    "postgresql",
    "sqlite",
    "mongodb",
    "redis",
    "oracle",
    "cassandra",
    "dynamodb",
    "firebase",
    "elasticsearch",
    "sql",
    "mariadb",
    "couchdb",
    "neo4j",
    "supabase",
    "cockroachdb",
    # Cloud & DevOps
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "jenkins",
    "terraform",
    "ansible",
    "git",
    "github",
    "gitlab",
    "linux",
    "nginx",
    "ci/cd",
    "devops",
    "bitbucket",
    "circleci",
    "travis ci",
    "prometheus",
    "grafana",
    "helm",
    "istio",
    "cloudflare",
    # AI / ML / Data
    "machine learning",
    "deep learning",
    "tensorflow",
    "pytorch",
    "keras",
    "scikit-learn",
    "opencv",
    "nlp",
    "computer vision",
    "pandas",
    "numpy",
    "matplotlib",
    "seaborn",
    "jupyter",
    "huggingface",
    "bert",
    "transformers",
    "langchain",
    "llm",
    "data science",
    "data analysis",
    "power bi",
    "tableau",
    "hadoop",
    "spark",
    "airflow",
    "dbt",
    "snowflake",
    "bigquery",
    # Mobile
    "android",
    "ios",
    "react native",
    "flutter",
    "xamarin",
    # Testing
    "selenium",
    "pytest",
    "junit",
    "jest",
    "postman",
    "cypress",
    "playwright",
    "mocha",
    "chai",
    "robot framework",
    # Tools & Methodologies
    "jira",
    "figma",
    "excel",
    "agile",
    "scrum",
    "kanban",
    "rest api",
    "graphql",
    "microservices",
    "soap",
    "grpc",
    "linux",
    "unix",
    "vim",
    "vs code",
    "intellij",
    # Security
    "cybersecurity",
    "penetration testing",
    "owasp",
    "oauth",
    "jwt",
    "ssl",
    "tls",
    "encryption",
    "firewall",
    # Other
    "blockchain",
    "web3",
    "solidity",
    "unity",
    "unreal engine",
    "arduino",
    "raspberry pi",
    "iot",
    "embedded systems",
}


# ═══════════════════════════════════════════════════════════════════
# DATE PARSER & EXPERIENCE CALCULATOR
# ═══════════════════════════════════════════════════════════════════


def _parse_date(date_str: str):
    """
    Parse a date string into a datetime object.
    Supports multiple formats from resumes worldwide.
    Returns None if parsing fails.
    """
    formats = [
        "%b %Y",  # Jan 2020
        "%B %Y",  # January 2020
        "%m/%Y",  # 01/2020
        "%m-%Y",  # 01-2020
        "%Y-%m",  # 2020-01
        "%Y/%m",  # 2020/01
        "%Y",  # 2020
        "%b. %Y",  # Jan. 2020
        "%d %b %Y",  # 01 Jan 2020
        "%B %d, %Y",  # January 01, 2020
    ]
    date_str = date_str.strip().title()
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def calculate_experience_years(experience_list: list) -> float:
    """
    Calculate total work experience in years from job date ranges.

    Handles:
      - 'Jan 2020 - Dec 2023'
      - '2019 - 2022'
      - 'March 2021 - Present'
      - '06/2018 - 12/2021'
      - '2020 - Current'

    Returns total years as float (e.g., 3.5)
    """
    total_months = 0
    today = datetime.today()

    for job in experience_list:
        duration = job.get("duration", "")
        if not duration:
            continue

        # Normalize unicode dashes and extra spaces
        duration = duration.replace("\u2013", "-").replace("\u2014", "-").strip()
        duration_lower = duration.lower()

        # Replace present/current/now/till date with today
        duration_lower = re.sub(
            r"\b(present|current|now|till\s*date|ongoing|to\s*date)\b",
            today.strftime("%b %Y").lower(),
            duration_lower,
        )

        # Split on dash or "to"
        parts = re.split(r"\s*[-\u2013]+\s*|\s+to\s+", duration_lower)
        if len(parts) < 2:
            continue

        start_str = parts[0].strip()
        end_str = parts[-1].strip()

        start = _parse_date(start_str)
        end = _parse_date(end_str)

        if start and end and end >= start:
            months = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += months

    return round(total_months / 12, 1)


# ═══════════════════════════════════════════════════════════════════
# LOCAL FALLBACK PARSER — no API, pure regex
# ═══════════════════════════════════════════════════════════════════


def _local_parse(text: str) -> dict:
    """
    Regex-based fallback parser.
    Used when Gemini API is unavailable or rate limited.
    Works for any resume — no region-specific assumptions.
    """
    print("🔍 Using local parser as fallback...")

    # ── Name — first clean short line
    name = ""
    for line in text.split("\n")[:10]:
        line = line.strip()
        if (
            line
            and "@" not in line
            and not re.search(r"\d{5,}", line)
            and len(line) < 60
        ):
            words = line.split()
            if 2 <= len(words) <= 5 and all(
                re.match(r"^[A-Za-z\.\-]+$", w) for w in words
            ):
                name = line.title()
                break

    # ── Email
    email_m = re.search(r"[\w\.\+\-]+@[\w\.\-]+\.\w{2,}", text)
    email = email_m.group(0).lower() if email_m else ""

    # ── Phone — international formats
    phone_m = re.search(r"(\+?\d[\d\s\-\.\(\)]{7,16}\d)", text)
    phone = phone_m.group(0).strip() if phone_m else ""

    # ── LinkedIn
    linkedin_m = re.search(r"linkedin\.com/in/[\w\-]+", text, re.IGNORECASE)
    linkedin = linkedin_m.group(0) if linkedin_m else ""

    # ── GitHub
    github_m = re.search(r"github\.com/[\w\-]+", text, re.IGNORECASE)
    github = github_m.group(0) if github_m else ""

    # ── Location — generic City, Country pattern
    location = ""
    loc_m = re.search(r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z][a-zA-Z\s]+)\b", text)
    if loc_m:
        location = loc_m.group(0).strip()

    # ── Skills — match against KNOWN_SKILLS
    text_lower = text.lower()
    skills = []
    for skill in KNOWN_SKILLS:
        if re.search(r"\b" + re.escape(skill) + r"\b", text_lower):
            skills.append(skill.title())
    skills = sorted(list(set(skills)))

    # ── Summary — first long paragraph
    summary = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if (
            len(para) > 100
            and "@" not in para
            and not re.match(r"^[\+\d]", para)
            and not re.match(r"^(education|experience|skills|projects)", para.lower())
        ):
            summary = re.sub(r"\s+", " ", para)[:600]
            break

    # ── Education — universal degree patterns
    education = []
    degree_pat = re.compile(
        r"\b(bachelor|master|b\.?tech|m\.?tech|b\.?e|m\.?e|bca|mca|"
        r"b\.?sc|m\.?sc|b\.?com|mba|ph\.?d|doctorate|diploma|"
        r"associate|b\.?a|m\.?a|llb|mbbs|bds|b\.?arch)\b",
        re.IGNORECASE,
    )
    for line in text.split("\n"):
        if degree_pat.search(line):
            education.append(
                {"degree": line.strip()[:120], "institution": "", "year": "", "gpa": ""}
            )
            if len(education) >= 5:
                break

    # ── Experience years from explicit mention in text
    exp_m = re.search(
        r"(\d+)\+?\s*years?\s*(?:of\s*)?(?:work\s*)?experience", text, re.IGNORECASE
    )
    exp_years = int(exp_m.group(1)) if exp_m else 0

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
        "location": location,
        "summary": summary,
        "skills": skills,
        "experience": [],
        "education": education,
        "certifications": [],
        "languages": [],
        "experience_years": exp_years,
    }


# ═══════════════════════════════════════════════════════════════════
# GEMINI PARSER — single AI call
# ═══════════════════════════════════════════════════════════════════


def _call_gemini(resume_text: str):
    """
    Single Gemini API call — no retries, no waiting.
    Returns structured dict or None if unavailable.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        print("⚠️  No GOOGLE_API_KEY found in .env")
        return None

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        resume_snippet = resume_text[:4000]

        prompt = f"""You are a resume parser. Parse the resume below and return ONLY a valid JSON object.
No explanation. No markdown. No code fences. Just raw JSON.

Resume:
{resume_snippet}

Return this exact JSON structure:
{{
  "name": "full name",
  "email": "email address",
  "phone": "phone number with country code if available",
  "linkedin": "linkedin profile url or username",
  "github": "github profile url or username",
  "location": "city, state/country",
  "summary": "2-3 sentence professional summary of the candidate",
  "skills": ["skill1", "skill2", "skill3"],
  "experience": [
    {{
      "title": "job title",
      "company": "company name",
      "duration": "Mon Year - Mon Year or Present",
      "location": "job location",
      "description": "key responsibilities and achievements"
    }}
  ],
  "education": [
    {{
      "degree": "degree name and field",
      "institution": "university or college name",
      "year": "graduation year",
      "gpa": "gpa or percentage if mentioned"
    }}
  ],
  "certifications": ["certification name and issuer"],
  "languages": ["language name"],
  "experience_years": 0
}}

Rules:
- Use empty string "" for missing text fields
- Use empty list [] for missing list fields
- Use 0 for missing numeric fields
- experience_years: only fill if explicitly stated in resume, else use 0
- Extract ALL skills mentioned anywhere in the resume
- Keep duration in original format from resume"""

        print("🤖 Calling Gemini (gemini-2.0-flash)...")
        response = client.models.generate_content(
            model="gemini-2.0-flash", contents=prompt
        )

        raw = response.text.strip()

        # Strip accidental markdown fences
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break

        # Extract JSON block if surrounded by extra text
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)

        result = json.loads(raw)
        print(
            f"✅ Gemini parsed: {result.get('name', 'Unknown')} "
            f"| {len(result.get('skills', []))} skills "
            f"| {len(result.get('experience', []))} jobs"
        )
        return result

    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            print("⚠️  Gemini rate limited — falling back to local parser")
        elif "404" in err:
            print("⚠️  Gemini model not found — falling back to local parser")
        else:
            print(f"⚠️  Gemini error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# NORMALIZE — guarantee all fields exist
# ═══════════════════════════════════════════════════════════════════


def _normalize(data: dict) -> dict:
    """Ensure all fields exist with correct types."""
    return {
        "name": str(data.get("name") or ""),
        "email": str(data.get("email") or ""),
        "phone": str(data.get("phone") or ""),
        "linkedin": str(data.get("linkedin") or ""),
        "github": str(data.get("github") or ""),
        "location": str(data.get("location") or ""),
        "summary": str(data.get("summary") or ""),
        "skills": list(data.get("skills") or []),
        "experience": list(data.get("experience") or []),
        "education": list(data.get("education") or []),
        "certifications": list(data.get("certifications") or []),
        "languages": list(data.get("languages") or []),
        "experience_years": float(data.get("experience_years") or 0),
    }


# ═══════════════════════════════════════════════════════════════════
# BUILD DB DOCUMENT
# ═══════════════════════════════════════════════════════════════════


def build_db_document(parsed: dict) -> dict:
    """
    Build a clean standardized document for DB storage.
    - Recalculates experience from actual date ranges
    - Deduplicates and sorts skills
    - Extracts highest qualification
    - Adds candidate_id UUID and parsed_at timestamp
    """
    experience_list = parsed.get("experience", [])
    education_list = parsed.get("education", [])

    # Recalculate experience years from actual date ranges
    calculated_years = calculate_experience_years(experience_list)
    exp_years = (
        calculated_years if calculated_years > 0 else parsed.get("experience_years", 0)
    )

    # Highest qualification = first education entry
    highest_edu = education_list[0] if education_list else {}

    # Deduplicate and sort skills
    all_skills = sorted(set(s.strip() for s in parsed.get("skills", []) if s.strip()))

    return {
        "candidate_id": str(uuid.uuid4()),
        "parsed_at": datetime.utcnow().isoformat(),
        "personal": {
            "name": parsed.get("name", ""),
            "email": parsed.get("email", ""),
            "phone": parsed.get("phone", ""),
            "linkedin": parsed.get("linkedin", ""),
            "github": parsed.get("github", ""),
            "location": parsed.get("location", ""),
        },
        "summary": parsed.get("summary", ""),
        "experience_years": exp_years,
        "experience": experience_list,
        "skills": all_skills,
        "qualification": {
            "highest_degree": highest_edu.get("degree", ""),
            "institution": highest_edu.get("institution", ""),
            "year": highest_edu.get("year", ""),
            "gpa": highest_edu.get("gpa", ""),
            "all_education": education_list,
        },
        "certifications": parsed.get("certifications", []),
        "languages": parsed.get("languages", []),
    }


# ═══════════════════════════════════════════════════════════════════
# STORE TO DB — MongoDB
# ═══════════════════════════════════════════════════════════════════


def store_to_db(parsed: dict, db_collection) -> dict:
    """
    Build and insert standardized resume document into MongoDB.

    Args:
        parsed:        Output from parse_resume()
        db_collection: pymongo collection object

    Returns:
        The document that was inserted

    Usage:
        from pymongo import MongoClient
        client     = MongoClient("mongodb://localhost:27017/")
        collection = client["resume_db"]["candidates"]
        result     = store_to_db(parsed, collection)
    """
    document = build_db_document(parsed)

    try:
        db_collection.insert_one(document)
        print(
            f"✅ Stored: {document['personal']['name']} "
            f"| {document['experience_years']} yrs exp "
            f"| {len(document['skills'])} skills"
        )
    except Exception as e:
        print(f"❌ DB insert failed: {e}")

    return document


# ═══════════════════════════════════════════════════════════════════
# MAIN PARSE FUNCTION
# ═══════════════════════════════════════════════════════════════════


def parse_resume(resume_text: str) -> dict:
    """
    Main entry point — parse resume text into structured dict.

    Flow:
      1. Check cache  → return instantly if same resume seen before
      2. Call Gemini  → AI-powered full extraction
      3. Fallback     → local regex parser if Gemini fails
      4. Normalize    → ensure all fields exist with correct types
      5. Recalculate  → experience years from actual date ranges
      6. Cache result → save for future calls

    Args:
        resume_text: Plain text content extracted from resume PDF

    Returns:
        dict with keys: name, email, phone, linkedin, github,
                        location, summary, skills, experience,
                        education, certifications, languages,
                        experience_years
    """
    if not resume_text or not resume_text.strip():
        print("❌ Empty resume text provided")
        return _normalize({})

    # Step 1 — Check cache
    cache = _get_cache()
    text_hash = _hash_text(resume_text)

    if text_hash in cache:
        print(f"✅ Cache hit! (hash: {text_hash[:8]}...)")
        return cache[text_hash]

    # Step 2 — Try Gemini AI
    result = _call_gemini(resume_text)

    # Step 3 — Fallback to local parser if Gemini failed
    if result is None:
        result = _local_parse(resume_text)

    # Step 4 — Normalize all fields
    result = _normalize(result)

    # Step 5 — Recalculate experience from actual date ranges
    calc_years = calculate_experience_years(result.get("experience", []))
    if calc_years > 0:
        result["experience_years"] = calc_years

    # Step 6 — Save to cache
    cache[text_hash] = result
    _save_cache(cache)
    print(f"💾 Cached (hash: {text_hash[:8]}...)")

    return result
