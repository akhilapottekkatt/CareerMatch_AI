"""
LinkedIn jobs via public guest listing API + optional description fetch.
Adapted from the LinkedIn guest / jobs-guest HTML pattern (BeautifulSoup).

Note: LinkedIn markup and endpoints change; failures are handled gracefully.
"""

from __future__ import annotations

import os
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def _get_soup(
    url: str, headers: dict | None = None, timeout: int = 15, retries: int = 3
) -> BeautifulSoup | None:
    h = {**DEFAULT_HEADERS, **(headers or {})}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=h, timeout=timeout)
            if r.status_code != 200:
                time.sleep(0.6 * (attempt + 1))
                continue
            return BeautifulSoup(r.content, "html.parser")
        except requests.RequestException:
            time.sleep(0.6 * (attempt + 1))
    return None


def _parse_listing_cards(soup: BeautifulSoup | None) -> list[dict]:
    if not soup:
        return []
    jobs: list[dict] = []
    divs = soup.find_all("div", class_="base-search-card__info")
    for item in divs:
        try:
            h3 = item.find("h3")
            title = h3.get_text(strip=True) if h3 else ""
            company_a = item.find("a", class_="hidden-nested-link")
            company = (
                company_a.get_text(strip=True).replace("\n", " ") if company_a else ""
            )
            loc_el = item.find("span", class_="job-search-card__location")
            location = loc_el.get_text(strip=True) if loc_el else ""
            parent = item.parent
            entity_urn = parent.get("data-entity-urn") if parent else None
            if not entity_urn:
                continue
            job_posting_id = str(entity_urn).split(":")[-1]
            job_url = f"https://www.linkedin.com/jobs/view/{job_posting_id}/"
            date_tag = item.find("time", class_="job-search-card__listdate")
            date_tag_new = item.find("time", class_="job-search-card__listdate--new")
            dt = ""
            if date_tag and date_tag.get("datetime"):
                dt = date_tag["datetime"]
            elif date_tag_new and date_tag_new.get("datetime"):
                dt = date_tag_new["datetime"]
            jobs.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "date": dt,
                    "job_url": job_url,
                    "job_description": "",
                }
            )
        except Exception:
            continue
    return jobs


def _parse_description_html(soup: BeautifulSoup | None) -> str:
    if not soup:
        return ""
    div = soup.find("div", class_="description__text description__text--rich")
    if not div:
        div = soup.find("div", class_=lambda c: c and "description__text" in str(c))
    if not div:
        return ""
    for el in div.find_all(["span", "a"]):
        el.decompose()
    for ul in div.find_all("ul"):
        for li in ul.find_all("li"):
            li.insert(0, "-")
    text = div.get_text(separator="\n").strip()
    for noise in ("\n\n", "::marker", "Show less", "Show more"):
        text = text.replace(noise, " ")
    text = text.replace("-\n", "- ")
    return text.strip()


def scrape_linkedin_guest(
    query: str,
    location: str = "India",
    pages: int = 1,
    fetch_descriptions: bool = True,
    max_description_fetches: int = 12,
    delay_between_desc: float = 0.45,
) -> list[dict]:
    """
    Fetch LinkedIn job cards from the guest API HTML, optionally loading descriptions.

    Returns dicts aligned with job_links / company_matcher:
    title, company, location, url, description, platform, posted, job_type, salary
    """
    if not (query or "").strip():
        return []

    keywords = quote(query.strip())
    loc_q = quote(location.strip() or "India")
    out: list[dict] = []

    for page in range(max(1, int(pages))):
        start = 25 * page
        # Guest API returns HTML fragments of job cards
        url = f"{GUEST_SEARCH}?keywords={keywords}&location={loc_q}&start={start}&f_TPR=&geoId="
        soup = _get_soup(url)
        cards = _parse_listing_cards(soup)
        if not cards:
            break
        out.extend(cards)

    # Dedupe by job_url
    seen: set[str] = set()
    unique: list[dict] = []
    for j in out:
        u = j.get("job_url") or ""
        if u and u not in seen:
            seen.add(u)
            unique.append(j)

    # Descriptions (rate-limited)
    if fetch_descriptions and unique:
        n = min(len(unique), max_description_fetches)
        for i, job in enumerate(unique[:n]):
            soup = _get_soup(job["job_url"])
            job["job_description"] = _parse_description_html(soup) or job.get(
                "title", ""
            )
            if i < n - 1:
                time.sleep(delay_between_desc)
        for job in unique[n:]:
            job["job_description"] = (
                job.get("title", "") + " " + job.get("company", "")
            ).strip()

    # Map to app schema
    mapped: list[dict] = []
    for job in unique:
        desc = job.get("job_description") or ""
        posted = (job.get("date") or "")[:10]
        mapped.append(
            {
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "url": job.get("job_url", ""),
                "description": desc,
                "platform": "LinkedIn",
                "salary": "",
                "job_type": "Full-time",
                "posted": posted,
            }
        )

    if os.getenv("LINKEDIN_SCRAPE_DEBUG"):
        print(f"   → LinkedIn guest: {len(mapped)} jobs for query {query!r}")
    return mapped
