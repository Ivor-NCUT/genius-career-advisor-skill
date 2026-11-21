#!/usr/bin/env python3
"""Recommend a few job sources from the published catalog.

At search time the latest catalog is fetched from the public main-branch file.
Network errors, timeouts, and invalid payloads fall back to the bundled snapshot.
"""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "data" / "job-source-catalog.json"
DEFAULT_REMOTE_CATALOG_URL = "https://raw.githubusercontent.com/Ivor-NCUT/genius-career-advisor-skill/main/genius-career-advisor/data/job-source-catalog.json"
ENV_CATALOG_URL = "FANHAN_SOURCE_CATALOG_URL"
REMOTE_TIMEOUT_SECONDS = 10
MAX_CATALOG_BYTES = 2_000_000
QUALITY_SCORE = {"高": 40, "中高": 30, "中": 20, "波动较大": 0, "待核实": -10}
ACCESS_SCORE = {"免费公开": 20, "免费注册后使用": 15, "基础免费/高级付费": 5, "会员主导": -100, "无法确认": -20}


def validate(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("岗位来源清单格式无效")
    records = payload.get("records")
    if payload.get("schema_version") != 1 or not isinstance(records, list) or not records:
        raise ValueError("岗位来源清单格式无效")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("岗位来源清单格式无效")
        name = record.get("name")
        url = record.get("url")
        if not isinstance(name, str) or not name.strip() or not isinstance(url, str) or not url.strip():
            raise ValueError("岗位来源清单格式无效")
    return payload


def load(path: Path) -> dict:
    return validate(json.loads(path.read_text(encoding="utf-8")))


def catalog_url(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    configured = source.get(ENV_CATALOG_URL, "").strip()
    return configured or DEFAULT_REMOTE_CATALOG_URL


def fetch_remote(url: str, opener=urlopen, timeout: float = REMOTE_TIMEOUT_SECONDS) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("岗位来源清单地址无效")
    request = Request(
        url,
        headers={
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "User-Agent": "genius-career-advisor/source-catalog",
        },
    )
    with opener(request, timeout=timeout) as response:
        body = response.read(MAX_CATALOG_BYTES + 1)
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_CATALOG_BYTES:
        raise ValueError("岗位来源清单格式无效")
    return validate(json.loads(bytes(body).decode("utf-8")))


def resolve_catalog(
    local_path: Path = DEFAULT_CATALOG,
    *,
    env: dict[str, str] | None = None,
    opener=urlopen,
    timeout: float = REMOTE_TIMEOUT_SECONDS,
) -> tuple[dict, str]:
    """Return the published catalog, or the local snapshot if that request cannot be used."""
    try:
        return fetch_remote(catalog_url(env), opener=opener, timeout=timeout), "remote"
    except Exception as error:
        # Tests assert inside the opener. A failed assertion must not look like a network fallback.
        if isinstance(error, AssertionError):
            raise
        return load(local_path), "bundled"


def load_search_catalog(
    catalog: Path | None = None,
    *,
    env: dict[str, str] | None = None,
    opener=urlopen,
    timeout: float = REMOTE_TIMEOUT_SECONDS,
) -> tuple[dict, str]:
    """Load the catalog for a search. An explicit local file skips the network."""
    if catalog is not None:
        return load(catalog), "file"
    return resolve_catalog(env=env, opener=opener, timeout=timeout)


def tokens(query: str) -> list[str]:
    return [item.casefold() for item in re.split(r"[\s,，、/|]+", query.strip()) if item]


def rank(record: dict, query: str, include_paid: bool) -> tuple[int, list[str]]:
    access = record.get("access", "无法确认")
    if access == "会员主导" and not include_paid:
        return -10_000, []
    searchable = " ".join(str(record.get(key, "")) for key in (
        "name", "intro", "target_audience", "direction",
    )) + " " + " ".join(record.get("tags") or [])
    searchable = searchable.casefold()
    matched = [token for token in tokens(query) if token in searchable]
    score = QUALITY_SCORE.get(record.get("quality"), -10) + ACCESS_SCORE.get(access, -20)
    score += 18 * len(matched)
    if record.get("type") != "公司招聘官网":
        score += 5
    return score, matched


def shortlist(payload: dict, query: str, limit: int = 5, include_paid: bool = False) -> dict:
    ranked = []
    for record in payload["records"]:
        score, matched = rank(record, query, include_paid)
        if score <= -10_000:
            continue
        item = dict(record)
        item["score"] = score
        item["reason"] = "、".join(filter(None, [
            f"匹配：{'、'.join(matched)}" if matched else "通用高质量来源",
            item.get("quality", ""), item.get("access", ""),
        ]))
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["name"]))
    broad = [item for item in ranked if item.get("type") != "公司招聘官网"]
    direct = [item for item in ranked if item.get("type") == "公司招聘官网"]
    selected = broad[: min(3, limit)] + direct[: max(0, limit - min(3, limit))]
    if len(selected) < limit:
        used = {item["url"] for item in selected}
        selected.extend(item for item in ranked if item["url"] not in used)
    return {
        "query": query,
        "catalog_generated_at": payload.get("generated_at"),
        "catalog_count": len(payload["records"]),
        "recommended_sources": selected[:limit],
        "requires_user_confirmation": True,
    }


def recommend(
    query: str,
    limit: int = 5,
    include_paid: bool = False,
    catalog: Path | None = None,
    *,
    env: dict[str, str] | None = None,
    opener=urlopen,
    timeout: float = REMOTE_TIMEOUT_SECONDS,
) -> dict:
    payload, origin = load_search_catalog(catalog, env=env, opener=opener, timeout=timeout)
    result = shortlist(payload, query, limit, include_paid)
    result["catalog_source"] = origin
    return result


def self_test() -> None:
    class Body:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, size: int = -1) -> bytes:
            if size is None or size < 0:
                return self.body
            return self.body[:size]

    def failing(error: BaseException):
        def opener(request, timeout):
            raise error

        return opener

    fixture = {"schema_version": 1, "generated_at": "2026-08-20", "records": [
        {"name": "免费 AI 平台", "url": "https://free.example", "type": "招聘平台", "intro": "AI 产品岗位", "access": "免费公开", "quality": "高", "tags": ["AI/大模型", "产品/设计/运营"]},
        {"name": "会员站", "url": "https://paid.example", "type": "岗位聚合站", "intro": "AI 产品岗位", "access": "会员主导", "quality": "高", "tags": ["AI/大模型"]},
        {"name": "AI 公司", "url": "https://company.example", "type": "公司招聘官网", "intro": "AI 产品团队", "access": "免费公开", "quality": "中高", "tags": ["AI应用/FDE"]},
    ]}
    remote_fixture = {"schema_version": 1, "generated_at": "2026-11-21", "records": [
        {"name": "远程新来源", "url": "https://remote.example/jobs", "type": "招聘平台", "intro": "远程目录里的 AI 产品岗位", "access": "免费公开", "quality": "高", "tags": ["AI/大模型"]},
    ]}
    published_url = "https://raw.githubusercontent.com/Ivor-NCUT/genius-career-advisor-skill/main/genius-career-advisor/data/job-source-catalog.json"
    assert DEFAULT_REMOTE_CATALOG_URL == published_url
    assert REMOTE_TIMEOUT_SECONDS == 10

    def forbid(request, timeout):
        raise AssertionError(f"unexpected request {request.full_url}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.json"
        path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        result = shortlist(load(path), "AI 产品", 2)
        assert [item["name"] for item in result["recommended_sources"]] == ["免费 AI 平台", "AI 公司"]
        assert all(item["name"] != "会员站" for item in result["recommended_sources"])
        pinned = recommend(
            "AI 产品",
            2,
            catalog=path,
            opener=forbid,
            env={ENV_CATALOG_URL: "https://catalog.example/job-source-catalog.json"},
        )
        assert pinned["catalog_source"] == "file"
        assert [item["name"] for item in pinned["recommended_sources"]] == ["免费 AI 平台", "AI 公司"]
        invalid = path.with_name("invalid.json")
        invalid.write_text('{"schema_version": 1, "records": []}', encoding="utf-8")
        try:
            load(invalid)
        except ValueError as error:
            assert str(error) == "岗位来源清单格式无效"
        else:
            raise AssertionError("invalid local catalog should fail")

    bundled = load(DEFAULT_CATALOG)
    assert bundled["schema_version"] == 1
    assert bundled["records"]

    def remote_ok(request, timeout):
        assert timeout == REMOTE_TIMEOUT_SECONDS
        assert request.full_url == published_url
        assert request.get_header("Authorization") is None
        return Body(json.dumps(remote_fixture, ensure_ascii=False).encode())

    fetched = recommend("AI 产品", 3, opener=remote_ok, env={})
    assert fetched["catalog_source"] == "remote"
    assert fetched["catalog_generated_at"] == "2026-11-21"
    assert fetched["catalog_count"] == 1
    assert [item["name"] for item in fetched["recommended_sources"]] == ["远程新来源"]

    custom_url = "https://catalog.example/job-source-catalog.json"
    seen: dict[str, object] = {}

    def custom_ok(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return Body(json.dumps(remote_fixture, ensure_ascii=False).encode())

    overridden = recommend("AI 产品", 3, opener=custom_ok, env={ENV_CATALOG_URL: f"  {custom_url}  "})
    assert seen == {"url": custom_url, "timeout": REMOTE_TIMEOUT_SECONDS}
    assert overridden["catalog_source"] == "remote"
    blank = {}

    def default_url(request, timeout):
        blank["url"] = request.full_url
        return Body(json.dumps(remote_fixture, ensure_ascii=False).encode())

    recommend("AI 产品", 3, opener=default_url, env={ENV_CATALOG_URL: "   "})
    assert blank["url"] == published_url

    invalid_payloads = [
        b"not-json",
        b"[]",
        b'{"schema_version": 1}',
        b'{"schema_version": 1, "records": []}',
        '{"schema_version": "1", "records": [{"name": "A", "url": "https://a.example"}]}'.encode(),
        '{"schema_version": 1, "records": [{"name": "缺链接"}]}'.encode(),
        b'{"schema_version": 1, "records": ["nope"]}',
        '{"schema_version": 1}'.encode("utf-16"),
        b"x" * (MAX_CATALOG_BYTES + 1),
    ]
    for body in invalid_payloads:
        fallback = recommend("AI 产品", 3, opener=lambda request, timeout, body=body: Body(body), env={})
        assert fallback["catalog_source"] == "bundled"
        assert fallback["catalog_generated_at"] == bundled["generated_at"]
        assert fallback["catalog_count"] == len(bundled["records"])
        assert fallback["recommended_sources"]

    def times_out(request, timeout):
        seen["timeout"] = timeout
        raise TimeoutError("timed out")

    seen.clear()
    offline = recommend("AI 产品", 5, opener=times_out, env={})
    bundled_urls = {item["url"] for item in bundled["records"]}
    assert seen["timeout"] == REMOTE_TIMEOUT_SECONDS
    assert offline["catalog_source"] == "bundled"
    assert offline["catalog_generated_at"] == bundled["generated_at"]
    assert offline["catalog_count"] == len(bundled["records"])
    assert offline["recommended_sources"]
    assert {item["url"] for item in offline["recommended_sources"]} <= bundled_urls

    for failure in (URLError("down"), OSError("reset"), TimeoutError("slow"), ValueError("bad")):
        failed = recommend("AI 产品", 3, opener=failing(failure), env={})
        assert failed["catalog_source"] == "bundled"
        assert failed["catalog_count"] == len(bundled["records"])
        assert {item["url"] for item in failed["recommended_sources"]} <= bundled_urls

    blocked = recommend("AI 产品", 3, opener=forbid, env={ENV_CATALOG_URL: "file:///tmp/job-source-catalog.json"})
    assert blocked["catalog_source"] == "bundled"
    assert blocked["catalog_count"] == len(bundled["records"])

    print("source_catalog self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--include-paid", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 3 <= args.limit <= 5:
        parser.error("--limit 必须在 3 到 5 之间")
    print(json.dumps(
        recommend(args.query, args.limit, args.include_paid, args.catalog),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
