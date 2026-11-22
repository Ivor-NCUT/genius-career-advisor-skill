#!/usr/bin/env python3
"""Read public job platforms and official career sites from the bundled catalog.

Official sites are fetched from the catalog URLs, so a later catalog update is
picked up without editing this file. Greenhouse, Ashby, Lever and the same kind
of public board JSON are preferred when the page or URL exposes them. Ordinary
HTML is used only when a real job list is present. Empty shells, login walls
and HTTP errors become an internal unavailable status.

One request uses a short timeout. Callers run sources in a bounded pool so one
slow site does not decide the search.
"""

from __future__ import annotations

import html
import json
import re
import ssl
import time
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import match_guard
import source_catalog


FETCH_TIMEOUT_SECONDS = 8
MAX_WORKERS = 8
MAX_RESPONSE_BYTES = 1_200_000
PER_SOURCE_JOB_CAP = 30
USER_AGENT = "Mozilla/5.0 (compatible; genius-career-advisor/1.0)"

STRONG_ROLE = re.compile(
    r"工程师|经理|设计师|研究员|实习生?|科学家|架构师|专家|负责人|主管|总监|算法|"
    r"前端|后端|全栈|产品经理|"
    r"\b(?:engineer|designer|manager|intern|scientist|developer|researcher|director|"
    r"recruiter|architect|analyst|officer)\b",
    re.I,
)
BROAD_ROLE = re.compile(r"产品|运营|销售|开发|数据|测试|顾问", re.I)
GENERIC_TITLE = re.compile(
    r"^(社会招聘|校园招聘|实习招聘|实习生招聘|加入我们|查看职位|开放职位|在招职位|"
    r"careers?|jobs?|open roles|view jobs|all jobs)$",
    re.I,
)
CTA_TEXT = re.compile(r"^(apply(?: now)?|立即申请|立刻投递|查看详情|了解更多|learn more|view details?)$", re.I)
MARKETING_PATH = re.compile(r"/(?:industry|product|products|solution|solutions|about|blog|news|article|hardware)/", re.I)
REJECT_TEXT = re.compile(
    r"介绍|关于我们|企业文化|首页|新闻|博客|登录|注册|隐私|条款|联系我们|了解更多|"
    r"view all|see all|learn more|sign in|log in|cookie",
    re.I,
)
SENIORITY = re.compile(
    r"^(experienced|intern|internship|junior|senior|mid|new grad|全职|实习|社招|校招|应届)$",
    re.I,
)
SPECIFIC_JOB_URL = re.compile(
    r"(/jobs?/[^/?#]{2,}|/positions?/[^/?#]{2,}|/position/[^/?#]{2,}|"
    r"gh_jid=|lever\.co/.+/.+|ashbyhq\.com/.+/.+|smartrecruiters\.com/.+/.+)",
    re.I,
)
SKIP_HOSTS = (
    "linkedin.com", "twitter.com", "x.com", "youtube.com", "youtu.be",
    "weixin.qq.com", "github.com", "facebook.com", "instagram.com",
    "beian.miit.gov.cn", "beian.mps.gov.cn", "zhihu.com",
)
GENERIC_CAREER_PATHS = {
    "",
    "/career",
    "/careers",
    "/job",
    "/jobs",
    "/join",
    "/join-us",
    "/joinus",
    "/position",
    "/positions",
    "/recruit",
    "/zhaopin",
}
LOGIN_MARKERS = ("请登录", "登录后", "sign in to", "log in to", "create an account", "会员专享", "开通会员")
BOARD_ORDER = ("greenhouse", "ashby", "lever", "workable", "smartrecruiters", "recruitee", "bamboohr")


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def fetch_url(url: str, timeout: int = FETCH_TIMEOUT_SECONDS, limit: int = MAX_RESPONSE_BYTES) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            status = getattr(response, "status", 200)
            body = response.read(limit).decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            if status >= 400:
                raise FetchError(f"HTTP {status}", status)
            return response.geturl(), body
    except HTTPError as error:
        raise FetchError(f"HTTP {error.code}", error.code) from error
    except TimeoutError as error:
        raise FetchError("timeout") from error
    except URLError as error:
        raise FetchError(str(error.reason or error)) from error


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = FETCH_TIMEOUT_SECONDS):
    header_map = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }
    if headers:
        header_map.update({key: value for key, value in headers.items() if value})
    request = Request(url, data=json.dumps(payload).encode(), headers=header_map, method="POST")
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(MAX_RESPONSE_BYTES).decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            if getattr(response, "status", 200) >= 400:
                raise FetchError(f"HTTP {response.status}", response.status)
            return json.loads(body)
    except HTTPError as error:
        raise FetchError(f"HTTP {error.code}", error.code) from error
    except TimeoutError as error:
        raise FetchError("timeout") from error
    except URLError as error:
        raise FetchError(str(error.reason or error)) from error


def unavailable(source: str, url: str, error: object) -> dict:
    return {
        "source": source,
        "source_url": url,
        "source_status": "unavailable",
        "matched_jobs": 0,
        "jobs": [],
        "error": str(error)[:180],
    }


def job_record(company: str, title: str, location: str, job_url: str, application_url: str = "", summary: str = "") -> dict:
    title = " ".join(str(title or "").split())
    location = " ".join(str(location or "").split())
    link = str(job_url or "").strip()
    apply_link = str(application_url or "").strip() or link
    return {
        "company": " ".join(str(company or "").split()),
        "title": title,
        "location": location,
        "job_url": link,
        "application_url": apply_link,
        "summary": " ".join(str(summary or "").split())[:240],
    }


def tokenize(query: str) -> list[str]:
    return source_catalog.tokens(query)


def relevance(job: dict, query_tokens: list[str]) -> float:
    if not query_tokens:
        return 1.0
    blob = " ".join(str(job.get(key) or "") for key in ("company", "title", "location", "summary")).casefold()
    hits = sum(1 for token in query_tokens if token in blob)
    return hits / len(query_tokens)


def select_jobs(jobs: list[dict], query: str, limit: int) -> tuple[list[dict], int]:
    query_tokens = tokenize(query)
    unique = []
    seen = set()
    for item in jobs:
        if not item.get("title") or not item.get("job_url"):
            continue
        key = _job_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    if not query_tokens:
        return unique[:limit], len(unique)
    matched = [item for item in unique if relevance(item, query_tokens) > 0]
    matched.sort(key=lambda item: (-relevance(item, query_tokens), item.get("title", "")))
    return matched[:limit], len(matched)


def _job_key(job: dict) -> tuple:
    link = _norm_url(job.get("job_url"))
    if link:
        return ("url", link)
    return ("text", _norm_text(job.get("company")), _norm_text(job.get("title")))


def _norm_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _norm_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    base, separator, fragment = text.partition("#")
    base = re.sub(r"([?&])(utm_[^=&]+|gh_src)=[^&]*", r"\1", base)
    base = re.sub(r"[?&]$", "", base).rstrip("/").casefold()
    if separator and (re.search(r"/job/|job-info/|jobid|job_id", fragment, re.I) or fragment.startswith("role=")):
        return base + "#" + fragment.casefold()
    return base


def _loads_relaxed(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        start = text.find("[")
        if start < 0:
            start = text.find("{")
        if start < 0:
            raise
        items = []
        index = start + 1 if text[start] == "[" else start
        if text[start] == "{":
            value, _end = decoder.raw_decode(text, start)
            return value
        while index < len(text):
            while index < len(text) and text[index] in " \n\r\t,":
                index += 1
            if index >= len(text) or text[index] == "]":
                break
            try:
                value, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                break
            items.append(value)
            index = end
        return items


def _location_name(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = [value.get(key) for key in ("city", "name", "location", "addressLocality", "country")]
        if isinstance(value.get("postalAddress"), dict):
            parts.extend(value["postalAddress"].get(key) for key in ("addressLocality", "addressRegion", "addressCountry"))
        return ", ".join(str(part).strip() for part in parts if part)
    if isinstance(value, list):
        return " / ".join(filter(None, (_location_name(item) for item in value[:3])))
    return ""


def parse_greenhouse(payload, company: str) -> list[dict]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    found = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        link = item.get("absolute_url")
        if not title or not link:
            continue
        found.append(job_record(company or item.get("company_name") or "", title, _location_name(item.get("location")), link, link))
    return found


def parse_ashby(payload, company: str) -> list[dict]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    found = []
    for item in jobs:
        if not isinstance(item, dict) or item.get("isListed") is False:
            continue
        title = item.get("title")
        link = item.get("jobUrl")
        if not title or not link:
            continue
        location = _location_name(item.get("location") or item.get("address"))
        if item.get("isRemote") and "remote" not in location.casefold() and "远程" not in location:
            location = "Remote" if not location else f"{location} / Remote"
        found.append(job_record(company, title, location, link, item.get("applyUrl") or link))
    return found


def parse_lever(payload, company: str) -> list[dict]:
    if not isinstance(payload, list):
        return []
    found = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        title = item.get("text")
        link = item.get("hostedUrl")
        if not title or not link:
            continue
        location = categories.get("location") or ""
        workplace = str(item.get("workplaceType") or "")
        if workplace and workplace.casefold() not in location.casefold():
            location = f"{location} / {workplace}".strip(" /")
        found.append(job_record(company or categories.get("team") or "", title, location, link, item.get("applyUrl") or link))
    return found


def parse_workable(payload, company: str) -> list[dict]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    found = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        link = item.get("url") or item.get("application_url")
        if not title or not link:
            continue
        found.append(job_record(company or item.get("company") or "", title, _location_name(item.get("location") or item.get("city")), link, link))
    return found


def parse_smartrecruiters(payload, company: str, token: str) -> list[dict]:
    jobs = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    found = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = item.get("name")
        identifier = item.get("id")
        if not title or not identifier:
            continue
        link = f"https://jobs.smartrecruiters.com/{token}/{identifier}"
        found.append(job_record(company, title, _location_name(item.get("location")), link, link))
    return found


def parse_recruitee(payload, company: str) -> list[dict]:
    jobs = payload.get("offers") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    found = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        link = item.get("careers_url") or item.get("url")
        if not title or not link:
            continue
        found.append(job_record(company, title, _location_name(item.get("location")), link, link))
    return found


def parse_bamboohr(payload, company: str, token: str) -> list[dict]:
    jobs = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []
    found = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = item.get("jobOpeningName") or item.get("title")
        identifier = item.get("id")
        if not title or identifier in (None, ""):
            continue
        link = f"https://{token}.bamboohr.com/careers/{identifier}"
        found.append(job_record(company, title, _location_name(item.get("location")), link, link))
    return found


def detect_boards(url: str, page: str = "") -> list[tuple[str, str]]:
    blob = f"{url}\n{page[:200_000]}"
    found: list[tuple[str, str]] = []

    def add(kind: str, token: str) -> None:
        token = (token or "").strip().strip("/")
        if not token or token.casefold() in {"embed", "jobs", "job", "j"}:
            return
        item = (kind, token)
        if item not in found:
            found.append(item)

    for match in re.finditer(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", blob, re.I):
        add("greenhouse", match.group(1))
    for match in re.finditer(r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)", blob, re.I):
        add("greenhouse", match.group(1))
    for match in re.finditer(r"greenhouse\.io/embed/job_board\?[^\"'\s>]*for=([A-Za-z0-9_-]+)", blob, re.I):
        add("greenhouse", match.group(1))
    for match in re.finditer(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_-]+)", blob, re.I):
        add("ashby", match.group(1))
    for match in re.finditer(r"jobs\.ashbyhq\.com/([A-Za-z0-9_-]+)", blob, re.I):
        add("ashby", match.group(1))
    for match in re.finditer(r"(?:jobs|api)\.lever\.co/(?:v0/postings/)?([A-Za-z0-9_-]+)", blob, re.I):
        add("lever", match.group(1))
    for match in re.finditer(r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([A-Za-z0-9_-]+)", blob, re.I):
        add("workable", match.group(1))
    for match in re.finditer(r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)", blob, re.I):
        add("smartrecruiters", match.group(1))
    for match in re.finditer(r"https?://([A-Za-z0-9_-]+)\.recruitee\.com", blob, re.I):
        add("recruitee", match.group(1))
    for match in re.finditer(r"https?://([A-Za-z0-9_-]+)\.bamboohr\.com", blob, re.I):
        add("bamboohr", match.group(1))
    rank = {kind: index for index, kind in enumerate(BOARD_ORDER)}
    found.sort(key=lambda item: rank.get(item[0], 99))
    return found[:2]


def jobs_from_boards(url: str, page: str, company: str, fetch) -> list[dict]:
    jobs = []
    for kind, token in detect_boards(url, page):
        api = _board_api(kind, token)
        if not api:
            continue
        try:
            _final, body = fetch(api)
            payload = _loads_relaxed(body)
        except Exception:
            continue
        jobs.extend(_parse_board(kind, payload, company, token))
    return jobs


def _board_api(kind: str, token: str) -> str:
    if kind == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    if kind == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    if kind == "lever":
        return f"https://api.lever.co/v0/postings/{token}?mode=json"
    if kind == "workable":
        return f"https://apply.workable.com/api/v1/widget/accounts/{token}"
    if kind == "smartrecruiters":
        return f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"
    if kind == "recruitee":
        return f"https://{token}.recruitee.com/api/offers/"
    if kind == "bamboohr":
        return f"https://{token}.bamboohr.com/careers/list"
    return ""


def _parse_board(kind: str, payload, company: str, token: str) -> list[dict]:
    if kind == "greenhouse":
        return parse_greenhouse(payload, company)
    if kind == "ashby":
        return parse_ashby(payload, company)
    if kind == "lever":
        return parse_lever(payload, company)
    if kind == "workable":
        return parse_workable(payload, company)
    if kind == "smartrecruiters":
        return parse_smartrecruiters(payload, company, token)
    if kind == "recruitee":
        return parse_recruitee(payload, company)
    if kind == "bamboohr":
        return parse_bamboohr(payload, company, token)
    return []


class _AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._href = None
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attributes = {key: value for key, value in attrs}
        if tag == "a" and self._href is None:
            self._href = attributes.get("href") or ""
            self._parts = []
        elif self._href is not None and tag in {"script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
            return
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, list(self._parts)))
            self._href = None
            self._parts = []

    def handle_data(self, data):
        if self._href is None or self._skip:
            return
        piece = " ".join(data.split())
        if piece:
            self._parts.append(piece)


def _visible_text(page: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", page, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _skipped_host(url: str) -> bool:
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in SKIP_HOSTS)


def _specific_job_url(url: str) -> bool:
    parsed = urlparse(url)
    if MARKETING_PATH.search(parsed.path):
        return False
    if re.search(r"(?:jobId|job_id|gh_jid)=", url, re.I):
        return True
    if SPECIFIC_JOB_URL.search(url):
        return True
    parts = [part for part in parsed.path.split("/") if part]
    generic = {"opportunities", "jobs", "job", "careers", "career", "position", "positions", "join", "recruit", "opening", "openings"}
    if len(parts) >= 2 and parts[-1].casefold() not in generic:
        slug = parts[-1]
        if re.search(r"\d", slug) or "-" in slug:
            return True
    return False


def _generic_career_url(url: str) -> bool:
    path = urlparse(url).path.rstrip("/").casefold()
    return path in GENERIC_CAREER_PATHS


def _accept_anchor(link: str, segments: list[str]) -> tuple[str, str] | None:
    if not link or link.startswith(("#", "mailto:", "javascript:", "tel:")):
        return None
    if _generic_career_url(link) or _skipped_host(link) or not _specific_job_url(link):
        return None
    title = ""
    candidates = []
    for segment in segments:
        if GENERIC_TITLE.match(segment) or CTA_TEXT.match(segment) or re.match(r"^\d+\s*[.、]", segment):
            continue
        if REJECT_TEXT.search(segment) or len(segment) > 80:
            continue
        if STRONG_ROLE.search(segment) or BROAD_ROLE.search(segment):
            candidates.append(segment)
    if candidates:
        title = min(candidates, key=len)
    if not title or GENERIC_TITLE.match(title):
        return None
    location = ""
    for segment in reversed(segments):
        if segment == title or SENIORITY.match(segment) or CTA_TEXT.match(segment):
            continue
        segment = re.split(r"\s*[|｜]\s*", segment)[0].strip()
        if len(segment) > 28 or re.search(r"[。；;]|^\d+\s*[.、]", segment):
            continue
        cjk_place = bool(re.fullmatch(r"[\u4e00-\u9fff]{2,8}", segment)) and not STRONG_ROLE.search(segment)
        geo = bool(re.search(r"remote|远程|hybrid|onsite|市|省|区|anywhere|worldwide|,|·|\s", segment, re.I))
        if not cjk_place and not geo:
            continue
        location = segment
        break
    if len(title) < 4 or len(title) > 90:
        return None
    return title, location


def html_jobs(page: str, base_url: str, company: str) -> list[dict]:
    jobs = _jsonld_jobs(page, base_url, company)
    if jobs:
        return jobs
    parser = _AnchorParser()
    try:
        parser.feed(page)
    except Exception:
        return []
    found = []
    for href, segments in parser.anchors:
        link = urljoin(base_url, html.unescape(href))
        if not link.startswith(("http://", "https://")):
            continue
        picked = _accept_anchor(link, segments)
        if not picked:
            continue
        title, location = picked
        employer = company
        company_match = re.search(r"/companies/([^/]+)/jobs/", link, re.I)
        if company_match:
            employer = company_match.group(1).replace("-", " ")
        found.append(job_record(employer, title, location, link, link))
        if len(found) >= 40:
            break
    return found


def _jsonld_jobs(page: str, base_url: str, company: str) -> list[dict]:
    found = []
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, flags=re.I | re.S):
        try:
            payload = json.loads(html.unescape(block.strip()))
        except json.JSONDecodeError:
            continue
        for node in _walk_jsonld(payload):
            if not _is_jobposting(node):
                continue
            title = node.get("title") or node.get("name")
            link = node.get("url") or node.get("sameAs")
            if not title or not link:
                continue
            employer = company
            org = node.get("hiringOrganization")
            if isinstance(org, dict) and org.get("name") and not company:
                employer = str(org.get("name"))
            location = ""
            place = node.get("jobLocation")
            if isinstance(place, dict):
                location = _location_name(place.get("address") or place)
            elif isinstance(place, list) and place:
                location = _location_name(place[0].get("address") if isinstance(place[0], dict) else place[0])
            found.append(job_record(employer, str(title), location, urljoin(base_url, str(link)), urljoin(base_url, str(link))))
    return found


def _walk_jsonld(node):
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
        return
    if not isinstance(node, dict):
        return
    graph = node.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            yield from _walk_jsonld(item)
    yield node


def _is_jobposting(node: dict) -> bool:
    kind = node.get("@type")
    values = kind if isinstance(kind, list) else [kind]
    return any(str(item).casefold() == "jobposting" for item in values if item)


def _page_unreadable(page: str, jobs: list[dict]) -> str:
    if jobs:
        return ""
    visible = _visible_text(page)
    lowered = visible.casefold()
    if any(marker in lowered for marker in LOGIN_MARKERS) and len(visible) < 2500:
        return "login_or_membership_wall"
    if len(visible) < 80:
        return "unreadable_page"
    return "no_public_job_list"


def _career_hop(page: str, base_url: str) -> str:
    parser = _AnchorParser()
    try:
        parser.feed(page)
    except Exception:
        return ""
    base_host = urlparse(base_url).netloc.casefold().removeprefix("www.")
    for href, segments in parser.anchors:
        link = urljoin(base_url, html.unescape(href or ""))
        if not link.startswith(("http://", "https://")) or _norm_url(link) == _norm_url(base_url):
            continue
        if _skipped_host(link) or "/share/base/form" in link or "login" in link.casefold():
            continue
        host = urlparse(link).netloc.casefold().removeprefix("www.")
        text = " ".join(segments)
        same_site = host == base_host or host.endswith("." + base_host)
        ats_host = any(piece in host for piece in ("greenhouse.io", "ashbyhq.com", "lever.co", "workable.com", "smartrecruiters.com", "recruitee.com", "bamboohr.com", "jobs.feishu.cn", "zhiye.com"))
        career_path = bool(re.search(r"/(career|careers|jobs|job|join|position|zhaopin|recruit)", urlparse(link).path, re.I))
        career_text = bool(re.search(r"招聘|职位|加入我们|在招|careers|jobs|open roles", text, re.I))
        if ats_host or (same_site and (career_path or career_text)):
            return link
    return ""


def _finish_source(record_name: str, url: str, jobs: list[dict], query: str, limit: int, empty_reason: str, pagination_complete=None) -> dict:
    if not jobs:
        result = unavailable(record_name, url, empty_reason or "no_public_job_list")
        result["collected_count"] = 0
        if pagination_complete is not None:
            result["pagination_complete"] = pagination_complete
        return result
    chosen, total = select_jobs(jobs, query, limit)
    if total:
        reason = ""
    elif pagination_complete is False:
        reason = "collection_incomplete"
    else:
        reason = "collected_no_match"
    result = {
        "source": record_name,
        "source_url": url,
        "source_status": "searched",
        "collected_count": len(jobs),
        "matched_jobs": total,
        "jobs": chosen,
        "_collected_jobs": jobs,
        "failure_reason": reason,
    }
    if pagination_complete is not None:
        result["pagination_complete"] = pagination_complete
    return result


def feishu_portal(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    host = parsed.netloc.casefold().removeprefix("www.")
    if not host.endswith(".jobs.feishu.cn"):
        return None
    parts = [part for part in parsed.path.split("/") if part and part not in {"position", "list", "m", "detail", "apply"}]
    return host, (parts[0] if parts else "index")


def parse_feishu_jobs(payload: dict, company: str, host: str, path: str) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    posts = data.get("job_post_list") if isinstance(data, dict) else None
    if not isinstance(posts, list):
        return []
    found = []
    for item in posts:
        if not isinstance(item, dict) or not item.get("title") or not item.get("id"):
            continue
        cities = [str(city.get("name")) for city in item.get("city_list") or [] if isinstance(city, dict) and city.get("name")]
        recruit = item.get("recruit_type") if isinstance(item.get("recruit_type"), dict) else {}
        kind = str(recruit.get("name") or "")
        parent = recruit.get("parent") if isinstance(recruit.get("parent"), dict) else {}
        if parent.get("name"):
            kind = f"{parent['name']} {kind}".strip()
        link = f"https://{host}/{path}/position/{item['id']}/detail"
        found.append(job_record(company, item["title"], " / ".join(cities), link, link, kind))
    return found


def zhiye_host(url: str) -> str:
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    return host if host.endswith(".zhiye.com") else ""


def parse_zhiye_jobs(payload: dict, company: str, host: str) -> list[dict]:
    rows = payload.get("Data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    found = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("JobAdName") or not item.get("Id"):
            continue
        places = item.get("LocNames") or []
        location = " / ".join(str(place) for place in places if place) if isinstance(places, list) else str(places or "")
        link = f"https://{host}/social/detail?jobAdId={item['Id']}"
        found.append(job_record(company, item["JobAdName"], location, link, link, str(item.get("Category") or "")))
    return found


def _opener_post(opener, url: str, payload: dict, headers: dict | None = None, timeout: int = FETCH_TIMEOUT_SECONDS):
    header_map = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
    }
    if headers:
        header_map.update({key: value for key, value in headers.items() if value})
    request = Request(url, data=json.dumps(payload).encode(), headers=header_map, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
            if getattr(response, "status", 200) >= 400:
                raise FetchError(f"HTTP {response.status}", response.status)
            return json.loads(body)
    except HTTPError as error:
        raise FetchError(f"HTTP {error.code}", error.code) from error
    except TimeoutError as error:
        raise FetchError("timeout") from error
    except URLError as error:
        raise FetchError(str(error.reason or error)) from error


def _post_retry(post, url: str, payload: dict, headers: dict):
    try:
        return post(url, payload, headers)
    except FetchError as error:
        if getattr(error, "status", None) not in {405, 429}:
            raise
        time.sleep(1.2)
        return post(url, payload, headers)


def read_feishu_board(origin: str, path: str, company: str, keyword: str = "") -> list[dict]:
    host = urlparse(origin).netloc.casefold()
    headers = {"website-path": path or "index", "Origin": origin, "Referer": f"{origin}/"}
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    post = lambda target, payload, header_map: _opener_post(opener, target, payload, header_map)
    token_payload = _post_retry(post, f"{origin}/api/v1/csrf/token", {}, headers)
    token = ((token_payload or {}).get("data") or {}).get("token")
    if not token:
        raise FetchError("feishu csrf missing")
    search_headers = dict(headers)
    search_headers["x-csrf-token"] = token
    search_headers["Portal-Platform"] = "pc"
    body = {
        "keyword": keyword or "",
        "limit": PER_SOURCE_JOB_CAP,
        "offset": 0,
        "job_category_id_list": [],
        "tag_id_list": [],
        "location_code_list": [],
        "subject_id_list": [],
        "recruitment_id_list": [],
        "portal_type": 6,
        "job_function_id_list": [],
        "storefront_id_list": [],
        "portal_entrance": 1,
    }
    payload = _post_retry(post, f"{origin}/api/v1/search/job/posts", body, search_headers)
    jobs = parse_feishu_jobs(payload, company, host, path or "index")
    if jobs:
        return jobs
    body["portal_type"] = 2
    payload = _post_retry(post, f"{origin}/api/v1/search/job/posts", body, search_headers)
    return parse_feishu_jobs(payload, company, host, path or "index")


def _portal_jobs(url: str, company: str, post=post_json, keyword: str = "") -> list[dict] | None:
    """Return jobs for a known portal, or None when the URL is not one."""
    portal = feishu_portal(url)
    if portal:
        host, path = portal
        return read_feishu_board(f"https://{host}", path, company, keyword)
    host = zhiye_host(url)
    if host:
        payload = post(
            f"https://{host}/api/Jobad/GetJobAdPageList",
            {"PageIndex": 1, "PageSize": PER_SOURCE_JOB_CAP},
            {"Origin": f"https://{host}", "Referer": f"https://{host}/"},
        )
        return parse_zhiye_jobs(payload, company, host)
    return None


def _embedded_portal(page: str) -> str:
    for match in re.finditer(r"https://[a-z0-9.-]+\.(?:jobs\.feishu\.cn|zhiye\.com)[^\"'\s<>]*", page or "", re.I):
        link = html.unescape(match.group(0)).split("\\")[0]
        if "/share/base/form" in link:
            continue
        return link
    return ""


def website_path_from_html(page: str) -> str:
    match = re.search(r'<script id="js-websiteInfo"[^>]*>(.*?)</script>', page or "", re.S)
    if not match:
        return ""
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""
    path = (data.get("website_info") or {}).get("path") if isinstance(data, dict) else ""
    return str(path or "index")


def parse_tencent_jobs(payload: dict) -> list[dict]:
    posts = ((payload.get("Data") or {}) if isinstance(payload, dict) else {}).get("Posts")
    if not isinstance(posts, list):
        return []
    found = []
    for item in posts:
        if not isinstance(item, dict) or not item.get("RecruitPostName"):
            continue
        link = str(item.get("PostURL") or "")
        if link.startswith("http://"):
            link = "https://" + link[len("http://"):]
        if not link:
            continue
        found.append(job_record(
            item.get("ComName") or "腾讯",
            item["RecruitPostName"],
            item.get("LocationName") or "",
            link,
            link,
            item.get("CategoryName") or "",
        ))
    return found


def parse_eleduck_jobs(payload: dict) -> list[dict]:
    posts = payload.get("posts") if isinstance(payload, dict) else None
    if not isinstance(posts, list):
        return []
    found = []
    for item in posts:
        if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
            continue
        title = str(item.get("title"))
        if "社区规则" in title or "新人必读" in title:
            continue
        link = f"https://eleduck.com/posts/{item['id']}"
        found.append(job_record("", title, "", link, link, str(item.get("summary") or "")[:180]))
    return found


def parse_microdata_jobs(page: str, base_url: str) -> list[dict]:
    parts = re.split(r'itemType="https://schema.org/JobPosting"', page or "")
    found = []
    for part in parts[1:41]:
        title_match = re.search(r'itemProp="title" content="([^"]+)"', part)
        href_match = re.search(r'href="([^"]+)"', part)
        if not title_match or not href_match:
            continue
        org_match = re.search(r'itemProp="name">([^<]+)', part)
        company = html.unescape(org_match.group(1)).strip() if org_match else ""
        title = html.unescape(title_match.group(1)).strip()
        link = urljoin(base_url, html.unescape(href_match.group(1)))
        if not title or not link.startswith(("http://", "https://")):
            continue
        found.append(job_record(company, title, "", link, link))
    return found


def parse_meituan_jobs(payload: dict) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get("list") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    found = []
    for item in rows:
        if not isinstance(item, dict) or not item.get("name") or not item.get("jobUnionId"):
            continue
        cities = [str(city.get("name")) for city in item.get("cityList") or [] if isinstance(city, dict) and city.get("name")]
        link = f"https://zhaopin.meituan.com/web/position/detail?jobUnionId={item['jobUnionId']}"
        found.append(job_record("美团", item["name"], " / ".join(cities[:4]), link, link))
    return found


def parse_next_positions(page: str, base_url: str, company: str) -> list[dict]:
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page or "", re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    positions = ((data.get("props") or {}).get("pageProps") or {}).get("positionList")
    if not isinstance(positions, list):
        return []
    found = []
    for item in positions:
        if not isinstance(item, dict):
            continue
        title = item.get("name") or item.get("title")
        if not title:
            continue
        places = item.get("workPlaceNameList") or []
        location = " / ".join(str(place) for place in places if place) if isinstance(places, list) else ""
        link = ""
        if item.get("id") and "netease.com" in base_url:
            link = f"https://hr.163.com/job-detail.html?id={item['id']}"
        elif item.get("url"):
            link = urljoin(base_url, str(item["url"]))
        if not link:
            continue
        found.append(job_record(company, str(title), location, link, link))
    return found


def _read_json_source(name: str, page_url: str, api_url: str, fetch, parser, query: str, limit: int) -> dict:
    try:
        _final, body = fetch(api_url)
        jobs = parser(_loads_relaxed(body))
    except Exception as error:
        return unavailable(name, page_url, error)
    return _finish_source(name, page_url, jobs, query, limit, "no_public_job_list")


def read_html_source(record: dict, query: str, limit: int, fetch, allow_board_api: bool) -> dict:
    url = str(record.get("url") or "")
    name = str(record.get("name") or url)
    if allow_board_api:
        from official_extra import read_known
        known = read_known(record, query, limit)
        if known is not None:
            return known
    host = urlparse(url).netloc.casefold().removeprefix("www.")
    if host in {"hr.tencent.com", "careers.tencent.com", "join.qq.com"}:
        return _read_json_source(
            name, url,
            "https://careers.tencent.com/tencentcareer/api/post/Query?pageIndex=1&pageSize=30&language=zh-cn&area=cn",
            fetch, parse_tencent_jobs, query, limit,
        )
    if host == "eleduck.com":
        return _read_json_source(
            name, url, "https://svc.eleduck.com/api/v1/posts?category=5&page=1",
            fetch, parse_eleduck_jobs, query, limit,
        )
    if host == "zhaopin.meituan.com":
        keywords = "LongCat" if "longcat" in url.casefold() else ""
        try:
            payload = post_json(
                "https://zhaopin.meituan.com/api/official/job/getJobList",
                {
                    "page": {"pageNo": 1, "pageSize": PER_SOURCE_JOB_CAP},
                    "keywords": keywords,
                    "cityCodeList": [],
                    "departmentIdList": [],
                    "jobCategoryIdList": [],
                    "jobTypeCodeList": ["1", "2", "3"],
                },
                {"Origin": "https://zhaopin.meituan.com", "Referer": url},
            )
            jobs = parse_meituan_jobs(payload)
            if keywords:
                jobs = [job for job in jobs if "longcat" in job["title"].casefold()]
        except Exception as error:
            return unavailable(name, url, error)
        return _finish_source(name, url, jobs, query, limit, "no_public_job_list", pagination_complete=len(jobs) < PER_SOURCE_JOB_CAP)
    if feishu_portal(url) or zhiye_host(url):
        try:
            jobs = _portal_jobs(url, name, keyword=query) or []
        except Exception as error:
            return unavailable(name, url, error)
        return _finish_source(name, url, jobs, query, limit, "no_public_job_list", pagination_complete=len(jobs) < PER_SOURCE_JOB_CAP)
    try:
        final, page = fetch(url)
    except Exception as error:
        return unavailable(name, url, error)
    jobs = jobs_from_boards(final, page, name, fetch) if allow_board_api else []
    if not jobs and allow_board_api:
        portal_path = website_path_from_html(page)
        if portal_path:
            origin = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
            try:
                jobs = read_feishu_board(origin, portal_path, name, query)
            except Exception:
                jobs = []
    if not jobs:
        jobs = parse_next_positions(page, final, name)
    if not jobs:
        jobs = parse_microdata_jobs(page, final)
    if not jobs:
        jobs = html_jobs(page, final, name)
    if not jobs:
        hop = _career_hop(page, final) or (_embedded_portal(page) if allow_board_api else "")
        if hop and (feishu_portal(hop) or zhiye_host(hop)):
            try:
                jobs = _portal_jobs(hop, name, keyword=query) or []
            except Exception:
                jobs = []
        elif hop:
            try:
                final_hop, hop_page = fetch(hop)
                jobs = jobs_from_boards(final_hop, hop_page, name, fetch) if allow_board_api else []
                if not jobs and allow_board_api and (feishu_portal(final_hop) or zhiye_host(final_hop) or _embedded_portal(hop_page)):
                    portal_url = final_hop if feishu_portal(final_hop) or zhiye_host(final_hop) else _embedded_portal(hop_page)
                    try:
                        jobs = _portal_jobs(portal_url, name, keyword=query) or []
                    except Exception:
                        jobs = []
                if not jobs:
                    jobs = html_jobs(hop_page, final_hop, name)
                page = hop_page
            except Exception:
                pass
    return _finish_source(name, url, jobs, query, limit, _page_unreadable(page, jobs))


def read_official(record: dict, query: str, limit: int, fetch=fetch_url, use_browser: bool = True) -> dict:
    result = read_html_source(record, query, limit, fetch, allow_board_api=True)
    if result.get("source_status") == "searched" or not use_browser:
        return result
    if record.get("access") == "会员主导" or source_catalog.hidden_from_search(record):
        return result
    try:
        return read_browser_source(record, query, limit)
    except Exception as error:
        result["error"] = str(error)[:180]
        return result


def read_browser_source(record: dict, query: str, limit: int) -> dict:
    from browser_jobs import MAX_PAGES, browse_official
    name = str(record.get("name") or "")
    url = str(record.get("url") or "")
    if record.get("access") == "会员主导" or source_catalog.hidden_from_search(record):
        return unavailable(name, url, "membership_required")
    jobs = browse_official(url, name, max(limit, PER_SOURCE_JOB_CAP * MAX_PAGES))
    result = _finish_source(name, url, jobs, query, limit, "no_readable_rendered_jobs")
    result["read_method"] = "browser"
    result["_collected_jobs"] = jobs
    result["collected_count"] = len(jobs)
    if result.get("source_status") != "searched":
        result["failure_reason"] = "parser_gap"
    return result


def read_platform(record: dict, query: str, limit: int, fetch=fetch_url) -> dict:
    host = urlparse(str(record.get("url") or "")).netloc.casefold().removeprefix("www.")
    readers = {
        "remoteok.com": read_remoteok,
        "weworkremotely.com": read_weworkremotely,
        "v2ex.com": read_v2ex,
        "news.ycombinator.com": read_hackernews,
    }
    reader = readers.get(host)
    if reader:
        return reader(record, query, limit, fetch)
    return read_html_source(record, query, limit, fetch, allow_board_api=False)


def read_remoteok(record: dict, query: str, limit: int, fetch) -> dict:
    url = "https://remoteok.com/api"
    try:
        _final, body = fetch(url, limit=2_000_000) if _accepts_limit(fetch) else fetch(url)
        payload = _loads_relaxed(body)
    except Exception as error:
        return unavailable(record["name"], record["url"], error)
    jobs = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            link = item.get("url") or item.get("apply_url")
            if not link:
                continue
            jobs.append(job_record(item.get("company") or "", item.get("position") or "", item.get("location") or "Remote", link, item.get("apply_url") or link))
    return _finish_source(record["name"], record["url"], jobs, query, limit, "no_public_job_list")


def read_weworkremotely(record: dict, query: str, limit: int, fetch) -> dict:
    url = "https://weworkremotely.com/remote-jobs.rss"
    try:
        _final, body = fetch(url)
    except Exception as error:
        return unavailable(record["name"], record["url"], error)
    jobs = []
    for block in re.findall(r"<item\b[\s\S]*?</item>", body, flags=re.I):
        title = _xml_text(block, "title")
        link = _xml_text(block, "link")
        if not title or not link:
            continue
        company, role = _split_company_title(title)
        region = _xml_text(block, "region") or "Remote"
        jobs.append(job_record(company, role or title, region, link, link))
    return _finish_source(record["name"], record["url"], jobs, query, limit, "no_public_job_list")


def read_v2ex(record: dict, query: str, limit: int, fetch) -> dict:
    url = "https://www.v2ex.com/api/topics/show.json?node_name=jobs"
    try:
        _final, body = fetch(url)
        payload = _loads_relaxed(body)
    except Exception as error:
        return unavailable(record["name"], record["url"], error)
    jobs = []
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            link = item.get("url") or f"https://www.v2ex.com/t/{item.get('id')}"
            company, role = _split_company_title(str(item.get("title")))
            title = role or str(item.get("title"))
            if not STRONG_ROLE.search(title):
                continue
            jobs.append(job_record(company, title, "", link, link, str(item.get("content") or "")[:180]))
    return _finish_source(record["name"], record["url"], jobs, query, limit, "no_public_job_list")


def read_hackernews(record: dict, query: str, limit: int, fetch) -> dict:
    story_url = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=1"
    try:
        _final, body = fetch(story_url)
        story_payload = json.loads(body)
        story = (story_payload.get("hits") or [None])[0]
        if not isinstance(story, dict) or not story.get("objectID"):
            return unavailable(record["name"], record["url"], "no_public_job_list")
        comment_url = f"https://hn.algolia.com/api/v1/search?tags=comment,story_{story['objectID']}&hitsPerPage=80"
        _final, comments_body = fetch(comment_url)
        comments = json.loads(comments_body).get("hits") or []
    except Exception as error:
        return unavailable(record["name"], record["url"], error)
    jobs = []
    for item in comments:
        if not isinstance(item, dict):
            continue
        text = _visible_text(str(item.get("comment_text") or ""))
        first = text.split("\n", 1)[0].strip()
        if len(first) < 8 or ("|" not in first and "｜" not in first):
            continue
        parts = [part.strip() for part in re.split(r"\s*[|｜]\s*", first) if part.strip()]
        company = parts[0] if len(parts) >= 2 else ""
        title = parts[1] if len(parts) >= 2 else first[:90]
        location = parts[2] if len(parts) >= 3 else ""
        if not STRONG_ROLE.search(first) and not BROAD_ROLE.search(first) and "remote" not in first.casefold():
            continue
        link = f"https://news.ycombinator.com/item?id={item.get('objectID')}"
        jobs.append(job_record(company, title, location, link, link, first[:180]))
    return _finish_source(record["name"], record["url"], jobs, query, limit, "no_public_job_list")


def _xml_text(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</{tag}>", block, flags=re.I)
    if not match:
        return ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())


def _split_company_title(title: str) -> tuple[str, str]:
    parts = [part.strip() for part in re.split(r"\s*[:：|｜]\s*", title, maxsplit=1) if part.strip()]
    if len(parts) == 2 and 1 < len(parts[0]) <= 40:
        return parts[0], parts[1]
    return "", title.strip()


def _accepts_limit(fetch) -> bool:
    try:
        return "limit" in fetch.__code__.co_varnames
    except Exception:
        return False


def _blocked_source_name(name: str) -> bool:
    folded = str(name or "").casefold().replace(" ", "")
    return "jobradar" in folded or "出海聘" in str(name or "") or "chuhaipin" in folded


def city_hint(location: object) -> str:
    for part in re.split(r"[,/|、，]+", str(location or "")):
        piece = part.strip()
        if piece and piece.casefold() not in {"remote", "远程", "hybrid", "onsite", "on-site", "anywhere"}:
            return piece
    return str(location or "").strip()


def to_guard_job(job: dict) -> dict:
    blob = " ".join(str(job.get(key) or "") for key in ("title", "location", "summary"))
    if re.search(r"实习|intern", blob, re.I):
        work_type = "实习"
    elif re.search(r"全职|正职|full[- ]?time", blob, re.I):
        work_type = "全职"
    else:
        work_type = "unknown"
    if re.search(r"远程|remote", blob, re.I):
        mode = "远程"
    elif re.search(r"混合|hybrid", blob, re.I):
        mode = "混合"
    elif re.search(r"现场|到岗|线下|on[- ]?site", blob, re.I):
        mode = "现场"
    else:
        mode = "unknown"
    payload = {"work_type": work_type, "city": city_hint(job.get("location")), "work_mode": mode}
    if re.search(r"需要搬迁|必须搬迁|relocation required", blob, re.I):
        payload["relocation_required"] = True
    elif re.search(r"无需搬迁|不要求搬迁|relocation not required", blob, re.I):
        payload["relocation_required"] = False
    return payload


AI_DUTY = (
    "大模型", "语言模型", "机器学习", "深度学习", "多模态", "智能体", "agent",
    "aigc", "文生图", "vla", "nlp", "llm", "人工智能", "生成式", "具身智能",
    "模型训练", "模型推理", "模型部署", "模型评测", "推理引擎", "推理部署", "推理加速",
)
AI_ROLE = ("产品", "运营", "设计", "增长")
NON_AI_FUNCTION = ("销售", "财务", "商务", "市场", "采购", "法务", "人事", "行政", "客服", "招聘")
MANUFACTURING_QUALITY = ("供应商质量", "生产质量", "制造质量", "来料质量", "制程质量", "过程质量", "出货质量", "进料质量")


def ai_relevance(job: dict) -> str:
    """Verified only from a specific AI duty. A lone 模型 or 算法 is not enough."""
    title = str(job.get("title") or "")
    summary = str(job.get("summary") or "")
    blob = f"{title} {summary}".casefold()
    if any(phrase in title for phrase in MANUFACTURING_QUALITY):
        return "unverified"
    if any(word in title for word in NON_AI_FUNCTION):
        return "unverified"
    if any(term in blob for term in AI_DUTY):
        return "verified"
    if any(role in blob for role in AI_ROLE) and any(term in blob for term in ("ai", "人工智能", "大模型", "aigc", "智能体")):
        return "verified"
    return "unverified"


def _screen(decision: str | None, score: float, query_tokens: list[str]) -> str:
    if decision == "not_recommended":
        return "暂不建议"
    if decision == "eligible_for_scoring" or (query_tokens and score >= 0.67):
        return "优先看"
    return "可以看"


def _diversify(jobs: list[dict], limit: int) -> list[dict]:
    """Keep the hard-constraint order, but rotate sources inside each band.

    Otherwise one platform's alphabetical names can fill the whole shortlist
    before an equally relevant official-site job appears.
    """
    chosen = []
    for screen in ("优先看", "可以看", "暂不建议"):
        grouped: dict[str, list[dict]] = {}
        order = []
        for job in jobs:
            if job.get("screen") != screen:
                continue
            source = str(job.get("source") or "")
            if source not in grouped:
                grouped[source] = []
                order.append(source)
            grouped[source].append(job)
        while order and len(chosen) < limit:
            remaining = []
            for source in order:
                if grouped[source]:
                    chosen.append(grouped[source].pop(0))
                    if len(chosen) >= limit:
                        break
                if grouped[source]:
                    remaining.append(source)
            order = remaining
    return chosen


def combine_results(sources: list[dict], query: str = "", limit: int = 20, profile: dict | None = None) -> dict:
    query_tokens = tokenize(query)
    visible = []
    for source in sources:
        name = str(source.get("source") or "")
        if source.get("source_status") == "membership_required" or _blocked_source_name(name):
            continue
        visible.append(source)
    merged = []
    seen = set()
    for source in visible:
        if source.get("source_status") != "searched":
            continue
        for item in source.get("jobs") or []:
            if not isinstance(item, dict) or not item.get("title") or not item.get("job_url"):
                continue
            prepared = dict(item)
            prepared["source"] = source.get("source") or prepared.get("source") or ""
            prepared["source_url"] = source.get("source_url") or prepared.get("source_url") or ""
            if _blocked_source_name(prepared["source"]):
                continue
            key = (_norm_text(prepared.get("company")), _norm_text(prepared.get("title")), _norm_url(prepared.get("job_url")))
            link_key = ("url", _norm_url(prepared.get("job_url")))
            if key in seen or link_key in seen:
                continue
            seen.add(key)
            seen.add(link_key)
            score = relevance(prepared, query_tokens)
            if query_tokens and score <= 0:
                continue
            decision = None
            conflicts = []
            unknowns = []
            if profile:
                try:
                    judged = match_guard.evaluate(profile, to_guard_job(prepared))
                    decision = judged.get("decision")
                    conflicts = judged.get("conflicts") or []
                    unknowns = judged.get("unknowns") or []
                except Exception:
                    decision = None
            prepared["ai_relevance"] = ai_relevance(prepared)
            prepared["screen"] = _screen(decision, score, query_tokens)
            if prepared["ai_relevance"] != "verified" and prepared["screen"] == "优先看":
                prepared["screen"] = "可以看"
            prepared["decision"] = decision or ""
            prepared["conflicts"] = conflicts
            prepared["unknowns"] = unknowns
            prepared.pop("summary", None)
            merged.append(prepared)
    order = {"优先看": 0, "可以看": 1, "暂不建议": 2}
    merged.sort(key=lambda item: (order.get(item.get("screen"), 9), -relevance(item, query_tokens), item.get("company", ""), item.get("title", "")))
    chosen = _diversify(merged, limit)
    attempted = [source.get("source") for source in visible if source.get("source")]
    public = [source for source in visible if source.get("kind") != "official"]
    official = [source for source in visible if source.get("kind") == "official"]
    payload = {
        "query": query,
        "internal_only_sources": True,
        "jobs": chosen,
        "matched_jobs": len(chosen),
        "sources_attempted": attempted,
        "sources": [
            {
                "source": source.get("source"),
                "source_url": source.get("source_url"),
                "source_status": source.get("source_status"),
                "matched_jobs": source.get("matched_jobs", 0),
                "collected_count": source.get("collected_count", 0),
                **({"failure_reason": source.get("failure_reason")} if source.get("failure_reason") else {}),
                **({"read_method": source.get("read_method")} if source.get("read_method") else {}),
                **({"pagination_complete": source.get("pagination_complete")} if "pagination_complete" in source else {}),
                **({"checked_at": source.get("checked_at")} if source.get("checked_at") else {}),
                **({"entry_url": source.get("entry_url")} if source.get("entry_url") else {}),
                **({"error": source.get("error")} if source.get("error") and source.get("source_status") != "searched" else {}),
            }
            for source in visible
        ],
        "source_summary": {
            "attempted": len(visible),
            "platforms_attempted": len(public),
            "official_sites_attempted": len(official),
            "with_jobs": sum(1 for source in visible if source.get("source_status") == "searched" and source.get("matched_jobs")),
            "unavailable": sum(1 for source in visible if source.get("source_status") == "unavailable"),
            "official_site_cap": source_catalog.OFFICIAL_SITE_CAP,
        },
    }
    if not chosen:
        payload["note"] = "这次没有从公开页面读到可推荐的职位。"
    return payload
