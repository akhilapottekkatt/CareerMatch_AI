# from playwright.sync_api import sync_playwright
# import json, time, random
# from typing import List, Dict
# import requests

# def scrape_indeed_jobs(search_term: str, location: str = "India", max_jobs: int = 10) -> List[Dict]:
#     jobs = []
    
#     # Use SerpAPI/Google Jobs (Legal alternative - get free key)
#     try:
#         # Mock data first - replace with API later
#         mock_jobs = [
#             {"title": "Python Developer", "company": "Tech Corp", "location": "Bangalore", "link": "indeed.com/job1", "description": "Python, Django, 3+ years exp"},
#             {"title": "AI Engineer", "company": "Data Inc", "location": "Hyderabad", "link": "indeed.com/job2", "description": "ML, BERT, PyTorch experience"},
#             {"title": "Backend Developer", "company": "StartupX", "location": "Remote", "link": "indeed.com/job3", "description": "FastAPI, SQLAlchemy, Docker"}
#         ]
#         return mock_jobs[:max_jobs]
#     except:
#         pass
    
#     # Anti-block Playwright (backup)
#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         context = browser.new_context(
#             user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
#             viewport={'width': 1366, 'height': 768}
#         )
#         page = context.new_page()
        
#         # Block images/ads
#         def block_resources(route):
#             if route.request.resource_type in ["image", "stylesheet", "font"]:
#                 route.abort()
#             else:
#                 route.continue_()
#         page.route("**/*", block_resources)
        
#         search_url = f"https://in.indeed.com/jobs?q={search_term.replace(' ', '+')}&l={location}"
#         page.goto(search_url, wait_until="domcontentloaded")
#         time.sleep(random.uniform(2, 4))  # Human delay
        
#         # Updated selectors (Indeed changes frequently)
#         job_cards = page.query_selector_all("div[data-jk], .job_seen_beacon")
#         print(f"Found {len(job_cards)} job cards")
        
#         for card in job_cards[:max_jobs]:
#             try:
#                 title_elem = card.query_selector("h2 a[title], .jobTitle a")
#                 title = title_elem.inner_text() if title_elem else "N/A"
                
#                 company_elem = card.query_selector("[data-testid='company-name'], .companyName")
#                 company = company_elem.inner_text() if company_elem else "N/A"
                
#                 loc_elem = card.query_selector("[data-testid='job-location'], .companyLocation")
#                 location_text = loc_elem.inner_text() if loc_elem else "N/A"
                
#                 link_elem = card.query_selector("h2 a, a.jcs-JobTitle")
#                 link = f"https://in.indeed.com{link_elem.get_attribute('href')}" if link_elem else "N/A"
                
#                 jobs.append({
#                     "title": title, "company": company, "location": location_text, 
#                     "link": link, "description": f"{title} at {company}"
#                 })
#             except Exception as e:
#                 print(f"Card parse error: {e}")
#                 continue
        
#         browser.close()
#     return jobs[:max_jobs]

# if __name__ == "__main__":
#     jobs = scrape_indeed_jobs("python developer", max_jobs=5)
#     print(json.dumps(jobs, indent=2))

# indeed_scraper.py
# Backward-compatibility shim.
# All real scraping is now in job_scraper.py

# indeed_scraper.py — backward-compat shim
from job_links import scrape_all_jobs

def scrape_indeed_jobs(query: str, location: str = "India") -> list:
    return scrape_all_jobs(query, location)