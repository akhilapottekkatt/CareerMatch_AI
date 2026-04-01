# company_matcher.py
"""
Fetches real jobs from multiple sources and computes
a real match score for each job against candidate skills.
"""
from job_links import scrape_jsearch, scrape_remoteok, scrape_linkedin


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


def build_queries_for_profile(skills: list, expected_roles: list, max_queries: int = 25) -> list:
    """
    Prefer **expected job roles** (profile "expected_roles") as search queries.
    If none are set, fall back to skill-derived queries from `build_queries`.
    """
    roles: list[str] = []
    for r in expected_roles or []:
        r = (r or "").strip()
        if r:
            roles.append(r)
    seen: set[str] = set()
    unique_roles: list[str] = []
    for r in roles:
        k = r.lower()
        if k not in seen:
            seen.add(k)
            unique_roles.append(r)
    if unique_roles:
        print(f"🔎 Using {len(unique_roles)} expected job profile(s) as search queries (skills used only for scoring)")
        return unique_roles[:max_queries]
    return build_queries(skills, [])[:max_queries]


def gather_union_queries_from_profiles(profiles: list[dict]) -> list[str]:
    """
    Build a deduplicated list of search strings from many user profiles
    (expected roles + skill-derived queries per `build_queries_for_profile`).
    """
    seen: set[str] = set()
    out: list[str] = []
    for fp in profiles:
        skills = fp.get("skills") or []
        roles = fp.get("expected_roles") or []
        if not skills and not roles:
            continue
        for q in build_queries_for_profile(skills, roles):
            ql = q.lower().strip()
            if ql and ql not in seen:
                seen.add(ql)
                out.append(q)
    return out


def _normalize_job_row(job: dict) -> dict:
    return {
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
    }


def fetch_global_job_pool(
    queries: list[str],
    location: str = "India",
    max_jobs: int = 300,
) -> list:
    """
    Fetch jobs once per unique query, merge, dedupe by apply_url.
    Used by the scheduler so **all users share one job pool**, then each user
    is scored against every job in that pool.
    """
    if not queries:
        return []

    print(f"\n🌐 Global job pool — {len(queries)} unique search query/queries, location={location!r}")

    all_jobs: list = []
    for query in queries:
        print(f"\n🔍 [Pool] Fetching jobs for: '{query}'")
        try:
            jsearch_jobs = scrape_jsearch(query, location=location, num_pages=2)
            all_jobs.extend(jsearch_jobs)
        except Exception as e:
            print(f"  ❌ JSearch failed: {e}")
        try:
            all_jobs.extend(scrape_remoteok(query))
        except Exception as e:
            print(f"  ❌ RemoteOK failed: {e}")
        try:
            li = scrape_linkedin(query, location=location, pages=1)
            all_jobs.extend(li)
            print(f"  ✅ LinkedIn: {len(li)} jobs")
        except Exception as e:
            print(f"  ❌ LinkedIn failed: {e}")

    normalized = [_normalize_job_row(j) for j in all_jobs]
    seen: set[str] = set()
    unique: list = []
    for job in normalized:
        url = job["apply_url"]
        if url and url not in seen:
            seen.add(url)
            unique.append(job)

    if len(unique) > max_jobs:
        unique = unique[:max_jobs]
    print(f"\n✅ Global pool: {len(unique)} unique jobs (cap {max_jobs})")
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

    # Search queries: expected job profiles first; else skill-derived queries
    all_queries = build_queries_for_profile(skills, expected_roles)

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
        try:
            li_jobs = scrape_linkedin(query, location=location, pages=1)
            all_jobs.extend(li_jobs)
            print(f"  ✅ LinkedIn: {len(li_jobs)} jobs")
        except Exception as e:
            print(f"  ❌ LinkedIn failed: {e}")

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
