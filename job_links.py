import urllib.parse
from typing import List


def generate_job_links(skills: List[str]) -> List[str]:
    """
    Generate dynamic job search links based on skills.

    Returns a list of URLs so the frontend can iterate
    directly over the links.
    """
    query = " ".join(skills)
    encoded_query = urllib.parse.quote(query)

    job_links = [
        f"https://www.linkedin.com/jobs/search/?keywords={encoded_query}",
        f"https://www.indeed.com/jobs?q={encoded_query}",
        f"https://www.naukri.com/{encoded_query}-jobs",
        f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={encoded_query}",
        f"https://www.monster.com/jobs/search?q={encoded_query}",
    ]

    return job_links
