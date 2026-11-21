#!/usr/bin/env python3
"""Load an official career page in headless Chrome when HTTP has no job list.

This is only a fallback for company career sites. It follows a public
加入我们 / 招聘 link, waits for the list, and reads title, location, and
detail URL. It does not open the system browser and does not log in.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

from career_sources import (
    CTA_TEXT,
    GENERIC_TITLE,
    SPECIFIC_JOB_URL,
    REJECT_TEXT,
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
SKIP_LINE = re.compile(r"^(急|分享|新|热|立即投递|投递|申请|apply now)$|发布于|^\d{4}-\d{2}-\d{2}$", re.I)
MAX_PAGES = 4
TIME_BUDGET_SECONDS = 45


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
            if not title and len(line) <= 120 and not CTA_TEXT.fullmatch(line) and not REJECT_TEXT.search(line):
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
        href = _absolute(str(anchor.get("href") or ""), base_url)
        if not href.startswith(("http://", "https://")) or href in seen or _skipped_host(href):
            continue
        host = urlparse(href).netloc.casefold()
        if "jobradar" in host or "chuhaipin" in host:
            continue
        moka_board = host == "app.mokahr.com" and re.match(r"/(apply|social-recruitment|campus-recruitment)/", urlparse(href).path)
        if not JOIN_LINK.search(text) and not moka_board:
            continue
        seen.add(href)
        found.append(href)
    return found


def next_list_url(url: str) -> str:
    """Advance a page=N query in either the hash or the main query string."""
    parsed = urlparse(url)
    fragment_path, _, fragment_query = parsed.fragment.partition("?")
    for prefix, raw_query in (("#", fragment_query), ("", parsed.query)):
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
            fragment = f"{fragment_path}?{new_query}" if fragment_path else new_query
            return urlunparse(parsed._replace(fragment=fragment))
        return urlunparse(parsed._replace(query=new_query))
    return ""


def _read_anchors(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('a[href]')].map(anchor => ({
            text: (anchor.getAttribute('aria-label') || anchor.innerText || '').trim(),
            href: anchor.href || ''
        }))"""
    )


def _remaining_ms(deadline):
    remaining = int((deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        raise TimeoutError("browser_time_budget_exceeded")
    return remaining


def _open(page, url: str, deadline: float) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=min(15000, _remaining_ms(deadline)))
    try:
        page.wait_for_function(
            """() => !document.body.innerText.includes('数据读取中') && (
                document.querySelector('a[href*="#/job/"], a[href*="/jobs/"]') ||
                [...document.querySelectorAll('a[href]')].some(a =>
                    /加入我们|招聘|join us|open roles/i.test(a.getAttribute('aria-label') || a.innerText || '') ||
                    (a.href.includes('app.mokahr.com') && /\\/(apply|social-recruitment)\\//.test(a.href))) ||
                /暂无职位|暂无招聘|no open positions/i.test(document.body.innerText))""",
            timeout=min(10000, _remaining_ms(deadline)),
        )
    except Exception:
        pass
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")


def browse_official(url: str, company: str, limit: int = 30) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("browser_dependency_missing: python3 -m pip install playwright") from error

    collected = []
    seen = set()
    deadline = time.monotonic() + TIME_BUDGET_SECONDS

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
        try:
            browser = playwright.chromium.launch(headless=True, timeout=min(15000, _remaining_ms(deadline)))
        except Exception:
            try:
                browser = playwright.chromium.launch(channel="chrome", headless=True, timeout=min(15000, _remaining_ms(deadline)))
            except Exception as error:
                raise RuntimeError("browser_runtime_missing: python3 -m playwright install chromium") from error
        try:
            page = browser.new_page()
            _open(page, url, deadline)
            added = take(page)
            if not added:
                hops = career_links(_read_anchors(page), page.url)
                for hop in hops[:2]:
                    if urlparse(hop).geturl() == page.url:
                        continue
                    _open(page, hop, deadline)
                    if take(page):
                        break
            pages = 1
            while len(collected) < limit and pages < MAX_PAGES:
                nxt = next_list_url(page.url)
                if not nxt or nxt == page.url:
                    break
                before = len(collected)
                try:
                    _open(page, nxt, deadline)
                except Exception:
                    if collected:
                        break
                    raise
                take(page)
                pages += 1
                if len(collected) == before:
                    break
        finally:
            browser.close()
    return collected[:limit]
