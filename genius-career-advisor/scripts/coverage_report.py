#!/usr/bin/env python3
"""Check every catalog source and record why a job list was or was not read.

Daily search still uses a small browser budget. This command is the full pass:
HTTP first, then a browser check for every official site HTTP could not read.
JobRadar and 出海聘 are skipped.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import browser_jobs
import career_cache
import career_sources
import source_catalog


def _row(name, kind, url, method, collected, matched, complete, reason, checked_at, entry_url, examples):
    return {
        "name": name,
        "kind": kind,
        "catalog_url": url,
        "entry_url": entry_url or url,
        "read_method": method,
        "collected_count": collected,
        "matched_count": matched,
        "pagination_complete": complete,
        "failure_reason": reason,
        "checked_at": checked_at,
        "examples": examples,
    }


def _examples(jobs):
    samples = []
    for job in jobs[:3]:
        samples.append({"title": job.get("title"), "location": job.get("location"), "job_url": job.get("job_url")})
    return samples


def check_http(record: dict, query: str) -> tuple[dict, list[dict]]:
    checked_at = career_cache._stamp()
    name = record.get("name") or ""
    url = record.get("url") or ""
    kind = "official" if record.get("type") == "公司招聘官网" else "platform"
    if source_catalog.hidden_from_search(record) or record.get("access") == "会员主导":
        return _row(name, kind, url, "skipped", 0, 0, None, "login_or_restricted", checked_at, url, []), []
    try:
        if kind == "official":
            result = career_sources.read_official(record, query, 20, use_browser=False)
        else:
            result = career_sources.read_platform(record, query, 20)
    except Exception as error:
        result = career_sources.unavailable(name, url, error)
    jobs = result.get("jobs") or []
    if result.get("source_status") == "searched" and jobs:
        reason = "" if result.get("matched_jobs") else "collected_no_match"
        return _row(name, kind, url, "http", result.get("collected_count") or len(jobs), result.get("matched_jobs") or 0,
                    None, reason, checked_at, url, _examples(jobs)), jobs
    reason = career_cache.classify_failure(result.get("error"))
    if kind != "official":
        return _row(name, kind, url, "http", 0, 0, None, reason, checked_at, url, []), []
    return _row(name, kind, url, "http", 0, 0, None, "not_browser_checked", checked_at, url, []), []


def check_browser(record: dict, query: str) -> tuple[dict, list[dict]]:
    checked_at = career_cache._stamp()
    name = record.get("name") or ""
    url = record.get("url") or ""
    try:
        jobs = browser_jobs.browse_official(url, name, 12)
    except Exception as error:
        return _row(name, "official", url, "browser", 0, 0, False, career_cache.classify_failure(error), checked_at, url, []), []
    if not jobs:
        return _row(name, "official", url, "browser", 0, 0, False, "parser_gap", checked_at, url, []), []
    _chosen, total = career_sources.select_jobs(jobs, query, 12)
    reason = "" if total else "collected_no_match"
    return _row(name, "official", url, "browser", len(jobs), total, False, reason, checked_at, url, _examples(jobs)), jobs


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = source_catalog.load(source_catalog.DEFAULT_CATALOG)
    records = [record for record in payload.get("records") or [] if isinstance(record, dict)]
    rows = []
    stored_jobs = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(check_http, record, query) for record in records]
        for future in as_completed(futures):
            row, jobs = future.result()
            rows.append(row)
            stored_jobs[row["name"]] = jobs
            print(f"http\t{row['failure_reason'] or 'ok'}\t{row['collected_count']}\t{row['name']}", flush=True)
    pending = [record for record in records if any(row["name"] == record.get("name") and row["failure_reason"] == "not_browser_checked" for row in rows)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(check_browser, record, query): record for record in pending}
        for future in as_completed(futures):
            row, jobs = future.result()
            rows = [row if item["name"] == row["name"] else item for item in rows]
            stored_jobs[row["name"]] = jobs
            print(f"browser\t{row['failure_reason'] or 'ok'}\t{row['collected_count']}\t{row['name']}", flush=True)
    rows.sort(key=lambda item: (item["kind"], bool(item["failure_reason"]), item["name"]))
    report = {"query": query, "generated_at": career_cache._stamp(), "rows": rows}
    report_path = career_cache.cache_path().parent / "career-coverage.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cache = {"entries": {}}
    for row in rows:
        if row["kind"] != "official" or row["read_method"] == "skipped":
            continue
        career_cache.remember(
            cache, row["name"], catalog_url=row["catalog_url"], entry_url=row["entry_url"],
            read_method=row["read_method"], collected_count=row["collected_count"],
            pagination_complete=row["pagination_complete"], failure_reason="" if row["collected_count"] else row["failure_reason"],
            jobs=stored_jobs.get(row["name"]) or [], fetched_at=row["checked_at"],
        )
    career_cache.save(cache)
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
