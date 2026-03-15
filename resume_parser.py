"""
resume_parser.py
================
Efficient Gemini AI resume parser.

Key improvements:
- Caches parsed results by file hash → never calls Gemini twice for same resume
- One API call only — no retries, no waiting
- Falls back to local parser instantly if rate limited
- Uses gemini-2.0-flash (fastest, cheapest, highest quota)
"""

import os
import re
import json
import hashlib
from dotenv import load_dotenv

load_dotenv()

# Cache file — stores parsed results so same resume never parsed twice
CACHE_FILE = "resume_cache.json"


# ═══════════════════════════════════════════════════════════════════
# CACHE — avoid redundant Gemini calls
# ═══════════════════════════════════════════════════════════════════

def _get_cache() -> dict:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def _hash_text(text: str) -> str:
    """MD5 hash of resume text — used as cache key."""
    return hashlib.md5(text[:2000].encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# LOCAL FALLBACK PARSER
# ═══════════════════════════════════════════════════════════════════

KNOWN_SKILLS = {
    "python", "java", "javascript", "typescript", "c++", "c#", "c",
    "ruby", "php", "swift", "kotlin", "go", "rust", "scala", "r",
    "matlab", "bash", "shell", "powershell",
    "django", "flask", "fastapi", "react", "angular", "vue", "nextjs",
    "nodejs", "express", "spring", "laravel", "asp.net",
    "html", "css", "bootstrap", "tailwind", "jquery", "redux",
    "mysql", "postgresql", "sqlite", "mongodb", "redis", "oracle",
    "cassandra", "dynamodb", "firebase", "elasticsearch", "sql",
    "aws", "azure", "gcp", "docker", "kubernetes", "jenkins",
    "terraform", "ansible", "git", "github", "gitlab", "linux",
    "nginx", "ci/cd", "devops",
    "machine learning", "deep learning", "tensorflow", "pytorch",
    "keras", "scikit-learn", "opencv", "nlp", "computer vision",
    "pandas", "numpy", "matplotlib", "seaborn", "jupyter",
    "huggingface", "bert", "transformers", "langchain",
    "android", "ios", "react native", "flutter",
    "selenium", "pytest", "junit", "jest", "postman",
    "jira", "figma", "excel", "tableau", "power bi",
    "agile", "scrum", "rest api", "graphql", "microservices",
}

def _local_parse(text: str) -> dict:
    """Fast local fallback — extracts key info without any API."""
    print("🔍 Using local parser as fallback...")

    # Name — first clean line
    name = ""
    for line in text.split("\n")[:8]:
        line = line.strip()
        if line and "@" not in line and len(line) < 50:
            words = line.split()
            if 1 <= len(words) <= 4 and all(re.match(r'^[A-Za-z\.\-]+$', w) for w in words):
                name = line.title()
                break

    # Email
    email_m = re.search(r'[\w\.\+\-]+@[\w\.\-]+\.\w{2,}', text)
    email = email_m.group(0) if email_m else ""

    # Phone
    phone_m = re.search(r'\+?\d[\d\s\-\(\)]{8,14}\d', text)
    phone = phone_m.group(0).strip() if phone_m else ""

    # Location
    location = ""
    for loc in ["bangalore", "bengaluru", "mumbai", "delhi", "hyderabad",
                "chennai", "pune", "kolkata", "kerala", "malappuram",
                "kochi", "thrissur", "calicut", "india", "remote"]:
        if re.search(r'\b' + loc + r'\b', text.lower()):
            location = loc.title()
            break

    # Skills — scan full text
    text_lower = text.lower()
    skills = []
    for skill in KNOWN_SKILLS:
        if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
            skills.append(skill.title() if " " not in skill else skill.title())
    skills = sorted(list(set(skills)))

    # Summary — first long paragraph
    summary = ""
    for para in re.split(r'\n\s*\n', text):
        para = para.strip()
        if len(para) > 80 and "@" not in para and not re.match(r'^[\+\d]', para):
            summary = re.sub(r'\s+', ' ', para)[:500]
            break

    # Experience years
    exp_m = re.search(r'(\d+)\+?\s*years?\s*(?:of\s*)?experience', text, re.IGNORECASE)
    exp_years = int(exp_m.group(1)) if exp_m else 0

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "location": location,
        "summary": summary,
        "skills": skills,
        "experience": [],
        "education": [],
        "certifications": [],
        "languages": [],
        "experience_years": exp_years,
    }


# ═══════════════════════════════════════════════════════════════════
# GEMINI PARSER — single efficient call
# ═══════════════════════════════════════════════════════════════════

def _call_gemini(resume_text: str):
    """
    Single Gemini API call — no retries, no waiting.
    Returns parsed dict or None if unavailable.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        print("⚠️  No GOOGLE_API_KEY in .env")
        return None

    try:
        from google import genai
        from google.genai import errors

        client = genai.Client(api_key=api_key)

        # Truncate to 4000 chars — enough for any resume, saves quota
        resume_snippet = resume_text[:4000]

        prompt = f"""Parse this resume and return ONLY a JSON object. 
No explanation. No markdown. No code fences. Just raw JSON.

Resume:
{resume_snippet}

Required JSON format:
{{
  "name": "full name here",
  "email": "email here",
  "phone": "phone here",
  "location": "city, country",
  "summary": "2-3 sentence professional summary",
  "skills": ["skill1", "skill2", "skill3"],
  "experience": [
    {{"title": "job title", "company": "company name", "duration": "date range", "description": "what they did"}}
  ],
  "education": [
    {{"degree": "degree name", "institution": "college name", "year": "year"}}
  ],
  "certifications": ["cert1"],
  "languages": ["English"],
  "experience_years": 0
}}"""

        print("🤖 Calling Gemini (gemini-2.0-flash)...")
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )

        raw = response.text.strip()

        # Clean any accidental markdown
        if "```" in raw:
            for part in raw.split("```"):
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    raw = part
                    break

        # Extract JSON if there's extra text
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)

        result = json.loads(raw)
        print(f"✅ Gemini parsed: {result.get('name')} | {len(result.get('skills', []))} skills")
        return result

    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            print("⚠️  Gemini rate limited — using local parser")
        elif "404" in err:
            print("⚠️  Gemini model not found — using local parser")
        else:
            print(f"⚠️  Gemini error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════════

def parse_resume(resume_text: str) -> dict:
    """
    Parse resume efficiently:
    1. Check cache — if same resume was parsed before, return instantly
    2. Call Gemini once — no retries, no long waits
    3. If Gemini fails — use local parser immediately
    4. Save result to cache for future calls
    """
    # Step 1: Check cache
    cache     = _get_cache()
    text_hash = _hash_text(resume_text)

    if text_hash in cache:
        print(f"✅ Cache hit! Returning saved result (hash: {text_hash[:8]}...)")
        return cache[text_hash]

    # Step 2: Try Gemini (one call only)
    result = _call_gemini(resume_text)

    # Step 3: Fall back to local if Gemini failed
    if result is None:
        result = _local_parse(resume_text)

    # Step 4: Ensure all required fields exist
    result = _normalize(result)

    # Step 5: Save to cache
    cache[text_hash] = result
    _save_cache(cache)
    print(f"💾 Result cached (hash: {text_hash[:8]}...)")

    return result


def _normalize(data: dict) -> dict:
    """Ensure all required fields exist with correct types."""
    return {
        "name":             str(data.get("name") or ""),
        "email":            str(data.get("email") or ""),
        "phone":            str(data.get("phone") or ""),
        "location":         str(data.get("location") or ""),
        "summary":          str(data.get("summary") or ""),
        "skills":           list(data.get("skills") or []),
        "experience":       list(data.get("experience") or []),
        "education":        list(data.get("education") or []),
        "certifications":   list(data.get("certifications") or []),
        "languages":        list(data.get("languages") or []),
        "experience_years": int(data.get("experience_years") or 0),
    }


# ─── Test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        from resume_extracter import extract_text
        text = extract_text(sys.argv[1])
        print(f"📄 Extracted {len(text)} characters from {sys.argv[1]}\n")
    else:
        text = """
AKHILA P
Python Developer
+91 9072554733 | akhilapadmanabhan2@gmail.com | Malappuram, Kerala

SUMMARY
Dedicated Python Developer with hands-on experience in Django and Machine Learning.
I enjoy learning new technologies and adapting to new challenges.

SKILLS
Python, Django, HTML, CSS, GitHub, Machine Learning, TensorFlow, MySQL, REST API

EXPERIENCE
Jan 2023 - Present | Python Developer | TechCorp Pvt Ltd
Built Django REST APIs and ML models for production systems.

EDUCATION
B.Tech Computer Science | NIT Calicut | 2022
        """

    result = parse_resume(text)

    print("\n=== PARSED RESULT ===")
    for k, v in result.items():
        print(f"  {k:20}: {v}")