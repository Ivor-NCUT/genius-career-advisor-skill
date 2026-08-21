#!/usr/bin/env python3
"""Read Watcha's public jobs feed without relying on its SPA page title."""

import argparse
import json
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen


API_URL = "https://watcha.cn/jobs-api/v1/public/teams"
JOBS_URL = "https://watcha.cn/study/jobs"


def fetch_payload():
    request = Request(API_URL, headers={"Accept": "application/json", "User-Agent": "fanhan-job-agent/1.0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def normalize(payload, query="", limit=20):
    teams = payload.get("teams")
    if not isinstance(teams, list):
        raise ValueError("Watcha response has no teams list")

    tokens = query.casefold().split()
    all_jobs = []
    for team in teams:
        team_slug = str(team.get("slug") or "").strip()
        if not team_slug or not isinstance(team.get("jobs"), list):
            continue
        team_label = str(team.get("name") or team.get("watchaProductSlug") or team_slug)
        for job in team["jobs"]:
            if job.get("status") not in (None, "published"):
                continue
            job_slug = str(job.get("pathSlug") or job.get("slug") or "").strip()
            title = str(job.get("title") or "").strip()
            if not job_slug or not title:
                continue
            sections = job.get("sections") if isinstance(job.get("sections"), list) else []
            searchable = " ".join(
                str(value)
                for value in (
                    team_label,
                    title,
                    job.get("direction", ""),
                    job.get("summary", ""),
                    job.get("salaryText", ""),
                    job.get("cities", []),
                    job.get("employmentTypes", []),
                    job.get("tags", []),
                    sections,
                )
            ).casefold()
            if tokens and not all(token in searchable for token in tokens):
                continue
            all_jobs.append(
                {
                    "id": job.get("id"),
                    "company": team_label,
                    "team_slug": team_slug,
                    "title": title,
                    "cities": job.get("cities") or [],
                    "employment_types": job.get("employmentTypes") or [],
                    "direction": job.get("direction") or "",
                    "work_mode": job.get("workMode") or "",
                    "salary": job.get("salaryText") or "",
                    "summary": job.get("summary") or "",
                    "job_url": f"{JOBS_URL}/{quote(team_slug)}/{quote(job_slug)}",
                    "application_url": job.get("externalApplyUrl") or f"{JOBS_URL}/{quote(team_slug)}/{quote(job_slug)}",
                }
            )

    return {
        "source": "Watcha",
        "source_url": JOBS_URL,
        "api_url": API_URL,
        "source_status": "searched",
        "reported_total_jobs": payload.get("totalJobs"),
        "matched_jobs": len(all_jobs),
        "jobs": all_jobs[:limit],
    }


def self_test():
    payload = {
        "totalJobs": 2,
        "teams": [
            {
                "slug": "demo-team",
                "watchaProductSlug": "Demo Team",
                "jobs": [
                    {"id": 1, "pathSlug": "job-1", "title": "AI 产品经理", "cities": ["杭州"], "status": "published"},
                    {"id": 2, "pathSlug": "job-2", "title": "后端工程师", "status": "published"},
                ],
            }
        ],
    }
    result = normalize(payload, "产品 经理", 10)
    assert result["reported_total_jobs"] == 2
    assert result["matched_jobs"] == 1
    assert result["jobs"][0]["company"] == "Demo Team"
    assert result["jobs"][0]["job_url"] == "https://watcha.cn/study/jobs/demo-team/job-1"
    try:
        normalize({})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid payload was accepted")
    print("watcha_jobs self-test: ok")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        print(json.dumps(normalize(fetch_payload(), args.query, args.limit), ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"source": "Watcha", "source_status": "unavailable", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
