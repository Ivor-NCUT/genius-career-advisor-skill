#!/usr/bin/env python3
"""Public job APIs found by opening the remaining official career sites."""

from __future__ import annotations

import json
import re
from http.cookiejar import CookieJar
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

import career_sources


def _post(url: str, data: bytes, headers: dict) -> str:
    from urllib.request import urlopen
    request = Request(url, data=data, headers={"User-Agent": career_sources.USER_AGENT, **headers})
    with urlopen(request, timeout=career_sources.FETCH_TIMEOUT_SECONDS, context=career_sources.ssl.create_default_context()) as response:
        return response.read(career_sources.MAX_RESPONSE_BYTES).decode("utf-8", "replace")


def parse_jd_jobs(payload) -> list[dict]:
    if not isinstance(payload, list):
        return []
    jobs = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("positionNameOpen") or item.get("positionName") or "").strip()
        requirement_id = item.get("requirementId")
        if not title or not requirement_id:
            continue
        link = f"https://zhaopin.jd.com/web/job/job_info_list/detail?requirementId={requirement_id}"
        jobs.append(career_sources.job_record("京东", title, str(item.get("workCity") or ""), link, link))
    return jobs


def parse_xiaohongshu_jobs(payload) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    jobs = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("positionName") or "").strip()
        position_id = item.get("positionId")
        if not title or not position_id:
            continue
        link = f"https://job.xiaohongshu.com/social/position/{position_id}"
        jobs.append(career_sources.job_record("小红书", title, str(item.get("workplace") or ""), link, link))
    return jobs


def parse_manus_jobs(payload) -> list[dict]:
    try:
        items = payload[0]["result"]["data"]["json"]
    except (KeyError, IndexError, TypeError):
        return []
    jobs = []
    for item in items:
        if not isinstance(item, dict) or not item.get("title") or not item.get("id"):
            continue
        places = item.get("locations") or []
        location = "、".join(str(place) for place in places if place)
        link = f"https://careers.manus.im/en/job/{item['id']}"
        jobs.append(career_sources.job_record("Manus", str(item["title"]), location, link, link))
    return jobs


def parse_horizon_jobs(payload) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    page = data.get("pageForm") if isinstance(data, dict) else None
    items = page.get("pageData") if isinstance(page, dict) else None
    if not isinstance(items, list):
        return []
    jobs = []
    for item in items:
        if not isinstance(item, dict) or not item.get("postName") or not item.get("postId"):
            continue
        link = (
            "https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/posDetail.html"
            f"?postId={item['postId']}&postType=society"
        )
        jobs.append(career_sources.job_record("地平线", str(item["postName"]), str(item.get("workPlaceStr") or ""), link, link))
    return jobs


def parse_alibaba_jobs(payload, origin: str) -> list[dict]:
    content = payload.get("content") if isinstance(payload, dict) else None
    items = content.get("datas") if isinstance(content, dict) else None
    if not isinstance(items, list):
        return []
    jobs = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        raw = str(item.get("positionUrl") or "")
        link = urljoin(origin, raw.split("&")[0]) if raw else origin
        places = item.get("workLocations") or []
        location = "、".join(str(place) for place in places if place)
        jobs.append(career_sources.job_record("阿里巴巴", str(item["name"]), location, link, link))
    return jobs


def parse_onetoken_jobs(script: str) -> list[dict]:
    jobs = []
    for job_id, title, _cat, location in re.findall(
        r'id:\s*"([^"]+)"\s*,\s*title:\s*"([^"]+)"\s*,\s*cat:\s*"([^"]+)"\s*,\s*loc:\s*"([^"]+)"',
        script,
    ):
        link = f"https://onetokencareers.com/job.html?id={job_id}"
        jobs.append(career_sources.job_record("万格智元", title, location, link, link))
    return jobs


def parse_luchen_jobs(page: str) -> list[dict]:
    titles = []
    for title in re.findall(r"<p>\s*([^<]{4,40})\s*</p>", page):
        title = " ".join(title.split())
        if "工程师" not in title and "经理" not in title:
            continue
        if title not in titles:
            titles.append(title)
    return [
        career_sources.job_record("潞晨科技", title, "", f"https://www.luchentech.com/join#role={title}", f"https://www.luchentech.com/join#role={title}")
        for title in titles
    ]


def _jd_jobs() -> list[dict]:
    body = _post(
        "https://zhaopin.jd.com/web/job/job_list",
        urlencode({
            "pageIndex": "1",
            "pageSize": "30",
            "workCityJson": "[]",
            "jobTypeJson": "[]",
            "jobSearch": "",
            "depTypeJson": "[]",
        }).encode(),
        {"Content-Type": "application/x-www-form-urlencoded", "Referer": "https://zhaopin.jd.com/"},
    )
    return parse_jd_jobs(json.loads(body))


def _xiaohongshu_jobs() -> list[dict]:
    body = _post(
        "https://job.xiaohongshu.com/websiterecruit/position/pageQueryPosition",
        json.dumps({"positionName": "", "pageNum": 1, "pageSize": 30, "recruitType": "social"}).encode(),
        {"Content-Type": "application/json", "Origin": "https://job.xiaohongshu.com", "Referer": "https://job.xiaohongshu.com/social/position"},
    )
    return parse_xiaohongshu_jobs(json.loads(body))


def _manus_jobs() -> list[dict]:
    _final, body = career_sources.fetch_url(
        "https://careers.manus.im/api/trpc/applications.publicJobs?batch=1&input=%7B%220%22%3A%7B%22json%22%3A%7B%22locale%22%3A%22en%22%7D%7D%7D"
    )
    return parse_manus_jobs(json.loads(body))


def _horizon_jobs() -> list[dict]:
    body = _post(
        "https://wecruit.hotjob.cn/wecruit/positionInfo/listPosition/SU64819a4f2f9d2433ba8b043a?iSaJAx=isAjax&request_locale=zh_CN",
        urlencode({"isFrompb": "true", "recruitType": "2", "pageSize": "30", "currentPage": "1"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded", "Referer": "https://wecruit.hotjob.cn/SU64819a4f2f9d2433ba8b043a/pb/social.html"},
    )
    return parse_horizon_jobs(json.loads(body))


def _alibaba_jobs() -> list[dict]:
    origin = "https://talent-holding.alibaba.com"
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    page = Request(origin + "/off-campus/position-list?lang=zh", headers={"User-Agent": career_sources.USER_AGENT})
    opener.open(page, timeout=career_sources.FETCH_TIMEOUT_SECONDS).read()
    token = next(cookie.value for cookie in jar if cookie.name == "XSRF-TOKEN")
    payload = json.dumps({
        "channel": "group_official_site", "language": "zh", "batchId": "", "categories": "",
        "deptCodes": [], "key": "", "pageIndex": 1, "pageSize": 30, "regions": "",
        "subCategories": "", "shareType": "", "shareId": "", "myReferralShareCode": "",
    }).encode()
    request = Request(
        origin + "/position/search?_csrf=" + token,
        data=payload,
        headers={
            "User-Agent": career_sources.USER_AGENT,
            "Content-Type": "application/json",
            "X-XSRF-TOKEN": token,
            "Referer": origin + "/off-campus/position-list?lang=zh",
        },
    )
    body = opener.open(request, timeout=career_sources.FETCH_TIMEOUT_SECONDS).read().decode("utf-8", "replace")
    return parse_alibaba_jobs(json.loads(body), origin)


def _onetoken_jobs() -> list[dict]:
    _final, body = career_sources.fetch_url("https://onetokencareers.com/assets/data.js")
    return parse_onetoken_jobs(body)


def _luchen_jobs() -> list[dict]:
    _final, body = career_sources.fetch_url("https://www.luchentech.com/join")
    return parse_luchen_jobs(body)


def read_known(record: dict, query: str, limit: int) -> dict | None:
    host = career_sources.urlparse(record.get("url") or "").netloc.casefold()
    name = str(record.get("name") or "")
    readers = {
        "zhaopin.jd.com": _jd_jobs,
        "job.xiaohongshu.com": _xiaohongshu_jobs,
        "careers.manus.im": _manus_jobs,
        "wecruit.hotjob.cn": _horizon_jobs,
        "talent-holding.alibaba.com": _alibaba_jobs,
        "onetokencareers.com": _onetoken_jobs,
        "www.luchentech.com": _luchen_jobs,
        "luchentech.com": _luchen_jobs,
    }
    if "manus.im" in host and "careers.manus.im" not in host:
        reader = _manus_jobs
    elif host.removeprefix("www.") in readers:
        reader = readers[host.removeprefix("www.")]
    elif host in readers:
        reader = readers[host]
    elif name.startswith("京东"):
        reader = _jd_jobs
    else:
        return None
    try:
        jobs = reader()
    except Exception as error:
        return career_sources.unavailable(name, record.get("url") or "", error)
    return career_sources._finish_source(name, record.get("url") or "", jobs, query, limit, "no_public_job_list")
