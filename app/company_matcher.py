# company_matcher.py
"""
Fetches real jobs from multiple sources and computes
a real match score for each job against candidate skills.
"""

from sklearn.metrics.pairwise import cosine_similarity

from app.job_links import scrape_jsearch, scrape_remoteok, scrape_linkedin

# ═══════════════════════════════════════════════════════════════════
# SEMANTIC SCORE — BERT embeddings + cosine similarity
# ═══════════════════════════════════════════════════════════════════

_sentence_model = None


def _get_model():
    global _sentence_model
    if _sentence_model is None:
        from sentence_transformers import SentenceTransformer

        print("🤖 Loading SentenceTransformer for profile matching...")
        _sentence_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _sentence_model


def _profile_to_text(profile: dict) -> str:
    skills = [str(s).strip() for s in (profile.get("skills") or []) if str(s).strip()]
    roles = [
        str(r).strip() for r in (profile.get("expected_roles") or []) if str(r).strip()
    ]
    exp = profile.get("experience_years", "")
    location = profile.get("preferred_location", "")
    job_type = profile.get("job_type", "")
    return (
        f"Expected roles: {', '.join(roles)}. "
        f"Skills: {', '.join(skills)}. "
        f"Experience years: {exp}. "
        f"Preferred location: {location}. "
        f"Job type: {job_type}."
    ).strip()


def _score_jobs_semantic(profile: dict, jobs: list[dict]) -> list[dict]:
    """
    Semantic ranking using BERT embeddings and cosine similarity
    between profile text and each job title+description+company.
    """
    if not jobs:
        return jobs
    profile_text = _profile_to_text(profile)
    if not profile_text:
        for j in jobs:
            j["match_score"] = 0.0
        return jobs

    model = _get_model()
    profile_emb = model.encode([profile_text])
    job_texts = [
        (
            (j.get("title", "") or "")
            + " "
            + (j.get("description", "") or "")
            + " "
            + (j.get("company", "") or "")
        ).strip()
        for j in jobs
    ]
    job_embs = model.encode(job_texts)
    sims = cosine_similarity(profile_emb, job_embs)[0]
    for idx, score in enumerate(sims):
        jobs[idx]["match_score"] = round(float(score), 3)
    return jobs


# ═══════════════════════════════════════════════════════════════════
# QUERY BUILDER — expected job roles only
# ═══════════════════════════════════════════════════════════════════


def build_queries_for_profile(
    _skills: list, expected_roles: list, max_queries: int = 25
) -> list:
    """
    Search queries come **only** from expected job roles (no skill combinations).
    The first argument is unused but kept so callers can pass ``(skills, roles)``.
    Returns [] if the user has not set any roles.
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
        print(f"🔎 Using {len(unique_roles)} expected job role(s) as search queries")
        return unique_roles[:max_queries]
    return []


def gather_union_queries_from_profiles(profiles: list[dict]) -> list[str]:
    """
    Build a deduplicated list of search strings from **expected_roles** on each profile.
    Profiles with no roles contribute nothing (skills are not expanded into queries).
    """
    seen: set[str] = set()
    out: list[str] = []
    for fp in profiles:
        skills = fp.get("skills") or []
        roles = fp.get("expected_roles") or []
        if not roles:
            continue
        for q in build_queries_for_profile(skills, roles):
            ql = q.lower().strip()
            if ql and ql not in seen:
                seen.add(ql)
                out.append(q)
    return out


def _normalize_job_row(job: dict) -> dict:
    return {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "platform": job.get("platform", ""),
        "apply_url": job.get("url") or job.get("apply_url", ""),
        "location": job.get("location", ""),
        "description": job.get("description", ""),
        "salary": job.get("salary", ""),
        "job_type": job.get("job_type", ""),
        "posted": job.get("posted", ""),
        "match_score": 0.0,
    }


def fetch_global_job_pool(
    queries: list[str],
    location: str = "India",
    max_jobs: int = 300,
) -> list:
    """
    Fetch jobs once per unique query, merge, dedupe by apply_url.
    Used by the scheduler: the pool is written to the ``jobs`` table, then each
    user is scored against that catalog in a separate match phase.
    """
    if not queries:
        return []

    print(
        f"\n🌐 Global job pool — {len(queries)} unique search query/queries, location={location!r}"
    )

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


def get_best_matching_companies_from_profile(profile: dict, limit: int = 50) -> list:
    """
    Fetch and score jobs using the full user profile from DB.
    Search uses expected_roles for fetch query generation.
    Ranking uses semantic similarity via BERT embeddings + cosine similarity.
    """
    skills = profile.get("skills", [])
    expected_roles = profile.get("expected_roles", [])
    job_type = profile.get("job_type", "")
    pref_location = profile.get("preferred_location", "")

    if not expected_roles:
        print("ℹ️  No expected job roles on profile — skipping job fetch")
        return []

    all_queries = build_queries_for_profile(skills, expected_roles)
    if not all_queries:
        return []

    location = "Remote" if pref_location == "Remote" else "India"
    unique = fetch_global_job_pool(all_queries, location=location, max_jobs=limit)

    unique = _score_jobs_semantic(profile, unique)

    # Filter by job_type if user specified one
    if job_type and job_type != "Any":
        filtered = [
            j for j in unique if job_type.lower() in j.get("job_type", "").lower()
        ]
        unique = (
            filtered if filtered else unique
        )  # fallback to all if filter removes everything

    unique.sort(key=lambda x: x["match_score"], reverse=True)
    print(f"\n✅ Total unique jobs from profile: {len(unique)}")
    return unique[:limit]
