"""
job_links.py
============
Master job scraper combining four sources:
1. JSearch API  (RapidAPI)  — LinkedIn + Indeed via API
2. RemoteOK API             — free, no key needed
3. Playwright               — Naukri direct scrape
4. LinkedIn Guest API       — direct unofficial scrape (fallback)
"""
import os
import time
import random
import requests
import urllib.parse
from urllib.parse import quote
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException

load_dotenv()
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")


# ═══════════════════════════════════════════════════════════════════
# 1. JSEARCH API  (LinkedIn + Indeed via RapidAPI)
# ═══════════════════════════════════════════════════════════════════

def scrape_jsearch(query: str, location: str = "India",
                   num_pages: int = 2) -> list:
    if not RAPIDAPI_KEY:
        print("⚠️  RAPIDAPI_KEY not set — skipping JSearch")
        return []

    jobs    = []
    url     = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for page in range(1, num_pages + 1):
        params = {
            "query":            f"{query} in {location}",
            "page":             str(page),
            "num_pages":        "1",
            "date_posted":      "week",
            "employment_types": "FULLTIME",
        }
        try:
            print(f"🔍 JSearch page {page}: '{query}' in {location}")
            resp = requests.get(url, headers=headers,
                                params=params, timeout=30)

            if resp.status_code == 403:
                print("❌ JSearch 403 — not subscribed to RapidAPI plan.")
                return []
            if resp.status_code == 429:
                print("⚠️  JSearch rate limited — waiting 30s...")
                time.sleep(30)
                continue
            if resp.status_code != 200:
                print(f"❌ JSearch error {resp.status_code}: "
                      f"{resp.text[:200]}")
                continue

            data = resp.json().get("data", [])
            print(f"✅ JSearch returned {len(data)} jobs (page {page})")

            for job in data:
                apply_link = job.get("job_apply_link", "")
                platform = (
                    "LinkedIn"     if "linkedin"          in apply_link.lower() else
                    "Indeed"       if "indeed"            in apply_link.lower() else
                    "Naukri"       if "naukri"            in apply_link.lower() else
                    "Glassdoor"    if "glassdoor"         in apply_link.lower() else
                    "Google Jobs"  if "google_jobs_apply" in apply_link.lower() else
                    "Company Site"
                )
                jobs.append({
                    "title":       job.get("job_title", ""),
                    "company":     job.get("employer_name", ""),
                    "location":    (job.get("job_city", "")
                                   or job.get("job_country", "")),
                    "url":         apply_link,
                    "description": job.get("job_description", "")[:500],
                    "platform":    platform,
                    "salary":      str(job.get("job_min_salary")
                                      or job.get("job_salary_period") or ""),
                    "job_type":    job.get("job_employment_type", ""),
                    "posted":      (job.get("job_posted_at_datetime_utc")
                                   or "")[:10],
                })
            time.sleep(1)

        except Exception as e:
            print(f"❌ JSearch exception: {e}")

    return jobs


# ═══════════════════════════════════════════════════════════════════
# 2. REMOTEOK API  (free, no key needed)
# ═══════════════════════════════════════════════════════════════════

def scrape_remoteok(query: str) -> list:
    url     = "https://remoteok.com/api"
    headers = {"User-Agent": "CareerMatchAI/1.0"}

    try:
        print(f"🔍 RemoteOK: searching '{query}'")
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            print(f"❌ RemoteOK error {resp.status_code}")
            return []

        data     = resp.json()
        listings = [d for d in data
                    if isinstance(d, dict) and d.get("position")]
        words    = query.lower().split()
        matched  = []

        for job in listings:
            title = (job.get("position") or "").lower()
            tags  = " ".join(job.get("tags") or []).lower()
            if any(w in f"{title} {tags}" for w in words):
                matched.append({
                    "title":       job.get("position", ""),
                    "company":     job.get("company", ""),
                    "location":    "Remote",
                    "url":         job.get("url", ""),
                    "description": (job.get("description") or "")[:500],
                    "platform":    "RemoteOK",
                    "salary":      job.get("salary", ""),
                    "job_type":    "Remote Full-time",
                    "posted":      (job.get("date") or "")[:10],
                })

        print(f"✅ RemoteOK returned {len(matched)} matching jobs")
        return matched[:15]

    except Exception as e:
        print(f"❌ RemoteOK exception: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════
# 3. PLAYWRIGHT SCRAPER — Naukri
# ═══════════════════════════════════════════════════════════════════

def scrape_naukri(query: str, location: str = "India") -> list:
    jobs = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️  Playwright not installed — skipping Naukri")
        return []

    slug       = query.lower().replace(" ", "-")
    loc_slug   = location.lower().replace(" ", "-")
    search_url = (f"https://www.naukri.com/"
                  f"{slug}-jobs-in-{loc_slug}")
    print(f"🔍 Naukri: {search_url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-IN",
            )
            page = context.new_page()
            page.route(
                "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,mp4,webp}",
                lambda r: r.abort(),
            )
            page.goto(search_url,
                      wait_until="domcontentloaded", timeout=30000)
            for _ in range(3):
                page.mouse.wheel(0, 3000)
                time.sleep(2)

            card_selectors = [
                ".srp-jobtuple-wrapper",
                ".jobTuple",
                "article.jobTupleHeader",
                "[class*='jobTuple']",
                ".job-container",
                ".cust-job-tuple",
                "div[type='tuple']",
            ]
            cards, used_selector = [], ""
            for sel in card_selectors:
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    cards = page.query_selector_all(sel)
                    if cards:
                        used_selector = sel
                        print(f"✅ Naukri: {len(cards)} cards "
                              f"using '{sel}'")
                        break
                except Exception:
                    continue

            if not cards:
                print("❌ Naukri: no job cards found")
                page.screenshot(path="naukri_debug.png")
                browser.close()
                return []

            title_sel   = [".title", "a.title", ".jobTitle",
                           "h2 a", "[class*='title']"]
            company_sel = [".comp-name", ".companyName",
                           "[class*='company']"]
            loc_sel     = [".locWdth", ".location",
                           "[class*='location']"]

            def try_text(card, sels):
                for s in sels:
                    el = card.query_selector(s)
                    if el:
                        t = el.inner_text().strip()
                        if t:
                            return t
                return ""

            def try_href(card, sels):
                for s in sels:
                    el = card.query_selector(s)
                    if el:
                        h = el.get_attribute("href")
                        if h:
                            return h
                return ""

            for card in cards[:15]:
                try:
                    title   = try_text(card, title_sel)
                    company = try_text(card, company_sel)
                    loc     = try_text(card, loc_sel) or location
                    url     = try_href(card,
                                       ["a.title", "a[title]", "a"])
                    if title:
                        jobs.append({
                            "title":    title,
                            "company":  company,
                            "location": loc,
                            "url":      (url if url.startswith("http")
                                         else
                                         f"https://www.naukri.com{url}"),
                            "description": f"{title} at {company} in {loc}",
                            "platform": "Naukri",
                            "salary":   "",
                            "job_type": "Full-time",
                            "posted":   "",
                        })
                except Exception as e:
                    print(f"  ⚠️  Card parse error: {e}")

            browser.close()

    except Exception as e:
        print(f"❌ Naukri Playwright error: {e}")

    print(f"✅ Naukri scraped {len(jobs)} jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════════
# 4. LINKEDIN GUEST API  (direct, no key needed — unofficial)
# ═══════════════════════════════════════════════════════════════════

def _safe_detect(text: str) -> str:
    try:
        return detect(text)
    except LangDetectException:
        return "en"


def _parse_linkedin_cards(soup) -> list:
    jobs = []
    try:
        divs = soup.find_all("div", class_="base-search-card__info")
    except Exception:
        return jobs

    for item in divs:
        title    = item.find("h3")
        company  = item.find("a", class_="hidden-nested-link")
        location = item.find("span",
                             class_="job-search-card__location")
        parent   = item.parent
        try:
            urn    = parent["data-entity-urn"]
            job_id = urn.split(":")[-1]
            job_url = (f"https://www.linkedin.com"
                       f"/jobs/view/{job_id}/")
        except (KeyError, IndexError):
            continue

        date_new = item.find(
            "time", class_="job-search-card__listdate--new")
        date_old = item.find(
            "time", class_="job-search-card__listdate")
        date = (date_old["datetime"] if date_old else
                date_new["datetime"] if date_new else "")

        jobs.append({
            "title":       title.text.strip() if title else "",
            "company":     (company.text.strip().replace("\n", " ")
                            if company else ""),
            "location":    location.text.strip() if location else "",
            "url":         job_url,
            "description": "",
            "platform":    "LinkedIn",
            "salary":      "",
            "job_type":    "",
            "posted":      date,
        })
    return jobs


def _get_linkedin_description(job_url: str,
                               headers: dict) -> str:
    try:
        resp = requests.get(job_url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.content, "html.parser")
        div  = soup.find("div",
                         class_="description__text "
                                "description__text--rich")
        if not div:
            return ""
        for el in div.find_all(["span", "a"]):
            el.decompose()
        return div.get_text(separator="\n").strip()[:500]
    except Exception:
        return ""


def scrape_linkedin_direct(query: str,
                            location: str = "India",
                            pages: int = 2) -> list:
    """
    Scrapes LinkedIn via the unofficial guest jobs API.
    No API key required. May be blocked by LinkedIn — use as fallback.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    all_jobs = []
    kw  = quote(query)
    loc = quote(location)

    for i in range(pages):
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/"
            f"seeMoreJobPostings/search?"
            f"keywords={kw}&location={loc}"
            f"&f_WT=2&start={25 * i}"
        )
        try:
            print(f"🔍 LinkedIn direct page {i+1}: '{query}'")
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"❌ LinkedIn direct error {resp.status_code}")
                break
            soup = BeautifulSoup(resp.content, "html.parser")
            cards = _parse_linkedin_cards(soup)
            print(f"✅ LinkedIn direct: {len(cards)} cards")

            # Fetch descriptions (throttled)
            for job in cards:
                job["description"] = _get_linkedin_description(
                    job["url"], headers
                )
                time.sleep(random.uniform(1.0, 2.5))

            all_jobs.extend(cards)
            time.sleep(random.uniform(2, 4))

        except Exception as e:
            print(f"❌ LinkedIn direct exception: {e}")
            break

    print(f"✅ LinkedIn direct total: {len(all_jobs)} jobs")
    return all_jobs


# ═══════════════════════════════════════════════════════════════════
# 5. REDIRECT LINK GENERATOR  (fallback — open browser search)
# ═══════════════════════════════════════════════════════════════════

import urllib.parse

def generate_redirect_links(query: str, location: str = "India") -> dict:
    search_query = f"{query} jobs {location}"
    fq = urllib.parse.quote(search_query)

    return {
        "query": search_query,
        "linkedin": f"https://www.linkedin.com/jobs/search/?keywords={fq}&location={location}",
        "indeed": f"https://www.indeed.com/jobs?q={fq}&l={location}",
        "naukri": f"https://www.naukri.com/{query.lower().replace(' ','-')}-jobs-in-{location.lower().replace(' ','-')}",
    }


# ═══════════════════════════════════════════════════════════════════
# MASTER FUNCTION
# ═══════════════════════════════════════════════════════════════════

def scrape_all_jobs(query: str, location: str = "India") -> list:
    print(f"\n{'='*55}")
    print(f"🚀 Scraping: '{query}' in {location}")
    print(f"{'='*55}")

    all_jobs = []

    # 1 — JSearch (LinkedIn + Indeed via RapidAPI)
    # try:
    #     all_jobs.extend(scrape_jsearch(query, location, num_pages=2))
    # except Exception as e:
    #     print(f"❌ JSearch failed: {e}")

    # 2 — RemoteOK (free API)
    try:
        all_jobs.extend(scrape_remoteok(query))
    except Exception as e:
        print(f"❌ RemoteOK failed: {e}")

    # 3 — Naukri (Playwright)
    try:
        all_jobs.extend(scrape_naukri(query, location))
    except Exception as e:
        print(f"❌ Naukri failed: {e}")

    # 4 — LinkedIn direct guest API (fallback if JSearch empty)
    linkedin_count = sum(
        1 for j in all_jobs if j.get("platform") == "LinkedIn"
    )
    if linkedin_count == 0:
        print("ℹ️  No LinkedIn jobs from JSearch — "
              "trying direct LinkedIn scraper...")
        try:
            all_jobs.extend(
                scrape_linkedin_direct(query, location, pages=2)
            )
        except Exception as e:
            print(f"❌ LinkedIn direct failed: {e}")

    # Deduplicate by URL
    seen, unique = set(), []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(job)
        elif not url:
            unique.append(job)

    # Summary by platform
    from collections import Counter
    counts = Counter(j.get("platform", "Unknown") for j in unique)
    print(f"\n✅ Total unique jobs: {len(unique)}")
    for platform, count in counts.most_common():
        print(f"   {platform}: {count}")
    print(f"{'='*55}\n")

    return unique


# Backward-compat alias
def scrape_indeed_jobs(query: str,
                        location: str = "India") -> list:
    return scrape_all_jobs(query, location)


if __name__ == "__main__":
    results = scrape_all_jobs("Python Developer", "India")
    for i, job in enumerate(results[:5], 1):
        print(f"{i}. [{job['platform']}] {job['title']} "
              f"@ {job['company']} → {job['url']}")