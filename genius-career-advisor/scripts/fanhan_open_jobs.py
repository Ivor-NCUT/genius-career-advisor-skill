#!/usr/bin/env python3
"""Read currently open Fanhan jobs from the public Twenty catalog.

The endpoint may return only company_name, job_name, and job_jd. Any other
field, including candidates, internal notes, and communication records, is
dropped and never printed. This command never sends a token and never reads
the retired Zeabur workbench.
"""

from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


ENV_URL = "FANHAN_PUBLIC_JOBS_URL"
RETIRED_HOSTS = {"fanhan-workbench.zeabur.app"}
CLOSED_EMPLOYERS = ("eazo",)
PUBLIC_FIELDS = ("company_name", "job_name", "job_jd")


class JobsError(ValueError):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def unavailable(reason: str, detail: str) -> dict:
    return {
        "source": "fanhan-open-jobs",
        "source_status": "unavailable",
        "reason": reason,
        "detail": detail,
        "jobs": [],
    }


def validate_public_url(value: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not host:
        raise JobsError("public_url_invalid", "公开岗位地址必须是不带账号的 HTTPS URL。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise JobsError("public_url_invalid", "公开岗位地址不能携带账号、查询参数或片段。")
    if host in RETIRED_HOSTS:
        raise JobsError("retired_workbench", "旧工作台岗位列表已停用，不能当作当前开放岗位。")
    return text


def closed_employer(company: str, title: str) -> bool:
    blob = f"{company}\n{title}".casefold()
    return any(name in blob for name in CLOSED_EMPLOYERS)


def normalize_job(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    company = str(value.get("company_name") or "").strip()
    title = str(value.get("job_name") or "").strip()
    description = str(value.get("job_jd") or "").strip()
    if not company or not title or closed_employer(company, title):
        return None
    job = {"company_name": company, "job_name": title}
    if description:
        job["job_jd"] = description
    return job


def with_query(url: str, query: str) -> str:
    parsed = urlparse(url)
    text = query.strip()
    return urlunparse(parsed._replace(query=urlencode({"q": text}) if text else ""))


def parse_jobs(payload: object) -> tuple[list[dict], int]:
    if isinstance(payload, dict):
        raw_jobs = payload.get("jobs")
    elif isinstance(payload, list):
        raw_jobs = payload
    else:
        raise JobsError("not_json_jobs", "公开岗位响应不是岗位列表。")
    if not isinstance(raw_jobs, list):
        raise JobsError("not_json_jobs", "公开岗位响应不是岗位列表。")
    jobs = []
    omitted = 0
    for item in raw_jobs:
        if isinstance(item, dict) and closed_employer(
            str(item.get("company_name") or ""), str(item.get("job_name") or ""),
        ):
            omitted += 1
            continue
        job = normalize_job(item)
        if job is not None:
            jobs.append(job)
    return jobs, omitted


def fetch(url: str, opener=urlopen, timeout: int = 15, query: str = "") -> dict:
    request = Request(
        with_query(url, query),
        headers={"Accept": "application/json", "User-Agent": "tiancai-career-advisor/1.0"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            body = response.read()
    except HTTPError as error:
        raise JobsError("http_error", f"公开岗位接口返回 HTTP {error.code}。") from error
    except URLError as error:
        raise JobsError("unreachable", "公开岗位接口无法连接。") from error
    if "json" not in content_type.lower():
        raise JobsError("not_json_jobs", "公开岗位接口没有返回 JSON。")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JobsError("not_json_jobs", "公开岗位接口没有返回 JSON。") from error
    jobs, omitted = parse_jobs(payload)
    return {
        "source": "fanhan-open-jobs",
        "source_status": "searched",
        "jobs": jobs,
        "omitted_closed_employers": omitted,
    }


def load(env: dict[str, str] | None = None, opener=urlopen, query: str = "") -> dict:
    source = os.environ if env is None else env
    raw = source.get(ENV_URL, "").strip()
    if not raw:
        return unavailable(
            "public_contract_missing",
            "新的招聘工作台还没有不带密钥的公开岗位接口。当前不能列出泛函开放岗位。",
        )
    try:
        url = validate_public_url(raw)
        return fetch(url, opener=opener, query=query)
    except JobsError as error:
        return unavailable(error.reason, error.detail)


def self_test() -> None:
    missing = load({})
    assert missing["source_status"] == "unavailable"
    assert missing["reason"] == "public_contract_missing"
    assert missing["jobs"] == []

    retired = load({ENV_URL: "https://fanhan-workbench.zeabur.app/api/public/jobs"})
    assert retired["reason"] == "retired_workbench"
    assert retired["jobs"] == []

    secret = load({ENV_URL: "https://user:password@example.com/jobs"})
    assert secret["reason"] == "public_url_invalid"

    class Response:
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({
                "jobs": [
                    {
                        "company_name": "泛函",
                        "job_name": "Agent工程师",
                        "job_jd": "负责 Agent 系统",
                        "candidates": [{"name": "秘密候选人"}],
                        "internal_note": "内部备注不要出现",
                        "group_chat": "沟通记录不要出现",
                    },
                    {"company_name": "Eazo", "job_name": "产品经理", "job_jd": "已停止"},
                    {"company": "旧字段", "title": "不能映射", "description": "完整 CRM"},
                ],
                "people": [{"name": "另一个候选人"}],
            }).encode()

    def opener(request, timeout):
        assert request.get_header("Authorization") is None
        assert request.full_url.endswith("?q=Agent%E5%B7%A5%E7%A8%8B%E5%B8%88")
        return Response()

    found = load(
        {ENV_URL: "https://jobs.example.com/api/public/jobs"},
        opener=opener,
        query="Agent工程师",
    )
    rendered = json.dumps(found, ensure_ascii=False)
    assert found["source_status"] == "searched"
    assert found["jobs"] == [{
        "company_name": "泛函",
        "job_name": "Agent工程师",
        "job_jd": "负责 Agent 系统",
    }]
    assert found["omitted_closed_employers"] == 1
    for secret in ("秘密候选人", "内部备注不要出现", "沟通记录不要出现", "另一个候选人", "Eazo", "旧字段"):
        assert secret not in rendered
    assert set(found["jobs"][0]) <= set(PUBLIC_FIELDS)

    class HtmlResponse(Response):
        headers = {"content-type": "text/html"}

        def read(self):
            return b"<!doctype html><html></html>"

    html = load({ENV_URL: "https://jobs.example.com/open-jobs"}, opener=lambda request, timeout: HtmlResponse())
    assert html["reason"] == "not_json_jobs"
    print("fanhan_open_jobs self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="", help="岗位搜索词，例如 Agent工程师")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    print(json.dumps(load(query=args.query), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
