from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://in.indeed.com")
    print(f"Title: {page.title()}")
    print(f"URL: {page.url}")
    browser.close()
    print("✅ Playwright working!")
