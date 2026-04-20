"""
job_links.py
============
Job scrapers used by ``company_matcher`` (scheduler / on-demand matching):

1. JSearch API (RapidAPI)  — LinkedIn + Indeed via API
2. RemoteOK API            — free, no key needed
3. LinkedIn guest HTML     — public jobs-guest listings (+ optional description fetch)
"""

import os
import time
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

from app.linkedin_scraper import scrape_linkedin_guest


def scrape_linkedin(query: str, location: str = "India", pages: int = 1) -> list:
    """
    LinkedIn jobs via the public guest listing endpoint.
    Disable with env ``LINKEDIN_SCRAPE=0`` if needed.
    """
    if os.getenv("LINKEDIN_SCRAPE", "1").lower() in ("0", "false", "no"):
        print("   → LinkedIn scrape skipped (LINKEDIN_SCRAPE=0)")
        return []
    return scrape_linkedin_guest(query, location=location, pages=pages)


# ═══════════════════════════════════════════════════════════════════
# 1. JSEARCH API  (LinkedIn + Indeed via RapidAPI)
# ═══════════════════════════════════════════════════════════════════


def scrape_jsearch(query: str, location: str = "India", num_pages: int = 2) -> list:
    if not RAPIDAPI_KEY:
        print("⚠️  RAPIDAPI_KEY not set — skipping JSearch")
        return []

    jobs = []
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for page in range(1, num_pages + 1):
        params = {
            "query": f"{query} in {location}",
            "page": str(page),
            "num_pages": "1",
            "date_posted": "week",
            "employment_types": "FULLTIME",
        }
        try:
            print(f"🔍 JSearch page {page}: '{query}' in {location}")
            resp = requests.get(url, headers=headers, params=params, timeout=30)

            if resp.status_code == 403:
                print("❌ JSearch 403 — Not subscribed. Visit:")
                print("   https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch")
                print(
                    "   → Subscribe to Test → Basic (Free) → copy API key → add to .env"
                )
                return []

            if resp.status_code == 429:
                print("⚠️  JSearch rate limited. Waiting 30s...")
                time.sleep(30)
                continue

            if resp.status_code != 200:
                print(f"❌ JSearch error {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json().get("data", [])
            print(f"✅ JSearch returned {len(data)} jobs (page {page})")

            for job in data:
                apply_link = job.get("job_apply_link", "")
                platform = (
                    "LinkedIn"
                    if "linkedin" in apply_link.lower()
                    else (
                        "Indeed"
                        if "indeed" in apply_link.lower()
                        else (
                            "Naukri"
                            if "naukri" in apply_link.lower()
                            else (
                                "Glassdoor"
                                if "glassdoor" in apply_link.lower()
                                else (
                                    "Google Jobs"
                                    if "google_jobs_apply" in apply_link.lower()
                                    else "Company Site"
                                )
                            )
                        )
                    )
                )
                jobs.append(
                    {
                        "title": job.get("job_title", ""),
                        "company": job.get("employer_name", ""),
                        "location": job.get("job_city", "")
                        or job.get("job_country", ""),
                        "url": apply_link,
                        "description": job.get("job_description", "")[:500],
                        "platform": platform,
                        "salary": str(
                            job.get("job_min_salary")
                            or job.get("job_salary_period")
                            or ""
                        ),
                        "job_type": job.get("job_employment_type", ""),
                        "posted": (job.get("job_posted_at_datetime_utc") or "")[:10],
                    }
                )
            time.sleep(1)

        except Exception as e:
            print(f"❌ JSearch exception: {e}")

    return jobs


# ═══════════════════════════════════════════════════════════════════
# 2. REMOTEOK API  (free, no key needed)
# ═══════════════════════════════════════════════════════════════════


def scrape_remoteok(query: str) -> list:
    url = "https://remoteok.com/api"
    headers = {"User-Agent": "CareerMatchAI/1.0"}

    try:
        print(f"🔍 RemoteOK: searching '{query}'")
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            print(f"❌ RemoteOK error {resp.status_code}")
            return []

        data = resp.json()
        listings = [d for d in data if isinstance(d, dict) and d.get("position")]
        words = query.lower().split()
        matched = []

        for job in listings:
            title = (job.get("position") or "").lower()
            tags = " ".join(job.get("tags") or []).lower()
            if any(w in f"{title} {tags}" for w in words):
                matched.append(
                    {
                        "title": job.get("position", ""),
                        "company": job.get("company", ""),
                        "location": "Remote",
                        "url": job.get("url", ""),
                        "description": (job.get("description") or "")[:500],
                        "platform": "RemoteOK",
                        "salary": job.get("salary", ""),
                        "job_type": "Remote Full-time",
                        "posted": (job.get("date") or "")[:10],
                    }
                )

        print(f"✅ RemoteOK returned {len(matched)} matching jobs")
        return matched[:15]

    except Exception as e:
        print(f"❌ RemoteOK exception: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════
# REDIRECT LINK GENERATOR
# ═══════════════════════════════════════════════════════════════════


def generate_redirect_links(query: str, location: str = "India") -> dict:
    full_query = f"{query} jobs {location}"
    formatted_query = urllib.parse.quote(full_query)

    linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={formatted_query}"
    indeed_url = f"https://www.indeed.com/jobs?q={formatted_query}"

    return {"query": full_query, "linkedin": linkedin_url, "indeed": indeed_url}
