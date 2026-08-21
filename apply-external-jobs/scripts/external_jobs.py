#!/usr/bin/env python3
"""Search external job sources without depending on browser rendering."""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from urllib.request import Request, urlopen

import watcha_jobs


BONJOUR_URL = "https://bonjour.bio/jobs-mapping/jobs"
JOBRADAR_URL = "https://jobradar.cc/zh/jobs"
JOB_PATTERN = re.compile(
    r'\{\\"id\\":\\"([0-9a-f-]{36})\\",\\"teamSlug\\":\\"(.*?)\\",'
    r'\\"role\\":\\"(.*?)\\",\\"loc\\":\\"(.*?)\\"'
)
TEAM_PATTERN = re.compile(r'\\"team\\":\{\\"slug\\":\\"(.*?)\\",\\"name\\":\\"(.*?)\\"')


def decode_json_string(value):
    return json.loads(f'"{value}"')


def fetch_text(url):
    request = Request(url, headers={"Accept": "text/html", "User-Agent": "fanhan-job-agent/1.0"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8")


def normalize_bonjour(page, query="", limit=20):
    teams = {decode_json_string(slug): decode_json_string(name) for slug, name in TEAM_PATTERN.findall(page)}
    tokens = query.casefold().split()
    jobs = []
    seen = set()
    for job_id, raw_slug, raw_title, raw_location in JOB_PATTERN.findall(page):
        if job_id in seen:
            continue
        seen.add(job_id)
        slug = decode_json_string(raw_slug)
        title = decode_json_string(raw_title)
        location = decode_json_string(raw_location)
        company = teams.get(slug, slug)
        if tokens and not all(token in f"{company} {title} {location}".casefold() for token in tokens):
            continue
        job_url = f"{BONJOUR_URL}/{quote(job_id)}"
        jobs.append(
            {
                "id": job_id,
                "company": company,
                "team_slug": slug,
                "title": title,
                "location": location,
                "job_url": job_url,
                "application_url": f"{job_url}/apply",
            }
        )
    if not seen:
        raise ValueError("Bonjour public page contained no recognizable jobs")
    return {
        "source": "Bonjour",
        "source_url": BONJOUR_URL,
        "source_status": "searched",
        "reported_total_jobs": len(seen),
        "matched_jobs": len(jobs),
        "jobs": jobs[:limit],
    }


def jobradar_status():
    return {
        "source": "JobRadar",
        "source_url": JOBRADAR_URL,
        "source_status": "membership_required",
        "matched_jobs": None,
        "jobs": [],
        "note": "免费层只提供基础预览；完整岗位与投递入口需登录/会员。未获得合作 API 前不绕过该限制。",
    }


def unavailable(source, url, error):
    return {
        "source": source,
        "source_url": url,
        "source_status": "unavailable",
        "matched_jobs": 0,
        "jobs": [],
        "error": str(error),
    }


def search_all(query="", limit=20):
    def bonjour():
        return normalize_bonjour(fetch_text(BONJOUR_URL), query, limit)

    def watcha():
        return watcha_jobs.normalize(watcha_jobs.fetch_payload(), query, limit)

    sources = {"Bonjour": (BONJOUR_URL, bonjour), "Watcha": (watcha_jobs.JOBS_URL, watcha)}
    results = {}
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = {name: (url, executor.submit(loader)) for name, (url, loader) in sources.items()}
        for name, (url, future) in pending.items():
            try:
                results[name] = future.result()
            except Exception as error:
                results[name] = unavailable(name, url, error)
    results["JobRadar"] = jobradar_status()
    return {
        "query": query,
        "sources_attempted": ["Bonjour", "Watcha", "JobRadar"],
        "sources": [results[name] for name in ("Bonjour", "Watcha", "JobRadar")],
    }


def self_test():
    page = (
        r'{\"jobs\":[{\"id\":\"754a2bba-7f71-488a-b49a-c6da56483bf0\",'
        r'\"teamSlug\":\"demo\",\"role\":\"AI \u4ea7\u54c1\u7ecf\u7406\",'
        r'\"loc\":\"\u676d\u5dde\",\"team\":{\"slug\":\"demo\",'
        r'\"name\":\"Demo AI\"}}]}'
    )
    result = normalize_bonjour(page, "AI 产品", 10)
    assert result["reported_total_jobs"] == 1
    assert result["matched_jobs"] == 1
    assert result["jobs"][0]["company"] == "Demo AI"
    assert result["jobs"][0]["title"] == "AI 产品经理"
    assert result["jobs"][0]["application_url"].endswith("/apply")
    assert jobradar_status()["source_status"] == "membership_required"
    assert unavailable("Demo", "https://example.com", RuntimeError("timeout"))["source_status"] == "unavailable"
    print("external_jobs self-test: ok")


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
        print(json.dumps(search_all(args.query, args.limit), ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"source_status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
