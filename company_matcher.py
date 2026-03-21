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

def build_queries(skills: list) -> list:
    """
    Build multiple search queries from skills so we
    don't miss jobs by using only 1-2 keywords.

    Example:
      skills = [Python, Django, React, AWS, Docker]
      queries = [
        "Python Django Developer",
        "React Frontend Developer",
        "AWS Docker DevOps",
        "Python Developer",
      ]
    """
    # Categorize skills
    languages   = []
    frameworks  = []
    cloud_devops = []
    data_ml     = []
    other       = []

    lang_keywords    = {"python","java","javascript","typescript","c++","c#","ruby","php","swift","kotlin","go","rust","scala","r","dart"}
    framework_kw     = {"django","flask","fastapi","react","angular","vue","nextjs","nodejs","express","spring","laravel"}
    cloud_kw         = {"aws","azure","gcp","docker","kubernetes","terraform","ansible","devops","jenkins","ci/cd","linux"}
    data_kw          = {"machine learning","deep learning","tensorflow","pytorch","pandas","numpy","nlp","data science","scikit-learn","computer vision"}

    for skill in skills:
        sl = skill.lower()
        if sl in lang_keywords:
            languages.append(skill)
        elif sl in framework_kw:
            frameworks.append(skill)
        elif sl in cloud_kw:
            cloud_devops.append(skill)
        elif sl in data_kw:
            data_ml.append(skill)
        else:
            other.append(skill)

    queries = []

    # Primary query — top language + framework
    if languages and frameworks:
        queries.append(f"{languages[0]} {frameworks[0]} Developer")
    elif languages:
        queries.append(f"{languages[0]} Developer")
    elif frameworks:
        queries.append(f"{frameworks[0]} Developer")

    # Secondary — cloud/devops query
    if cloud_devops:
        queries.append(f"{' '.join(cloud_devops[:2])} Engineer")

    # Tertiary — data/ML query
    if data_ml:
        queries.append(f"{data_ml[0]} Engineer")

    # Fallback — use top 3 skills as one query
    if not queries:
        queries.append(" ".join(skills[:3]))

    # Always add a simple single-skill query for broader results
    if languages:
        queries.append(f"{languages[0]} Developer")

    # Deduplicate
    seen, unique = set(), []
    for q in queries:
        if q.lower() not in seen:
            seen.add(q.lower())
            unique.append(q)

    print(f"🔎 Search queries built: {unique}")
    return unique


# ═══════════════════════════════════════════════════════════════════
# MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════════

def get_best_matching_companies(skills: list, limit: int = 15) -> list:
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