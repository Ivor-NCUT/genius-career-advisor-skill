#!/usr/bin/env python3
"""Load an official career page in headless Chrome when HTTP has no job list.

This is only a fallback for company career sites. It follows a public
加入我们 / 招聘 link, waits for the list, and reads title, location, and
detail URL for every visible opening. It does not open the system browser
and does not log in.
"""

from __future__ import annotations

import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from career_sources import (
    CTA_TEXT,
    GENERIC_TITLE,
    REJECT_TEXT,
    SPECIFIC_JOB_URL,
    _skipped_host,
    job_record,
)


JOBISH = re.compile(
    r"/job/|jobid=|job_id=|jobdesc|position/detail|/position/\d|"
    r"/careers/jobs/\d|#/official/(?:social|trainee)/job-info/\d",
    re.I,
)
JOIN_LINK = re.compile(
    r"加入我们|社会招聘|社招职位|校园招聘|热招职位|在招职位|查看职位|开放职位|工作机会|"
    r"浏览全部职位|全部职位|更多岗位|岗位机会|查看全部|招聘官网|招聘官網|"
    r"join us|we.?re hiring|view (?:all|open )?jobs|open roles|see jobs|opportunities",
    re.I,
)
CAMPUS_LINK = re.compile(r"校园招聘|校招|实习生招聘|campus", re.I)
LIST_HINT = re.compile(r"#/jobs\?|共\d+个职位")
PLACE = re.compile(r"市|省|区|Remote|远程|北京|上海|杭州|深圳|广州|成都|南京|武汉|新加坡|美国")
SKIP_LINE = re.compile(
    r"^(急|分享|新|热|社招|校招|查看职位详情|查看详情|职位详情|立即投递|投递简历|投递|申请|apply now)$|"
    r"发布于|^\d{4}-\d{2}-\d{2}$",
    re.I,
)
DETAIL_PATH = re.compile(r"/jobs/\d+(?:$|[/?#])|/careers/jobs/\d+(?:$|[/?#])", re.I)
MAX_PAGES = 4
TIME_BUDGET_SECONDS = 45
CITY_CODE = {
    "beijing": "北京",
    "shanghai": "上海",
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "hangzhou": "杭州",
    "chengdu": "成都",
    "wuhan": "武汉",
    "nanjing": "南京",
    "tianjin": "天津",
    "xian": "西安",
    "suzhou": "苏州",
    "chongqing": "重庆",
}


def _compact(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", collapsed)


def _lines(text: str) -> list[str]:
    lines = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line or SKIP_LINE.search(line) or GENERIC_TITLE.match(line) or CTA_TEXT.fullmatch(line):
            continue
        if line in {"全职", "兼职", "实习", "其他"}:
            continue
        lines.append(line)
    return lines


def _absolute(href: str, base_url: str) -> str:
    if not href or href.startswith(("javascript:", "mailto:", "tel:")):
        return ""
    return urljoin(base_url or "", href.strip())


def _is_job_href(href: str) -> bool:
    return bool(JOBISH.search(href) or SPECIFIC_JOB_URL.search(href))


def _blocked_host(href: str) -> bool:
    if not href.startswith(("http://", "https://")) or _skipped_host(href):
        return True
    host = urlparse(href).netloc.casefold()
    return "jobradar" in host or "chuhaipin" in host


def _place_line(line: str) -> bool:
    if PLACE.fullmatch(line):
        return True
    return bool(PLACE.search(line) and len(line) <= 24 and not REJECT_TEXT.search(line) and not re.search(r"工程师|经理|设计师|研究员|运营|策划", line))


def jobs_from_anchors(anchors: list[dict], company: str, base_url: str, limit: int) -> list[dict]:
    found = []
    seen = set()
    for anchor in anchors:
        href = _absolute(str(anchor.get("href") or ""), base_url)
        if _blocked_host(href) or not _is_job_href(href):
            continue
        title = ""
        location = ""
        for line in _lines(str(anchor.get("text") or "")):
            if _place_line(line):
                location = location or line
                continue
            if not title and 2 <= len(line) <= 120 and not REJECT_TEXT.search(line):
                title = line
        if not title or re.fullmatch(r"\d+", title) or re.fullmatch(r"\d+\s*jobs?", title, re.I):
            continue
        if re.fullmatch(r"首\s*页|首页|home", title, re.I):
            continue
        if href in seen:
            continue
        seen.add(href)
        found.append(job_record(company, title, location, href, href))
        if len(found) >= limit:
            break
    return found


def jobs_from_kuaishou(payload: dict, company: str, limit: int) -> list[dict]:
    result = payload.get("result") if isinstance(payload, dict) else None
    items = result.get("list") if isinstance(result, dict) else None
    if not isinstance(items, list):
        return []
    found = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("name") or "").strip()
        job_id = item.get("id")
        if not title or not job_id:
            continue
        location = CITY_CODE.get(str(item.get("workLocationCode") or "").casefold(), "")
        section = "trainee" if str(item.get("positionNatureCode") or "").upper() == "C002" else "social"
        href = f"https://zhaopin.kuaishou.cn/#/official/{section}/job-info/{job_id}"
        found.append(job_record(company, title, location, href, href))
        if len(found) >= limit:
            break
    return found


def career_links(anchors: list[dict], base_url: str) -> list[str]:
    ranked = []
    seen = set()
    for anchor in anchors:
        text = _compact(anchor.get("text") or "")
        href = _absolute(str(anchor.get("href") or ""), base_url)
        if _blocked_host(href) or href in seen:
            continue
        host = urlparse(href).netloc.casefold()
        moka_board = host == "app.mokahr.com" and re.match(
            r"/(apply|social-recruitment|campus-recruitment)/", urlparse(href).path
        )
        listed = bool(LIST_HINT.search(text) or LIST_HINT.search(href))
        if not JOIN_LINK.search(text) and not moka_board and not listed:
            continue
        if DETAIL_PATH.search(urlparse(href).path):
            continue
        score = 1 if moka_board else 0
        if re.search(r"社会招聘|社招职位|浏览全部职位|热招职位|加入我们", text):
            score += 3
        if listed:
            score += 2
        if CAMPUS_LINK.search(text) or CAMPUS_LINK.search(href):
            score -= 2
        seen.add(href)
        ranked.append((score, href))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [href for score, href in ranked if score >= 0]


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


def list_url_from_detail(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/jobs/\d+$", "/jobs", parsed.path)
    if path == parsed.path:
        return ""
    return urlunparse(parsed._replace(path=path, query="", fragment=""))


def _kuaishou_jobs(payloads: list[dict], company: str, limit: int) -> list[dict]:
    found = []
    seen = set()
    for payload in payloads:
        for job in jobs_from_kuaishou(payload, company, limit):
            if job["job_url"] in seen:
                continue
            seen.add(job["job_url"])
            found.append(job)
            if len(found) >= limit:
                return found
    return found


def _read_anchors(page, climb: bool = True) -> list[dict]:
    return page.evaluate(
        """(climb) => [...document.querySelectorAll('a[href]')].map(anchor => {
          let text = (anchor.getAttribute('aria-label') || anchor.innerText || '').trim();
          if (!climb) return {text, href: anchor.href || ''};
          const jobHref = /\\/jobs\\/\\d+|\\/job\\/|\\/position\\/\\d+|job-info\\/\\d+/i;
          let node = anchor;
          for (let step = 0; step < 5 && node.parentElement; step += 1) {
            const parent = node.parentElement;
            const jobLinks = [...parent.querySelectorAll('a[href]')].filter(link => jobHref.test(link.href)).length;
            if (jobLinks > 1) break;
            const parentText = (parent.innerText || '').trim();
            if (parentText.length > text.length) text = parentText;
            node = parent;
          }
          return {text, href: anchor.href || ''};
        })""",
        climb,
    )


def _same_document(current: str, target: str) -> bool:
    left = urlparse(current)
    right = urlparse(target)
    return left.scheme == right.scheme and left.netloc == right.netloc and left.path.rstrip("/") == right.path.rstrip("/")


def _remaining_ms(deadline):
    remaining = int((deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        raise TimeoutError("browser_time_budget_exceeded")
    return remaining


def _open(page, url: str, deadline: float) -> None:
    if page.url and page.url != "about:blank" and _same_document(page.url, url) and "#" in url:
        page.evaluate("(href) => { window.location.href = href }", url)
        try:
            page.wait_for_selector("a[href*='#/job/']", timeout=min(8000, _remaining_ms(deadline)))
        except Exception:
            page.wait_for_timeout(min(2000, _remaining_ms(deadline)))
    else:
        page.goto(url, wait_until="domcontentloaded", timeout=min(15000, _remaining_ms(deadline)))
    try:
        page.wait_for_function(
            """() => !document.body.innerText.includes('数据读取中') && (
                document.querySelector('a[href*="#/job/"], a[href*="/jobs/"], a.job-title, tr') ||
                [...document.querySelectorAll('a[href]')].some(a =>
                    /加入我们|招聘|join us|open roles|浏览全部职位/i.test(a.getAttribute('aria-label') || a.innerText || '') ||
                    (a.href.includes('app.mokahr.com') && /\\/(apply|social-recruitment)\\//.test(a.href))) ||
                /暂无职位|暂无招聘|no open positions/i.test(document.body.innerText))""",
            timeout=min(10000, _remaining_ms(deadline)),
        )
    except Exception:
        pass
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")


def _click_next(page) -> bool:
    return bool(page.evaluate(
        """() => {
          const next = document.querySelector('.ant-pagination-next:not(.ant-pagination-disabled)');
          if (next) { next.click(); return true; }
          const element = [...document.querySelectorAll('a,button,li')].find(node => /^(下一页|下页|next)$/i.test((node.innerText || '').trim()));
          if (!element || element.getAttribute('aria-disabled') === 'true' || /disabled/.test(element.className || '')) return false;
          element.click();
          return true;
        }"""
    ))


def _homepage_candidates(url: str) -> list[str]:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return []
    found = []
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    if parsed.path not in {"", "/"}:
        found.append(origin)
    labels = parsed.netloc.casefold().split(".")
    if labels and labels[0] in {"career", "careers", "talent", "hr", "job", "jobs", "zhaopin", "join"} and len(labels) > 2:
        parent = ".".join(labels[1:])
        found.append(f"{parsed.scheme}://{parent}/")
        found.append(f"{parsed.scheme}://www.{parent}/")
    unique = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique


def browse_official(url: str, company: str, limit: int = 30) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("browser_dependency_missing: python3 -m pip install playwright") from error

    collected = []
    seen = set()
    captured = []
    deadline = time.monotonic() + TIME_BUDGET_SECONDS

    def take(page) -> int:
        added = 0
        batch = jobs_from_anchors(_read_anchors(page), company, page.url, limit)
        if "kuaishou.cn" in urlparse(page.url).netloc and captured:
            batch = _kuaishou_jobs(captured, company, limit)
        for job in batch:
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

            def on_response(response) -> None:
                if "positions/simple" not in response.url or "pageNum=" not in response.url:
                    return
                try:
                    captured.append(response.json())
                except Exception:
                    return

            page.on("response", on_response)
            try:
                _open(page, url, deadline)
            except Exception as first_error:
                opened_home = False
                for home in _homepage_candidates(url):
                    try:
                        _open(page, home, deadline)
                        opened_home = True
                        break
                    except Exception:
                        continue
                if not opened_home:
                    raise first_error
            if "kuaishou.cn" in urlparse(page.url).netloc:
                try:
                    page.wait_for_response(lambda response: "positions/simple" in response.url, timeout=min(8000, _remaining_ms(deadline)))
                except Exception:
                    pass
            added = take(page)
            if added < 8 and ("mokahr.com" in page.url or "#/jobs" in page.url or "#/job" in url):
                try:
                    page.wait_for_selector("a[href*='#/job/']", timeout=min(8000, _remaining_ms(deadline)))
                except Exception:
                    pass
                page.wait_for_timeout(min(1500, _remaining_ms(deadline)))
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                added = take(page)
            if added < 2:
                try:
                    page.wait_for_selector("a[href*='#/jobs?'], a[href*='#/job/']", timeout=min(6000, _remaining_ms(deadline)))
                except Exception:
                    pass
                hops = career_links(_read_anchors(page, climb=False), page.url)
                opened = False
                for hop in hops[:3]:
                    if hop.rstrip("/") == page.url.rstrip("/"):
                        continue
                    _open(page, hop, deadline)
                    if take(page):
                        opened = True
                        break
                parent = list_url_from_detail(page.url)
                if not opened and parent:
                    _open(page, parent, deadline)
                    if take(page):
                        opened = True
                if not opened:
                    for home in _homepage_candidates(url):
                        if home.rstrip("/") == page.url.rstrip("/"):
                            continue
                        try:
                            _open(page, home, deadline)
                        except Exception:
                            continue
                        if take(page):
                            break
                        for hop in career_links(_read_anchors(page, climb=False), page.url)[:3]:
                            if hop.rstrip("/") == page.url.rstrip("/"):
                                continue
                            try:
                                _open(page, hop, deadline)
                            except Exception:
                                continue
                            if take(page):
                                break
                        if collected:
                            break
            pages = 1
            while len(collected) < limit and pages < MAX_PAGES:
                before = len(collected)
                nxt = next_list_url(page.url)
                try:
                    if nxt and nxt != page.url:
                        _open(page, nxt, deadline)
                    elif not _click_next(page):
                        break
                    else:
                        page.wait_for_timeout(min(1500, _remaining_ms(deadline)))
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
