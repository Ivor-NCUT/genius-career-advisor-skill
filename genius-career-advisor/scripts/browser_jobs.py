#!/usr/bin/env python3
"""Load an official career page in headless Chrome when HTTP has no job list.

This is only a fallback for company career sites. It follows a public
加入我们 / 招聘 link, waits for the list, and reads title, location, and
detail URL. It does not open the system browser and does not log in.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

from career_sources import (
    BROAD_ROLE,
    GENERIC_TITLE,
    SPECIFIC_JOB_URL,
    STRONG_ROLE,
    _skipped_host,
    job_record,
)


JOBISH = re.compile(r"/job/|jobid=|job_id=|jobdesc|position/detail", re.I)
JOIN_LINK = re.compile(
    r"加入我们|社会招聘|校园招聘|在招职位|查看职位|开放职位|工作机会|"
    r"join us|we.?re hiring|view (?:open )?jobs|open roles|see jobs",
    re.I,
)
PLACE = re.compile(r"市|省|区|Remote|远程|北京|上海|杭州|深圳|广州|成都|新加坡|美国")
SKIP_LINE = re.compile(r"^(急|分享|新|热)$|发布于|^\d{4}-\d{2}-\d{2}$")
MAX_PAGES = 4


def _compact(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", collapsed)


def _lines(text: str) -> list[str]:
    lines = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line or SKIP_LINE.search(line) or GENERIC_TITLE.match(line):
            continue
        if line in {"全职", "兼职", "实习", "其他"}:
            continue
        lines.append(line)
    return lines


def _absolute(href: str, base_url: str) -> str:
    if not href or href.startswith(("javascript:", "mailto:", "tel:")):
        return ""
    return urljoin(base_url or "", href.strip())


def jobs_from_anchors(anchors: list[dict], company: str, base_url: str, limit: int) -> list[dict]:
    found = []
    seen = set()
    for anchor in anchors:
        href = _absolute(str(anchor.get("href") or ""), base_url)
        if not href.startswith(("http://", "https://")) or _skipped_host(href):
            continue
        host = urlparse(href).netloc.casefold()
        if "jobradar" in host or "chuhaipin" in host:
            continue
        lines = _lines(str(anchor.get("text") or ""))
        title = ""
        location = ""
        for line in lines:
            role = bool(STRONG_ROLE.search(line) or BROAD_ROLE.search(line))
            if not title and role and len(line) <= 80:
                title = line
                continue
            if title and not location and PLACE.search(line) and len(line) <= 40:
                location = line
        if not title or not (JOBISH.search(href) or SPECIFIC_JOB_URL.search(href)):
            continue
        if href in seen:
            continue
        seen.add(href)
        found.append(job_record(company, title, location, href, href))
        if len(found) >= limit:
            break
    return found


def career_links(anchors: list[dict], base_url: str) -> list[str]:
    found = []
    seen = set()
    for anchor in anchors:
        text = _compact(anchor.get("text") or "")
        if not JOIN_LINK.search(text):
            continue
        href = _absolute(str(anchor.get("href") or ""), base_url)
        if not href.startswith(("http://", "https://")) or href in seen or _skipped_host(href):
            continue
        host = urlparse(href).netloc.casefold()
        if "jobradar" in host or "chuhaipin" in host:
            continue
        seen.add(href)
        found.append(href)
    return found


def next_list_url(url: str) -> str:
    """Advance a page=N query in either the hash or the main query string."""
    parsed = urlparse(url)
    for prefix, query in (("", parsed.query), ("#", parsed.fragment)):
        if "page=" not in query and not query.startswith("page="):
            # fragment may be "jobs?page=1"
            if "?" not in query or "page=" not in query.split("?", 1)[-1]:
                continue
        path, _, raw_query = query.partition("?")
        if prefix == "" and "?" not in url.split("#", 1)[0]:
            raw_query = parsed.query
            path = ""
        pairs = parse_qsl(raw_query, keep_blank_values=True)
        updated = []
        found = False
        for key, value in pairs:
            if key == "page" and value.isdigit():
                updated.append((key, str(int(value) + 1)))
                found = True
            else:
                updated.append((key, value))
        if not found:
            continue
        new_query = urlencode(updated)
        if prefix == "#":
            fragment = f"{path}?{new_query}" if path else new_query
            return urlunparse(parsed._replace(fragment=fragment))
        return urlunparse(parsed._replace(query=new_query))
    return ""


def _read_anchors(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('a[href]')].map(anchor => ({
            text: (anchor.innerText || '').trim(),
            href: anchor.href || ''
        }))"""
    )


def _open(page, url: str) -> None:
    last_error = None
    for _attempt in range(3):
        try:
            page.goto(url, wait_until="commit", timeout=20000)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            last_error = None
            break
        except Exception as error:
            last_error = error
    if last_error:
        raise last_error
    try:
        page.wait_for_function(
            """() => document.querySelectorAll("a[href*='job']").length >= 5""",
            timeout=12000,
        )
    except Exception:
        page.wait_for_timeout(2000)
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(600)


def browse_official(url: str, company: str, limit: int = 30) -> list[dict]:
    from playwright.sync_api import sync_playwright

    collected = []
    seen = set()

    def take(page) -> int:
        added = 0
        for job in jobs_from_anchors(_read_anchors(page), company, page.url, limit):
            if job["job_url"] in seen:
                continue
            seen.add(job["job_url"])
            collected.append(job)
            added += 1
            if len(collected) >= limit:
                break
        return added

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        try:
            _open(page, url)
            added = take(page)
            if added < 2:
                hops = career_links(_read_anchors(page), page.url)
                for hop in hops[:2]:
                    if urlparse(hop).geturl() == page.url:
                        continue
                    _open(page, hop)
                    if take(page):
                        break
            pages = 1
            while len(collected) < limit and pages < MAX_PAGES:
                nxt = next_list_url(page.url)
                if not nxt or nxt == page.url:
                    break
                before = len(collected)
                _open(page, nxt)
                take(page)
                pages += 1
                if len(collected) == before:
                    break
        finally:
            browser.close()
    return collected[:limit]
