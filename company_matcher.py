# company_matcher.py
"""
Fetches real jobs from multiple sources and computes
a real match score for each job against candidate skills.
"""
from job_links import scrape_jsearch, scrape_remoteok


# ═══════════════════════════════════════════════════════════════════
# MATCH SCORE — compares job vs candidate skills
# ═══════════════════════════════════════════════════════════════════

def compute_match_score(job: dict, skills: list) -> float:
    """
    Compare job title + description against candidate skills.
    Returns score between 0.0 and 1.0
    """
    if not skills:
        return 0.0

    job_text = (
        job.get("title", "") + " " +
        job.get("description", "") + " " +
        job.get("company", "")
    ).lower()

    matched = sum(1 for skill in skills if skill.lower() in job_text)
    score   = matched / len(skills)
    return round(min(score, 1.0), 2)


# ═══════════════════════════════════════════════════════════════════
# QUERY BUILDER — builds multiple smart queries from skills
# ═══════════════════════════════════════════════════════════════════

def build_queries(skills: list, expected_roles: list = []) -> list:
    """
    Build search queries from ALL skills + ALL expected roles.
    No hardcoded category lists — every skill is used directly.
    """
    queries = []

    # ── 1. ALL expected roles first (highest priority) ──
    for role in expected_roles:
        role = role.strip()
        if role:
            queries.append(role)

    # ── 2. Every single skill becomes its own query ──
    for skill in skills:
        skill = skill.strip()
        if skill:
            queries.append(f"{skill} Developer")
            queries.append(f"{skill} Engineer")

    # ── 3. Combine pairs of skills for richer queries ──
    for i in range(0, min(len(skills), 20), 2):
        pair = skills[i:i+2]
        if len(pair) == 2:
            queries.append(f"{pair[0]} {pair[1]} Developer")

    # ── 4. Combine top 3 skills into one broad query ──
    if len(skills) >= 3:
        queries.append(" ".join(skills[:3]) + " Developer")

    # ── 5. Deduplicate while preserving order ──
    seen, unique = set(), []
    for q in queries:
        ql = q.lower().strip()
        if ql and ql not in seen:
            seen.add(ql)
            unique.append(q)

    print(f"🔎 Total search queries: {len(unique)}")
    for q in unique:
        print(f"   → {q}")

    return unique


# ═══════════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════════

def get_best_matching_companies(skills: list, limit: int = 50) -> list:
    """
    Fetch jobs from multiple sources using multiple queries,
    then score each job against the candidate's full skill set.

    Returns top `limit` jobs sorted by match_score descending.
    """
    if not skills:
        return []

    queries  = build_queries(skills)
    all_jobs = []

    for query in queries:
        print(f"\n🔍 Fetching jobs for: '{query}'")

        # JSearch — LinkedIn + Indeed via RapidAPI
        try:
            jsearch_jobs = scrape_jsearch(query, location="India", num_pages=2)
            all_jobs.extend(jsearch_jobs)
            print(f"  ✅ JSearch: {len(jsearch_jobs)} jobs")
        except Exception as e:
            print(f"  ❌ JSearch failed: {e}")

        # RemoteOK — free remote jobs
        try:
            remote_jobs = scrape_remoteok(query)
            all_jobs.extend(remote_jobs)
            print(f"  ✅ RemoteOK: {len(remote_jobs)} jobs")
        except Exception as e:
            print(f"  ❌ RemoteOK failed: {e}")

    # Normalize key names
    normalized = []
    for job in all_jobs:
        normalized.append({
            "title":       job.get("title", ""),
            "company":     job.get("company", ""),
            "platform":    job.get("platform", ""),
            "apply_url":   job.get("url") or job.get("apply_url", ""),
            "location":    job.get("location", ""),
            "description": job.get("description", ""),
            "salary":      job.get("salary", ""),
            "job_type":    job.get("job_type", ""),
            "posted":      job.get("posted", ""),
            "match_score": 0.0,   # will be computed below
        })

    # Deduplicate by apply_url
    seen, unique = set(), []
    for job in normalized:
        url = job["apply_url"]
        if url and url not in seen:
            seen.add(url)
            unique.append(job)

    # Compute real match score for every job
    for job in unique:
        job["match_score"] = compute_match_score(job, skills)

    # Sort by match score — best first
    unique.sort(key=lambda x: x["match_score"], reverse=True)

    print(f"\n✅ Total unique jobs: {len(unique)}")
    print(f"🏆 Top match: {unique[0]['title']} @ {unique[0]['company']} → {unique[0]['match_score']*100:.0f}%" if unique else "")

    return unique[:limit]



def get_best_matching_companies_from_profile(profile: dict, limit: int = 50) -> list:
    """
    Fetch and score jobs using the full user profile from DB.
    Uses skills + expected_roles + job_type + preferred_location.
    """
    skills         = profile.get("skills", [])
    expected_roles = profile.get("expected_roles", [])
    job_type       = profile.get("job_type", "")
    pref_location  = profile.get("preferred_location", "")

    if not skills and not expected_roles:
        return []

    # Build queries from both skills AND expected roles
    all_queries = build_queries(skills)

    # Add expected roles as extra queries
    for role in expected_roles[:3]:
        if role and role not in all_queries:
            all_queries.append(role)

    all_jobs = []

    # Use "Remote" location if user prefers remote
    location = "Remote" if pref_location == "Remote" else "India"

    for query in all_queries:
        print(f"\n🔍 Fetching jobs for: '{query}'")
        try:
            jsearch_jobs = scrape_jsearch(query, location=location, num_pages=2)
            all_jobs.extend(jsearch_jobs)
        except Exception as e:
            print(f"  ❌ JSearch failed: {e}")
        try:
            remote_jobs = scrape_remoteok(query)
            all_jobs.extend(remote_jobs)
        except Exception as e:
            print(f"  ❌ RemoteOK failed: {e}")

    # Normalize
    normalized = []
    for job in all_jobs:
        normalized.append({
            "title":       job.get("title", ""),
            "company":     job.get("company", ""),
            "platform":    job.get("platform", ""),
            "apply_url":   job.get("url") or job.get("apply_url", ""),
            "location":    job.get("location", ""),
            "description": job.get("description", ""),
            "salary":      job.get("salary", ""),
            "job_type":    job.get("job_type", ""),
            "posted":      job.get("posted", ""),
            "match_score": 0.0,
        })

    # Deduplicate
    seen, unique = set(), []
    for job in normalized:
        url = job["apply_url"]
        if url and url not in seen:
            seen.add(url)
            unique.append(job)

    # Score each job against full profile skills
    for job in unique:
        job["match_score"] = compute_match_score(job, skills)

    # Filter by job_type if user specified one
    if job_type and job_type != "Any":
        filtered = [j for j in unique if job_type.lower() in j.get("job_type", "").lower()]
        unique   = filtered if filtered else unique  # fallback to all if filter removes everything

    unique.sort(key=lambda x: x["match_score"], reverse=True)
    print(f"\n✅ Total unique jobs from profile: {len(unique)}")
    return unique[:limit]
