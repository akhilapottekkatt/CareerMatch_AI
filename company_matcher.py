from typing import List, Dict


# Very simple in-memory "company database".
# In a real system, this would come from a database or an API.
COMPANY_DATABASE: List[Dict[str, object]] = [
    {
        "name": "TechSoft Solutions",
        "skills": ["python", "django", "fastapi", "machine learning"],
        "apply_url": "https://careers.techsoft.example/jobs/search?query=python",
    },
    {
        "name": "CloudNova",
        "skills": ["aws", "azure", "docker", "linux"],
        "apply_url": "https://jobs.cloudnova.example/search?type=cloud",
    },
    {
        "name": "DataSphere Analytics",
        "skills": ["sql", "data science", "machine learning"],
        "apply_url": "https://careers.datasphere.example/jobs?query=data",
    },
    {
        "name": "WebCraft Studios",
        "skills": ["html", "css", "javascript"],
        "apply_url": "https://jobs.webcraft.example/open-roles/frontend",
    },
    {
        "name": "DevOpsWorks",
        "skills": ["linux", "docker", "aws", "git", "github"],
        "apply_url": "https://devopsworks.example/careers",
    },
    {
        "name": "AI Labs",
        "skills": ["python", "machine learning", "data science"],
        "apply_url": "https://ailabs.example/jobs",
    },
]


def match_companies(skills: List[str], limit: int = 5) -> List[Dict[str, str]]:
    """
    Match up to `limit` companies whose required skills
    intersect with the skills extracted from the resume.
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

