#!/usr/bin/env python3
"""Search public sources, then render a bounded set of dynamic official sites."""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import career_cache
import career_sources
import source_catalog
import watcha_jobs


BONJOUR_URL = "https://bonjour.bio/jobs-mapping/jobs"
JOBRADAR_URL = "https://jobradar.cc/zh/jobs"
JOB_PATTERN = re.compile(
    r'\{\\"id\\":\\"([0-9a-f-]{36})\\",\\"teamSlug\\":\\"(.*?)\\",'
    r'\\"role\\":\\"(.*?)\\",\\"loc\\":\\"(.*?)\\"'
)
TEAM_PATTERN = re.compile(r'\\"team\\":\{\\"slug\\":\\"(.*?)\\",\\"name\\":\\"(.*?)\\"')
FLIGHT_JOB_PATTERN = re.compile(r'id:"([0-9a-f-]{36})",teamSlug:"([^"]*)",role:"([^"]*)"')
FLIGHT_TEAM_PATTERN = re.compile(r'slug:"([^"]+)",name:"([^"]*)"')


def decode_json_string(value):
    return json.loads(f'"{value}"')


def fetch_text(url):
    _final, body = career_sources.fetch_url(url)
    return body


def bonjour_rows(page):
    escaped = JOB_PATTERN.findall(page)
    if escaped:
        teams = {decode_json_string(slug): decode_json_string(name) for slug, name in TEAM_PATTERN.findall(page)}
        rows = []
        for job_id, raw_slug, raw_title, raw_location in escaped:
            rows.append((job_id, decode_json_string(raw_slug), decode_json_string(raw_title), decode_json_string(raw_location), teams))
        return rows
    teams = {slug: name for slug, name in FLIGHT_TEAM_PATTERN.findall(page)}
    rows = []
    for match in FLIGHT_JOB_PATTERN.finditer(page):
        job_id, slug, title = match.groups()
        window = page[match.end():match.end() + 1200]
        loc_match = re.search(r'loc:"([^"]*)"', window)
        location = loc_match.group(1) if loc_match and 'id:"' not in window[:loc_match.start()] else ""
        rows.append((job_id, slug, title, location, teams))
    return rows


def normalize_bonjour(page, query="", limit=20):
    tokens = query.casefold().split()
    jobs = []
    seen = set()
    for job_id, slug, title, location, teams in bonjour_rows(page):
        if job_id in seen:
            continue
        seen.add(job_id)
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


def visible_sources(sources):
    visible = []
    for item in sources:
        name = str(item.get("source", "")).casefold().replace(" ", "")
        if item.get("source_status") == "membership_required" or "jobradar" in name:
            continue
        visible.append(item)
    return visible


def load_catalog(path: Path | None = None) -> dict:
    try:
        return source_catalog.load(path or source_catalog.DEFAULT_CATALOG)
    except Exception:
        return {"schema_version": 1, "generated_at": None, "records": []}


def planned_sources(payload: dict, query: str = "") -> tuple[dict, list[dict]]:
    plan = source_catalog.search_plan(payload, query)
    sources = [
        {"name": "Bonjour", "kind": "bonjour", "url": BONJOUR_URL},
        {"name": "Watcha", "kind": "watcha", "url": watcha_jobs.JOBS_URL},
    ]
    for record in plan["public_platforms"]:
        if "bonjour.bio" in str(record.get("url", "")):
            continue
        sources.append({"name": record.get("name"), "kind": "platform", "url": record.get("url"), "record": record})
    for record in plan["official_sites"]:
        sources.append({"name": record.get("name"), "kind": "official", "url": record.get("url"), "record": record})
    return plan, sources


def _load_profile(profile):
    if not profile:
        return None
    try:
        if isinstance(profile, dict):
            return profile
        return json.loads(Path(profile).expanduser().read_text(encoding="utf-8"))
    except Exception:
        return None


def _cached_result(record: dict, entry: dict, query: str, limit: int) -> dict:
    result = career_sources._finish_source(
        record.get("name") or "",
        entry.get("entry_url") or record.get("url") or "",
        entry.get("jobs") or [],
        query,
        limit,
        entry.get("failure_reason") or "no_public_job_list",
    )
    result["read_method"] = "cache"
    result["checked_at"] = entry.get("fetched_at") or ""
    result["entry_url"] = entry.get("entry_url") or record.get("url") or ""
    result["pagination_complete"] = entry.get("pagination_complete")
    if entry.get("collected_count") is not None and result.get("source_status") == "searched":
        result["collected_count"] = entry.get("collected_count")
    return result


def _remember_read(cache: dict, record: dict, result: dict) -> None:
    if record.get("access") == "会员主导" or source_catalog.hidden_from_search(record):
        return
    reason = result.get("failure_reason") or ""
    if result.get("source_status") == "searched" and reason == "collected_no_match":
        reason = ""
    career_cache.remember(
        cache,
        str(record.get("name") or ""),
        catalog_url=record.get("url") or "",
        entry_url=result.get("entry_url") or record.get("url") or "",
        read_method=result.get("read_method") or "",
        collected_count=result.get("collected_count") or 0,
        pagination_complete=result.get("pagination_complete"),
        failure_reason=reason,
        jobs=result.get("_collected_jobs") or (result.get("jobs") if result.get("source_status") == "searched" and not reason else []),
    )


def search_all(query="", limit=20, profile=None, catalog=None, fetch=None, browser_limit=5, cache_file=None):
    """Search public platforms and official career sites together.

    Bonjour and Watcha are one class of source. Catalog platforms and company
    career sites run in the same pool. A single failure stays inside that source.
    """
    fetch = fetch or career_sources.fetch_url
    payload = catalog if isinstance(catalog, dict) else load_catalog(catalog)
    plan, sources = planned_sources(payload, query)
    profile_data = _load_profile(profile)
    per_source = career_sources.PER_SOURCE_JOB_CAP

    def run(meta):
        try:
            if meta["kind"] == "bonjour":
                result = normalize_bonjour(fetch(meta["url"])[1], query, per_source)
            elif meta["kind"] == "watcha":
                result = watcha_jobs.normalize(watcha_jobs.fetch_payload(), query, per_source)
            elif meta["kind"] == "official":
                result = career_sources.read_official(meta["record"], query, per_source, fetch, use_browser=False)
            else:
                result = career_sources.read_platform(meta["record"], query, per_source, fetch)
        except Exception as error:
            result = unavailable(meta["name"], meta["url"], error)
        result["kind"] = "official" if meta["kind"] == "official" else "platform"
        return meta["name"], result

    cache_path = cache_file if cache_file is not None else career_cache.cache_path(
        catalog if isinstance(catalog, Path) else None
    )
    stored = career_cache.load(cache_path)
    results = {}
    workers = min(career_sources.MAX_WORKERS, max(1, len(sources)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(run, meta) for meta in sources]
        for future in as_completed(futures):
            name, result = future.result()
            results[name] = result
    for meta in sources:
        if meta["kind"] != "official":
            continue
        result = results[meta["name"]]
        if result.get("failure_reason"):
            continue
        if result.get("source_status") == "searched":
            result["failure_reason"] = "" if result.get("matched_jobs") else "collected_no_match"
            result["read_method"] = result.get("read_method") or "http"
            continue
        result["failure_reason"] = career_cache.classify_failure(result.get("error"))
        entry = career_cache.entry_for(stored, meta["name"])
        if entry and entry.get("jobs") and career_cache.fresh(entry):
            results[meta["name"]] = _cached_result(meta["record"], entry, query, per_source)
            results[meta["name"]]["kind"] = "official"
    candidates = []
    for meta in sources:
        if meta["kind"] != "official":
            continue
        named = career_cache.company_named(meta["record"], query)
        status = results[meta["name"]].get("source_status")
        cached_hit = results[meta["name"]].get("read_method") == "cache"
        if status != "searched" or (named and cached_hit):
            candidates.append(meta["record"])
    chosen_records = career_cache.pick_browser_targets(candidates, stored, query, browser_limit)
    chosen_names = {record.get("name") for record in chosen_records}
    browser_sources = [meta for meta in sources if meta["name"] in chosen_names]

    def render(meta):
        try:
            result = career_sources.read_browser_source(meta["record"], query, per_source)
        except Exception as error:
            result = unavailable(meta["name"], meta["url"], error)
        result["kind"] = "official"
        result["read_method"] = "browser"
        if result.get("source_status") != "searched":
            result["failure_reason"] = career_cache.classify_failure(result.get("failure_reason") or result.get("error"))
        elif not result.get("matched_jobs"):
            result["failure_reason"] = "collected_no_match"
        result["_collected_jobs"] = result.get("jobs") or []
        return meta["name"], result

    if browser_sources:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(render, meta) for meta in browser_sources]
            for future in as_completed(futures):
                name, result = future.result()
                previous = results.get(name) or {}
                keep_cache = (
                    previous.get("read_method") == "cache"
                    and result.get("source_status") != "searched"
                    and result.get("failure_reason") in {"network_error", "page_not_ready"}
                )
                if not keep_cache:
                    results[name] = result
                    record = next(meta["record"] for meta in browser_sources if meta["name"] == name)
                    _remember_read(stored, record, result)
                result.pop("_collected_jobs", None)
    if cache_file is not None or any(meta["kind"] == "official" for meta in sources):
        career_cache.save(stored, cache_path)
    ordered = [results[meta["name"]] for meta in sources if meta["name"] in results]
    combined = career_sources.combine_results(ordered, query, limit, profile_data)
    combined["official_sites_selected"] = plan["official_sites_selected"]
    combined["official_sites_total"] = plan["official_sites_total"]
    combined["official_site_cap"] = plan["official_site_cap"]
    combined["catalog_count"] = plan["catalog_count"]
    combined["catalog_generated_at"] = plan.get("catalog_generated_at")
    combined["source_summary"]["browser_attempted"] = len(browser_sources)
    combined["browser_site_cap"] = browser_limit
    return combined


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
    flight = (
        'id:"754a2bba-7f71-488a-b49a-c6da56483bf0",teamSlug:"demo",role:"AI 产品经理",'
        'hot:!1,loc:"杭州",team:{slug:"demo",name:"Demo AI"}'
    )
    flight_result = normalize_bonjour(flight, "产品", 10)
    assert flight_result["jobs"][0]["company"] == "Demo AI"
    assert flight_result["jobs"][0]["title"] == "AI 产品经理"
    assert flight_result["jobs"][0]["location"] == "杭州"
    assert jobradar_status()["source_status"] == "membership_required"
    assert jobradar_status()["jobs"] == []
    visible = visible_sources([
        {"source": "Bonjour", "source_status": "searched", "jobs": [{"title": "AI 产品经理"}]},
        {"source": "Watcha", "source_status": "unavailable", "jobs": []},
        jobradar_status(),
    ])
    assert [item["source"] for item in visible] == ["Bonjour", "Watcha"]
    encoded = json.dumps(visible, ensure_ascii=False)
    assert "JobRadar" not in encoded
    assert "membership_required" not in encoded
    assert unavailable("Demo", "https://example.com", RuntimeError("timeout"))["source_status"] == "unavailable"

    catalog = source_catalog.load(source_catalog.DEFAULT_CATALOG)
    plan, sources = planned_sources(catalog, "AI 产品")
    names = [item["name"] for item in sources]
    assert names[0] == "Bonjour" and "Watcha" in names
    assert "JobRadar" not in names
    assert all("出海聘" not in str(name) for name in names)
    assert sum(item["kind"] == "platform" for item in sources) >= 8
    assert sum(item["kind"] == "official" for item in sources) > 5
    assert plan["official_sites_selected"] == plan["official_sites_total"]
    assert plan["official_site_cap"] == source_catalog.OFFICIAL_SITE_CAP

    def fake_fetch(url, timeout=8, limit=1000):
        if "down.example" in url:
            raise career_sources.FetchError("timeout")
        if "boards-api.greenhouse.io" in url:
            return url, json.dumps({"jobs": [{
                "title": "AI 产品经理",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                "location": {"name": "北京"},
            }]})
        if "company.example" in url:
            return url, '<a href="https://boards.greenhouse.io/acme">开放职位</a>'
        if "remoteok.com/api" in url:
            return url, json.dumps([
                {"legal": "mention Remote OK"},
                {"company": "Remote Co", "position": "AI 产品经理", "location": "Remote", "url": "https://remoteok.com/jobs/1", "apply_url": "https://remoteok.com/jobs/1"},
            ])
        if "shell.example" in url:
            return url, "<html><body><div id='root'></div></body></html>"
        if "list.example" in url:
            return url, (
                '<a href="https://list.example/jobs/pm"><span>AI 产品经理</span><span>杭州</span></a>'
                '<a href="https://list.example/about">关于我们</a>'
            )
        raise career_sources.FetchError("HTTP 404", 404)

    official = career_sources.read_official(
        {"name": "示例公司", "url": "https://company.example/careers", "type": "公司招聘官网"},
        "产品经理",
        10,
        fake_fetch,
        use_browser=False,
    )
    assert official["source_status"] == "searched"
    assert official["jobs"][0]["title"] == "AI 产品经理"
    assert official["jobs"][0]["company"] == "示例公司"
    assert "greenhouse.io" in official["jobs"][0]["job_url"]
    unreadable = career_sources.read_official(
        {"name": "打不开的官网", "url": "https://down.example", "type": "公司招聘官网"},
        "产品经理",
        10,
        fake_fetch,
        use_browser=False,
    )
    assert unreadable["source_status"] == "unavailable"
    shell = career_sources.read_official(
        {"name": "空壳官网", "url": "https://shell.example", "type": "公司招聘官网"},
        "产品经理",
        10,
        fake_fetch,
        use_browser=False,
    )
    assert shell["source_status"] == "unavailable"
    assert shell["jobs"] == []
    listed = career_sources.read_platform(
        {"name": "列表示例", "url": "https://list.example/jobs"},
        "产品经理",
        10,
        fake_fetch,
    )
    assert listed["matched_jobs"] == 1
    assert listed["jobs"][0]["location"] == "杭州"
    remote = career_sources.read_platform(
        {"name": "Remote OK", "url": "https://remoteok.com/"},
        "产品经理",
        10,
        fake_fetch,
    )
    assert remote["jobs"][0]["company"] == "Remote Co"

    combined = career_sources.combine_results([
        {"source": "Bonjour", "source_status": "searched", "source_url": BONJOUR_URL, "kind": "platform", "matched_jobs": 1, "jobs": [{
            "company": "Demo AI", "title": "AI 产品经理", "location": "杭州",
            "job_url": "https://bonjour.example/jobs/1", "application_url": "https://bonjour.example/jobs/1/apply",
        }]},
        official,
        unreadable,
        jobradar_status(),
        {"source": "出海聘", "source_status": "searched", "source_url": "https://www.chuhaipin.cn/", "matched_jobs": 1, "jobs": [{
            "company": "Hidden", "title": "AI 产品经理", "location": "上海", "job_url": "https://www.chuhaipin.cn/job/1",
        }]},
    ], "产品经理", 10)
    combined_names = [item["company"] for item in combined["jobs"]]
    assert "示例公司" in combined_names
    assert "Demo AI" in combined_names
    assert all(item["source"] != "JobRadar" for item in combined["jobs"])
    assert "JobRadar" not in combined["sources_attempted"]
    assert "出海聘" not in combined["sources_attempted"]
    assert combined["source_summary"]["unavailable"] >= 1
    encoded = json.dumps(combined, ensure_ascii=False)
    assert "JobRadar" not in encoded
    assert "出海聘" not in encoded
    assert "membership_required" not in encoded

    profile = {
        "schema_version": "fanhan-career-profile-v1",
        "intent": {
            "employment_type": "full_time",
            "preferred_locations": ["杭州"],
            "remote_preference": "reject",
            "relocation_preference": "reject",
            "available_from": "2026-01-01",
            "work_authorization": ["中国大陆"],
        },
    }
    ranked = career_sources.combine_results([
        {"source": "Bonjour", "source_status": "searched", "source_url": BONJOUR_URL, "kind": "platform", "matched_jobs": 2, "jobs": [
            {"company": "远方", "title": "AI 产品经理", "location": "Remote", "job_url": "https://jobs.example/remote", "summary": "全职 remote"},
            {"company": "本地", "title": "AI 产品经理", "location": "杭州", "job_url": "https://jobs.example/hz", "summary": "全职 现场 无需搬迁"},
        ]},
    ], "产品经理", 10, profile)
    assert [item["company"] for item in ranked["jobs"]][0] == "本地"
    assert ranked["jobs"][-1]["screen"] == "暂不建议"
    mixed = career_sources.combine_results([
        {"source": "平台甲", "source_status": "searched", "source_url": "https://platform.example", "kind": "platform", "matched_jobs": 6, "jobs": [
            {"company": f"P{index}", "title": "工程师", "location": "北京", "job_url": f"https://platform.example/{index}"}
            for index in range(6)
        ]},
        {"source": "官网公司", "source_status": "searched", "source_url": "https://official.example", "kind": "official", "matched_jobs": 1, "jobs": [
            {"company": "官网公司", "title": "工程师", "location": "北京", "job_url": "https://official.example/1"},
        ]},
    ], "工程师", 4)
    assert any(item["source"] == "官网公司" for item in mixed["jobs"])
    assert career_sources.feishu_portal("https://x2-robot.jobs.feishu.cn/index/position/list") == ("x2-robot.jobs.feishu.cn", "index")
    assert career_sources.feishu_portal("https://deeplang.jobs.feishu.cn/913608/position/list") == ("deeplang.jobs.feishu.cn", "913608")
    feishu_jobs = career_sources.parse_feishu_jobs(
        {"data": {"job_post_list": [{
            "id": "100",
            "title": "算法工程师",
            "city_list": [{"name": "深圳"}],
            "recruit_type": {"name": "全职", "parent": {"name": "社招"}},
        }]}},
        "自变量",
        "x2-robot.jobs.feishu.cn",
        "index",
    )
    assert feishu_jobs[0]["title"] == "算法工程师"
    assert feishu_jobs[0]["location"] == "深圳"
    assert feishu_jobs[0]["job_url"] == "https://x2-robot.jobs.feishu.cn/index/position/100/detail"
    assert "全职" in feishu_jobs[0]["summary"]
    zhiye_jobs = career_sources.parse_zhiye_jobs(
        {"Data": [{"Id": "abc", "JobAdName": "导航算法工程师", "LocNames": ["深圳"], "Category": "社会招聘"}]},
        "优必选",
        "ubtrobot.zhiye.com",
    )
    assert zhiye_jobs[0]["company"] == "优必选"
    assert zhiye_jobs[0]["job_url"].endswith("jobAdId=abc")
    tencent_jobs = career_sources.parse_tencent_jobs({"Data": {"Posts": [{
        "RecruitPostName": "后端工程师", "LocationName": "深圳",
        "PostURL": "http://careers.tencent.com/jobdesc.html?postId=1", "ComName": "腾讯",
    }]}})
    assert tencent_jobs[0]["job_url"].startswith("https://")
    assert tencent_jobs[0]["location"] == "深圳"
    duck_jobs = career_sources.parse_eleduck_jobs({"posts": [
        {"id": "rule", "title": "社区规则新人必读"},
        {"id": "abc", "title": "远程后端工程师"},
    ]})
    assert len(duck_jobs) == 1
    assert duck_jobs[0]["job_url"] == "https://eleduck.com/posts/abc"
    mee_jobs = career_sources.parse_microdata_jobs(
        '<tr itemType="https://schema.org/JobPosting"><span itemProp="name">示例公司</span>'
        '<meta itemProp="title" content="算法工程师"><a href="/offer-detail/1.html">投递</a></tr>',
        "https://offers.51mee.com/",
    )
    assert mee_jobs[0]["company"] == "示例公司"
    assert mee_jobs[0]["job_url"] == "https://offers.51mee.com/offer-detail/1.html"
    meituan_jobs = career_sources.parse_meituan_jobs({"data": {"list": [{
        "name": "LongCat 算法工程师", "jobUnionId": "9",
        "cityList": [{"name": "北京市"}],
    }]}})
    assert meituan_jobs[0]["job_url"].endswith("jobUnionId=9")
    assert meituan_jobs[0]["location"] == "北京市"
    fuxi_jobs = career_sources.parse_next_positions(
        '<script id="__NEXT_DATA__">{"props":{"pageProps":{"positionList":[{"id":7,"name":"算法工程师","workPlaceNameList":["杭州市"]}]}}}</script>',
        "https://fuxi.netease.com/laboratory",
        "网易伏羲",
    )
    assert fuxi_jobs[0]["job_url"] == "https://hr.163.com/job-detail.html?id=7"
    assert fuxi_jobs[0]["location"] == "杭州市"
    import browser_jobs
    deepseek = browser_jobs.jobs_from_anchors(
        [{
            "text": "服务端开发工程师\n全栈开发/算法\n北京市 杭州市",
            "href": "/social-recruitment/high-flyer/140576#/job/abc",
        }],
        "DeepSeek",
        "https://talent.deepseek.com/",
        5,
    )
    assert deepseek[0]["title"] == "服务端开发工程师"
    assert "北京" in deepseek[0]["location"] and "杭州" in deepseek[0]["location"]
    assert deepseek[0]["job_url"].startswith("https://talent.deepseek.com/social-recruitment/")
    kept, total = career_sources.select_jobs([
        {"company": "DeepSeek", "title": "服务端开发工程师", "location": "北京", "job_url": "https://app.mokahr.com/social-recruitment/high-flyer/1#/job/aaa"},
        {"company": "DeepSeek", "title": "预训练数据工程师", "location": "杭州", "job_url": "https://app.mokahr.com/social-recruitment/high-flyer/1#/job/bbb"},
    ], "工程师", 5)
    assert total == 2
    kimi_links = browser_jobs.career_links(
        [{"text": "加入我们", "href": "/apply/moonshot/148506#/jobs?page=1"}],
        "https://careers.kimi.com/",
    )
    assert kimi_links == ["https://careers.kimi.com/apply/moonshot/148506#/jobs?page=1"]
    assert browser_jobs.next_list_url(kimi_links[0]).endswith("page=2")
    planner = browser_jobs.jobs_from_anchors(
        [{"text": "数值策划\n上海|社招", "href": "/careers/jobs/15"}],
        "元境",
        "https://www.yuanjingos.com/careers/jobs",
        5,
    )
    assert planner[0]["title"] == "数值策划"
    assert "上海" in planner[0]["location"]
    ordered = browser_jobs.career_links([
        {"text": "校园招聘", "href": "https://hr.xiaomi.com/website/campus.html"},
        {"text": "浏览全部职位", "href": "https://hr.xiaomi.com/website/opportunities.html"},
    ], "https://hr.xiaomi.com/")
    assert ordered[0].endswith("/opportunities.html")
    kuaishou_jobs = browser_jobs.jobs_from_kuaishou(
        {"result": {"list": [{"id": 31601, "name": "服务商运营专家", "workLocationCode": "Shanghai", "positionNatureCode": "C001"}]}},
        "快手",
        5,
    )
    assert kuaishou_jobs[0]["job_url"].endswith("/job-info/31601")
    kept_ks, total_ks = career_sources.select_jobs([
        {"company": "快手", "title": "服务商运营专家", "location": "上海", "job_url": "https://zhaopin.kuaishou.cn/#/official/social/job-info/1"},
        {"company": "快手", "title": "行业运营专家", "location": "北京", "job_url": "https://zhaopin.kuaishou.cn/#/official/social/job-info/2"},
    ], "", 5)
    assert total_ks == 2
    assert kuaishou_jobs[0]["location"] == "上海"
    import official_extra
    jd = official_extra.parse_jd_jobs([{"positionNameOpen": "数据分析岗", "requirementId": 227248, "workCity": "北京市"}])
    assert jd[0]["title"] == "数据分析岗" and "requirementId=227248" in jd[0]["job_url"]
    xhs = official_extra.parse_xiaohongshu_jobs({"data": {"list": [{"positionId": 19566, "positionName": "产品经理", "workplace": "上海市"}]}})
    assert xhs[0]["job_url"].endswith("/social/position/19566")
    manus = official_extra.parse_manus_jobs([{"result": {"data": {"json": [{"id": "abc", "title": "Product Designer", "locations": ["Beijing"]}]}}}])
    assert manus[0]["job_url"].endswith("/en/job/abc") and manus[0]["location"] == "Beijing"
    horizon = official_extra.parse_horizon_jobs({"data": {"pageForm": {"pageData": [{"postName": "ISP设计工程师", "postId": "p1", "workPlaceStr": "上海市"}]}}})
    assert "postId=p1" in horizon[0]["job_url"]
    ali = official_extra.parse_alibaba_jobs({"content": {"datas": [{"name": "高级算法工程师", "positionUrl": "/off-campus/position-detail?positionId=9", "workLocations": ["杭州"]}]}}, "https://talent-holding.alibaba.com")
    assert ali[0]["job_url"].endswith("positionId=9") and ali[0]["location"] == "杭州"
    token = official_extra.parse_onetoken_jobs('id: "edge-inference-eng", title: "端侧大模型推理优化工程师", cat: "AI Infra", loc: "北京",')
    assert token[0]["job_url"].endswith("id=edge-inference-eng")
    luchen = official_extra.parse_luchen_jobs("<p>AI 平台研发工程师</p><p>关于我们</p>")
    assert luchen[0]["title"] == "AI 平台研发工程师"
    ant = official_extra.parse_ant_jobs({"content": [{"id": 99, "name": "蚂蚁集团-大模型算法评测", "workLocations": ["杭州"], "description": "负责大模型应用的质量评测。"}]})
    assert ant[0]["job_url"].endswith("positionId=99") and "大模型" in ant[0]["summary"]
    ai2 = official_extra.parse_ai2_jobs('<h1>机器人VLA算法工程师</h1> 北京、深圳｜研发岗 <a href="https://ai2robotics.com/join/vla/">查看详情</a>')
    assert ai2[0]["title"] == "vla" or "ai2robotics.com/join/vla" in ai2[0]["job_url"]
    zerith = official_extra.parse_zerith_jobs('<div class="listTitle">具身智能工程师</div><div class="city">地点: 深圳市</div><p><span>1、参与具身模型训练。</span></p><div class="list ')
    assert zerith[0]["title"] == "具身智能工程师" and zerith[0]["location"] == "深圳市"
    assert browser_jobs.list_url_from_detail("https://www.yuanjingos.com/careers/jobs/16") == "https://www.yuanjingos.com/careers/jobs"
    assert browser_jobs.jobs_from_anchors(
        [{"text": "查看职位详情", "href": "/careers/jobs/16"}],
        "元境",
        "https://www.yuanjingos.com/careers",
        5,
    ) == []
    blocked = career_sources.read_official(
        {"name": "JobRadar", "url": "https://jobradar.cc/zh", "type": "岗位聚合站", "access": "基础免费/高级付费"},
        "",
        5,
        fake_fetch,
        use_browser=True,
    )
    assert blocked["jobs"] == []
    print("external_jobs self-test: ok")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--profile", type=Path, help="职业档案 JSON。有则按硬性条件排序，没有则只按查询重合排序。")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--browser-limit", type=int, default=5, help="HTTP 失败后最多补读的相关官网数")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.limit < 1:
        parser.error("--limit must be positive")
    if args.browser_limit < 0:
        parser.error("--browser-limit must not be negative")
    try:
        print(json.dumps(search_all(args.query, args.limit, args.profile, args.catalog, browser_limit=args.browser_limit), ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({"source_status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
