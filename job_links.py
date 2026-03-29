"""
job_links.py
============
Master job scraper combining three sources:
1. JSearch API (RapidAPI)  — LinkedIn + Indeed results via API
2. RemoteOK API            — free, no key needed
3. Playwright              — Naukri direct scrape
"""
import os
import time
import random
import requests
from dotenv import load_dotenv
load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")


# ═══════════════════════════════════════════════════════════════════
# 1. JSEARCH API  (LinkedIn + Indeed via RapidAPI)
# ═══════════════════════════════════════════════════════════════════

def scrape_jsearch(query: str, location: str = "India", num_pages: int = 2) -> list:
    if not RAPIDAPI_KEY:
        print("⚠️  RAPIDAPI_KEY not set — skipping JSearch")
        return []

    jobs = []
    url  = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
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
            resp = requests.get(url, headers=headers, params=params, timeout=30)

            if resp.status_code == 403:
                print("❌ JSearch 403 — Not subscribed. Visit:")
                print("   https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch")
                print("   → Subscribe to Test → Basic (Free) → copy API key → add to .env")
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
                platform = "LinkedIn"     if "linkedin"          in apply_link.lower() else \
                           "Indeed"      if "indeed"            in apply_link.lower() else \
                           "Naukri"      if "naukri"            in apply_link.lower() else \
                           "Glassdoor"   if "glassdoor"         in apply_link.lower() else \
                           "Google Jobs" if "google_jobs_apply" in apply_link.lower() else \
                           "Company Site"
                jobs.append({
                    "title":       job.get("job_title", ""),
                    "company":     job.get("employer_name", ""),
                    "location":    job.get("job_city", "") or job.get("job_country", ""),
                    "url":         apply_link,
                    "description": job.get("job_description", "")[:500],
                    "platform":    platform,
                    "salary":      str(job.get("job_min_salary") or job.get("job_salary_period") or ""),
                    "job_type":    job.get("job_employment_type", ""),
                    "posted":      (job.get("job_posted_at_datetime_utc") or "")[:10],
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
        listings = [d for d in data if isinstance(d, dict) and d.get("position")]
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
# 3. PLAYWRIGHT SCRAPER — Naukri (fixed selectors)
# ═══════════════════════════════════════════════════════════════════

def scrape_naukri(query: str, location: str = "India") -> list:
    jobs = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️  Playwright not installed.")
        return []

    # Naukri URL format: /python-developer-jobs-in-india
    slug       = query.lower().replace(" ", "-")
    loc_slug   = location.lower().replace(" ", "-")
    search_url = f"https://www.naukri.com/{slug}-jobs-in-{loc_slug}"
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
                ]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-IN",
            )

            page = context.new_page()

            # Block images/fonts/media to load faster
            page.route(
                "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,mp4,webp}",
                lambda r: r.abort()
            )

            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(3):
                page.mouse.wheel(0, 3000)
                time.sleep(2)
            

            # ── Try multiple selectors (Naukri updates their HTML often) ──
            card_selectors = [
                ".srp-jobtuple-wrapper",   # old
                ".jobTuple",               # older
                "article.jobTupleHeader",  # alternative
                "[class*='jobTuple']",     # wildcard match
                ".job-container",   
                ".cust-job-tuple",       # fallback
                "div[type='tuple']",       # another variant
            ]

            cards = []
            used_selector = ""
            for sel in card_selectors:
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    cards = page.query_selector_all(sel)
                    if cards:
                        used_selector = sel
                        print(f"✅ Naukri: found {len(cards)} cards using '{sel}'")
                        break
                except Exception:
                    continue

            if not cards:
                # Last resort: dump page content to debug
                print("❌ Naukri: no job cards found with any selector")
                print("   Page title:", page.title())
                # Save screenshot for debugging
                page.screenshot(path="naukri_debug.png")
                print("   Screenshot saved: naukri_debug.png")
                browser.close()
                return []

            # ── Parse job cards ────────────────────────────────────
            title_selectors   = [".title", "a.title", ".jobTitle", "h2 a", "[class*='title']"]
            company_selectors = [".comp-name", ".companyName", "[class*='company']"]
            loc_selectors     = [".locWdth", ".location", "[class*='location']"]

            def try_get_text(card, selectors):
                for sel in selectors:
                    el = card.query_selector(sel)
                    if el:
                        txt = el.inner_text().strip()
                        if txt:
                            return txt
                return ""

            def try_get_href(card, selectors):
                for sel in selectors:
                    el = card.query_selector(sel)
                    if el:
                        href = el.get_attribute("href")
                        if href:
                            return href
                return ""

            for card in cards[:15]:
                try:
                    title   = try_get_text(card, title_selectors)
                    company = try_get_text(card, company_selectors)
                    loc     = try_get_text(card, loc_selectors) or location
                    url     = try_get_href(card, ["a.title", "a[title]", "a"])

                    if title:
                        jobs.append({
                            "title":       title,
                            "company":     company,
                            "location":    loc,
                            "url":         url if url.startswith("http") else f"https://www.naukri.com{url}",
                            "description": f"{title} at {company} in {loc}",
                            "platform":    "Naukri",
                            "salary":      "",
                            "job_type":    "Full-time",
                            "posted":      "",
                        })
                except Exception as e:
                    print(f"  ⚠️  Card parse error: {e}")
                    continue

            browser.close()

    except Exception as e:
        print(f"❌ Naukri Playwright error: {e}")

    print(f"✅ Naukri scraped {len(jobs)} jobs")
    return jobs


# ═══════════════════════════════════════════════════════════════════
# 4. REDIRECT LINK GENERATOR (Option B)
# ═══════════════════════════════════════════════════════════════════

import urllib.parse

def generate_redirect_links(query: str, location: str = "India") -> dict:
    full_query = f"{query} jobs {location}"
    formatted_query = urllib.parse.quote(full_query)

    linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={formatted_query}"
    indeed_url   = f"https://www.indeed.com/jobs?q={formatted_query}"

    return {
        "query": full_query,
        "linkedin": linkedin_url,
        "indeed": indeed_url
    }

# ═══════════════════════════════════════════════════════════════════
# MASTER FUNCTION
# ═══════════════════════════════════════════════════════════════════

def scrape_all_jobs(query: str, location: str = "India") -> list:
    print(f"\n{'='*50}")
    print(f"🚀 Scraping jobs for: '{query}' in {location}")
    print(f"{'='*50}")

    all_jobs = []

    try:
        all_jobs.extend(scrape_jsearch(query, location, num_pages=2))
    except Exception as e:
        print(f"❌ JSearch failed: {e}")

    try:
        all_jobs.extend(scrape_remoteok(query))
    except Exception as e:
        print(f"❌ RemoteOK failed: {e}")

    try:
        all_jobs.extend(scrape_naukri(query, location))
    except Exception as e:
        print(f"❌ Naukri failed: {e}")

    # Deduplicate by URL
    seen, unique = set(), []
    for job in all_jobs:
        url = job.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(job)
        elif not url:
            unique.append(job)

    print(f"\n✅ Total unique jobs: {len(unique)}")
    print(f"{'='*50}\n")
    return unique


# Backward-compat aliases used by main.py and indeed_scraper.py
def scrape_indeed_jobs(query: str, location: str = "India") -> list:
    return scrape_all_jobs(query, location)


if __name__ == "__main__":
    results = scrape_all_jobs("Python Developer", "India")
    for i, job in enumerate(results[:5], 1):
        print(f"{i}. [{job['platform']}] {job['title']} @ {job['company']} → {job['url']}")
