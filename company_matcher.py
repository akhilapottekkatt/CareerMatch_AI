from typing import List, Dict, Any


# Very simple in-memory "company database".
# In a real system, this would come from a database or an API.
COMPANY_DATABASE: List[Dict[str, Any]] = [
    {
        "name": "TechSoft Solutions",
        "role": "Backend Engineer (Python/FastAPI)",
        "skills": ["python", "django", "fastapi", "machine learning"],
        "apply_url": "https://careers.techsoft.example/jobs/search?query=python",
    },
    {
        "name": "CloudNova",
        "role": "Cloud DevOps Engineer",
        "skills": ["aws", "azure", "docker", "linux"],
        "apply_url": "https://jobs.cloudnova.example/search?type=cloud",
    },
    {
        "name": "DataSphere Analytics",
        "role": "Data Scientist",
        "skills": ["sql", "data science", "machine learning"],
        "apply_url": "https://careers.datasphere.example/jobs?query=data",
    },
    {
        "name": "WebCraft Studios",
        "role": "Frontend Engineer",
        "skills": ["html", "css", "javascript"],
        "apply_url": "https://jobs.webcraft.example/open-roles/frontend",
    },
    {
        "name": "DevOpsWorks",
        "role": "DevOps Engineer",
        "skills": ["linux", "docker", "aws", "git", "github"],
        "apply_url": "https://devopsworks.example/careers",
    },
    {
        "name": "AI Labs",
        "role": "Machine Learning Engineer",
        "skills": ["python", "machine learning", "data science"],
        "apply_url": "https://ailabs.example/jobs",
    },
]


def get_best_matching_companies(
    skills: List[str],
    limit: int = 5,
    min_match_ratio: float = 0.8,
) -> List[Dict[str, Any]]:
    """
    Return up to `limit` companies whose required skills match
    at least `min_match_ratio` (e.g. 0.8 = 80%) of the company's
    required skills.
    """
    resume_skills = {s.lower() for s in skills}
    ranked: List[Dict[str, Any]] = []

    for company in COMPANY_DATABASE:
        company_skills = {s.lower() for s in company.get("skills", [])}
        if not company_skills:
            continue

        overlap = resume_skills.intersection(company_skills)
        match_ratio = len(overlap) / len(company_skills)

        if match_ratio >= min_match_ratio:
            ranked.append(
                {
                    "name": company["name"],
                    "role": company.get("role", ""),
                    "apply_url": company["apply_url"],
                    "match_score": int(match_ratio * 100),
                }
            )

    ranked.sort(key=lambda c: c.get("match_score", 0), reverse=True)
    return ranked[:limit]


def match_companies(skills: List[str], limit: int = 5) -> List[Dict[str, str]]:
    """
    Backwards-compatible helper used in older parts of the code.
    Simply returns up to `limit` companies that share at least
    one skill with the resume (no 80% filter).
    """
    resume_skills = {s.lower() for s in skills}
    matched: List[Dict[str, str]] = []

    for company in COMPANY_DATABASE:
        company_skills = {s.lower() for s in company.get("skills", [])}
        if resume_skills.intersection(company_skills):
            matched.append(
                {
                    "name": company["name"],
                    "apply_url": company["apply_url"],
                }
            )

        if len(matched) >= limit:
            break

    return matched


def send_resume_to_companies(
    file_path: str, companies: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """
    Pretend to send the resume file to each matched company.

    This is a stub implementation that *does not* actually
    send emails or submit forms. It simply marks each company
    as 'sent' so the frontend can show a clear status.
    """
    results: List[Dict[str, str]] = []

    for company in companies:
        results.append(
            {
                "name": company["name"],
                "apply_url": company["apply_url"],
                "status": "sent",
            }
        )

    return results

