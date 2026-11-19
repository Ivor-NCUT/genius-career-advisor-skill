#!/usr/bin/env python3
"""Optional reader for team and Fanhan open jobs.

Those jobs live on the current Twenty recruiting workbench. This command
does not log into Twenty or query its full API. It reads only the
secret-free, JD-only HTTPS JSON contract in FANHAN_PUBLIC_JOBS_URL, and it
never sends Authorization.

If that variable is unset, the result is unavailable / public_contract_missing.
Do not invent a job list. A closed employer is omitted.
"""

from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ENV_URL = "FANHAN_PUBLIC_JOBS_URL"
# Safety net only. Refusal stays inside the script and is not a user-facing story.
RETIRED_HOSTS = {"fanhan-workbench.zeabur.app"}
CLOSED_EMPLOYERS = ("eazo",)
FIELDS = (
    "id",
    "company",
    "title",
    "summary",
    "description",
    "city",
    "work_type",
    "work_mode",
    "url",
)


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
        raise JobsError("retired_workbench", "当前不能列出团体岗位。")
    return text


def closed_employer(job: dict) -> bool:
    company = str(job.get("company") or "")
    title = str(job.get("title") or "")
    blob = f"{company}\n{title}".casefold()
    return any(name in blob for name in CLOSED_EMPLOYERS)


def normalize_job(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    company = str(value.get("company") or "").strip()
    title = str(value.get("title") or "").strip()
    if not company or not title or closed_employer(value):
        return None
    job = {field: str(value.get(field) or "").strip() for field in FIELDS}
    job["company"] = company
    job["title"] = title
    return job


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
        if isinstance(item, dict) and closed_employer(item):
            omitted += 1
            continue
        job = normalize_job(item)
        if job is not None:
            jobs.append(job)
    return jobs, omitted


def fetch(url: str, opener=urlopen, timeout: int = 15) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "tiancai-career-advisor/1.0"})
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


def load(env: dict[str, str] | None = None, opener=urlopen) -> dict:
    source = os.environ if env is None else env
    raw = source.get(ENV_URL, "").strip()
    if not raw:
        return unavailable(
            "public_contract_missing",
            "团体岗位的公开清单还没有配置。当前不能列出团体岗位。",
        )
    try:
        url = validate_public_url(raw)
        return fetch(url, opener=opener)
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
                    {"id": "keep", "company": "Example", "title": "工程师", "city": "上海"},
                    {"id": "drop", "company": "Eazo", "title": "产品经理", "city": "北京"},
                    {"company": "", "title": "无公司"},
                ]
            }).encode()

    def opener(request, timeout):
        assert request.get_header("Authorization") is None
        assert "example.com" in request.full_url
        return Response()

    found = load({ENV_URL: "https://jobs.example.com/open-jobs"}, opener=opener)
    assert found["source_status"] == "searched"
    assert [job["company"] for job in found["jobs"]] == ["Example"]
    assert found["omitted_closed_employers"] == 1
    assert "Eazo" not in json.dumps(found, ensure_ascii=False)

    class HtmlResponse(Response):
        headers = {"content-type": "text/html"}

        def read(self):
            return b"<!doctype html><html></html>"

    html = load({ENV_URL: "https://jobs.example.com/open-jobs"}, opener=lambda request, timeout: HtmlResponse())
    assert html["reason"] == "not_json_jobs"
    print("fanhan_open_jobs self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    print(json.dumps(load(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
