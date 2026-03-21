# job_matching.py  ← CREATE THIS FILE

def compute_job_match_score(job: dict, profile: dict) -> int:
    """
    Compare job description against candidate's skills.
    Returns score 0-100.
    """
    if not profile or not job:
        return 0

    job_text = (
        job.get("job_description", "") + " " +
        job.get("title", "")
    ).lower()

    skills = [s.lower() for s in profile.get("skills", [])]

    if not skills:
        return 0

    matched = sum(1 for skill in skills if skill in job_text)
    score   = int((matched / len(skills)) * 100)
    return min(score, 100)